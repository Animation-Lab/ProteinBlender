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
