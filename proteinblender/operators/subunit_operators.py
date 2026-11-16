"""Choosing a filament's subunits and coloring them.

The Subunits list (``panels.subunit_panel``) shows every monomer of a filament.
These are its buttons: select rows, and color or clear the selected ones. What a color *is* and how it
is drawn lives in ``core.subunit_colors``.
"""

import logging

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


def ticked_filaments(context):
    """The filaments whose own row is ticked in the PB Outliner."""
    ticked = {row.item_id for row in getattr(context.scene, "outliner_items", ())
              if row.is_selected and row.item_type == 'PROTEIN'}
    return [molecule for molecule in filaments() if molecule.identifier in ticked]


def subunit_filament(context, molecule_id: str = ""):
    """The filament the Subunits list is showing.

    The one asked for by id, among every filament. Else, among the filaments
    ticked in the PB Outliner: the one chosen in the list's picker, else the
    active protein, else the first ticked. None when no filament is ticked.
    """
    from ..utils.scene_manager import resolve_active_molecule_id

    if molecule_id:
        for molecule in filaments():
            if molecule.identifier == molecule_id:
                return molecule
    found = ticked_filaments(context)
    by_id = {molecule.identifier: molecule for molecule in found}
    for wanted in (getattr(context.scene, "pb_subunit_filament", ""),
                   resolve_active_molecule_id(context)):
        if wanted and wanted in by_id:
            return by_id[wanted]
    return found[0] if found else None


#: Blender keeps no reference to strings an enum items callback returns.
_ITEMS_CACHE = []


def filament_items(self, context):
    """The ticked filaments the Subunits list can show, for its picker."""
    from ..core import filament_presets

    items = []
    for molecule in ticked_filaments(context):
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
    """Color the selected subunits, or give them back the filament's color"""

    bl_idname = "molecule.color_subunits"
    bl_label = "Color Selected"
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={"SKIP_SAVE"})
    clear: BoolProperty(
        name="Clear", default=False, options={"SKIP_SAVE"},
        description="Give the subunits back the filament's own color")

    @classmethod
    def description(cls, context, properties):
        if getattr(properties, "clear", False):
            return ("Give the selected subunits back the filament's own "
                    "color, and drop their color keyframes")
        return ("Paint the selected subunits the color beside this button. "
                "Key it with Create Keyframe to animate it")

    def execute(self, context):
        molecule = subunit_filament(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No cytoskeleton filament to color")
            return {"CANCELLED"}
        subunit_colors.sync_roster(molecule)
        keys = subunit_colors.selected_keys(molecule)
        if not keys:
            self.report({"WARNING"}, "Select subunits in the list first")
            return {"CANCELLED"}
        if self.clear:
            done = subunit_colors.clear(molecule, keys)
            self.report({"INFO"}, f"Cleared the color of {done} subunits")
        else:
            done = subunit_colors.paint(molecule, keys, context.scene.pb_subunit_color)
            self.report({"INFO"}, f"Colored {done} subunits")
        _redraw(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_select_subunits(Operator):
    """Select all, none, the other, or one chain's subunits of the filament"""

    bl_idname = "molecule.select_subunits"
    bl_label = "Select Subunits"
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={"SKIP_SAVE"})
    action: EnumProperty(
        name="Action",
        items=(("ALL", "All", "Select every subunit the filament has now"),
               ("NONE", "None", "Select no subunits"),
               ("INVERT", "Invert", "Select the subunits that are not selected"),
               ("CHAIN", "Chain", "Select every subunit of one chain, and no other")),
        default="ALL")
    chain: StringProperty(
        name="Chain", options={"SKIP_SAVE"},
        description="The chain whose subunits the Chain action selects")

    @classmethod
    def description(cls, context, properties):
        if properties.action == "CHAIN":
            molecule = subunit_filament(context, properties.molecule_id)
            name = (subunit_colors.chain_labels(molecule).get(properties.chain)
                    if molecule is not None else None) or f"Chain {properties.chain}"
            return (f"Select every {name} subunit the filament has now, and "
                    f"deselect the others")
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
            elif self.action == "CHAIN":
                row.select = here and row.chain == self.chain
            elif self.action == "NONE":
                row.select = False
            else:
                row.select = here and not row.select
        _redraw(context)
        return {"FINISHED"}


CLASSES = (
    MOLECULE_PB_OT_color_subunits,
    MOLECULE_PB_OT_select_subunits,
)
