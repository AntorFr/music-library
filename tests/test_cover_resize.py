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


def test_resize_bmp_format(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    Image.new("RGB", (300, 300), (10, 20, 30)).save(tmp_path / "abc.jpg", "JPEG")

    p = cover_service.get_or_make_resized("abc", 64, "bmp")
    assert p is not None and p.exists()
    assert p.name == "abc_64.bmp"
    with Image.open(p) as im:
        assert im.format == "BMP" and im.size == (64, 64)
    assert cover_service.media_type_for("bmp") == "image/bmp"

    # Both encodings coexist in the cache, and clear_resized drops both.
    cover_service.get_or_make_resized("abc", 64, "jpg")
    assert (tmp_path / "abc_64.jpg").exists() and (tmp_path / "abc_64.bmp").exists()
    cover_service.clear_resized("abc")
    assert not (tmp_path / "abc_64.jpg").exists() and not (tmp_path / "abc_64.bmp").exists()


def test_bmp_native_size_conversion(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    Image.new("RGB", (300, 300)).save(tmp_path / "abc.jpg", "JPEG")
    p = cover_service.get_or_make_resized("abc", None, "bmp")  # no resize, just convert
    assert p is not None and p.name == "abc_orig.bmp"
    with Image.open(p) as im:
        assert im.format == "BMP" and im.size == (300, 300)


def test_unknown_fmt_falls_back_to_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "covers_dir", tmp_path)
    Image.new("RGB", (300, 300)).save(tmp_path / "abc.jpg", "JPEG")
    assert cover_service.media_type_for("webp") == "image/jpeg"
    p = cover_service.get_or_make_resized("abc", 48, "webp")
    assert p is not None and p.name == "abc_48.jpg"
