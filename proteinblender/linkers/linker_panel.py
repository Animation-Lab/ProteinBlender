"""UI Panel for managing flexible linkers within a single puppet."""

import bpy
from bpy.types import Panel, UIList

from .linker_geometry import BU_PER_RESIDUE


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
        """Draw detailed settings for the selected linker."""
        main_box.separator()

        # Puppet info
        box = main_box.box()
        puppet_name = self._get_puppet_name(linker.puppet_id)
        box.label(text=f"Puppet: {puppet_name}", icon='ARMATURE_DATA')

        # Endpoints
        box = main_box.box()
        box.label(text="Endpoints", icon='LINKED')

        row = box.row()
        row.label(text="Start:")
        row.label(text=linker.get_endpoint_a_display())

        row = box.row()
        row.label(text="End:")
        row.label(text=linker.get_endpoint_b_display())

        # Length and reach
        box.separator()
        box.prop(linker, "length_residues")
        max_reach = linker.get_max_reach_bu()
        max_reach_angstrom = linker.length_residues * 3.5
        box.label(text=f"Max reach: {max_reach:.3f} BU ({max_reach_angstrom:.1f} \u00C5)")

        # Physics behavior
        box.separator()
        box.prop(linker, "behavior")

        # Appearance
        box = main_box.box()
        box.label(text="Appearance", icon='MATERIAL')

        col = box.column()
        col.prop(linker, "style")
        col.prop(linker, "rendering_mode")
        col.prop(linker, "color")

        if linker.style == 'TUBE':
            col.prop(linker, "tube_radius")

        col.prop(linker, "binding_zone_residues")

        # Actions
        main_box.separator()
        row = main_box.row(align=True)

        op = row.operator("pb2.edit_linker", text="Edit", icon='GREASEPENCIL')
        op.linker_uid = linker.uid

        op = row.operator("pb2.select_linker_object", text="Select", icon='RESTRICT_SELECT_OFF')
        op.linker_uid = linker.uid

        op = row.operator("pb2.update_linker", text="Refresh", icon='FILE_REFRESH')
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
