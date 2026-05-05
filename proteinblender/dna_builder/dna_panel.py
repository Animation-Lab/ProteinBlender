"""Builder panel for DNA/RNA creation."""

import bpy
from bpy.types import Panel


def _validate_seq(seq, nt):
    """Lightweight validation without importing heavy deps."""
    valid = set("ATGC") if nt == "DNA" else set("AUGC")
    return "".join(c for c in seq.upper() if c in valid)


def _helix_info(length, nt):
    """Lightweight helix info without importing heavy deps."""
    rise = 2.6 if nt == "RNA" else 3.38
    twist = 32.7 if nt == "RNA" else 36.0
    return {
        "helix_length_angstrom": length * rise,
        "turns": length * twist / 360.0,
    }


class PROTEINBLENDER_PT_builders(Panel):
    """Builders panel (DNA/RNA, future: membranes)."""

    bl_label = "Builders"
    bl_idname = "PROTEINBLENDER_PT_builders"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_order = 8  # After Flexible Linkers (7)
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.dna_builder_props

        # ---- DNA / RNA builder section -----------------------------------
        main_box = layout.box()
        main_box.label(text="Builders", icon="CURVE_DATA")
        main_box.separator()

        # Sub-header
        main_box.label(text="DNA / RNA builder")

        # Type toggle
        row = main_box.row(align=True)
        row.prop(props, "nucleic_type", expand=True)

        main_box.separator(factor=0.3)

        # Input mode toggle
        row = main_box.row(align=True)
        row.prop(props, "input_mode", expand=True)

        if props.input_mode == "RANDOM":
            row = main_box.row(align=True)
            row.prop(props, "sequence_length", text="Length")
            row.operator(
                "proteinblender.randomize_sequence", text="", icon="FILE_REFRESH"
            )

        # Sequence text area
        main_box.prop(props, "sequence", text="")

        # Validation feedback
        nt = props.nucleic_type
        seq = _validate_seq(props.sequence, nt)
        valid_chars = "A T G C" if nt == "DNA" else "A U G C"
        status = "\u2713 valid" if len(seq) >= 2 else "\u2717 too short"
        main_box.label(
            text=f"{valid_chars} only \u00b7 {len(seq)} / 500 \u00b7 {status}"
        )

        main_box.separator(factor=0.3)

        # Double / single stranded
        main_box.prop(props, "double_stranded")

        # Style
        main_box.prop(props, "style")

        # Name
        main_box.prop(props, "name_prefix", text="Name")

        # ---- Collapsible colour section ----------------------------------
        color_box = main_box.box()
        color_header = color_box.row()
        color_header.prop(
            props,
            "show_colors",
            text="Base Colors",
            icon="TRIA_DOWN" if props.show_colors else "TRIA_RIGHT",
            emboss=False,
        )

        if props.show_colors:
            col = color_box.column(align=True)
            col.prop(props, "color_a")
            if nt == "DNA":
                col.prop(props, "color_t")
            else:
                col.prop(props, "color_u")
            col.prop(props, "color_g")
            col.prop(props, "color_c")
            col.separator(factor=0.3)
            col.prop(props, "color_backbone")

            # Update existing button (only if a DNA object is selected)
            obj = context.active_object
            if obj and obj.get("pb_is_nucleic_acid", False):
                col.separator(factor=0.3)
                col.operator(
                    "proteinblender.update_dna_colors",
                    text="Apply to Selected",
                    icon="CHECKMARK",
                )

        # ---- Info readout ------------------------------------------------
        if len(seq) >= 2:
            info = _helix_info(len(seq), nt)
            info_box = main_box.box()
            row = info_box.row()
            row.label(text="Helix length")
            row.label(text=f"{info['helix_length_angstrom']:.1f} \u00c5")
            row = info_box.row()
            row.label(text="Turns")
            row.label(text=f"{info['turns']:.2f}")

        # ---- Build button ------------------------------------------------
        main_box.separator(factor=0.5)
        build_row = main_box.row()
        build_row.scale_y = 1.4
        build_row.operator(
            "proteinblender.build_dna",
            text=f"\u25b6 Build {nt}",
            icon="MESH_CYLINDER",
        )


CLASSES = (PROTEINBLENDER_PT_builders,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
