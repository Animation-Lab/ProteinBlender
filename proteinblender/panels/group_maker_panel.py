"""Group Maker panel for creating and managing groups"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import StringProperty, EnumProperty
from ..utils.scene_manager import build_outliner_hierarchy


class PROTEINBLENDER_OT_create_group(Operator):
    """Create a new group from selected items"""
    bl_idname = "proteinblender.create_group"
    bl_label = "Create New Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    group_name: StringProperty(
        name="Group Name",
        description="Name for the new group",
        default="New Group"
    )
    
    def invoke(self, context, event):
        """Show dialog to get group name"""
        # Check if any items are selected
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "Select items to create a group")
            return {'CANCELLED'}
        
        # Generate default name
        self.group_name = f"Group {len([i for i in context.scene.outliner_items if i.item_type == 'GROUP']) + 1}"
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "group_name")
        
        # Show what will be grouped
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        layout.label(text=f"Grouping {len(selected_items)} items", icon='INFO')
    
    def execute(self, context):
        scene = context.scene
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            return {'CANCELLED'}
        
        # Create group item
        import uuid
        group_item = scene.outliner_items.add()
        group_item.item_type = 'GROUP'
        group_item.item_id = f"group_{uuid.uuid4().hex[:8]}"
        group_item.name = self.group_name
        group_item.parent_id = ""
        group_item.indent_level = 0
        group_item.icon = 'GROUP'
        group_item.is_expanded = True
        
        # Move selected items under the group
        # (In a real implementation, this would update parent relationships)
        
        # Rebuild outliner
        build_outliner_hierarchy(context)
        
        self.report({'INFO'}, f"Created group: {self.group_name}")
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_group(Operator):
    """Edit selected group"""
    bl_idname = "proteinblender.edit_group"
    bl_label = "Edit Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    action: EnumProperty(
        name="Action",
        items=[
            ('ADD', "Add to Group", "Add selected items to group"),
            ('REMOVE', "Remove from Group", "Remove selected items from group"),
            ('RENAME', "Rename Group", "Rename the group"),
            ('DELETE', "Delete Group", "Delete the group"),
        ]
    )
    
    new_name: StringProperty(
        name="New Name",
        description="New name for the group"
    )
    
    def invoke(self, context, event):
        if self.action == 'RENAME':
            # Get selected group name
            for item in context.scene.outliner_items:
                if item.is_selected and item.item_type == 'GROUP':
                    self.new_name = item.name
                    break
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)
    
    def draw(self, context):
        if self.action == 'RENAME':
            layout = self.layout
            layout.prop(self, "new_name")
    
    def execute(self, context):
        scene = context.scene
        
        # Find selected group
        selected_group = None
        for item in scene.outliner_items:
            if item.is_selected and item.item_type == 'GROUP':
                selected_group = item
                break
        
        if not selected_group and self.action != 'ADD':
            self.report({'WARNING'}, "Select a group first")
            return {'CANCELLED'}
        
        if self.action == 'ADD':
            # Add selected items to group
            # TODO: Implement adding logic
            self.report({'INFO'}, "Would add items to group")
            
        elif self.action == 'REMOVE':
            # Remove selected items from group
            # TODO: Implement removal logic
            self.report({'INFO'}, "Would remove items from group")
            
        elif self.action == 'RENAME':
            # Rename group
            if selected_group:
                selected_group.name = self.new_name
                self.report({'INFO'}, f"Renamed group to: {self.new_name}")
                
        elif self.action == 'DELETE':
            # Delete group
            # TODO: Implement deletion logic
            self.report({'INFO'}, "Would delete group")
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}


class PROTEINBLENDER_PT_group_maker(Panel):
    """Group Maker panel for creating and managing groups"""
    bl_label = "Group Maker"
    bl_idname = "PROTEINBLENDER_PT_group_maker"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 4  # After domain maker
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Add panel title
        layout.label(text="Group Maker", icon='GROUP')
        layout.separator()
        
        # Check for existing groups
        groups = [item for item in scene.outliner_items if item.item_type == 'GROUP']
        
        # Create New Group button
        col = layout.column(align=True)
        row = col.row()
        row.scale_y = 1.5
        row.operator("proteinblender.create_group", text="Create New Group", icon='GROUP')
        
        if groups:
            col.separator()
            
            # Show existing groups
            box = col.box()
            box_col = box.column(align=True)
            box_col.label(text="Groups:", icon='GROUP')
            
            for group in groups:
                row = box_col.row(align=True)
                
                # Group name
                if group.is_selected:
                    row.label(text=group.name, icon='RADIOBUT_ON')
                else:
                    row.label(text=group.name, icon='RADIOBUT_OFF')
                
                # Edit operations
                if group.is_selected:
                    sub = row.row(align=True)
                    sub.scale_x = 0.8
                    
                    op = sub.operator("proteinblender.edit_group", text="", icon='ADD')
                    op.action = 'ADD'
                    
                    op = sub.operator("proteinblender.edit_group", text="", icon='REMOVE')
                    op.action = 'REMOVE'
                    
                    op = sub.operator("proteinblender.edit_group", text="", icon='GREASEPENCIL')
                    op.action = 'RENAME'
                    
                    op = sub.operator("proteinblender.edit_group", text="", icon='X')
                    op.action = 'DELETE'
        
        # Info section
        layout.separator()
        info_box = layout.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 0.8
        
        # Show selection info
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        ungrouped_items = [item for item in selected_items if item.item_type != 'GROUP']
        
        if ungrouped_items:
            info_col.label(text=f"{len(ungrouped_items)} items selected", icon='INFO')
            info_col.label(text="Ready to create group")
        else:
            info_col.label(text="Select items to group", icon='INFO')
            info_col.label(text="Proteins, chains, or domains")
        
        # Add bottom spacing
        layout.separator()



# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_create_group,
    PROTEINBLENDER_OT_edit_group,
    PROTEINBLENDER_PT_group_maker,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)