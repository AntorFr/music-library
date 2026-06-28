from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.services.music_assistant import MusicAssistantClient


class _FakeWebSocket:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages

    def __aiter__(self) -> _FakeWebSocket:
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return json.dumps(self._messages.pop(0))


@pytest.mark.asyncio
async def test_reader_accumulates_partial_results() -> None:
    ma = MusicAssistantClient(url="http://music-assistant.local:8095")
    fut = asyncio.get_running_loop().create_future()
    ma._pending["msg-1"] = fut
    ma._ws = _FakeWebSocket(  # type: ignore[assignment]
        [
            {"event": "players/updated", "object_id": "speaker"},
            {
                "message_id": "msg-1",
                "result": [{"name": "Episode 1"}],
                "partial": True,
            },
            {
                "message_id": "msg-1",
                "result": [{"name": "Episode 2"}],
                "partial": True,
            },
            {"message_id": "msg-1", "result": [{"name": "Episode 3"}]},
        ]
    )

    await ma._reader_loop()

    assert fut.result()["result"] == [
        {"name": "Episode 1"},
        {"name": "Episode 2"},
        {"name": "Episode 3"},
    ]
    assert ma._pending == {}
    assert ma._partial_results == {}
