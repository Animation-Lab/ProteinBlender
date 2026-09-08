"""ProteinBlender's custom UI icons.

Blender's built-in icon set has nothing that reads as "split this domain in
two" or "merge these domains", so those buttons ship their own images. The
PNGs live in ``resources/icons/`` and are drawn by ``scripts/generate_icons.py``
- edit the shapes there and re-run it rather than editing pixels.

Loaded through ``bpy.utils.previews`` at register time. Look an icon up with
:func:`button_icon`, which hands back the keyword arguments for
``layout.operator`` / ``layout.label`` and falls back to a built-in icon if
the image failed to load, so a missing file degrades to a working button
rather than a blank one.
"""

import logging
import os

import bpy
import bpy.utils.previews

logger = logging.getLogger(__name__)

_collection = None
_palette_colors = {}

_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "resources", "icons")


def icon_id(name):
    """The preview icon id for ``name``, or 0 when it is not loaded."""
    if _collection is None:
        return 0
    icon = _collection.get(name)
    return icon.icon_id if icon else 0


def button_icon(name, fallback):
    """Keyword arguments giving a layout element this icon.

    ``layout.operator(..., **button_icon("split_domain", 'MOD_ARRAY'))``.
    The built-in ``fallback`` keeps the button usable if the image is missing.
    """
    loaded = icon_id(name)
    return {"icon_value": loaded} if loaded else {"icon": fallback}


def update_palette_icon(key, colors):
    """Two adjoining preview tiles form a full-width color swatch.

    Keep two previews per mixed row and update them in place when recolored;
    dragging a picker must not allocate an unbounded set of preview images.
    Preview pixels are display-referred sRGB, while COLOR properties are linear.
    """
    if _collection is None:
        return
    colors = tuple(tuple(color) for color in colors[:4])
    if _palette_colors.get(key) == colors:
        return

    def srgb(value):
        return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055

    bands = [tuple(srgb(c) for c in color[:3]) + (1.0,) for color in colors]
    # Blender limits an operator icon to a square regardless of button width.
    # Draw the two halves separately so the colored area spans the same width
    # as the native color property. Both halves open the same shared picker.
    size = 32
    for half in range(2):
        pixels = []
        for y in range(size):
            for x in range(size):
                band = (half * size + x) * len(bands) // (2 * size)
                pixels.extend(bands[band])
        tile_key = f"{key}:{half}"
        preview = _collection.get(tile_key)
        if preview is None:
            preview = _collection.new(tile_key)
        preview.icon_size = (size, size)
        preview.icon_pixels_float = pixels
    _palette_colors[key] = colors


def prune_palette_icons(active_keys):
    """Release previews for rows that were deleted or now have a solid color."""
    for key in set(_palette_colors) - active_keys:
        for half in range(2):
            tile_key = f"{key}:{half}"
            if _collection is not None and tile_key in _collection:
                del _collection[tile_key]
        del _palette_colors[key]


def register():
    global _collection
    unregister()
    _collection = bpy.utils.previews.new()
    if not os.path.isdir(_ICON_DIR):
        logger.error(f"icon directory missing: {_ICON_DIR}")
        return
    for filename in sorted(os.listdir(_ICON_DIR)):
        if not filename.endswith(".png"):
            continue
        name = os.path.splitext(filename)[0]
        try:
            _collection.load(name, os.path.join(_ICON_DIR, filename), 'IMAGE')
        except Exception as exc:
            logger.error(f"failed to load icon {filename}: {exc}")


def unregister():
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
        _collection = None
    _palette_colors.clear()
