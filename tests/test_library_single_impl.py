"""Review tests: one get_library implementation, one /library/{kind} handler."""
from __future__ import annotations

from typing import Any

import pytest

from app.api.music_assistant import router
from app.services.music_assistant import MusicAssistantClient

KINDS = ["playlists", "albums", "tracks", "radios", "audiobooks", "podcasts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_get_library_sends_matching_command_and_filters(monkeypatch, kind) -> None:
    ma = MusicAssistantClient(url="http://music-assistant.local:8095")
    sent: list[tuple[str, dict[str, Any]]] = []

    async def fake_send(command: str, **kwargs: Any):
        sent.append((command, kwargs))
        return [{"name": "A", "uri": "library://x/1"}]

    monkeypatch.setattr(ma, "_send_command", fake_send)
    items = await getattr(ma, f"get_library_{kind}")(search="ab", limit=3)

    assert sent == [(f"music/{kind}/library_items", {"search": "ab", "limit": 3})]
    assert [i.name for i in items] == ["A"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_get_library_defaults_and_none_result(monkeypatch, kind) -> None:
    ma = MusicAssistantClient(url="http://music-assistant.local:8095")
    sent: list[tuple[str, dict[str, Any]]] = []

    async def fake_send(command: str, **kwargs: Any):
        sent.append((command, kwargs))
        return None

    monkeypatch.setattr(ma, "_send_command", fake_send)
    assert await getattr(ma, f"get_library_{kind}")() == []
    assert sent == [(f"music/{kind}/library_items", {"search": None, "limit": None})]


def test_single_library_route_handler_serves_all_six_paths() -> None:
    routes = [r for r in router.routes if "/library/" in getattr(r, "path", "")]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    for kind in KINDS:
        match, _ = routes[0].matches(
            {"type": "http", "method": "GET", "path": f"{router.prefix}/library/{kind}"}
        )
        assert match.name == "FULL"

