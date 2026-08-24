"""Generate ProteinBlender's custom UI icons.

Draws the toolbar icons the add-on ships under
``proteinblender/resources/icons/`` and writes them as 64x64 RGBA PNGs.
Pure stdlib (zlib + struct), so it runs under any Python - no PIL, no Blender.

Run it after editing a shape below:

    python scripts/generate_icons.py

The icons are deliberately simple before-above / after-below diagrams, because
Blender draws them at roughly 16px:

* ``split_domain``: one bar with a cut mark, becoming two separate bars.
* ``merge_domains``: two separate bars, becoming one bar.
"""

from __future__ import annotations

import os
import struct
import zlib

SIZE = 64          # final icon edge, px
SUPERSAMPLE = 4    # subpixels per pixel edge, for anti-aliasing
COLOR = (204, 204, 204)  # neutral grey: legible on dark and light themes


# ---------------------------------------------------------------------------
# Shape tests. All coordinates are in the 64-unit icon space; y grows down.
# ---------------------------------------------------------------------------

def rounded_bar(x0, y0, x1, y1):
    """A horizontal bar with fully rounded ends."""
    radius = (y1 - y0) / 2.0

    def inside(x, y):
        if not (y0 <= y <= y1):
            return False
        if x0 + radius <= x <= x1 - radius:
            return True
        for cx in (x0 + radius, x1 - radius):
            if (x - cx) ** 2 + (y - (y0 + radius)) ** 2 <= radius ** 2:
                return True
        return False

    return inside


def slanted_gap(cx, y0, y1, width, slope):
    """A slanted band, used to carve the cut mark out of a bar."""
    def inside(x, y):
        if not (y0 <= y <= y1):
            return False
        centre = cx + (y - (y0 + y1) / 2.0) * slope
        return abs(x - centre) <= width / 2.0

    return inside


def down_arrow(cx, y0, y1, half_width):
    """A downward-pointing triangle: "the layout above becomes the one below"."""
    def inside(x, y):
        if not (y0 <= y <= y1):
            return False
        t = (y - y0) / (y1 - y0)
        return abs(x - cx) <= half_width * (1.0 - t)

    return inside


def coverage(shapes, holes, x, y):
    if any(hole(x, y) for hole in holes):
        return False
    return any(shape(x, y) for shape in shapes)


# ---------------------------------------------------------------------------
# The icons
# ---------------------------------------------------------------------------

BAR_TOP = (8.0, 21.0)
BAR_BOTTOM = (43.0, 56.0)
FULL_X = (6.0, 58.0)
LEFT_X = (6.0, 29.0)
RIGHT_X = (35.0, 58.0)
ARROW = down_arrow(32.0, 26.0, 38.0, 6.5)

ICONS = {
    "split_domain": {
        "shapes": [
            rounded_bar(FULL_X[0], BAR_TOP[0], FULL_X[1], BAR_TOP[1]),
            ARROW,
            rounded_bar(LEFT_X[0], BAR_BOTTOM[0], LEFT_X[1], BAR_BOTTOM[1]),
            rounded_bar(RIGHT_X[0], BAR_BOTTOM[0], RIGHT_X[1], BAR_BOTTOM[1]),
        ],
        # The cut mark: a slanted notch through the whole bar, so the icon
        # reads as "this one gets cut there" rather than as three plain bars.
        "holes": [slanted_gap(32.0, BAR_TOP[0], BAR_TOP[1], 3.0, 0.45)],
    },
    "merge_domains": {
        "shapes": [
            rounded_bar(LEFT_X[0], BAR_TOP[0], LEFT_X[1], BAR_TOP[1]),
            rounded_bar(RIGHT_X[0], BAR_TOP[0], RIGHT_X[1], BAR_TOP[1]),
            ARROW,
            rounded_bar(FULL_X[0], BAR_BOTTOM[0], FULL_X[1], BAR_BOTTOM[1]),
        ],
        "holes": [],
    },
}


# ---------------------------------------------------------------------------
# Rasterise + PNG writer
# ---------------------------------------------------------------------------

def rasterise(shapes, holes):
    subpixels = SUPERSAMPLE * SUPERSAMPLE
    rows = []
    for py in range(SIZE):
        row = bytearray()
        for px in range(SIZE):
            hits = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = px + (sx + 0.5) / SUPERSAMPLE
                    y = py + (sy + 0.5) / SUPERSAMPLE
                    if coverage(shapes, holes, x, y):
                        hits += 1
            alpha = round(255 * hits / subpixels)
            row.extend((*COLOR, alpha))
        rows.append(bytes(row))
    return rows


def write_png(path, rows):
    def chunk(tag, payload):
        data = tag + payload
        return (struct.pack(">I", len(payload)) + data
                + struct.pack(">I", zlib.crc32(data)))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", header))
        handle.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        handle.write(chunk(b"IEND", b""))


def main():
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "proteinblender", "resources", "icons")
    os.makedirs(target, exist_ok=True)
    for name, spec in ICONS.items():
        path = os.path.join(target, f"{name}.png")
        write_png(path, rasterise(spec["shapes"], spec["holes"]))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
