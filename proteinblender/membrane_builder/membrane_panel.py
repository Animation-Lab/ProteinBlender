"""UI panel for the Membrane Builder.

Sits in the Properties → Scene tab, immediately below the DNA/RNA panel
(bl_order = 8 for DNA, so we take 9).

Two display modes:
 - **Build** (no membrane selected): the user is configuring a new membrane.
   The button at the bottom is "Build Membrane".
 - **Edit** (a membrane or one of its children is the active object): the
   user is editing the selected membrane. Live property changes write through
   to the GN modifier via the props' update callback. The bottom button
   becomes "Resize" (to apply width/height — which require a mesh rebuild —
   instead of live-syncing on every nudge).
"""

import bpy
from bpy.types import Panel

from .membrane_operators import (
    _get_membrane_root,
    _iter_hole_names,
    MAX_HOLES,
)


class PROTEINBLENDER_PT_membrane_builder(Panel):
    """Membrane builder panel — appears below the DNA panel."""

    bl_label = "Membrane Builder"
    bl_idname = "PROTEINBLENDER_PT_membrane_builder"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_order = 9  # After DNA/RNA Builder (8)
    bl_options = {"HIDE_HEADER", "HEADER_LAYOUT_EXPAND"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.membrane_builder_props

        root = _get_membrane_root(context.active_object)
        editing = root is not None

        main_box = layout.box()
        main_box.label(text="Membrane Builder", icon="MOD_FLUIDSIM")
        main_box.separator()

        # ---- Edit header --------------------------------------------------
        if editing:
            header = main_box.row()
            header.label(text=f"Editing: {root.name}", icon="GREASEPENCIL")

            # Quick-jump back to the root if user is inside a child (hole or
            # lattice). Helpful because deforming/positioning easily steals
            # focus.
            active_obj = context.active_object
            if active_obj is not root:
                jump_row = main_box.row()
                jump_row.scale_y = 1.0
                op = jump_row.operator(
                    "proteinblender.membrane_select_hole",
                    text=f"Back to {root.name}",
                    icon="LOOP_BACK",
                )
                op.hole_name = root.name

            # If the active object is the lattice in EDIT mode, surface a
            # "Done Deforming" button.
            if (active_obj is not None
                    and active_obj.type == "LATTICE"
                    and context.mode == "EDIT_LATTICE"):
                done_row = main_box.row()
                done_row.scale_y = 1.1
                done_row.operator(
                    "proteinblender.membrane_finish_deform",
                    text="✓ Done Deforming",
                    icon="LOOP_BACK",
                )
                main_box.separator(factor=0.5)
        else:
            main_box.label(text="Build a new lipid bilayer", icon="INFO")

        # ---- Shape + size -------------------------------------------------
        main_box.prop(props, "shape", text="Shape")
        if props.shape == "FLAT":
            size_row = main_box.row(align=True)
            size_row.prop(props, "width", text="Width (nm)")
            size_row.prop(props, "height", text="Height (nm)")
        else:
            main_box.prop(props, "radius", text="Radius (nm)")

        if not editing:
            main_box.prop(props, "name_prefix", text="Name")
            main_box.prop(props, "lattice_resolution", text="Deform Res")

        # ---- Lipid section (collapsible) ---------------------------------
        lip_box = main_box.box()
        lip_header = lip_box.row()
        lip_header.prop(
            props, "show_lipid_section",
            text="Lipids",
            icon="TRIA_DOWN" if props.show_lipid_section else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_lipid_section:
            lip_box.prop(props, "render_style", text="Style")
            col = lip_box.column(align=True)
            col.prop(props, "density")
            col.prop(props, "bilayer_thickness")
            col.prop(props, "lipid_scale")
            lip_box.prop(props, "random_rotation")

        # ---- Animation section -------------------------------------------
        anim_box = main_box.box()
        anim_header = anim_box.row()
        anim_header.prop(
            props, "show_animation_section",
            text="Bobbing Animation",
            icon="TRIA_DOWN" if props.show_animation_section else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_animation_section:
            anim_box.prop(props, "animate_bob")
            col = anim_box.column(align=True)
            col.enabled = props.animate_bob
            col.prop(props, "bob_amplitude")
            col.prop(props, "bob_speed")
            if props.animate_bob:
                anim_box.label(
                    text="Lipids jostle on 6 axes — bob, sway, lean, twist.",
                    icon="INFO",
                )
                anim_box.label(
                    text="Per-lipid random timing; same every playback.",
                    icon="BLANK1",
                )

        # ---- Colors section ----------------------------------------------
        col_box = main_box.box()
        col_header = col_box.row()
        col_header.prop(
            props, "show_colors_section",
            text="Colors",
            icon="TRIA_DOWN" if props.show_colors_section else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_colors_section:
            c = col_box.column(align=True)
            # SURFACE style fuses head + tail into one mesh — a single
            # picker controls it. Other styles keep the head/tail split.
            from . import lipid_assets as _la
            if props.render_style == _la.STYLE_SURFACE:
                c.prop(props, "color_surface")
            else:
                c.prop(props, "color_head")
                c.prop(props, "color_tail")
            col_box.label(
                text="Colors are shared across all membranes.",
                icon="INFO",
            )

        # ---- Deformation section (only when editing) ---------------------
        if editing:
            deform_box = main_box.box()
            deform_header = deform_box.row()
            deform_header.prop(
                props, "show_deform_section",
                text="Deformation",
                icon="TRIA_DOWN" if props.show_deform_section else "TRIA_RIGHT",
                emboss=False,
            )
            if props.show_deform_section:
                row = deform_box.row(align=True)
                row.scale_y = 1.2
                row.operator(
                    "proteinblender.membrane_edit_deform",
                    text="Edit Deformation",
                    icon="MOD_LATTICE",
                )
                row.operator(
                    "proteinblender.membrane_reset_deform",
                    text="",
                    icon="LOOP_BACK",
                )
                deform_box.label(
                    text=(
                        "Grab lattice points to deform. Right-click → Insert "
                        "Keyframe to animate."
                    ),
                    icon="INFO",
                )

        # ---- Holes section (only when editing) ---------------------------
        if editing:
            hole_box = main_box.box()
            hole_header = hole_box.row()
            hole_header.prop(
                props, "show_holes_section",
                text="Holes",
                icon="TRIA_DOWN" if props.show_holes_section else "TRIA_RIGHT",
                emboss=False,
            )
            if props.show_holes_section:
                hole_names = list(_iter_hole_names(root))
                count_row = hole_box.row()
                count_row.label(
                    text=f"Holes: {len(hole_names)} / {MAX_HOLES}",
                )
                add_row = hole_box.row()
                add_row.scale_y = 1.2
                add_row.enabled = len(hole_names) < MAX_HOLES
                add_row.operator(
                    "proteinblender.membrane_add_hole",
                    text="➕ Add Hole",
                    icon="MESH_TORUS",
                )

                if hole_names:
                    hole_box.separator(factor=0.3)
                    for hname in hole_names:
                        hole_obj = bpy.data.objects.get(hname)
                        if hole_obj is None:
                            continue
                        row = hole_box.row(align=True)
                        is_active = (context.active_object is hole_obj)
                        sel = row.operator(
                            "proteinblender.membrane_select_hole",
                            text=hname,
                            icon="OUTLINER_OB_EMPTY" if not is_active else "RESTRICT_SELECT_OFF",
                            depress=is_active,
                        )
                        sel.hole_name = hname
                        # Quick radius edit via the empty's scale.x
                        row.prop(hole_obj, "scale", index=0, text="r")
                        rem = row.operator(
                            "proteinblender.membrane_remove_hole",
                            text="",
                            icon="X",
                        )
                        rem.hole_name = hname
                    hole_box.separator(factor=0.3)
                    hole_box.label(
                        text="Animate r (scale) or hole position to grow/move it.",
                        icon="INFO",
                    )
                    hole_box.label(
                        text="Lipids are pushed aside, not deleted — they pile up at the rim.",
                        icon="BLANK1",
                    )
                    hole_box.label(
                        text="The hole is a sphere — slide it up/down in Z to close it.",
                        icon="BLANK1",
                    )

        # ---- Action button ------------------------------------------------
        main_box.separator(factor=0.5)
        if editing:
            # In edit mode, size changes don't auto-apply (they need a mesh
            # rebuild). Surface a Resize button labelled for the shape.
            if props.shape == "FLAT":
                resize_label = (
                    f"↻ Resize to {props.width:.1f} × {props.height:.1f} nm")
            else:
                resize_label = f"↻ Resize to r={props.radius:.1f} nm"
            resize_row = main_box.row()
            resize_row.scale_y = 1.4
            resize_row.operator(
                "proteinblender.resize_membrane",
                text=resize_label,
                icon="FILE_REFRESH",
            )
            new_row = main_box.row(align=True)
            new_row.operator(
                "proteinblender.build_membrane",
                text="Build New Instead",
                icon="ADD",
            )
            new_row.operator(
                "proteinblender.delete_membrane",
                text="",
                icon="TRASH",
            )
        else:
            build_row = main_box.row()
            build_row.scale_y = 1.4
            build_row.operator(
                "proteinblender.build_membrane",
                text="▶ Build Membrane",
                icon="MOD_FLUIDSIM",
            )


CLASSES = (PROTEINBLENDER_PT_membrane_builder,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
