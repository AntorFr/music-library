"""Pin: the MA models/helpers moved out of music_assistant.py stay importable from it."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import ma_helpers, ma_models, music_assistant


@pytest.mark.parametrize("name", ["MAImage", "MAMediaItem", "MAPlayer", "MASearchResults"])
def test_models_reexported_same_object(name):
    assert getattr(music_assistant, name) is getattr(ma_models, name)


@pytest.mark.parametrize("name", [
    "resolve_ma_provider_and_id", "normalize_chapters", "fetch_podcast_episodes",
    "fetch_audiobook", "_single_flight_episodes", "_episode_fetches",
])
def test_helpers_reexported_same_object(name):
    assert getattr(music_assistant, name) is getattr(ma_helpers, name)


def test_client_entry_points_defined_in_music_assistant():
    for name in ("MusicAssistantClient", "get_ma_client", "close_ma_client"):
        assert getattr(music_assistant, name).__module__ == "app.services.music_assistant"


def test_resolve_prefers_uri_then_falls_back():
    item = SimpleNamespace(source_uri="library://audiobook/29", provider="audible", metadata_extra={"ma_item_id": 5})
    assert music_assistant.resolve_ma_provider_and_id(item) == ("library", "29")
    item = SimpleNamespace(source_uri="bad", provider=" spotify ", metadata_extra={"ma_item_id": 5})
    assert music_assistant.resolve_ma_provider_and_id(item) == ("spotify", "5")
    item = SimpleNamespace(source_uri="library://x", provider="", metadata_extra=None)
    assert music_assistant.resolve_ma_provider_and_id(item) == (None, None)


def test_normalize_chapters_sorted_and_durations():
    mi = music_assistant.MAMediaItem({"metadata": {"chapters": [
        {"position": "2", "name": None, "start": "10", "end": "25"},
        {"position": 1, "name": "A", "start": None, "end": None},
    ]}})
    out = music_assistant.normalize_chapters(mi)
    assert [c["position"] for c in out] == [1, 2]
    assert out[0] == {"position": 1, "name": "A", "start": 0.0, "end": None, "duration": None}
    assert out[1]["duration"] == 15.0 and out[1]["name"] == ""


@pytest.mark.asyncio
async def test_single_flight_shares_one_fetch_and_clears():
    calls = 0

    class FakeMA:
        async def get_podcast_episodes(self, item_id, provider):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return [music_assistant.MAMediaItem({"name": "e"})]

    ma = FakeMA()
    a, b = await asyncio.gather(
        music_assistant._single_flight_episodes(ma, "p", "1"),
        music_assistant._single_flight_episodes(ma, "p", "1"),
    )
    assert calls == 1 and a is not b and len(a) == len(b) == 1
    await asyncio.sleep(0)
    assert music_assistant._episode_fetches == {}
