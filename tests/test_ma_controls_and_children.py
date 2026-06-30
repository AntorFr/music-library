from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import media as _media_models  # noqa: F401
from app.models import rfid as _rfid_models  # noqa: F401
from app.models.media import MediaType
from app.schemas.media import MediaCreate
from app.services import media_service
from app.services.music_assistant import get_ma_client
from app.services.tag_service import seed_default_tags

# --- Fakes -----------------------------------------------------------------

class FakeEpisode:
    def __init__(self, name, uri, position, duration=600, resume_ms=None, fully=False):
        self.name = name
        self.uri = uri
        self.position = position
        self.duration = duration
        self.resume_position_ms = resume_ms
        self.fully_played = fully


class FakeAudiobook:
    def __init__(self, uri, chapters):
        self.uri = uri
        self.chapters = chapters


class FakeMA:
    def __init__(self):
        self.calls: list[tuple] = []
        self.episodes: list[FakeEpisode] = []
        self.audiobook: FakeAudiobook | None = None

    # browse
    async def get_podcast_episodes(self, item_id, provider):
        self.calls.append(("episodes", item_id, provider))
        return self.episodes

    async def get_item(self, media_type, item_id, provider):
        self.calls.append(("get_item", media_type, item_id, provider))
        return self.audiobook

    async def get_item_by_uri(self, uri):
        self.calls.append(("item_by_uri", uri))
        return self.audiobook

    def get_item_image_url(self, item, size=0):
        return f"thumb/{item.uri}?s={size}"

    # transport
    async def pause(self, q): self.calls.append(("pause", q))
    async def play(self, q): self.calls.append(("play", q))
    async def play_pause(self, q): self.calls.append(("play_pause", q))
    async def stop(self, q): self.calls.append(("stop", q))
    async def next_track(self, q): self.calls.append(("next", q))
    async def previous_track(self, q): self.calls.append(("previous", q))
    async def seek(self, q, p): self.calls.append(("seek", q, p))
    async def set_shuffle(self, q, e): self.calls.append(("shuffle", q, e))
    async def set_repeat(self, q, m): self.calls.append(("repeat", q, m))
    async def set_volume(self, p, level): self.calls.append(("volume", p, level))
    async def volume_up(self, p): self.calls.append(("vol_up", p))
    async def volume_down(self, p): self.calls.append(("vol_down", p))
    async def set_mute(self, p, m): self.calls.append(("mute", p, m))
    async def set_power(self, p, pw): self.calls.append(("power", p, pw))

    async def get_now_playing(self, q):
        return {
            "queue_id": q, "available": True, "state": "playing",
            "title": "Comptines", "artist": "VA", "cover_url": "c", "uri": "u",
            "duration_s": 120, "position_s": 12, "volume": 40, "muted": False,
            "shuffle": True, "repeat": "all", "powered": True,
        }


# --- Fixtures --------------------------------------------------------------

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
def fake_ma():
    return FakeMA()


@pytest.fixture
async def client(db: AsyncSession, fake_ma: FakeMA):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ma_client] = lambda: fake_ma
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(db, *, title, media_type, uri):
    item, _ = await media_service.create_media(
        db,
        MediaCreate(
            title=title, media_type=media_type, source_uri=uri, provider="spotify",
            cover_url=None, duration_min=None, description=None, metadata_extra=None,
            tag_ids=[], tags_inline=[],
        ),
    )
    await db.commit()
    return item


# --- Children: podcast -----------------------------------------------------

@pytest.mark.asyncio
async def test_children_podcast_paginated(client, db, fake_ma):
    item = await _create(db, title="Henri", media_type=MediaType.podcast, uri="spotify://podcast/p1")
    fake_ma.episodes = [
        FakeEpisode("Ep1", "spotify://episode/e1", 1, duration=600, resume_ms=5000),
        FakeEpisode("Ep2", "spotify://episode/e2", 2),
    ]

    r = await client.get(f"/api/v1/quick/item/{item.id}/children?limit=1")
    assert r.status_code == 200
    data = r.json()
    assert data["media_type"] == "podcast"
    assert data["count"] == 1
    assert data["has_more"] is True
    e = data["items"][0]
    assert e["title"] == "Ep1"
    assert e["uri"] == "spotify://episode/e1"
    assert e["cover_url"] == "thumb/spotify://episode/e1?s=300"
    assert e["resume_s"] == 5
    assert e["seek"] is None
    assert ("episodes", "p1", "spotify") in fake_ma.calls

    r2 = await client.get(f"/api/v1/quick/item/{item.id}/children?offset=1&limit=1")
    d2 = r2.json()
    assert d2["has_more"] is False
    assert d2["items"][0]["title"] == "Ep2"


# --- Children: audiobook ---------------------------------------------------

