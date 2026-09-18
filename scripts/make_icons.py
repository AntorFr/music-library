#!/usr/bin/env python3
"""Generate the app icon — the SVG and the PNGs iOS and Android need.

The mark follows the Home Assistant family charter, which Music Assistant and
ESPHome follow too: one shared house silhouette in #18BCF2, and a flat #F2F4F9
glyph inside it that belongs to the project. Ours is three centred bars — a
catalogue. Music Assistant already owns the vertical axis, so we take the other.

The house geometry was measured off the official brand icon
(brands.home-assistant.io/homeassistant/icon@2x.png), not copied from the Home
Assistant *sticker*, whose house is squatter — a roof 10px lower at the apex and
26px lower at the shoulders, on a 512 canvas. In the icon the apex touches the
top of the square and the shoulders sit at exactly half height, with a 45° roof.
Checked against that PNG row by row: the largest deviation is 1px in 512.

Why PNGs at all: iOS Safari ignores SVG for apple-touch-icon and for the
manifest icons, so "Add to Home Screen" falls back to a screenshot of the page.

The PNGs get a white ground because iOS composites a transparent icon over
black, which would swallow the house. The SVG stays transparent like the rest of
the family, so it sits on whatever a browser tab or the sidebar provides.

Usage:  python scripts/make_icons.py
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "img"

#: The whole drawing is expressed on this square, the one the measurements used.
BOX = 512
#: Rendered at this resolution then downscaled — cheap anti-aliasing.
SUPERSAMPLE = 2048

HOUSE = "#18BCF2"      # sampled from the official icons; identical on all three
GLYPH = "#F2F4F9"      # idem
GROUND = "#FFFFFF"     # PNG only — see the module docstring

#: Corners of the house before rounding, clockwise from the bottom-left, with
#: the radius applied at each. The apex lands on the top edge and the shoulders
#: at half height, which is what makes the silhouette the family's rather than
#: merely house-shaped.
HOUSE_CORNERS = [((0, 512), 32), ((0, 256), 80), ((256, 0), 30),
                 ((512, 256), 80), ((512, 512), 32)]

#: The glyph: three bars, centred, in the band Music Assistant uses for its own.
BARS = [(258, 340), (328, 244), (398, 296)]   # (y, width), height 46, fully rounded
BAR_H = 46

#: (filename, pixel size) — 180 is the iOS home-screen size, 192/512 the manifest ones.
TARGETS = [("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)]


def _rounded_corner(prev_pt, corner, next_pt, radius, steps=48):
    """Points along the arc that rounds `corner`, tangent to both its edges."""
    (cx, cy), (px, py), (nx, ny) = corner, prev_pt, next_pt
    v1 = (px - cx, py - cy)
    v2 = (nx - cx, ny - cy)
    l1 = math.hypot(*v1)
    l2 = math.hypot(*v2)
    u1 = (v1[0] / l1, v1[1] / l1)
    u2 = (v2[0] / l2, v2[1] / l2)

    interior = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
    tangent = radius / math.tan(interior / 2)          # along each edge
    centre_d = radius / math.sin(interior / 2)         # along the bisector

    bis = (u1[0] + u2[0], u1[1] + u2[1])
    bl = math.hypot(*bis)
    centre = (cx + bis[0] / bl * centre_d, cy + bis[1] / bl * centre_d)

    start = (cx + u1[0] * tangent, cy + u1[1] * tangent)
    end = (cx + u2[0] * tangent, cy + u2[1] * tangent)
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    # Sweep the short way round.
    while a1 - a0 > math.pi:
        a1 -= 2 * math.pi
    while a0 - a1 > math.pi:
        a1 += 2 * math.pi

    return [(centre[0] + radius * math.cos(a0 + (a1 - a0) * i / steps),
             centre[1] + radius * math.sin(a0 + (a1 - a0) * i / steps))
            for i in range(steps + 1)]


def house_points(scale: float) -> list[tuple[float, float]]:
    """The house outline as a dense polygon, ready for Pillow."""
    pts: list[tuple[float, float]] = []
    n = len(HOUSE_CORNERS)
    for i, (corner, radius) in enumerate(HOUSE_CORNERS):
        prev_pt = HOUSE_CORNERS[(i - 1) % n][0]
        next_pt = HOUSE_CORNERS[(i + 1) % n][0]
        pts.extend(_rounded_corner(prev_pt, corner, next_pt, radius))
    return [(x * scale, y * scale) for x, y in pts]


def svg() -> str:
    """The vector icon, transparent outside the house like the rest of the family."""
    path = []
    n = len(HOUSE_CORNERS)
    for i, (corner, radius) in enumerate(HOUSE_CORNERS):
        prev_pt = HOUSE_CORNERS[(i - 1) % n][0]
        next_pt = HOUSE_CORNERS[(i + 1) % n][0]
        (cx, cy) = corner
        v1 = (prev_pt[0] - cx, prev_pt[1] - cy)
        v2 = (next_pt[0] - cx, next_pt[1] - cy)
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)
        interior = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
        t = radius / math.tan(interior / 2)
        path.append((
            (cx + u1[0] * t, cy + u1[1] * t),
            (cx + u2[0] * t, cy + u2[1] * t),
            radius,
        ))

    d = f"M{path[0][1][0]:g},{path[0][1][1]:g}"
    for i in range(1, n + 1):
        (t1, t2, r) = path[i % n]
        d += f"L{t1[0]:g},{t1[1]:g}A{r:g},{r:g} 0 0 1 {t2[0]:g},{t2[1]:g}"
    d += "Z"

    bars = "\n    ".join(
        f'<rect x="{256 - w / 2:g}" y="{y:g}" width="{w:g}" height="{BAR_H}" '
        f'rx="{BAR_H / 2:g}"/>'
        for y, w in BARS
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}"
     role="img" aria-label="Music Library">
  <title>Music Library</title>
  <path d="{d}" fill="{HOUSE}"/>
  <g fill="{GLYPH}">
    {bars}
  </g>
</svg>
"""


def build(opaque: bool) -> Image.Image:
    scale = SUPERSAMPLE / BOX
    mode = "RGB" if opaque else "RGBA"
    bg = GROUND if opaque else (0, 0, 0, 0)
    img = Image.new(mode, (SUPERSAMPLE, SUPERSAMPLE), bg)
    draw = ImageDraw.Draw(img)

    draw.polygon(house_points(scale), fill=HOUSE)
    for y, w in BARS:
        x0 = (256 - w / 2) * scale
        draw.rounded_rectangle(
            [x0, y * scale, x0 + w * scale, (y + BAR_H) * scale],
            radius=BAR_H / 2 * scale, fill=GLYPH,
        )
    return img


def main() -> None:
    svg_path = OUT_DIR / "favicon.svg"
    svg_path.write_text(svg(), encoding="utf-8")
    print(f"{svg_path.relative_to(OUT_DIR.parents[2])}  {svg_path.stat().st_size} B")

    icon = build(opaque=True)
    for name, size in TARGETS:
        out = icon.resize((size, size), Image.LANCZOS)
        path = OUT_DIR / name
        out.save(path, "PNG", optimize=True)
        print(f"{path.relative_to(OUT_DIR.parents[2])}  {size}x{size}  {path.stat().st_size} B")


if __name__ == "__main__":
    main()
