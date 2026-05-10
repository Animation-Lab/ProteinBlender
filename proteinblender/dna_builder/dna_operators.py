"""Operators for the DNA/RNA Builder.

Heavy imports (biotite, scipy) are deferred to execute() time
so that panel/operator classes can register before dependencies are loaded.
"""

import random
import bpy
from bpy.types import Operator
from bpy.props import StringProperty


def _build_dna_from_props(operator, context, identifier):
    """Shared build path: read scene props, build the AtomArray, create the
    Blender object via MN pipeline, apply colours and finalize.

    Returns (wrapper, info_dict) on success or (None, None) on failure
    (the operator's `report` will already have been called).
    """
    from ..utils.scene_manager import ProteinBlenderScene
    from .sequence_builder import (
        build_nucleic_acid,
        validate_sequence,
        calculate_helix_info,
    )
    from .dna_colors import apply_base_colors, colors_from_props, store_colors_on_object

    props = context.scene.dna_builder_props
    nucleic_type = props.nucleic_type
    seq = validate_sequence(props.sequence, nucleic_type)
    if len(seq) < 2:
        operator.report({"ERROR"}, "Sequence must be at least 2 valid nucleotides.")
        return None, None
    if len(seq) > 500:
        operator.report(
            {"WARNING"}, f"Long sequence ({len(seq)} nt) may be slow to build."
        )

    scene_mgr = ProteinBlenderScene.get_instance()

    try:
        array = build_nucleic_acid(
            sequence=seq,
            nucleic_type=nucleic_type,
            double_stranded=props.double_stranded,
        )
    except Exception as e:
        operator.report({"ERROR"}, f"Build failed: {e}")
        return None, None

    try:
        wrapper = scene_mgr.molecule_manager.create_from_array(
            array=array, identifier=identifier, style=props.style,
        )
    except Exception as e:
        operator.report({"ERROR"}, f"Object creation failed: {e}")
        return None, None

    obj = wrapper.molecule.object
    obj["pb_is_nucleic_acid"] = True
    obj["pb_nucleic_type"] = nucleic_type
    obj["pb_sequence"] = seq
    obj["pb_double_stranded"] = props.double_stranded
    obj["pb_style"] = props.style

    context.evaluated_depsgraph_get()
    colors = colors_from_props(props)
    store_colors_on_object(obj, colors)
    apply_base_colors(obj, colors)

    scene_mgr._finalize_dna_molecule(wrapper)

    return wrapper, calculate_helix_info(len(seq), nucleic_type)


class PROTEINBLENDER_OT_build_dna(Operator):
    """Build a DNA or RNA molecule from a nucleotide sequence"""

    bl_idname = "proteinblender.build_dna"
    bl_label = "Build DNA/RNA"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..utils.scene_manager import ProteinBlenderScene

        props = context.scene.dna_builder_props
        scene_mgr = ProteinBlenderScene.get_instance()
        identifier = self._next_id(props, scene_mgr)

        wrapper, info = _build_dna_from_props(self, context, identifier)
        if wrapper is None:
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Created {identifier}: {info['base_pairs']} nt, "
            f"{info['helix_length_angstrom']:.1f} \u00c5, "
            f"{info['turns']:.1f} turns",
        )
        return {"FINISHED"}

    @staticmethod
    def _next_id(props, scene_mgr):
        prefix = props.name_prefix or ("DNA" if props.nucleic_type == "DNA" else "RNA")
        counter = 1
        while True:
            name = f"{prefix}_{counter:03d}"
            if name not in scene_mgr.molecules:
                return name
            counter += 1