@pytest.mark.asyncio
async def test_children_audiobook_chapters(client, db, fake_ma):
    item = await _create(db, title="Prince", media_type=MediaType.audiobook, uri="spotify://audiobook/b1")
    fake_ma.audiobook = FakeAudiobook(
        "spotify://audiobook/b1",
        chapters=[
            {"position": 1, "name": "Ch1", "start": 0, "end": 60},
            {"position": 2, "name": "Ch2", "start": 60, "end": 150},
        ],
    )

    r = await client.get(f"/api/v1/quick/item/{item.id}/children")
    assert r.status_code == 200
    data = r.json()
    assert data["media_type"] == "audiobook"
    assert data["count"] == 2
    assert data["has_more"] is False
    c0, c1 = data["items"]
    assert c0["uri"] == "spotify://audiobook/b1"   # chapters share the book uri
    assert c0["seek"] == 0
    assert c0["cover_url"] is None                  # no per-chapter thumbnail
    assert c0["duration_s"] == 60
    assert c1["seek"] == 60


@pytest.mark.asyncio
async def test_children_rejects_non_drillable(client, db):
    item = await _create(db, title="Mix", media_type=MediaType.playlist, uri="spotify://playlist/x")
    r = await client.get(f"/api/v1/quick/item/{item.id}/children")
    assert r.status_code == 400

    r404 = await client.get("/api/v1/quick/item/nope/children")
    assert r404.status_code == 404


# --- Transport controls ----------------------------------------------------

@pytest.mark.asyncio
async def test_transport_commands(client, fake_ma):
    assert (await client.post("/api/v1/ma/pause?queue_id=spk")).status_code == 200
    assert (await client.post("/api/v1/ma/resume?queue_id=spk")).status_code == 200
    assert (await client.post("/api/v1/ma/next?queue_id=spk")).status_code == 200
    assert (await client.post("/api/v1/ma/previous?queue_id=spk")).status_code == 200
    assert (await client.post("/api/v1/ma/stop?queue_id=spk")).status_code == 200
    assert (await client.post("/api/v1/ma/seek?queue_id=spk&position=42")).status_code == 200
    assert ("pause", "spk") in fake_ma.calls
    assert ("play", "spk") in fake_ma.calls       # resume maps to play
    assert ("next", "spk") in fake_ma.calls
    assert ("seek", "spk", 42) in fake_ma.calls


@pytest.mark.asyncio
async def test_shuffle_repeat_volume(client, fake_ma):
    assert (await client.post("/api/v1/ma/shuffle?queue_id=spk&enabled=true")).status_code == 200
    assert ("shuffle", "spk", True) in fake_ma.calls

    assert (await client.post("/api/v1/ma/repeat?queue_id=spk&mode=all")).status_code == 200
    assert ("repeat", "spk", "all") in fake_ma.calls
    assert (await client.post("/api/v1/ma/repeat?queue_id=spk&mode=bogus")).status_code == 422

    assert (await client.post("/api/v1/ma/volume?queue_id=spk&level=30")).status_code == 200
    assert ("volume", "spk", 30) in fake_ma.calls
    assert (await client.post("/api/v1/ma/volume?queue_id=spk&level=200")).status_code == 422

    up = await client.post("/api/v1/ma/volume_step?queue_id=spk&direction=up")
    assert up.status_code == 200
    assert ("vol_up", "spk") in fake_ma.calls
    bad = await client.post("/api/v1/ma/volume_step?queue_id=spk&direction=sideways")
    assert bad.status_code == 422

    assert (await client.post("/api/v1/ma/mute?queue_id=spk&muted=true")).status_code == 200
    assert ("mute", "spk", True) in fake_ma.calls
    assert (await client.post("/api/v1/ma/power?queue_id=spk&powered=false")).status_code == 200
    assert ("power", "spk", False) in fake_ma.calls


@pytest.mark.asyncio
async def test_now_playing(client):
    r = await client.get("/api/v1/ma/now_playing?queue_id=spk")
    assert r.status_code == 200
    data = r.json()
    assert data["queue_id"] == "spk"
    assert data["state"] == "playing"
    assert data["shuffle"] is True
    assert data["repeat"] == "all"
    assert data["volume"] == 40


def test_resolve_prefers_source_uri_over_provider():
    """library://audiobook/29 must resolve to (library, 29), not (audible, 29)."""
    from app.api.quick import _resolve_ma_provider_and_id

    class It:
        source_uri = "library://audiobook/29"
        provider = "audible"  # origin provider — must NOT win over the source_uri scheme
        metadata_extra = {"ma_item_id": "29"}

    assert _resolve_ma_provider_and_id(It()) == ("library", "29")

    class NoUri:
        source_uri = ""
        provider = "spotify"
        metadata_extra = {"ma_item_id": "abc"}

    assert _resolve_ma_provider_and_id(NoUri()) == ("spotify", "abc")
