"""Cytoskeleton Subunits panel: every monomer of a filament, to pick and colour.

Shown only while the scene has a filament. Its list has one row per monomer -
"Actin 12", "Beta Tubulin 3 - Strand 5" - counted up each strand from the
minus end, with a checkbox to select it and, once it has one, its own colour.
Pointing at a row lights its subunit up yellow in the viewport
(``subunit_hover``). Below the list: select all, none or the rest, pick
subunits by clicking them in the 3D Viewport, and colour or clear the selected
ones. Colours are keyed with the filament's row in Create Keyframe.
"""

import fnmatch

import bpy
from bpy.types import Panel, UIList

from ..core import subunit_colors
from ..operators.subunit_operators import filaments, subunit_filament
from . import subunit_hover


class PROTEINBLENDER_UL_subunits(UIList):
    """One row per monomer of a filament."""

    bl_idname = "PROTEINBLENDER_UL_subunits"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        # The checkbox carries the name, so the whole row is one button and
        # pointing anywhere on it tells the hover watch which subunit it is.
        row.prop(item, "select", text=item.label)
        # A small swatch at the right edge, as the PB Outliner draws its own.
        controls = row.row(align=True)
        controls.alignment = 'RIGHT'
        swatch = controls.row(align=True)
        swatch.ui_units_x = 1.0
        colour = data.colors.get(item.name)
        if colour is not None:
            swatch.prop(colour, "color", text="")
        else:
            swatch.label(text="", icon="BLANK1")

    def filter_items(self, context, data, propname):
        rows = getattr(data, propname)
        molecule = subunit_colors.molecule_of_object(data.id_data)
        present = subunit_colors.present_sites(molecule) if molecule else set()
        pattern = f"*{self.filter_name}*".lower() if self.filter_name else None
        shown = self.bitflag_filter_item
        flags = []
        for row in rows:
            keep = row.site in present and (
                pattern is None or fnmatch.fnmatch(row.label.lower(), pattern))
            if self.use_filter_invert:
                keep = row.site in present and not keep
            flags.append(shown if keep else 0)
        return flags, []


#: A roster rebuild asked for from draw(), which may not write data itself.
_PENDING = set()


def _sync_later(molecule_id):
    if molecule_id in _PENDING:
        return
    _PENDING.add(molecule_id)

    def run():
        _PENDING.discard(molecule_id)
        from ..utils.scene_manager import ProteinBlenderScene
        molecule = ProteinBlenderScene.get_instance().molecules.get(molecule_id)
        if molecule is not None:
            subunit_colors.sync_roster(molecule)
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "PROPERTIES":
                        area.tag_redraw()
        return None

    bpy.app.timers.register(run, first_interval=0.0)


class PROTEINBLENDER_PT_subunits(Panel):
    """Every monomer of a filament, to select, pick and colour."""

    bl_label = "Cytoskeleton Subunits"
    bl_idname = "PROTEINBLENDER_PT_subunits"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    # Beside the PB Outliner it extends: the filament's row is there, its
    # subunits are here.
    bl_order = 2
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    @classmethod
    def poll(cls, context):
        return bool(filaments())

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        box.label(text="Cytoskeleton Subunits", icon="OUTLINER_DATA_POINTCLOUD")

        molecule = subunit_filament(context)
        if molecule is None:
            box.label(text="No filament", icon="INFO")
            return
        if len(filaments()) > 1:
            box.prop(scene, "pb_subunit_filament", text="")

        params = molecule.object.pb_filament
        if subunit_colors.roster_stale(molecule):
            _sync_later(molecule.identifier)

        box.template_list("PROTEINBLENDER_UL_subunits", "", params, "subunits",
                          params, "subunit_index", rows=8)
        # Drawn because the mouse may be on its way to the list.
        subunit_hover.watch()

        picks = box.row(align=True)
        for action, icon, text in (("ALL", "CHECKBOX_HLT", "All"),
                                   ("NONE", "CHECKBOX_DEHLT", "None"),
                                   ("INVERT", "ARROW_LEFTRIGHT", "Invert")):
            op = picks.operator("molecule.select_subunits", text=text, icon=icon)
            op.action = action
            op.molecule_id = molecule.identifier
        pick = box.row()
        pick.operator("molecule.pick_subunits", icon="EYEDROPPER").molecule_id = (
            molecule.identifier)

        selected = len(subunit_colors.selected_keys(molecule))
        paint = box.row(align=True)
        paint.enabled = selected > 0
        swatch = paint.row(align=True)
        swatch.ui_units_x = 3
        swatch.prop(scene, "pb_subunit_color", text="")
        paint.operator("molecule.color_subunits", text="Colour Selected",
                       icon="BRUSH_DATA").molecule_id = molecule.identifier
        clear = paint.operator("molecule.color_subunits", text="Clear", icon="X")
        clear.molecule_id = molecule.identifier
        clear.clear = True

        note = box.column(align=True)
        note.enabled = False
        note.label(text=f"{selected} selected" if selected else "Nothing selected",
                   icon="INFO")
        note.label(text="Key colours with Create Keyframe", icon="BLANK1")


CLASSES = (
    PROTEINBLENDER_UL_subunits,
    PROTEINBLENDER_PT_subunits,
)
