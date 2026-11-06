"""``/api/v1/ma`` routes with Music Assistant behind a stub: response shapes, parameter
validation and the mapping of MA failures to HTTP codes. Transport happy paths, now-playing
and import-equals-browse are pinned in test_ma_controls_and_children / test_ma_import."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags


class Item:
    def __init__(self, name, uri="library://playlist/1"):
        self.name = name
        self.uri = uri
        self.images = [SimpleNamespace(type="thumb", path="p.jpg", provider="spotify",
                                       remotely_accessible=True)]

    def to_dict(self):
        return {"name": self.name, "uri": self.uri}


class FakeMA:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail = False
        self.item = Item("Comptines")

    def _boom(self):
        if self.fail:
            raise RuntimeError("MA down")

    def get_item_image_url(self, item, size=0):
        return f"img/{item.name}?s={size}"

    def get_image_url(self, img, size=0):
        return f"imgpath/{img.path}?s={size}"

    async def search(self, q, media_types=None, limit=25, library_only=False):
        self.calls.append(("search", q, media_types, limit, library_only))
        self._boom()
        return SimpleNamespace(
            tracks=[Item("T")], albums=[], playlists=[Item("P")], artists=[],
            radio=[], audiobooks=[], podcasts=[Item("Pod")],
        )

    async def get_item_by_uri(self, uri):
        self.calls.append(("item", uri))
        self._boom()
        return self.item

    def _lib(name):
        async def fn(self, search=None, limit=None):
            self.calls.append((name, search, limit))
            self._boom()
            return [Item(name)]
        return fn

    get_library_playlists = _lib("playlists")
    get_library_albums = _lib("albums")
    get_library_tracks = _lib("tracks")
    get_library_radios = _lib("radios")
    get_library_audiobooks = _lib("audiobooks")
    get_library_podcasts = _lib("podcasts")

    async def get_players(self):
        self._boom()
        return [SimpleNamespace(to_dict=lambda: {"player_id": "p1", "name": "Salon"})]

    async def play_media(self, queue_id, uri, option=None, radio_mode=False):
        self.calls.append(("play_media", queue_id, uri, option, radio_mode))
        self._boom()

    async def seek(self, q, p):
        self.calls.append(("seek", q, p))
        self._boom()
        if self.fail_seek:
            raise RuntimeError("seek refused")

    fail_seek = False

    async def get_now_playing(self, q):
        self._boom()
        return {}

    def _cmd(name):
        async def fn(self, *a):
            self.calls.append((name, *a))
            self._boom()
        return fn

    pause = _cmd("pause")
    stop = _cmd("stop")
    next_track = _cmd("next")
    previous_track = _cmd("previous")
    set_volume = _cmd("volume")
    volume_up = _cmd("vol_up")
    volume_down = _cmd("vol_down")
    set_mute = _cmd("mute")
    set_power = _cmd("power")
    set_shuffle = _cmd("shuffle")
    set_repeat = _cmd("repeat")
    play = _cmd("resume")
    play_pause = _cmd("play_pause")


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_default_tags(session)
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def ma():
    return FakeMA()


@pytest.fixture
async def client(db: AsyncSession, ma: FakeMA):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ma_client] = lambda: ma
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --- search / item ----------------------------------------------------------


@pytest.mark.asyncio
async def test_search_groups_results_by_type_with_resolved_thumbs(client, ma):
    r = await client.get("/api/v1/ma/search?q=comptines")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"tracks", "albums", "playlists", "artists", "radio", "audiobooks", "podcasts"}
    assert body["tracks"] == [{"name": "T", "uri": "library://playlist/1", "thumb_url_resolved": "img/T?s=300"}]
    assert body["albums"] == []
    assert [p["name"] for p in body["podcasts"]] == ["Pod"]
    assert ma.calls == [("search", "comptines", None, 25, False)]


@pytest.mark.asyncio
async def test_search_passes_types_limit_and_library_only(client, ma):
    await client.get("/api/v1/ma/search?q=x&types=track,album&limit=5&library_only=true")
    assert ma.calls == [("search", "x", ["track", "album"], 5, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["", "q=", "q=x&limit=0", "q=x&limit=101"])
async def test_search_validates_parameters(client, q):
    assert (await client.get(f"/api/v1/ma/search?{q}")).status_code == 422


@pytest.mark.asyncio
async def test_search_ma_failure_is_not_caught(db, ma):
    """Doubtful, pinned as is: ``/search`` has no error mapping, a MA failure is a bare 500."""
    ma.fail = True

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ma_client] = lambda: ma
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            assert (await ac.get("/api/v1/ma/search?q=x")).status_code == 500
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_item_returns_details_thumbs_and_all_images(client, ma):
    r = await client.get("/api/v1/ma/item?uri=library://playlist/1")
    assert r.status_code == 200
    assert r.json() == {
        "name": "Comptines",
        "uri": "library://playlist/1",
        "thumb_url_resolved": "img/Comptines?s=300",
        "thumb_url_full": "img/Comptines?s=0",
        "all_images": [{
            "type": "thumb", "path": "p.jpg", "provider": "spotify", "remotely_accessible": True,
            "url_300": "imgpath/p.jpg?s=300", "url_original": "imgpath/p.jpg?s=0",
        }],
    }
    assert ma.calls == [("item", "library://playlist/1")]


@pytest.mark.asyncio
async def test_item_requires_uri_and_maps_ma_failure_to_400(client, ma):
    assert (await client.get("/api/v1/ma/item")).status_code == 422
    ma.fail = True
    r = await client.get("/api/v1/ma/item?uri=library://x/1")
    assert r.status_code == 400
    assert r.json() == {"detail": "Impossible de récupérer l'élément: MA down"}


# --- library / players -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["playlists", "albums", "tracks", "radios", "audiobooks", "podcasts"]
)
async def test_library_lists_return_items_with_thumb_and_forward_filters(client, ma, kind):
    r = await client.get(f"/api/v1/ma/library/{kind}?search=ab&limit=3")
    assert r.status_code == 200
    assert r.json() == [{
        "name": kind, "uri": "library://playlist/1", "thumb_url_resolved": f"img/{kind}?s=300",
    }]
    assert ma.calls == [(kind, "ab", 3)]


@pytest.mark.asyncio
async def test_library_without_filters_forwards_none(client, ma):
    await client.get("/api/v1/ma/library/albums")
    assert ma.calls == [("albums", None, None)]


@pytest.mark.asyncio
async def test_unknown_library_kind_is_404(client):
    assert (await client.get("/api/v1/ma/library/vinyls")).status_code == 404


@pytest.mark.asyncio
async def test_players_lists_player_dicts(client):
    r = await client.get("/api/v1/ma/players")
    assert r.status_code == 200
    assert r.json() == [{"player_id": "p1", "name": "Salon"}]


# --- play ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_play_echoes_the_request_and_forwards_options(client, ma):
    r = await client.post("/api/v1/ma/play?queue_id=q1&uri=spotify://playlist/1&option=add&radio_mode=true")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "queue_id": "q1", "uri": "spotify://playlist/1", "seek": None}
    assert ma.calls == [("play_media", "q1", "spotify://playlist/1", "add", True)]


@pytest.mark.asyncio
async def test_play_requires_queue_and_uri(client):
    assert (await client.post("/api/v1/ma/play?queue_id=q1")).status_code == 422
    assert (await client.post("/api/v1/ma/play?uri=u")).status_code == 422


@pytest.mark.asyncio
async def test_play_with_seek_waits_then_seeks(client, ma, monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    r = await client.post("/api/v1/ma/play?queue_id=q1&uri=u&seek=90")
    assert r.status_code == 200
    assert r.json()["seek"] == 90
    assert slept == [1.5]
    assert ma.calls == [("play_media", "q1", "u", None, False), ("seek", "q1", 90)]


@pytest.mark.asyncio
async def test_play_with_zero_seek_does_not_seek(client, ma):
    await client.post("/api/v1/ma/play?queue_id=q1&uri=u&seek=0")
    assert [c[0] for c in ma.calls] == ["play_media"]


@pytest.mark.asyncio
async def test_play_seek_failure_is_not_fatal(client, ma, monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    ma.fail_seek = True
    r = await client.post("/api/v1/ma/play?queue_id=q1&uri=u&seek=30")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_play_failure_is_a_500_with_message(client, ma):
    ma.fail = True
    r = await client.post("/api/v1/ma/play?queue_id=q1&uri=u")
    assert r.status_code == 500
    assert r.json() == {"detail": "Erreur de lecture: MA down"}


# --- controls: validation and failures -----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,label",
    [
        ("pause?queue_id=q", "pause"),
        ("resume?queue_id=q", "resume"),
        ("play_pause?queue_id=q", "play_pause"),
        ("stop?queue_id=q", "stop"),
        ("next?queue_id=q", "next"),
        ("previous?queue_id=q", "previous"),
        ("seek?queue_id=q&position=3", "seek"),
        ("shuffle?queue_id=q&enabled=true", "shuffle"),
        ("repeat?queue_id=q&mode=all", "repeat"),
        ("volume?queue_id=q&level=10", "volume"),
        ("volume_step?queue_id=q&direction=up", "volume_up"),
        ("volume_step?queue_id=q&direction=down", "volume_down"),
        ("mute?queue_id=q&muted=true", "mute"),
        ("power?queue_id=q&powered=false", "power"),
    ],
)
async def test_control_failure_maps_to_500_naming_the_command(client, ma, path, label):
    ma.fail = True
    r = await client.post(f"/api/v1/ma/{path}")
    assert r.status_code == 500
    assert r.json() == {"detail": f"Erreur {label}: MA down"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "pause",
        "seek?queue_id=q&position=-1",
        "volume?queue_id=q&level=101",
        "volume?queue_id=q&level=-1",
        "volume?queue_id=q",
        "shuffle?queue_id=q",
        "mute?queue_id=q",
        "power?queue_id=q",
        "repeat?queue_id=q",
        "volume_step?queue_id=q",
    ],
)
async def test_control_parameters_are_validated(client, ma, path):
    assert (await client.post(f"/api/v1/ma/{path}")).status_code == 422
    assert ma.calls == []


@pytest.mark.asyncio
async def test_repeat_and_volume_step_reject_unknown_values_with_422(client, ma):
    r = await client.post("/api/v1/ma/repeat?queue_id=q&mode=twice")
    assert r.status_code == 422
    assert r.json() == {"detail": "mode doit être off | one | all"}
    r = await client.post("/api/v1/ma/volume_step?queue_id=q&direction=sideways")
    assert r.status_code == 422
    assert r.json() == {"detail": "direction doit être up | down"}
    assert ma.calls == []


@pytest.mark.asyncio
async def test_now_playing_failure_is_a_503_and_needs_queue_id(client, ma):
    assert (await client.get("/api/v1/ma/now_playing")).status_code == 422
    ma.fail = True
    r = await client.get("/api/v1/ma/now_playing?queue_id=q")
    assert r.status_code == 503
    assert r.json() == {"detail": "Music Assistant indisponible: MA down"}


@pytest.mark.asyncio
async def test_now_playing_exposes_the_documented_keys_and_proxies_the_cover(client, ma):
    async def np(q):
        return {"queue_id": q, "available": True, "state": "playing", "cover_url": "http://cdn/c.jpg"}

    ma.get_now_playing = np
    body = (await client.get("/api/v1/ma/now_playing?queue_id=q")).json()
    assert set(body) == {
        "queue_id", "available", "state", "title", "artist", "cover_url", "uri", "duration_s",
        "position_s", "volume", "muted", "shuffle", "repeat", "powered",
    }
    assert body["cover_url"].startswith("http://test/api/v1/quick/thumb?src=")
    assert "&size=300&sig=" in body["cover_url"]
    assert body["title"] is None


@pytest.mark.asyncio
async def test_import_requires_uri(client):
    assert (await client.post("/api/v1/ma/import")).status_code == 422


@pytest.mark.parametrize("kind", ["__class__", "Playlists", "search", "playlists.json"])
async def test_library_rejects_non_whitelisted_kind(client, ma, kind):
    r = await client.get(f"/api/v1/ma/library/{kind}")
    assert r.status_code == 404
    assert ma.calls == []
