"""PropertyGroup for the DNA/RNA Builder panel."""

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def _on_nucleic_type_changed(self, context):
    """Flip biologically natural defaults when the user toggles DNA <-> RNA.

    DNA is ~always double-stranded in nature; RNA is ~always single-stranded
    (mRNA, tRNA, rRNA, lncRNA — dsRNA exists in viruses/siRNA but is rare).
    Flip ``double_stranded`` accordingly, and rename ``name_prefix`` to
    match the type — but only when it still looks like a default
    ("DNA"/"RNA"), so a user's custom name isn't clobbered.
    """
    is_dna = self.nucleic_type == "DNA"
    self.double_stranded = is_dna
    if self.name_prefix in ("DNA", "RNA", ""):
        self.name_prefix = "DNA" if is_dna else "RNA"


class DNABuilderProperties(PropertyGroup):
    """Scene-level properties for the DNA/RNA Builder UI."""

    nucleic_type: EnumProperty(
        name="Type",
        items=[
            ("DNA", "DNA", "Deoxyribonucleic acid"),
            ("RNA", "RNA", "Ribonucleic acid"),
        ],
        default="DNA",
        update=_on_nucleic_type_changed,
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
        default="ATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGAT",
        maxlen=1000,
    )

    sequence_length: IntProperty(
        name="Length",
        description="Number of nucleotides for random sequence generation",
        default=50,
        min=2,
        max=500,
    )

    double_stranded: BoolProperty(
        name="Double Stranded",
        description="Build a double-stranded helix with the complementary strand",
        default=True,
    )

    # ------------------------------------------------------------------
    # Winding (helix vs ladder)
    # ------------------------------------------------------------------
    winding_mode: EnumProperty(
        name="Winding",
        description="How the strands relate to each other",
        items=[
            ("HELIX", "Helix", "Standard double helix (fully wound, paired)"),
            ("LADDER", "Ladder",
             "Fully unwound textbook ladder — bases stacked in a flat ladder. "
             "Stylised: backbone geometry is not atomically valid in this mode."),
        ],
        default="HELIX",
    )

    # Hidden: kept unchecked. Functionality is preserved but no longer
    # exposed in the UI.
    ladder_uniform: BoolProperty(
        name="Uniform Rungs",
        description=(
            "Share one set of backbone + base-ring atom positions across "
            "every residue and collapse the purine N7/C8/N9 extension "
            "onto the 6-ring so every rung renders with the same outline. "
            "Per-base colours still apply. Best paired with the Ball & "
            "Stick style — Cartoon style still draws purine vs pyrimidine "
            "blocks at MN's hardcoded sizes. Only applies in Ladder mode."
        ),
        default=False,
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
    show_winding: BoolProperty(name="Show Winding", default=False)


CLASSES = (DNABuilderProperties,)


# ---------------------------------------------------------------------------
# Auto-sync: when a DNA/RNA molecule becomes the active object, copy its
# stored pb_* custom properties into the scene's dna_builder_props so the
# panel acts as an editor for the selected molecule.
# ---------------------------------------------------------------------------

_msgbus_owner = object()


def sync_props_from_object(props, obj) -> bool:
    """Copy pb_* custom props from *obj* into *props*.

    Returns True if any value was actually changed (used to suppress no-op
    redraws).
    """
    if not obj or not obj.get("pb_is_nucleic_acid", False):
        return False

    changed = False

    def _set(attr, value):
        nonlocal changed
        try:
            cur = getattr(props, attr)
            is_seq = isinstance(cur, (list, tuple)) or (
                hasattr(cur, "__iter__") and not isinstance(cur, str)
            )
            if is_seq:
                cur_list = list(cur)
                new_list = list(value)
                if cur_list != new_list:
                    setattr(props, attr, new_list)
                    changed = True
            else:
                if cur != value:
                    setattr(props, attr, value)
                    changed = True
        except Exception:
            pass

    seq = obj.get("pb_sequence")
    if isinstance(seq, str):
        _set("sequence", seq)

    nt = obj.get("pb_nucleic_type")
    if nt in ("DNA", "RNA"):
        _set("nucleic_type", nt)

    ds = obj.get("pb_double_stranded")
    if ds is not None:
        _set("double_stranded", bool(ds))

    style = obj.get("pb_style")
    if isinstance(style, str) and style:
        _set("style", style)

    wm = obj.get("pb_winding_mode")
    if wm in ("HELIX", "LADDER"):
        _set("winding_mode", wm)
    elif wm in ("BUBBLE", "REGION"):
        # Old strands built before BUBBLE/REGION were removed: fall back
        # to HELIX rather than leaving the panel in an unknown state.
        _set("winding_mode", "HELIX")

    lu = obj.get("pb_ladder_uniform")
    if lu is not None:
        _set("ladder_uniform", bool(lu))

    for key, prop_name in (
        ("a", "color_a"), ("t", "color_t"), ("g", "color_g"),
        ("c", "color_c"), ("u", "color_u"), ("backbone", "color_backbone"),
    ):
        v = obj.get(f"pb_color_{key}")
        if v is not None:
            try:
                _set(prop_name, list(v))
            except Exception:
                pass

    return changed


def _on_active_object_changed(*_args):
    try:
        ctx = bpy.context
        scene = getattr(ctx, "scene", None)
        if scene is None or not hasattr(scene, "dna_builder_props"):
            return
        obj = getattr(ctx, "active_object", None)
        if obj is None:
            return
        sync_props_from_object(scene.dna_builder_props, obj)
    except Exception:
        # msgbus callbacks must never raise
        pass


def register_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=_msgbus_owner,
            args=(),
            notify=_on_active_object_changed,
        )
    except Exception:
        pass


def unregister_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass


@persistent
def _load_post_handler(_dummy):
    register_msgbus()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dna_builder_props = bpy.props.PointerProperty(
        type=DNABuilderProperties
    )
    register_msgbus()
    if _load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_handler)


def unregister():
    unregister_msgbus()
    if _load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_handler)
    if hasattr(bpy.types.Scene, "dna_builder_props"):
        del bpy.types.Scene.dna_builder_props
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
