"""Choosing a filament's subunits and colouring them.

The Subunits list (``panels.subunit_panel``) shows every monomer of a filament.
These are its buttons: select rows, pick subunits by clicking them in the 3D
Viewport, and colour or clear the selected ones. What a colour *is* and how it
is drawn lives in ``core.subunit_colors``.
"""

import logging

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from ..core import subunit_colors

logger = logging.getLogger(__name__)


def filaments():
    """Every filament in the scene: molecules with a helical assembly built."""
    from ..core import filament_animation
    from ..utils.scene_manager import ProteinBlenderScene

    found = []
    for molecule in ProteinBlenderScene.get_instance().molecules.values():
        try:
            if filament_animation.is_filament(molecule):
                found.append(molecule)
        except ReferenceError:
            continue
    return found


def subunit_filament(context, molecule_id: str = ""):
    """The filament the Subunits list is showing.

    The one asked for by id; else the one chosen in the list's picker; else
    the active protein, if it is a filament; else the first filament.
    """
    from ..utils.scene_manager import resolve_active_molecule_id

    found = filaments()
    by_id = {molecule.identifier: molecule for molecule in found}
    for wanted in (molecule_id,
                   getattr(context.scene, "pb_subunit_filament", ""),
                   resolve_active_molecule_id(context)):
        if wanted and wanted in by_id:
            return by_id[wanted]
    return found[0] if found else None


#: Blender keeps no reference to strings an enum items callback returns.
_ITEMS_CACHE = []


def filament_items(self, context):
    """The filaments the Subunits list can show, for its picker."""
    from ..core import filament_presets

    items = []
    for molecule in filaments():
        preset = filament_presets.of_molecule(molecule)
        label = molecule.identifier
        items.append((molecule.identifier, label,
                      preset.label if preset is not None else "Helical assembly"))
    _ITEMS_CACHE[:] = items or [("", "No filament", "")]
    return _ITEMS_CACHE


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {"PROPERTIES", "VIEW_3D"}:
                area.tag_redraw()


