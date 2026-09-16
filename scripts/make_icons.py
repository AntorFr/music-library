#!/usr/bin/env python3
"""Rasterise the app icon (app/static/img/favicon.svg) into the PNGs iOS/Android need.

Why PNGs at all: iOS Safari ignores SVG for ``apple-touch-icon`` (and for the manifest
icons), so "Add to Home Screen" falls back to a screenshot of the page unless a PNG is
offered. Same story for the Android/Chrome install prompt.

The corners are deliberately left **square** even though the SVG is a rounded square:
both platforms apply their own mask (squircle on iOS, adaptive shape on Android). A
pre-rounded icon would be rounded twice and show dark gaps in the corners.

The shapes are redrawn here rather than rasterised from the SVG so the script needs no
SVG toolchain — Pillow is already a project dependency. Keep the two in sync by eye; the
coordinates below are the SVG's own 256x256 viewBox units.

Usage:  python scripts/make_icons.py
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "img"

#: Rendered at this resolution then downscaled — cheap anti-aliasing.
SUPERSAMPLE = 2048
#: SVG viewBox side, the unit all coordinates below are expressed in.
VIEWBOX = 256

GRADIENT_FROM = (3, 155, 229)    # #039be5
GRADIENT_TO = (2, 136, 209)      # #0288d1

#: (filename, pixel size) — 180 is the iOS home-screen size, 192/512 the manifest ones.
TARGETS = [
    ("apple-touch-icon.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
]


def _scale(value: float) -> float:
    return value * SUPERSAMPLE / VIEWBOX


def _gradient_background() -> Image.Image:
    """Diagonal top-left -> bottom-right gradient, matching the SVG's linearGradient."""
    img = Image.new("RGB", (SUPERSAMPLE, SUPERSAMPLE))
    pixels = img.load()
    span = 2 * (SUPERSAMPLE - 1)
    for y in range(SUPERSAMPLE):
        for x in range(SUPERSAMPLE):
            t = (x + y) / span
            pixels[x, y] = tuple(
                round(a + (b - a) * t) for a, b in zip(GRADIENT_FROM, GRADIENT_TO, strict=True)
            )
    return img


def _draw_house(base: Image.Image) -> None:
    """Translucent house outline — a separate layer so the 25% alpha composites properly."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    points = [(128, 52), (56, 112), (56, 204), (200, 204), (200, 112)]
    scaled = [(_scale(x), _scale(y)) for x, y in points]
    width = round(_scale(10))
    draw.line([*scaled, scaled[0]], fill=(255, 255, 255, 64), width=width, joint="curve")
    # `joint="curve"` rounds the inner joints; the closing vertex needs its own cap.
    radius = width / 2
    for x, y in scaled:
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255, 64))
    base.alpha_composite(layer)


def _rotated_note_head(cx: float, cy: float, rx: float, ry: float, angle: float) -> Image.Image:
    """An ellipse rotated about its own centre, as its own transparent tile."""
    box = round(_scale(max(rx, ry)) * 4)
    tile = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    mid = box / 2
    ImageDraw.Draw(tile).ellipse(
        [mid - _scale(rx), mid - _scale(ry), mid + _scale(rx), mid + _scale(ry)],
        fill=(255, 255, 255, 255),
    )
    return tile.rotate(angle, resample=Image.BICUBIC)


def _draw_notes(base: Image.Image) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    for x, y, w, h in [(96, 88, 6, 80), (152, 76, 6, 80)]:           # stems
        draw.rounded_rectangle(
            [_scale(x), _scale(y), _scale(x + w), _scale(y + h)],
            radius=_scale(3), fill=(255, 255, 255, 255),
        )
    draw.polygon(                                                     # beam
        [(_scale(96), _scale(88)), (_scale(102), _scale(88)),
         (_scale(158), _scale(76)), (_scale(152), _scale(76))],
        fill=(255, 255, 255, 255),
    )
    for cx, cy in [(88, 168), (144, 156)]:                            # note heads
        head = _rotated_note_head(cx, cy, 18, 13, 15)                 # SVG rotates -15deg
        layer.alpha_composite(
            head, (round(_scale(cx) - head.width / 2), round(_scale(cy) - head.height / 2))
        )

    base.alpha_composite(layer)


def build() -> Image.Image:
    icon = _gradient_background().convert("RGBA")
    _draw_house(icon)
    _draw_notes(icon)
    return icon


def main() -> None:
    icon = build()
    for name, size in TARGETS:
        # RGB, not RGBA: iOS renders a transparent icon over black, and we want the gradient.
        out = icon.resize((size, size), Image.LANCZOS).convert("RGB")
        path = OUT_DIR / name
        out.save(path, "PNG", optimize=True)
        print(f"{path.relative_to(OUT_DIR.parents[2])}  {size}x{size}  {path.stat().st_size} B")


if __name__ == "__main__":
    main()
