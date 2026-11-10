"""Pointing at a row of the Cytoskeleton Subunits list lights its subunit up.

Blender tells no one which list row the mouse is over, but it does know which
button is under the mouse in a region: ``context.property``, read with that
region as the context, is the property of the button there. Each row of the
list is one wide button (its checkbox and name), so the property names the
row: ``pb_filament.subunits[12].select``, or ``.hide`` for its eye.

Its colour swatch (``subunits[12].color``, or ``pb_filament.colors[3].color``
once painted) lights nothing. That is where a colour is chosen, and the
highlight is drawn instead of the subunit's colour; Blender keeps naming the
swatch for as long as its colour picker is open, so a lit swatch hid every
colour picked in it until the picker closed.

While the panel is on screen a light timer reads that and lays a highlight
over the subunit (``subunit_colors.LIST_LAYER``). The panel's draw starts the
timer, and it stops itself a little while after the mouse has left the list,
clearing the highlight as it goes, so nothing runs while the panel is unused.
"""

import re

import bpy

from ..core import subunit_colors

#: How often to look, and how many empty looks before stopping.
INTERVAL = 0.05
IDLE_LOOKS = 40

_ROW = re.compile(r"^pb_filament\.subunits\[(\d+)\]\.(\w+)$")

#: ``(molecule id, key)`` lit now, and how many looks found nothing.
_STATE = {"lit": None, "idle": 0}


def _properties_regions():
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", ()):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "PROPERTIES":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    yield window, area, region


def row_under_mouse():
    """``(molecule, key)`` of the Subunits row the mouse is over, or None."""
    for window, area, region in _properties_regions():
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                found = bpy.context.property
        except (AttributeError, RuntimeError, TypeError):
            continue
        if not found:
            continue
        owner, path, _index = found
        match = _ROW.match(path or "")
        params = getattr(owner, "pb_filament", None)
        if match is None or params is None or match.group(2) == "color":
            continue
        rows = params.subunits
        index = int(match.group(1))
        if index >= len(rows):
            continue
        molecule = subunit_colors.molecule_of_object(owner)
        if molecule is not None:
            return molecule, rows[index].name
    return None


def _molecule(molecule_id):
    from ..utils.scene_manager import ProteinBlenderScene
    return ProteinBlenderScene.get_instance().molecules.get(molecule_id)


def _light(found) -> None:
    lit = (found[0].identifier, found[1]) if found else None
    if lit == _STATE["lit"]:
        return
    previous = _STATE["lit"]
    _STATE["lit"] = lit
    if previous is not None and (lit is None or previous[0] != lit[0]):
        molecule = _molecule(previous[0])
        if molecule is not None:
            subunit_colors.set_overlay(molecule, {}, subunit_colors.LIST_LAYER)
    if lit is not None:
        subunit_colors.set_overlay(found[0], {lit[1]: subunit_colors.HOVER_TINT},
                                   subunit_colors.LIST_LAYER)
    for _window, area, _region in _viewports():
        area.tag_redraw()


def _viewports():
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", ()):
        if window.screen is None:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                yield window, area, None


def _look():
    try:
        found = row_under_mouse()
        _light(found)
    except ReferenceError:
        found = None
        _STATE["lit"] = None
    _STATE["idle"] = 0 if found else _STATE["idle"] + 1
    if _STATE["idle"] > IDLE_LOOKS:
        return None
    return INTERVAL


def watch() -> None:
    """Look for a pointed-at row until the mouse has been away for a while."""
    _STATE["idle"] = 0
    if not bpy.app.timers.is_registered(_look):
        bpy.app.timers.register(_look, first_interval=INTERVAL)


def stop() -> None:
    """Stop looking and take the highlight off."""
    if bpy.app.timers.is_registered(_look):
        bpy.app.timers.unregister(_look)
    try:
        _light(None)
    except ReferenceError:
        _STATE["lit"] = None
