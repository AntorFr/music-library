from __future__ import annotations

from PIL import Image

from app.config import settings
from app.services import cover_service


def test_resize_creates_cached_variant(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    Image.new("RGB", (300, 300), (10, 20, 30)).save(tmp_path / "abc.jpg", "JPEG")

    p = cover_service.get_or_make_resized("abc", 64)
    assert p is not None and p.exists()
    assert p.name == "abc_64.jpg"
    with Image.open(p) as im:
        assert im.size == (64, 64)

    # Second call is served from cache (returns the same path).
    assert cover_service.get_or_make_resized("abc", 64) == p


def test_resize_missing_base_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    assert cover_service.get_or_make_resized("nope", 64) is None


def test_clear_resized_removes_variants_only(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    base = tmp_path / "abc.jpg"
    Image.new("RGB", (300, 300)).save(base, "JPEG")
    cover_service.get_or_make_resized("abc", 64)
    cover_service.get_or_make_resized("abc", 96)
    assert (tmp_path / "abc_64.jpg").exists()

    cover_service.clear_resized("abc")
    assert not (tmp_path / "abc_64.jpg").exists()
    assert not (tmp_path / "abc_96.jpg").exists()
    assert base.exists()  # base cover untouched
