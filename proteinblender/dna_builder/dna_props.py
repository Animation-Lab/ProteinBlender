"""PropertyGroup for the DNA/RNA Builder panel."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class DNABuilderProperties(PropertyGroup):
    """Scene-level properties for the DNA/RNA Builder UI."""

    nucleic_type: EnumProperty(
        name="Type",
        items=[
            ("DNA", "DNA", "Deoxyribonucleic acid"),
            ("RNA", "RNA", "Ribonucleic acid"),
        ],
        default="DNA",
    )

    input_mode: EnumProperty(
        name="Input Mode",
        items=[
            ("MANUAL", "Sequence", "Type a nucleotide sequence"),
            ("RANDOM", "Length", "Generate a random sequence of given length"),
        ],
        default="MANUAL",
    )

    sequence: StringProperty(
        name="Sequence (5'\u21923')",
        description="Nucleotide sequence. DNA: A T G C. RNA: A U G C",
        default="ATCGATCGATCG",
        maxlen=1000,
    )

    sequence_length: IntProperty(
        name="Length",
        description="Number of nucleotides for random sequence generation",
        default=12,
        min=2,
        max=500,
    )

    double_stranded: BoolProperty(
        name="Double Stranded",
        description="Build a double-stranded helix with the complementary strand",
        default=True,
    )

    style: EnumProperty(
        name="Style",
        items=[
            ("ball_and_stick", "Ball & Stick", "Atoms as spheres, bonds as sticks"),
            ("cartoon", "Cartoon", "Cartoon ribbon representation"),
            ("spheres", "Spheres", "Space-filling VDW spheres"),
            ("sticks", "Sticks", "Bonds only"),
            ("surface", "Surface", "Solvent-accessible surface"),
        ],
        default="ball_and_stick",
    )

    name_prefix: StringProperty(
        name="Name",
        description="Base name for the generated molecule",
        default="DNA",
    )

    # Per-base colours (RGBA, size=4)
    color_a: FloatVectorProperty(
        name="Adenine",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.0, 0.0, 1.0),
    )
    color_t: FloatVectorProperty(
        name="Thymine",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 1.0, 1.0),
    )
    color_g: FloatVectorProperty(
        name="Guanine",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 1.0, 0.0, 1.0),
    )
    color_c: FloatVectorProperty(
        name="Cytosine",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 0.0, 1.0),
    )
    color_u: FloatVectorProperty(
        name="Uracil",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 1.0, 1.0, 1.0),
    )
    color_backbone: FloatVectorProperty(
        name="Backbone",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.75, 0.75, 0.75, 1.0),
    )

    # Collapsible sections
    show_colors: BoolProperty(name="Show Colors", default=False)


CLASSES = (DNABuilderProperties,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dna_builder_props = bpy.props.PointerProperty(
        type=DNABuilderProperties
    )


def unregister():
    if hasattr(bpy.types.Scene, "dna_builder_props"):
        del bpy.types.Scene.dna_builder_props
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
