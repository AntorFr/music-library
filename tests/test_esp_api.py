"""Tests for the dedicated ESP API surface (app.esp_app) and the thumbnail proxy cache."""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.esp_app import esp_app
from app.services import cover_service


def _esp_routes() -> set[tuple[str, str]]:
    paths = esp_app.openapi()["paths"]
    return {(p, m.upper()) for p, methods in paths.items() for m in methods}


def test_esp_surface_includes_only_device_endpoints():
    routes = _esp_routes()
    # Endpoints the device needs are present...
    for r in [
        ("/api/v1/quick/thumb", "GET"),
        ("/api/v1/quick/{owner}", "GET"),
        ("/api/v1/quick/item/{media_id}/children", "GET"),
        ("/covers/{media_id}.jpg", "GET"),
        ("/api/v1/ma/now_playing", "GET"),
        ("/api/v1/ma/play", "POST"),
        ("/api/v1/health", "GET"),
    ]:
        assert r in routes, f"missing {r}"
    # ...while the RFID API and HTML frontend never reach this surface.
    assert not any(p.startswith("/api/v1/rfid") for p, _ in routes)
    assert ("/", "GET") not in routes


@pytest.fixture
async def esp_client():
    transport = ASGITransport(app=esp_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("path", ["/api/v1/ma/import", "/api/v1/media/abc/cover"])
async def test_admin_writes_blocked(esp_client: AsyncClient, path: str):
    # Library-mutating writes that ride the shared routers are not reachable here.
    assert (await esp_client.post(path)).status_code == 404


async def test_thumb_rejects_missing_or_bad_signature(esp_client: AsyncClient):
    # No signature, and a forged one, are both refused — any host, no allow-list needed.
    r = await esp_client.get(
        "/api/v1/quick/thumb", params={"src": "https://evil.example.com/x.jpg", "size": 96}
    )
    assert r.status_code == 422  # `sig` is required
    r = await esp_client.get(
        "/api/v1/quick/thumb",
        params={"src": "https://evil.example.com/x.jpg", "size": 96, "sig": "deadbeef"},
    )
    assert r.status_code == 403


def test_thumb_signature_roundtrip():
    src, size = "https://i.scdn.co/image/abc", 96
    sig = cover_service.sign_thumb(src, size)
    assert cover_service.verify_thumb(src, size, sig)
    assert not cover_service.verify_thumb(src, size, "deadbeef")
    assert not cover_service.verify_thumb(src, size + 1, sig)  # bound to size


def test_thumbnail_cache_lru_eviction(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "thumbs_dir", tmp_path)
    monkeypatch.setattr(settings, "thumb_cache_max_bytes", 1000)

    for i in range(5):  # five 300B files, f0 oldest .. f4 newest
        f = tmp_path / f"f{i}_96.jpg"
        f.write_bytes(b"x" * 300)
        t = time.time() - (5 - i) * 10
        os.utime(f, (t, t))

    cover_service._enforce_thumb_cache_limit()

    remaining = {p.name for p in tmp_path.glob("*.jpg")}
    total = sum(p.stat().st_size for p in tmp_path.glob("*.jpg"))
    assert total <= 900  # trimmed to the 90% low-water mark
    assert "f0_96.jpg" not in remaining  # oldest evicted first
    assert {"f3_96.jpg", "f4_96.jpg"} <= remaining  # newest kept
