"""The Symmetry Builder dialog.

One button in the Symmetry panel opens this; everything that *shapes* a
generated symmetry lives inside it. Three ways out, and they mean different
things:

* **Apply** builds the symmetry and leaves the dialog open, so the settings
  can be judged against the viewport rather than against the numbers. It is an
  ordinary operator button drawn in the dialog body - Blender keeps a props
  dialog open across those, which is what makes a preview possible at all.
* **OK** builds and closes, and refreshes the PB Outliner so the result takes
  its place there as a row of its own.
* **Cancel** puts back whatever was on screen before the dialog opened -
  nothing, a deposited assembly, or an earlier generated symmetry - because a
  preview the user rejected should not be what they are left with.

Two modes, like the membrane builder's dialog and for the same reason:
opened empty it configures a new build, and opened from the outliner's edit
pencil it reopens on what that protein was actually built with.
"""

from __future__ import annotations

import logging

from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..core import symmetry_builder
from ..utils.scene_manager import ProteinBlenderScene, resolve_active_molecule_id
from .assembly_operators import (
    apply_symmetry_settings,
    build_generated_symmetry,
    symmetry_settings,
)

logger = logging.getLogger(__name__)

#: Blender does not keep the strings an EnumProperty items callback returns
#: alive, so they must be held on the Python side or the picker draws garbage.
_TARGET_ENUM_CACHE = []

#: What Cancel has to put back, as {molecule id: pre-preview state}.
#:
#: Module state rather than operator properties, for two reasons this codebase
#: has already been bitten by: a modal ``invoke_props_dialog`` operator is
#: absent from ``wm.operators`` until it finishes, so Apply cannot reach the
#: running dialog through the operator history; and Blender rebuilds the
#: instance behind a props dialog, so the one that ran ``invoke`` is not
#: necessarily the one whose ``cancel`` runs. Anything that must survive from
#: opening to dismissal cannot live on the instance.
#:
#: Keyed by molecule because the picker can be moved mid-dialog: preview A,
#: switch to B, preview B, and both need putting back.
_PREVIEWS: dict = {}


def remember_preview_target(molecule) -> None:
    """Record what to put back for this molecule, before a preview builds.

    First preview of a molecule wins: later ones would record the previous
    *preview* as the thing to restore, which is how Cancel ends up putting
    back a state the user never had.
    """
    if molecule.identifier not in _PREVIEWS:
        _PREVIEWS[molecule.identifier] = snapshot_state(molecule)


def pending_previews() -> list:
    """Which molecules have a preview outstanding that Cancel would undo."""
    return list(_PREVIEWS)


def discard_previews(keep: str = "") -> list:
    """Put back every previewed molecule, optionally sparing one.

    ``keep`` is the molecule being committed by OK: its preview *is* the
    result, so it stays. Everything else the dialog touched on the way there
    was only ever a preview and goes back to what it was.
    """
    restored = []
    for molecule_id, state in list(_PREVIEWS.items()):
        if molecule_id == keep:
            continue
        molecule = _molecule(molecule_id)
        if molecule is not None:
            restore_state(molecule, state)
            restored.append(molecule_id)
    _PREVIEWS.clear()
    return restored


def _molecules():
    return ProteinBlenderScene.get_instance().molecules


def _molecule(molecule_id):
    return _molecules().get(molecule_id)


def target_enum_items(self, context):
    """Every loaded molecule, as the dialog's "which protein" picker.

    One at a time: the generator works in a molecule's own coordinate frame,
    so the same operator set applied to two proteins rings each about its own
    origin rather than building one assembly out of both.
    """
    global _TARGET_ENUM_CACHE

    items = []
    for molecule_id, molecule in _molecules().items():
        name = getattr(molecule, "name", None) or molecule_id
        items.append((molecule_id, name, f"Build symmetry for {name}"))

    if not items:
        items = [("", "No protein loaded", "Import a structure first")]

    _TARGET_ENUM_CACHE = items
    return _TARGET_ENUM_CACHE


def snapshot_state(molecule) -> dict:
    """What is on screen now, in enough detail to put it back.

    Three states worth restoring and they restore differently: nothing built,
    a deposited assembly (rebuild it by id), or a generated symmetry (rebuild
    it from the settings recorded with it).
    """
    return {
        "assembly_id": assembly_core.built_assembly_id(molecule),
        "params": assembly_core.built_build_params(molecule),
    }


def restore_state(molecule, state: dict) -> None:
    """Put back what :func:`snapshot_state` recorded."""
    assembly_id = state.get("assembly_id")
    if not assembly_id:
        assembly_core.clear_assembly(molecule)
        return

    params = state.get("params")
    if params and str(assembly_id).startswith("generated:"):
        ok, message = build_generated_symmetry(molecule, params)
        if not ok:
            logger.warning("could not restore the previous symmetry: %s",
                           message)
        return

    assembly_core.build_assembly(molecule, str(assembly_id))


