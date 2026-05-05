"""Operators for the DNA/RNA Builder.

Heavy imports (biotite, scipy) are deferred to execute() time
so that panel/operator classes can register before dependencies are loaded.
"""

import random
import bpy
from bpy.types import Operator
from bpy.props import StringProperty


class PROTEINBLENDER_OT_build_dna(Operator):
    """Build a DNA or RNA molecule from a nucleotide sequence"""

    bl_idname = "proteinblender.build_dna"
    bl_label = "Build DNA/RNA"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy
        from .sequence_builder import build_nucleic_acid, validate_sequence, calculate_helix_info
        from .dna_colors import apply_base_colors, colors_from_props, store_colors_on_object

        props = context.scene.dna_builder_props
        nucleic_type = props.nucleic_type

        # Validate sequence
        raw = props.sequence
        seq = validate_sequence(raw, nucleic_type)
        if len(seq) < 2:
            self.report({"ERROR"}, "Sequence must be at least 2 valid nucleotides.")
            return {"CANCELLED"}

        if len(seq) > 500:
            self.report(
                {"WARNING"},
                f"Long sequence ({len(seq)} nt) may be slow to build.",
            )

        # Unique identifier
        scene_mgr = ProteinBlenderScene.get_instance()
        identifier = self._next_id(props, scene_mgr)

        # Build the AtomArray
        try:
            array = build_nucleic_acid(
                sequence=seq,
                nucleic_type=nucleic_type,
                double_stranded=props.double_stranded,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Build failed: {e}")
            return {"CANCELLED"}

        # Create Blender object via MN pipeline
        try:
            wrapper = scene_mgr.molecule_manager.create_from_array(
                array=array,
                identifier=identifier,
                style=props.style,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Object creation failed: {e}")
            return {"CANCELLED"}

        obj = wrapper.molecule.object

        # Store DNA metadata as custom properties (persists across undo/save)
        obj["pb_is_nucleic_acid"] = True
        obj["pb_nucleic_type"] = nucleic_type
        obj["pb_sequence"] = seq
        obj["pb_double_stranded"] = props.double_stranded
        obj["pb_style"] = props.style

        # Apply per-base colouring.
        # Force depsgraph evaluation first so res_name attribute is populated.
        context.evaluated_depsgraph_get()
        colors = colors_from_props(props)
        store_colors_on_object(obj, colors)
        apply_base_colors(obj, colors)

        # Finalize: add to molecule list, build outliner
        scene_mgr._finalize_dna_molecule(wrapper)

        info = calculate_helix_info(len(seq), nucleic_type)
        self.report(
            {"INFO"},
            f"Created {identifier}: {len(seq)} nt, "
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