class PROTEINBLENDER_OT_update_dna(Operator):
    """Rebuild the selected DNA/RNA molecule with the current builder settings.

    Preserves the molecule's identifier so it stays in the same outliner slot.
    """

    bl_idname = "proteinblender.update_dna"
    bl_label = "Update Selected DNA/RNA"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # Allow the operator while a DNA molecule is active OR while the
        # active object is a related bend curve / bend node.
        from . import bender as _bender
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False):
            return True
        if obj.type == "CURVE" and _bender.get_dna_for_curve(obj) is not None:
            return True
        if obj.type == "EMPTY" and _bender.get_dna_for_node(obj) is not None:
            return True
        return False

    def execute(self, context):
        from ..utils.scene_manager import ProteinBlenderScene
        from . import bender as _bender

        # ---- Step 1: ensure OBJECT mode and that the DNA is the active obj.
        # The rebuild path uses ops that require OBJECT mode (origin_set,
        # select_all in set_protein_pivot_to_center_of_mass).
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        old_obj = context.active_object

        # If the active object is the bend curve or one of the bend nodes,
        # resolve to the owning DNA.
        if old_obj is not None and not old_obj.get("pb_is_nucleic_acid", False):
            if old_obj.type == "CURVE":
                resolved = _bender.get_dna_for_curve(old_obj)
                if resolved is not None:
                    old_obj = resolved
            elif old_obj.type == "EMPTY":
                resolved = _bender.get_dna_for_node(old_obj)
                if resolved is not None:
                    old_obj = resolved

        if not old_obj or not old_obj.get("pb_is_nucleic_acid", False):
            self.report({"ERROR"}, "No DNA/RNA molecule selected.")
            return {"CANCELLED"}

        try:
            bpy.ops.object.select_all(action="DESELECT")
            old_obj.select_set(True)
            context.view_layer.objects.active = old_obj
        except Exception:
            pass

        scene_mgr = ProteinBlenderScene.get_instance()

        # Find the identifier this molecule is registered under
        identifier = None
        for ident, wrapper in scene_mgr.molecules.items():
            try:
                if wrapper.molecule.object == old_obj:
                    identifier = ident
                    break
            except Exception:
                continue

        if identifier is None:
            self.report({"ERROR"}, "Selected molecule is not registered with the manager.")
            return {"CANCELLED"}

        # Preserve the user's transform and bend curve across the rebuild.
        from . import bender as _bender
        from mathutils import Vector

        # Save the world-space bounding-box centre rather than obj.location.
        # obj.location includes the pivot-shift offset added by
        # shift_origin_to_bottom (bend system); restoring it and then
        # applying a *new* pivot shift would accumulate downward drift on
        # every rebuild.
        bbox = [old_obj.matrix_world @ Vector(c) for c in old_obj.bound_box]
        old_visual_center = sum(bbox, Vector()) / 8

        old_rot_mode = old_obj.rotation_mode
        old_rot_euler = old_obj.rotation_euler.copy()
        old_rot_quat = old_obj.rotation_quaternion.copy()
        bend_curve_name = old_obj.get(_bender.BEND_CURVE_PROP)
        bend_curve_obj = bpy.data.objects.get(bend_curve_name) if bend_curve_name else None

        # Delete the old molecule (object, collection, registry, list item).
        # The bend curve is a separate object and survives this deletion.
        scene_mgr.delete_molecule(identifier)

        # Purge the cached node tree from the previous build — otherwise
        # create_starting_node_tree finds it by name (MN_<identifier>) and
        # early-returns, silently ignoring any style change on rebuild.
        ng_name = f"MN_{identifier}"
        old_tree = bpy.data.node_groups.get(ng_name)
        if old_tree is not None:
            try:
                bpy.data.node_groups.remove(old_tree, do_unlink=True)
            except Exception:
                pass

        # Build new with the same identifier
        wrapper, info = _build_dna_from_props(self, context, identifier)
        if wrapper is None:
            return {"CANCELLED"}

        new_obj = wrapper.molecule.object

        # Restore rotation (but NOT location yet — shift_origin_to_bottom
        # in reattach_after_rebuild will modify location, so we restore
        # visual position after all origin shifts are done).
        if new_obj is not None:
            new_obj.rotation_mode = old_rot_mode
            new_obj.rotation_euler = old_rot_euler
            new_obj.rotation_quaternion = old_rot_quat

        # Restore the bend if there was one. The curve object survived;
        # reattach a fresh Curve modifier and re-shift the new mesh's pivot
        # to its bottom so the deformation lines up.
        if bend_curve_obj is not None and new_obj is not None:
            try:
                _bender.reattach_after_rebuild(new_obj, bend_curve_obj)
            except Exception as e:
                self.report({"WARNING"}, f"Could not reattach bend: {e}")

        # Restore visual position: compare where the new object's bbox
        # centre ended up (after any pivot shift) with the saved centre
        # and translate by the difference.
        if new_obj is not None:
            context.view_layer.update()
            bbox = [new_obj.matrix_world @ Vector(c) for c in new_obj.bound_box]
            new_visual_center = sum(bbox, Vector()) / 8
            new_obj.location += old_visual_center - new_visual_center

        # Re-select the new object so the panel stays in edit mode for it
        if new_obj:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                new_obj.select_set(True)
                context.view_layer.objects.active = new_obj
            except Exception:
                pass

        self.report(
            {"INFO"},
            f"Updated {identifier}: {info['helix_length_angstrom']:.1f} \u00c5, "
            f"{info['turns']:.1f} turns",
        )
        return {"FINISHED"}


class PROTEINBLENDER_OT_randomize_sequence(Operator):
    """Generate a random nucleotide sequence of the specified length"""

    bl_idname = "proteinblender.randomize_sequence"
    bl_label = "Generate Random Sequence"

    def execute(self, context):
        props = context.scene.dna_builder_props
        chars = "ATGC" if props.nucleic_type == "DNA" else "AUGC"
        props.sequence = "".join(random.choice(chars) for _ in range(props.sequence_length))
        return {"FINISHED"}


class PROTEINBLENDER_OT_update_dna_colors(Operator):
    """Update per-base colours on the selected DNA/RNA molecule"""

    bl_idname = "proteinblender.update_dna_colors"
    bl_label = "Update DNA Colors"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("pb_is_nucleic_acid", False)

    def execute(self, context):
        from .dna_colors import apply_base_colors, colors_from_props, store_colors_on_object

        obj = context.active_object
        props = context.scene.dna_builder_props
        colors = colors_from_props(props)
        store_colors_on_object(obj, colors)
        apply_base_colors(obj, colors)
        self.report({"INFO"}, "Colours updated.")
        return {"FINISHED"}


class PROTEINBLENDER_OT_update_dna_style(Operator):
    """Change the visualisation style of the selected DNA/RNA molecule"""

    bl_idname = "proteinblender.update_dna_style"
    bl_label = "Update DNA Style"

    new_style: StringProperty()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("pb_is_nucleic_acid", False)

    def execute(self, context):
        from ..utils.molecularnodes.blender.nodes import change_style_node
        from .dna_colors import apply_base_colors, colors_from_object

        obj = context.active_object
        if not self.new_style:
            self.new_style = context.scene.dna_builder_props.style

        change_style_node(obj, self.new_style)
        obj["pb_style"] = self.new_style

        # Re-apply base colours (style change may reset Color attribute)
        colors = colors_from_object(obj)
        apply_base_colors(obj, colors)

        self.report({"INFO"}, f"Style changed to {self.new_style}.")
        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_build_dna,
    PROTEINBLENDER_OT_update_dna,
    PROTEINBLENDER_OT_randomize_sequence,
    PROTEINBLENDER_OT_update_dna_colors,
    PROTEINBLENDER_OT_update_dna_style,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
