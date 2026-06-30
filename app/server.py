"""Run the full API and the dedicated ESP API on two ports in one process.

The main app (:data:`app.main.app`) keeps everything — admin CRUD, RFID, the HTML
frontend — on ``settings.port`` (fronted by the public HTTPS reverse proxy). The trimmed
ESP app (:data:`app.esp_app.esp_app`) is served on ``settings.esp_port`` so it can be
exposed directly on a fast, plaintext internal network, without surfacing the management
UI. Both share the same process / database engine; the main app owns table initialisation.

Run with ``python -m app.server``.
"""

from __future__ import annotations

import asyncio
import signal

import uvicorn

from app.config import settings


def _build(target: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(target, host=settings.host, port=port, log_level="info")
    server = uvicorn.Server(config)
    # Each uvicorn server would otherwise install its own signal handlers and clobber the
    # others'; we install one shared handler below instead so SIGTERM stops both cleanly.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    return server


async def _serve() -> None:
    servers = [
        _build("app.main:app", settings.port),
        _build("app.esp_app:esp_app", settings.esp_port),
    ]

    def _request_shutdown() -> None:
        for s in servers:
            s.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
