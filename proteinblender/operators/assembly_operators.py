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

        operators = _filtered(context, molecule,
                              assembly_core._operators_for(molecule, assembly_id))
        if not operators:
            self.report({"WARNING"}, "The range or contact limit removed every copy")
            return {"CANCELLED"}

        if not assembly_core.apply_operators(molecule, operators, str(assembly_id)):
            self.report({"ERROR"}, "Could not build the assembly")
            return {"CANCELLED"}

        trimmed = ("" if len(operators) == info.transform_count
                   else f" (trimmed from {info.transform_count})")
        self.report(
            {"INFO"},
            f"Built assembly {assembly_id}: {len(operators)} copies{trimmed}")
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


class MOLECULE_PB_OT_build_symmetry(Operator):
    """Generate symmetry copies from parameters, not from the file"""

    bl_idname = "molecule.build_symmetry"
    bl_label = "Build Symmetry"
    bl_description = (
        "Generate a symmetric assembly - a ring, a double ring or a filament - "
        "for a structure whose file does not describe one")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    kind: StringProperty(default="")

    def execute(self, context):
        from ..core import symmetry_builder

        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        scene = context.scene
        kind = self.kind or getattr(scene, "pb_symmetry_kind", "C")

        operators = _filtered(context, molecule, symmetry_builder.build_operators(
            kind,
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0),
            axis=tuple(getattr(scene, "pb_symmetry_axis", (0.0, 0.0, 1.0))),
        ))
        if not operators:
            self.report({"WARNING"}, "The range or contact limit removed every copy")
            return {"CANCELLED"}

        ok = assembly_core.apply_operators(
            molecule, operators, f"generated:{kind.upper()}")
        if not ok:
            self.report({"ERROR"}, "Could not build that symmetry")
            return {"CANCELLED"}

        self.report({"INFO"}, symmetry_builder.describe(
            kind,
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0)))
        _refresh(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_toggle_symmetry_axes(Operator):
    """Show or hide the assembly's symmetry axes"""

    bl_idname = "molecule.toggle_symmetry_axes"
    bl_label = "Symmetry Axes"
    bl_description = (
        "Draw the rotation axes of the built symmetry as renderable objects - "
        "the five-fold through a capsid vertex, the two-fold between subunits")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        from ..core import symmetry_axes

        molecule = _molecule(self.molecule_id or _active_molecule_id(context))
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        if symmetry_axes.symmetry_axis_objects(molecule):
            symmetry_axes.clear_symmetry_axes(molecule)
            self.report({"INFO"}, "Symmetry axes hidden")
            _refresh(context)
            return {"FINISHED"}

        tag = assembly_core.built_assembly_id(molecule)
        if tag is None:
            self.report({"WARNING"}, "Build a symmetry before showing its axes")
            return {"CANCELLED"}

        operators = _operators_of_built(context, molecule, tag)
        if not operators:
            self.report({"WARNING"}, "Could not recover the built operators")
            return {"CANCELLED"}

        created = symmetry_axes.show_symmetry_axes(molecule, operators)
        if not created:
            self.report({"INFO"}, "This symmetry has no axes to draw")
            return {"CANCELLED"}

        folds = ", ".join(sorted({a.label for a in symmetry_axes.axes_of(operators)}))
        self.report({"INFO"}, f"Showing {len(created)} axes ({folds})")
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


def _operators_of_built(context, molecule, tag):
    """Rebuild the operator list behind whatever is currently built.

    The tag on the node says which: a deposited assembly id, or
    ``generated:<kind>``. The panel's current builder settings stand in for a
    generated one, which is right as long as they have not been changed since.
    """
    from ..core import symmetry_builder

    tag = str(tag)
    if tag.startswith("generated:"):
        scene = context.scene
        return symmetry_builder.build_operators(
            tag.split(":", 1)[1],
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0),
            axis=tuple(getattr(scene, "pb_symmetry_axis", (0.0, 0.0, 1.0))),
        )
    return assembly_core._operators_for(molecule, tag)


def _filtered(context, molecule, operators):
    """Apply the panel's range and contact limits. 0 means "no limit"."""
    scene = context.scene
    range_limit = getattr(scene, "pb_symmetry_range", 0.0) or None
    contact = getattr(scene, "pb_symmetry_contact", 0.0) or None
    if range_limit is None and contact is None:
        return list(operators)
    return assembly_core.filter_operators(
        molecule, operators, range_limit=range_limit, contact_distance=contact)


def _refresh(context):
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


CLASSES = (
    MOLECULE_PB_OT_build_assembly,
    MOLECULE_PB_OT_build_symmetry,
    MOLECULE_PB_OT_toggle_symmetry_axes,
    MOLECULE_PB_OT_keyframe_assembly,
    MOLECULE_PB_OT_clear_assembly,
)