class MOLECULE_PB_OT_symmetry_dialog(Operator):
    """Configure and build a generated symmetry"""

    bl_idname = "molecule.symmetry_dialog"
    bl_label = "Build Symmetry"
    bl_description = (
        "Generate a symmetric assembly - a ring, a double ring or a filament - "
        "for a structure whose file does not describe one. Apply to preview it "
        "in the viewport, OK to keep it")
    bl_options = {"REGISTER", "UNDO"}

    target_id: EnumProperty(
        name="Protein",
        description="Which protein to build the symmetry for",
        items=target_enum_items,
        options={'SKIP_SAVE'},
    )

    #: Set by the PB Outliner's edit pencil to reopen the dialog on an existing
    #: build. Empty means "configure a new one".
    molecule_id_to_update: StringProperty(
        name="Symmetry to edit",
        description=("If set, open on this protein's existing generated "
                     "symmetry instead of on the scene's current settings"),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    # -- opening -----------------------------------------------------------

    def invoke(self, context, event):
        molecule_id = (self.molecule_id_to_update
                       or resolve_active_molecule_id(context) or "")
        molecule = _molecule(molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        try:
            self.target_id = molecule_id
        except TypeError:
            # The picker refuses an identifier its items callback is not
            # currently offering; it then opens on its first entry, which is
            # a live molecule either way.
            logger.warning("could not point the picker at %s", molecule_id)

        # Reopening on a build shows what that build was made with, not what
        # the scene sliders happen to say - they are one set of controls
        # standing in for whichever protein was last active.
        stored = assembly_core.built_build_params(molecule)
        if stored:
            apply_symmetry_settings(context.scene, stored)

        # Anything left over from a dialog that was torn down without its
        # cancel() running would otherwise be restored on top of this one.
        _PREVIEWS.clear()
        return context.window_manager.invoke_props_dialog(self, width=380)

    # -- body --------------------------------------------------------------

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Labelled, unlike the kind dropdown below it: "Cyclic (Cn)" says what
        # it is on its own, where a bare "ubq" does not.
        picker = layout.row(align=True)
        picker.label(text="Protein")
        picker.prop(self, "target_id", text="")
        layout.separator(factor=0.5)

        kind = getattr(scene, "pb_symmetry_kind", "C")

        col = layout.column(align=True)
        col.prop(scene, "pb_symmetry_kind", text="")
        if kind in {"C", "D"}:
            col.prop(scene, "pb_symmetry_order")
        else:
            col.prop(scene, "pb_symmetry_count")
            col.prop(scene, "pb_symmetry_rise")
            col.prop(scene, "pb_symmetry_twist")

        axis_row = col.row(align=True)
        axis_row.label(text="Axis")
        axis_row.prop(scene, "pb_symmetry_axis", text="")

        summary = layout.row()
        summary.enabled = False
        summary.label(text=symmetry_builder.describe(
            kind,
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0)))

        layout.separator(factor=0.5)
        trim = layout.box()
        trim.label(text="Trim Copies")
        trim_col = trim.column(align=True)
        trim_col.prop(scene, "pb_symmetry_range")
        trim_col.prop(scene, "pb_symmetry_contact")
        note = trim.row()
        note.enabled = False
        note.label(text="0 keeps every copy", icon='INFO')

        layout.separator(factor=0.5)
        apply_row = layout.row(align=True)
        apply_row.scale_y = 1.2
        apply_row.enabled = bool(self.target_id)
        apply_op = apply_row.operator("molecule.symmetry_preview",
                                      text="Apply", icon='CHECKMARK')
        apply_op.molecule_id = self.target_id

        hint = layout.row()
        hint.enabled = False
        hint.label(text="Apply previews it - OK keeps it", icon='INFO')

    # -- leaving -----------------------------------------------------------

    def execute(self, context):
        molecule = _molecule(self.target_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        ok, message = build_generated_symmetry(
            molecule, symmetry_settings(context.scene))
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        # A preview on some *other* protein - the picker was moved after an
        # Apply - was still only a preview, and goes back to what it was. The
        # one being committed keeps its build.
        discard_previews(keep=molecule.identifier)

        # The outliner derives its symmetry row from what is actually built,
        # so this is a refresh rather than a write - which is what keeps the
        # row correct through undo, save/load and a build made any other way.
        _rebuild_outliner(context)
        self.report({"INFO"}, message)
        _refresh(context)
        return {"FINISHED"}

    def cancel(self, context):
        """Take every preview back down.

        Reads module state, not ``self``: the instance running cancel is not
        reliably the one that ran invoke.
        """
        if not _PREVIEWS:
            return
        discard_previews()
        _rebuild_outliner(context)
        _refresh(context)


class MOLECULE_PB_OT_symmetry_preview(Operator):
    """Build the symmetry now, without closing the dialog"""

    bl_idname = "molecule.symmetry_preview"
    bl_label = "Apply"
    bl_description = (
        "Build the symmetry with these settings so it can be judged in the "
        "viewport. The dialog stays open; Cancel puts back what was there "
        "before")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        molecule = _molecule(self.molecule_id
                             or resolve_active_molecule_id(context) or "")
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        # Before building, not after: the point of the record is what was
        # there *instead* of this preview.
        remember_preview_target(molecule)

        ok, message = build_generated_symmetry(
            molecule, symmetry_settings(context.scene))
        if not ok:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}

        self.report({"INFO"}, message)
        _refresh(context)
        return {"FINISHED"}


def _rebuild_outliner(context) -> None:
    from ..utils.scene_manager import build_outliner_hierarchy

    try:
        build_outliner_hierarchy(context)
    except Exception:
        logger.exception("could not rebuild the outliner")


def _refresh(context) -> None:
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


CLASSES = (
    MOLECULE_PB_OT_symmetry_dialog,
    MOLECULE_PB_OT_symmetry_preview,
)