class MOLECULE_PB_OT_color_subunits(Operator):
    """Colour the selected subunits, or give them back the filament's colour"""

    bl_idname = "molecule.color_subunits"
    bl_label = "Colour Selected"
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={"SKIP_SAVE"})
    clear: BoolProperty(
        name="Clear", default=False, options={"SKIP_SAVE"},
        description="Give the subunits back the filament's own colour")

    @classmethod
    def description(cls, context, properties):
        if getattr(properties, "clear", False):
            return ("Give the selected subunits back the filament's own "
                    "colour, and drop their colour keyframes")
        return ("Paint the selected subunits the colour beside this button. "
                "Key it with Create Keyframe to animate it")

    def execute(self, context):
        molecule = subunit_filament(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No cytoskeleton filament to colour")
            return {"CANCELLED"}
        subunit_colors.sync_roster(molecule)
        keys = subunit_colors.selected_keys(molecule)
        if not keys:
            self.report({"WARNING"}, "Select subunits in the list first")
            return {"CANCELLED"}
        if self.clear:
            done = subunit_colors.clear(molecule, keys)
            self.report({"INFO"}, f"Cleared the colour of {done} subunits")
        else:
            done = subunit_colors.paint(molecule, keys, context.scene.pb_subunit_color)
            self.report({"INFO"}, f"Coloured {done} subunits")
        _redraw(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_select_subunits(Operator):
    """Select all, none, or the other subunits of the filament"""

    bl_idname = "molecule.select_subunits"
    bl_label = "Select Subunits"
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={"SKIP_SAVE"})
    action: EnumProperty(
        name="Action",
        items=(("ALL", "All", "Select every subunit the filament has now"),
               ("NONE", "None", "Select no subunits"),
               ("INVERT", "Invert", "Select the subunits that are not selected")),
        default="ALL")

    @classmethod
    def description(cls, context, properties):
        return {"ALL": "Select every subunit the filament has now",
                "NONE": "Deselect every subunit",
                "INVERT": "Select the subunits that are not selected, and "
                          "deselect the ones that are"}[properties.action]

    def execute(self, context):
        molecule = subunit_filament(context, self.molecule_id)
        if molecule is None:
            return {"CANCELLED"}
        subunit_colors.sync_roster(molecule)
        present = subunit_colors.present_sites(molecule)
        for row in molecule.object.pb_filament.subunits:
            here = row.site in present
            if self.action == "ALL":
                row.select = here
            elif self.action == "NONE":
                row.select = False
            else:
                row.select = here and not row.select
        _redraw(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_pick_subunits(Operator):
    """Click subunits in the 3D Viewport to select them"""

    bl_idname = "molecule.pick_subunits"
    bl_label = "Pick in Viewport"
    bl_description = (
        "Point at the filament in the 3D Viewport: the subunit under the mouse "
        "lights up, and a click selects or deselects it. Right-click or Esc "
        "to finish")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={"SKIP_SAVE"})

    _HEADER = ("Pick subunits: click to select or deselect - "
               "Right-click, Enter or Esc to finish")

    def invoke(self, context, event):
        molecule = subunit_filament(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No cytoskeleton filament to pick from")
            return {"CANCELLED"}
        subunit_colors.sync_roster(molecule)
        self._molecule_id = molecule.identifier
        self._spheres = subunit_colors.subunit_spheres(molecule)
        if not self._spheres:
            self.report({"WARNING"}, "The filament has no subunits to pick")
            return {"CANCELLED"}
        self._hover = None
        context.window_manager.modal_handler_add(self)
        for area in self._viewports(context):
            area.header_text_set(self._HEADER)
        self._show(context)
        return {"RUNNING_MODAL"}

    def _molecule(self):
        from ..utils.scene_manager import ProteinBlenderScene
        return ProteinBlenderScene.get_instance().molecules.get(self._molecule_id)

    @staticmethod
    def _viewports(context):
        return [area for area in context.window.screen.areas
                if area.type == "VIEW_3D"]

    def _hit(self, context, event):
        """The subunit under the mouse, if the mouse is over a 3D Viewport."""
        from bpy_extras import view3d_utils

        x, y = event.mouse_x, event.mouse_y
        for area in self._viewports(context):
            for region in area.regions:
                if region.type != "WINDOW":
                    continue
                if not (region.x <= x < region.x + region.width
                        and region.y <= y < region.y + region.height):
                    continue
                view = area.spaces.active.region_3d
                where = (x - region.x, y - region.y)
                origin = view3d_utils.region_2d_to_origin_3d(region, view, where)
                direction = view3d_utils.region_2d_to_vector_3d(region, view, where)
                molecule = self._molecule()
                if molecule is None:
                    return None, True
                return subunit_colors.subunit_on_ray(
                    molecule, origin, direction, self._spheres), True
        return None, False

    def _show(self, context):
        molecule = self._molecule()
        if molecule is None:
            return
        tints = {row.name: subunit_colors.SELECTED_TINT
                 for row in molecule.object.pb_filament.subunits if row.select}
        if self._hover is not None:
            tints[self._hover] = subunit_colors.HOVER_TINT
        subunit_colors.set_overlay(molecule, tints)
        _redraw(context)

    def _finish(self, context):
        molecule = self._molecule()
        if molecule is not None:
            subunit_colors.set_overlay(molecule, {})
        for area in self._viewports(context):
            area.header_text_set(None)
        _redraw(context)

    def modal(self, context, event):
        if self._molecule() is None:
            self._finish(context)
            return {"CANCELLED"}
        if event.type in {"ESC", "RIGHTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self._finish(context)
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            hit, inside = self._hit(context, event)
            if hit != self._hover:
                self._hover = hit
                self._show(context)
            return {"PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit, inside = self._hit(context, event)
            if not inside:
                return {"PASS_THROUGH"}
            if hit is not None:
                row = self._molecule().object.pb_filament.subunits.get(hit)
                if row is not None:
                    row.select = not row.select
                    self._show(context)
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}


CLASSES = (
    MOLECULE_PB_OT_color_subunits,
    MOLECULE_PB_OT_select_subunits,
    MOLECULE_PB_OT_pick_subunits,
)
