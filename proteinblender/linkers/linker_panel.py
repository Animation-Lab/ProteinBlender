"""UI Panel for managing flexible linkers within a single puppet."""

import bpy
from bpy.types import Operator, Panel, UIList
from bpy.props import StringProperty


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

            # Edit button — opens the same pop-up dialog as Create Linker,
            # pre-populated from this linker's current settings. Replaces
            # the prior expand-toggle + inline editor so the create/edit
            # flows are consistent (always a pop-up).
            op = row.operator("pb2.edit_linker", text="", icon='GREASEPENCIL', emboss=False)
            op.linker_uid = linker.uid

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
