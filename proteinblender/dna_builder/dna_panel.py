"""Builder panel for DNA/RNA creation."""

import bpy
from bpy.types import Panel


def _validate_seq(seq, nt):
    """Lightweight validation without importing heavy deps."""
    valid = set("ATGC") if nt == "DNA" else set("AUGC")
    return "".join(c for c in seq.upper() if c in valid)


def _helix_info(length, nt, winding_mode="HELIX"):
    """Lightweight helix info without importing heavy deps.

    LADDER zeroes out the twist accumulation. Length along the helix
    axis is unchanged (rise per bp is constant).
    """
    rise = 2.6 if nt == "RNA" else 3.38
    twist = 32.7 if nt == "RNA" else 36.0

    wound_transitions = 0 if winding_mode == "LADDER" else max(0, length - 1)

    return {
        "helix_length_angstrom": length * rise,
        "turns": wound_transitions * twist / 360.0,
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

        # ---- Edit mode detection -----------------------------------------
        # The user is "editing a DNA" if either:
        #   (a) the active object is a DNA molecule
        #   (b) the active object is its bend curve, or
        #   (c) the active object is one of its bend control nodes (the
        #       Empties placed by "Edit Bend").
        from .bender import (
            BEND_CURVE_PROP,
            get_dna_for_curve,
            get_dna_for_node,
        )
        active_obj = context.active_object
        dna_obj = None

        if active_obj is not None and active_obj.get("pb_is_nucleic_acid", False):
            dna_obj = active_obj
        elif active_obj is not None and active_obj.type == "CURVE":
            dna_obj = get_dna_for_curve(active_obj)
        elif active_obj is not None and active_obj.type == "EMPTY":
            dna_obj = get_dna_for_node(active_obj)

        editing = dna_obj is not None
        editing_node = (editing
                        and active_obj is not None
                        and active_obj is not dna_obj
                        and active_obj.type == "EMPTY")

        # ---- DNA / RNA builder section -----------------------------------
        main_box = layout.box()
        # Tinted-box-style header: a colour swatch icon + bold label. Each
        # builder panel uses a distinct COLORSET_*_VEC swatch so tools
        # read as visually distinct sections at a glance. DNA = green
        # (COLORSET_04) to evoke life / strands.
        _hdr = main_box.row(align=True)
        _hdr.scale_y = 1.15
        _hdr.label(text="", icon="COLORSET_04_VEC")
        _hdr.label(text="DNA / RNA Builder", icon="CURVE_DATA")
        main_box.separator()

        # Sub-header — switches based on edit/build mode
        if editing:
            row = main_box.row()
            row.label(
                text=f"Editing: {dna_obj.name}",
                icon="GREASEPENCIL",
            )
            if editing_node:
                # User is dragging a control node — offer a fast way to
                # bounce back to the DNA when they're done.
                done_row = main_box.row()
                done_row.scale_y = 1.1
                done_row.operator(
                    "proteinblender.dna_finish_bend_edit",
                    text="\u2713 Done Editing Bend",
                    icon="LOOP_BACK",
                )
                main_box.separator(factor=0.5)
        else:
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

        # Single-strand mode: offer a quick way to flip to the antisense
        # strand (reverse complement) so the user can build both strands
        # back-to-back without retyping the sequence.
        if not props.double_stranded:
            row = main_box.row()
            row.operator(
                "proteinblender.swap_to_complement",
                text="⇄ Swap to Complement",
                icon="ARROW_LEFTRIGHT",
            )

        # Style
        main_box.prop(props, "style")

        # Name
        main_box.prop(props, "name_prefix", text="Name")

        # ---- Collapsible winding section ---------------------------------
        wind_box = main_box.box()
        wind_header = wind_box.row()
        wind_header.prop(
            props,
            "show_winding",
            text="Winding",
            icon="TRIA_DOWN" if props.show_winding else "TRIA_RIGHT",
            emboss=False,
        )

        if props.show_winding:
            wind_box.prop(props, "winding_mode", expand=True)

            if props.winding_mode == "LADDER":
                wind_box.label(
                    text="Stylised flat ladder. Backbone is not atomically valid here.",
                    icon="INFO",
                )

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
            if dna_obj is not None:
                col.separator(factor=0.3)
                col.operator(
                    "proteinblender.update_dna_colors",
                    text="Apply to Selected",
                    icon="CHECKMARK",
                )

        # ---- Info readout ------------------------------------------------
        if len(seq) >= 2:
            info = _helix_info(len(seq), nt, winding_mode=props.winding_mode)
            info_box = main_box.box()
            row = info_box.row()
            row.label(text="Helix length")
            row.label(text=f"{info['helix_length_angstrom']:.1f} \u00c5")
            row = info_box.row()
            row.label(text="Turns")
            row.label(text=f"{info['turns']:.2f}")

        # ---- Shape (bending) section — only when editing a DNA ----------
        if editing:
            self._draw_shape_section(main_box, dna_obj)

        # ---- Action button(s) -------------------------------------------
        main_box.separator(factor=0.5)
        if editing:
            update_row = main_box.row()
            update_row.scale_y = 1.4
            update_row.operator(
                "proteinblender.update_dna",
                text=f"\u21bb Update {nt}",
                icon="FILE_REFRESH",
            )
            new_row = main_box.row()
            new_row.operator(
                "proteinblender.build_dna",
                text="Build New Instead",
                icon="ADD",
            )
        else:
            build_row = main_box.row()
            build_row.scale_y = 1.4
            build_row.operator(
                "proteinblender.build_dna",
                text=f"\u25b6 Build {nt}",
                icon="MESH_CYLINDER",
            )

    def _draw_shape_section(self, parent_layout, dna_obj):
        """Bending controls — visible only when a DNA molecule is active."""
        from .bender import (
            BEND_CURVE_PROP,
            BEND_NODES_PROP,
            RES_DEFAULT, RES_MIN, RES_MAX,
            get_bend_curve,
            get_bend_nodes,
            dna_has_keyframes,
        )

        shape_box = parent_layout.box()
        shape_box.label(text="Shape", icon="CURVE_BEZCURVE")

        has_bend = bool(dna_obj.get(BEND_CURVE_PROP))

        # Rig-structural changes (Add/Remove bend, change node count) rebuild
        # the bend curve and nodes \u2014 if the strand is already animated this
        # orphans every F-curve keyed against the old data and silently
        # corrupts the animation. Lock those controls while keyframes exist;
        # the user can delete keyframes from the Animate panel to unlock.
        is_keyframed = dna_has_keyframes(dna_obj)
        lock_msg = "Locked: remove this DNA's keyframes (Animate panel) to change the bend rig."

        if not has_bend:
            row = shape_box.row()
            row.scale_y = 1.2
            row.enabled = not is_keyframed
            row.operator(
                "proteinblender.dna_add_bend",
                text="\u2795 Add Bend Control",
                icon="OUTLINER_OB_CURVE",
            )
            if is_keyframed:
                shape_box.label(text=lock_msg, icon="LOCKED")
            else:
                shape_box.label(
                    text="Adds a Bezier curve along the helix axis.",
                    icon="INFO",
                )
            return

        # ---- Bend exists ---------------------------------------------------
        nodes = get_bend_nodes(dna_obj)
        n_nodes = len(nodes)
        has_nodes = n_nodes > 0

        # Edit / Remove row. Edit Bend just re-selects existing nodes (no
        # structural change), so it stays enabled even when keyframed — the
        # user still needs to grab nodes to set new keyframe values. Remove
        # Bend rebuilds the strand's origin and would orphan the F-curves,
        # so it's locked.
        row = shape_box.row(align=True)
        row.scale_y = 1.2
        edit_op = row.operator(
            "proteinblender.dna_edit_bend",
            text="Edit Bend" if has_nodes else "Place Control Nodes",
            icon="EMPTY_AXIS",
        )
        # When creating fresh, default the count to RES_DEFAULT; otherwise
        # the existing count (this property only matters on first place).
        edit_op.n_points = n_nodes if n_nodes >= RES_MIN else RES_DEFAULT
        remove_sub = row.row(align=True)
        remove_sub.enabled = not is_keyframed
        remove_sub.operator(
            "proteinblender.dna_remove_bend",
            text="",
            icon="X",
        )

        # Node-count control (only after first Edit Bend)
        if has_nodes:
            shape_box.separator(factor=0.3)
            res_row = shape_box.row(align=True)
            res_row.enabled = not is_keyframed
            res_row.label(text="Nodes:")
            minus = res_row.operator(
                "proteinblender.dna_set_bend_resolution",
                text="", icon="REMOVE",
            )
            minus.n_points = max(RES_MIN, n_nodes - 1)
            res_row.label(text=str(n_nodes))
            plus = res_row.operator(
                "proteinblender.dna_set_bend_resolution",
                text="", icon="ADD",
            )
            plus.n_points = min(RES_MAX, n_nodes + 1)

            if is_keyframed:
                shape_box.label(text=lock_msg, icon="LOCKED")
            else:
                shape_box.label(
                    text="Click a node to grab it. Shift-click to multi-select.",
                    icon="INFO",
                )

        # Bend curve visibility toggle. The curve is a viewport-only guide
        # (hide_render is forced True in bender.py), so toggling viewport
        # visibility here lets the user clear the line out of the way without
        # affecting the final rendered image.
        curve_obj = get_bend_curve(dna_obj)
        if curve_obj is not None:
            shape_box.separator(factor=0.3)
            vis_row = shape_box.row(align=True)
            vis_row.prop(
                curve_obj,
                "hide_viewport",
                text="Hide Bend Curve",
                icon="HIDE_ON" if curve_obj.hide_viewport else "HIDE_OFF",
            )
            shape_box.label(
                text="Bend curve is a guide only — never appears in renders.",
                icon="INFO",
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
