"""Operators for building and clearing deposited biological assemblies.

The domain logic lives in ``core.assembly``; these are the thin Blender-facing
wrappers the panel drives.
"""

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..utils.scene_manager import ProteinBlenderScene, resolve_active_molecule_id

#: Blender does not keep a reference to the strings an EnumProperty items
#: callback returns, so anything built on the fly there must be held alive on
#: the Python side or the UI shows garbage. Rebuilt on every call.
_ASSEMBLY_ENUM_CACHE = []


def _molecule(molecule_id):
    return ProteinBlenderScene.get_instance().molecules.get(molecule_id)


def _active_molecule_id(context):
    return resolve_active_molecule_id(context) or ""


def assembly_enum_items(self, context):
    """Assemblies worth offering for the active molecule.

    Only those with a non-identity transform: an assembly that is purely the
    identity is the asymmetric unit already on screen, so offering it would be
    a button that visibly does nothing.
    """
    global _ASSEMBLY_ENUM_CACHE

    molecule_id = getattr(self, "molecule_id", "") or _active_molecule_id(context)
    molecule = _molecule(molecule_id)

    items = []
    if molecule is not None:
        for info in assembly_core.buildable_assemblies(molecule):
            items.append((
                info.assembly_id,
                info.label,
                f"Build biological assembly {info.assembly_id}",
            ))

    if not items:
        items = [("NONE", "No symmetry in this file", "")]

    _ASSEMBLY_ENUM_CACHE = items
    return _ASSEMBLY_ENUM_CACHE


class MOLECULE_PB_OT_build_assembly(Operator):
    """Build the deposited biological assembly for this protein"""

    bl_idname = "molecule.build_assembly"
    bl_label = "Build Assembly"
    bl_description = (
        "Repeat this protein under the symmetry operators deposited with it, "
        "building the biological assembly - the dimer, ring or capsid it forms")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    assembly_id: StringProperty()

    def execute(self, context):
        molecule_id = self.molecule_id or _active_molecule_id(context)
        molecule = _molecule(molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        assembly_id = self.assembly_id
        if not assembly_id or assembly_id == "NONE":
            assembly_id = getattr(context.scene, "pb_assembly_id", "") or ""
        if not assembly_id or assembly_id == "NONE":
            buildable = assembly_core.buildable_assemblies(molecule)
            if not buildable:
                self.report({"WARNING"}, "This structure has no deposited symmetry")
                return {"CANCELLED"}
            assembly_id = buildable[0].assembly_id

        info = assembly_core.get_assembly_info(molecule, assembly_id)
        if info is None:
            self.report({"ERROR"}, f"No assembly {assembly_id} in this structure")
            return {"CANCELLED"}

        if not assembly_core.build_assembly(molecule, assembly_id):
            self.report({"ERROR"}, "Could not build the assembly")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Built assembly {assembly_id}: {info.transform_count} copies")
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_keyframe_assembly(Operator):
    """Key the current assembly state at the playhead"""

    bl_idname = "molecule.keyframe_assembly"
    bl_label = "Keyframe Assembly"
    bl_description = (
        "Key how far assembled the copies are at the current frame. Key 0 on "
        "one frame and 1 on another to animate the assembly forming")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        if assembly_core.built_assembly_id(molecule) is None:
            self.report({"WARNING"}, "Build an assembly before keyframing it")
            return {"CANCELLED"}

        keyed = assembly_core.keyframe_assembly(molecule)
        if not keyed:
            self.report({"ERROR"}, "Could not key the assembly")
            return {"CANCELLED"}

        self.report({"INFO"},
                    f"Keyed the assembly at frame {context.scene.frame_current}")
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_clear_assembly(Operator):
    """Drop the assembly copies, leaving the deposited asymmetric unit"""

    bl_idname = "molecule.clear_assembly"
    bl_label = "Clear Assembly"
    bl_description = (
        "Remove the symmetry copies and show only the asymmetric unit as "
        "deposited")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule_id = self.molecule_id or _active_molecule_id(context)
        molecule = _molecule(molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        if not assembly_core.clear_assembly(molecule):
            self.report({"INFO"}, "No assembly was built")
            return {"CANCELLED"}

        self.report({"INFO"}, "Assembly cleared")
        _refresh(context)
        return {"FINISHED"}


def _refresh(context):
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


CLASSES = (
    MOLECULE_PB_OT_build_assembly,
    MOLECULE_PB_OT_keyframe_assembly,
    MOLECULE_PB_OT_clear_assembly,
)
