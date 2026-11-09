"""Cytoskeleton Subunits panel: every monomer of a filament, to pick and colour.

Shown only while a filament's own row is ticked in the PB Outliner, and
showing that filament; with several ticked, a picker chooses between them.
Its list has one row per monomer - "Actin 12", "Beta Tubulin 3 - Strand 5" -
counted up each strand from the minus end, with a checkbox to select it and,
at its right, an eye to hide it and its colour, which paints it alone.
Pointing at a row lights its subunit up yellow in the viewport
(``subunit_hover``). Above the list: select all, none or the rest, and on
a filament of more than one chain - a microtubule's alpha and beta tubulin -
every subunit of one chain. Below it: pick subunits by clicking them in the 3D
Viewport; a colour that applies to the selected subunits as soon as it
changes, and Clear. Colours are keyed with the filament's row in Create
Keyframe, or with I over a painted subunit's swatch.
"""

import fnmatch

import bpy
from bpy.types import Panel, UIList

from ..core import subunit_colors
from ..operators.subunit_operators import subunit_filament, ticked_filaments
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
        # At the right edge, as the PB Outliner draws its own: the eye, then
        # the subunit's colour. A painted subunit shows its colour entry
        # itself, so I over the swatch keys it; any other shows the colour it
        # is drawn and, changed, is painted that.
        controls = row.row(align=True)
        controls.alignment = 'RIGHT'
        controls.prop(item, "hide", text="", emboss=False,
                      icon="HIDE_ON" if item.hide else "HIDE_OFF")
        swatch = controls.row(align=True)
        swatch.ui_units_x = 1.0
        colour = data.colors.get(item.name)
        swatch.prop(colour if colour is not None else item, "color", text="")

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


def _chains_in_list_order(params):
    """The chains a filament's list names, in the order it first names them."""
    seen = []
    for row in params.subunits:
        if row.chain not in seen:
            seen.append(row.chain)
    return seen


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
        return bool(ticked_filaments(context))

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        box.label(text="Cytoskeleton Subunits", icon="OUTLINER_DATA_POINTCLOUD")

        molecule = subunit_filament(context)
        if molecule is None:
            box.label(text="No filament", icon="INFO")
            return
        if len(ticked_filaments(context)) > 1:
            box.prop(scene, "pb_subunit_filament", text="")

        params = molecule.object.pb_filament
        if subunit_colors.roster_stale(molecule):
            _sync_later(molecule.identifier)

        picks = box.row(align=True)
        for action, icon, text in (("ALL", "CHECKBOX_HLT", "Select All"),
                                   ("NONE", "CHECKBOX_DEHLT", "None"),
                                   ("INVERT", "ARROW_LEFTRIGHT", "Invert")):
            op = picks.operator("molecule.select_subunits", text=text, icon=icon)
            op.action = action
            op.molecule_id = molecule.identifier
        chains = _chains_in_list_order(params)
        if len(chains) > 1:
            names = subunit_colors.chain_labels(molecule)
            by_chain = box.row(align=True)
            for chain in chains:
                op = by_chain.operator("molecule.select_subunits",
                                       text=f"All {names.get(chain, f'Chain {chain}')}",
                                       icon="CHECKBOX_HLT")
                op.action = "CHAIN"
                op.chain = chain
                op.molecule_id = molecule.identifier

        box.template_list("PROTEINBLENDER_UL_subunits", "", params, "subunits",
                          params, "subunit_index", rows=8)
        # Drawn because the mouse may be on its way to the list.
        subunit_hover.watch()

        pick = box.row()
        pick.operator("molecule.pick_subunits", icon="EYEDROPPER").molecule_id = (
            molecule.identifier)

        selected = len(subunit_colors.selected_keys(molecule))
        # The field shows the first selected subunit and, changed, paints
        # every selected one at once. There is no Strength slider (taken out
        # 2026-11-03): a colour is keyed on its own. Strengths already set or
        # keyed in a file still play back.
        paint = box.row(align=True)
        paint.enabled = selected > 0
        paint.prop(scene, "pb_subunit_color", text="")
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
