"""Builder panel for DNA/RNA creation.

The panel is intentionally minimal: a single "Create New DNA / RNA"
button that pops the build dialog (``proteinblender.build_dna``). All
of the build form lives inside that dialog so create and edit (the
PB Outliner's edit pencil also fires the same operator with
``molecule_id_to_update`` set) look pixel-identical.

The Shape / bend-rig controls remain in the panel because they're
live viewport editing tools (drag node empties, toggle curve
visibility), not one-shot dialog inputs.
"""

import bpy
from bpy.types import Panel


class PROTEINBLENDER_PT_builders(Panel):
    """Builders panel — entry point for the DNA / RNA dialog and the
    bend-rig controls for the currently active strand."""

    bl_label = "Builders"
    bl_idname = "PROTEINBLENDER_PT_builders"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_order = 8  # After Flexible Linkers (7)
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    def draw(self, context):
        layout = self.layout

        # ---- Edit mode detection -----------------------------------------
        # The user is "editing a DNA" if either:
        #   (a) the active object is a DNA molecule
        #   (b) the active object is its bend curve, or
        #   (c) the active object is one of its bend control nodes (the
        #       Empties placed by "Edit Bend").
        from .bender import get_dna_for_curve, get_dna_for_node
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

        # ---- Panel body --------------------------------------------------
        main_box = layout.box()
        main_box.label(text="Builders", icon="CURVE_DATA")
        main_box.separator()

        # ---- Create button — fires the build dialog (Create mode) -------
        create_row = main_box.row()
        create_row.scale_y = 1.4
        create_row.operator(
            "proteinblender.build_dna",
            text="Create New DNA / RNA",
            icon="ADD",
        )

        if editing:
            main_box.separator(factor=0.5)

            # Editing-context header
            row = main_box.row()
            row.label(
                text=f"Editing: {dna_obj.name}",
                icon="GREASEPENCIL",
            )

            # Edit-this-strand shortcut — same dialog, pre-populated.
            edit_row = main_box.row()
            edit_row.scale_y = 1.2
            # Look up the molecule's identifier in the scene manager so
            # the operator knows which one to rebuild.
            mol_id = self._find_molecule_id_for_object(dna_obj)
            if mol_id:
                op = edit_row.operator(
                    "proteinblender.build_dna",
                    text=f"Edit {dna_obj.name}…",
                    icon="GREASEPENCIL",
                )
                op.molecule_id_to_update = mol_id

            if editing_node:
                # User is dragging a control node — offer a fast way to
                # bounce back to the DNA when they're done.
                done_row = main_box.row()
                done_row.scale_y = 1.1
                done_row.operator(
                    "proteinblender.dna_finish_bend_edit",
                    text="✓ Done Editing Bend",
                    icon="LOOP_BACK",
                )

            # Shape / bend-rig controls (live viewport editing — kept in
            # the panel because they're not one-shot dialog inputs)
            self._draw_shape_section(main_box, dna_obj)

    @staticmethod
    def _find_molecule_id_for_object(dna_obj):
        """Look up the molecule manager identifier for a DNA object."""
        from ..utils.scene_manager import ProteinBlenderScene
        sm = ProteinBlenderScene.get_instance()
        for ident, wrapper in sm.molecules.items():
            try:
                if wrapper.molecule and wrapper.molecule.object is dna_obj:
                    return ident
            except Exception:
                continue
        return None

    def _draw_shape_section(self, parent_layout, dna_obj):
        """Bending controls — visible only when a DNA molecule is active."""
        from .bender import (
            BEND_CURVE_PROP,
            RES_DEFAULT, RES_MIN, RES_MAX,
            get_bend_curve,
            get_bend_nodes,
            dna_has_keyframes,
        )

        shape_box = parent_layout.box()
        shape_box.label(text="Shape", icon="CURVE_BEZCURVE")

        has_bend = bool(dna_obj.get(BEND_CURVE_PROP))

        # Rig-structural changes (Add/Remove bend, change node count) rebuild
        # the bend curve and nodes — if the strand is already animated this
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
                text="✚ Add Bend Control",
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
