"""UI Panel for managing flexible linkers within a single puppet."""

import bpy
from bpy.types import Operator, Panel, UIList
from bpy.props import StringProperty

from .linker_geometry import BU_PER_RESIDUE


class PB2_OT_show_help_popup(Operator):
    """Show a help popup with an explanation"""
    bl_idname = "pb2.show_help_popup"
    bl_label = "Help"
    bl_options = {'INTERNAL'}

    title: StringProperty(name="Title", default="Help")
    message: StringProperty(name="Message", default="")

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.label(text=self.title, icon='INFO')
        layout.separator()
        # Word-wrap the message into multiple lines
        words = self.message.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > 45:
                layout.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            layout.label(text=line)


class PB2_UL_linkers(UIList):
    """UIList for displaying linkers."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        linker = item

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Expand/collapse toggle
            expand_icon = 'TRIA_DOWN' if linker.is_expanded else 'TRIA_RIGHT'
            row.prop(linker, "is_expanded", text="", icon=expand_icon, emboss=False)

            # Visibility toggle
            vis_icon = 'HIDE_OFF' if linker.is_visible else 'HIDE_ON'
            op = row.operator("pb2.toggle_linker_visibility", text="", icon=vis_icon, emboss=False)
            op.linker_uid = linker.uid

            # Linker name with validity indicator
            if linker.is_valid:
                row.label(text=linker.name, icon='LINK_BLEND')
            else:
                row.label(text=f"{linker.name} (Invalid)", icon='ERROR')

            # Style icon
            style_icons = {'TUBE': 'CURVE_BEZCIRCLE', 'BEADS': 'MESH_UVSPHERE'}
            row.label(text="", icon=style_icons.get(linker.style, 'CURVE_DATA'))

            # Rendering mode indicator
            if linker.rendering_mode == 'DETAILED':
                row.label(text="", icon='MESH_DATA')

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=linker.name, icon='LINK_BLEND')


class PB2_PT_linkers(Panel):
    """Panel for linker management."""
    bl_label = "Flexible Linkers"
    bl_idname = "PB2_PT_linkers"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 6

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        main_box = layout.box()
        main_box.label(text="Flexible Linkers", icon='LINK_BLEND')
        main_box.separator()

        # Check if any puppets exist
        has_puppets = False
        if hasattr(scene, 'outliner_items'):
            for item in scene.outliner_items:
                if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                    has_puppets = True
                    break

        if not has_puppets:
            info_box = main_box.box()
            info_box.label(text="Create a puppet first to use linkers", icon='INFO')
            return

        # Create Linker button
        header_row = main_box.row()
        header_row.scale_y = 1.2
        header_row.operator("pb2.add_linker", text="Create Linker", icon='ADD')

        # Linker list
        if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
            info_box = main_box.box()
            info_box.label(text="No linkers defined", icon='INFO')
            info_box.label(text="Click 'Create Linker' to connect chains within a puppet")
            return

        main_box.separator()

        # List with side buttons
        row = main_box.row()
        row.template_list(
            "PB2_UL_linkers", "",
            scene, "pb2_linkers",
            scene, "pb2_linkers_index",
            rows=3
        )

        col = row.column(align=True)
        col.operator("pb2.add_linker", icon='ADD', text="")

        if 0 <= scene.pb2_linkers_index < len(scene.pb2_linkers):
            linker = scene.pb2_linkers[scene.pb2_linkers_index]
            op = col.operator("pb2.remove_linker", icon='REMOVE', text="")
            op.linker_uid = linker.uid
        else:
            col.label(text="", icon='REMOVE')

        col.separator()
        col.operator("pb2.update_all_linkers", icon='FILE_REFRESH', text="")

        # Expanded details for selected linker
        if 0 <= scene.pb2_linkers_index < len(scene.pb2_linkers):
            linker = scene.pb2_linkers[scene.pb2_linkers_index]
            if linker.is_expanded:
                self._draw_linker_details(main_box, linker)

    def _draw_linker_details(self, main_box, linker):
        """Draw detailed settings for the selected linker.

        Everything for the selected linker lives inside ONE outer box so
        the panel reads as a single cohesive editor for that linker \u2014 not
        as a stack of disconnected sections that happen to follow the list.
        """
        main_box.separator(factor=0.5)

        # One box that owns the whole "editor for this linker" surface.
        editor = main_box.box()
        header = editor.row(align=True)
        header.label(text=f"Editing: {linker.name}", icon='LINK_BLEND')
        # Show the linker's style + rendering mode in the header so the
        # user can see what they're editing at a glance.
        style_icons = {'TUBE': 'CURVE_BEZCIRCLE', 'BEADS': 'MESH_UVSPHERE'}
        header.label(text="", icon=style_icons.get(linker.style, 'CURVE_DATA'))
        if linker.rendering_mode == 'DETAILED':
            header.label(text="", icon='MESH_DATA')

        # ---- Connection (puppet + endpoints) ---------------------------
        section = editor.column(align=True)
        section.separator(factor=0.5)

        puppet_name = self._get_puppet_name(linker.puppet_id)
        row = section.row(align=True)
        row.label(text="Puppet:", icon='ARMATURE_DATA')
        row.label(text=puppet_name)

        row = section.row(align=True)
        row.label(text="Start:", icon='TRACKING_BACKWARDS')
        row.label(text=linker.get_endpoint_a_display())

        row = section.row(align=True)
        row.label(text="End:", icon='TRACKING_FORWARDS')
        row.label(text=linker.get_endpoint_b_display())

        # ---- Physics --------------------------------------------------
        editor.separator(factor=0.6)
        section = editor.column(align=True)
        section.label(text="Physics", icon='PHYSICS')
        section.prop(linker, "length_residues")
        max_reach = linker.get_max_reach_bu()
        max_reach_angstrom = linker.length_residues * 3.5
        section.label(text=f"Max reach: {max_reach:.3f} BU ({max_reach_angstrom:.1f} \u00C5)")
        section.prop(linker, "behavior")
        bz_row = section.row(align=True)
        bz_row.prop(linker, "binding_zone_residues")
        help_op = bz_row.operator("pb2.show_help_popup", text="", icon='QUESTION')
        help_op.title = "Binding Zone"
        help_op.message = (
            "The binding zone is the number of residues at each end of the linker "
            "that stay rigid and align with the backbone direction of the connected chain. "
            "This prevents the linker from bending unnaturally right at the attachment point, "
            "mimicking how real peptide linkers emerge from a protein surface."
        )

        # ---- Appearance -----------------------------------------------
        editor.separator(factor=0.6)
        section = editor.column(align=True)
        section.label(text="Appearance", icon='MATERIAL')
        section.prop(linker, "style")
        section.prop(linker, "rendering_mode")
        section.prop(linker, "color")
        if linker.style == 'TUBE':
            section.prop(linker, "tube_radius")
        elif linker.style == 'BEADS':
            section.prop(linker, "bead_radius")
            section.prop(linker, "bead_radius_variance")
            section.prop(linker, "bead_overlap")
            section.prop(linker, "bead_jitter")

        # ---- Actions: Edit / Select / Apply ---------------------------
        # Apply rebuilds the geometry from the current property values \u2014
        # used to be labelled "Refresh" but "Apply" is clearer about
        # what the button does.
        editor.separator(factor=0.6)
        action_row = editor.row(align=True)
        action_row.scale_y = 1.15

        op = action_row.operator("pb2.edit_linker", text="Edit", icon='GREASEPENCIL')
        op.linker_uid = linker.uid

        op = action_row.operator("pb2.select_linker_object", text="Select", icon='RESTRICT_SELECT_OFF')
        op.linker_uid = linker.uid

        op = action_row.operator("pb2.update_linker", text="Apply", icon='CHECKMARK')
        op.linker_uid = linker.uid

    @staticmethod
    def _get_puppet_name(puppet_id: str) -> str:
        """Get display name for a puppet by its ID."""
        scene = bpy.context.scene
        if hasattr(scene, 'outliner_items'):
            for item in scene.outliner_items:
                if item.item_id == puppet_id and item.item_type == 'PUPPET':
                    return item.name
        return puppet_id or "Unknown"


# Registration
CLASSES = [
    PB2_OT_show_help_popup,
    PB2_UL_linkers,
    PB2_PT_linkers,
]


def register():
    """Register linker panel classes."""
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    """Unregister linker panel classes."""
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
