"""Group Maker panel for managing protein groups.

This module implements the Group Maker panel with:
- Group list display
- Create/Edit group popup dialog
- Tree view with checkboxes for membership
- Group management operations
"""

import bpy
from bpy.types import Panel, Operator, UIList
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from ..properties.group_props import create_new_group, get_group_by_id, update_outliner_for_groups
from ..utils.scene_manager import ProteinBlenderScene


class VIEW3D_PT_pb_group_maker(Panel):
    """Group Maker panel for creating and managing groups."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "Group Maker"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create New Group button
        layout.operator("pb.create_edit_group", text="Create New Group", icon='ADD')
        
        # List existing groups
        if hasattr(scene, 'pb_groups') and len(scene.pb_groups) > 0:
            layout.separator()
            
            # Draw each group with its contents
            for i, group in enumerate(scene.pb_groups):
                box = layout.box()
                row = box.row()
                
                # Expand/collapse icon
                if group.is_expanded:
                    row.prop(group, "is_expanded", text="", icon='DOWNARROW_HLT', emboss=False)
                else:
                    row.prop(group, "is_expanded", text="", icon='RIGHTARROW', emboss=False)
                
                # Group name
                row.label(text=group.name)
                
                # Edit button
                edit_op = row.operator("pb.create_edit_group", text="", icon='PREFERENCES')
                edit_op.mode = 'EDIT'
                edit_op.group_index = i
                
                # Delete button
                delete_op = row.operator("pb.delete_group", text="", icon='X')
                delete_op.group_index = i
                
                # Show group contents if expanded
                if group.is_expanded and len(group.members) > 0:
                    col = box.column(align=True)
                    for member in group.members:
                        member_row = col.row()
                        member_row.scale_y = 0.8
                        
                        # Indent based on type
                        if member.type == 'CHAIN':
                            member_row.separator(factor=1.0)
                        elif member.type == 'DOMAIN':
                            member_row.separator(factor=2.0)
                        
                        # Member name
                        member_row.label(text=member.name, icon='DOT')
                        
                elif group.is_expanded:
                    box.label(text="  (empty)", icon='INFO')
        else:
            layout.label(text="No groups created")


class PB_OT_create_edit_group(Operator):
    """Create a new group or edit existing group."""
    bl_idname = "pb.create_edit_group"
    bl_label = "Create/Edit Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Mode: CREATE or EDIT
    mode: EnumProperty(
        name="Mode",
        items=[
            ('CREATE', "Create", "Create new group"),
            ('EDIT', "Edit", "Edit existing group")
        ],
        default='CREATE'
    )
    
    # Group index for editing
    group_index: IntProperty(default=-1)
    
    # Temporary group name
    group_name: StringProperty(
        name="Group Name",
        default="New Group"
    )
    
    # Track checkbox states
    item_states: {}
    
    def invoke(self, context, event):
        """Initialize the dialog."""
        scene = context.scene
        
        # Initialize item states
        self.item_states = {}
        
        if self.mode == 'EDIT' and self.group_index >= 0:
            # Editing existing group
            group = scene.pb_groups[self.group_index]
            self.group_name = group.name
            
            # Mark existing members as checked
            for member in group.members:
                self.item_states[member.identifier] = True
        else:
            # Creating new group
            self.mode = 'CREATE'
            self.group_name = f"Group {len(scene.pb_groups) + 1}"
        
        # Show dialog
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        """Draw the dialog interface."""
        layout = self.layout
        scene = context.scene
        outliner_state = scene.protein_outliner_state
        
        # Group name field
        layout.prop(self, "group_name", text="")
        
        layout.separator()
        
        # Info text
        layout.label(text="PDBs, chains or domains added to the group will be grayed")
        layout.label(text="out and no longer selectable unless selecting them")
        layout.label(text="within the group.")
        
        layout.separator()
        
        # Tree view of all items
        box = layout.box()
        col = box.column(align=True)
        
        # Organize items by hierarchy
        current_protein = None
        current_chain = None
        
        for item in outliner_state.items:
            if item.type == 'GROUP':
                continue  # Skip groups in the selection tree
            
            row = col.row(align=True)
            
            # Indentation
            if item.type == 'PROTEIN':
                current_protein = item
                current_chain = None
            elif item.type == 'CHAIN':
                row.separator(factor=1.0)
                current_chain = item
            elif item.type == 'DOMAIN':
                row.separator(factor=2.0)
            
            # Checkbox
            is_checked = self.item_states.get(item.identifier, False)
            
            # Check if item is already in another group
            in_other_group = False
            if self.mode == 'EDIT':
                # When editing, allow items from this group
                for other_group in scene.pb_groups:
                    if other_group != scene.pb_groups[self.group_index]:
                        if other_group.has_member(item.identifier):
                            in_other_group = True
                            break
            else:
                # When creating, check all groups
                for other_group in scene.pb_groups:
                    if other_group.has_member(item.identifier):
                        in_other_group = True
                        break
            
            # Draw checkbox
            if in_other_group:
                row.enabled = False
                row.label(text="", icon='CHECKBOX_DEHLT')
            else:
                checkbox_op = row.operator(
                    "pb.toggle_group_member", 
                    text="", 
                    icon='CHECKBOX_HLT' if is_checked else 'CHECKBOX_DEHLT',
                    emboss=False
                )
                checkbox_op.item_id = item.identifier
                checkbox_op.item_type = item.type
                checkbox_op.item_name = item.name
            
            # Item name
            if in_other_group:
                row.label(text=f"{item.name} (in group)")
            else:
                row.label(text=item.name)
    
    def execute(self, context):
        """Create or update the group."""
        scene = context.scene
        
        if self.mode == 'CREATE':
            # Create new group
            group = create_new_group(context, self.group_name)
        else:
            # Edit existing group
            group = scene.pb_groups[self.group_index]
            group.name = self.group_name
            group.clear_members()
        
        # Add checked items as members
        outliner_state = scene.protein_outliner_state
        for item_id, is_checked in self.item_states.items():
            if is_checked:
                # Find the item
                for item in outliner_state.items:
                    if item.identifier == item_id:
                        # Add to group
                        parent_id = ""
                        if item.type == 'CHAIN':
                            # Find parent protein
                            parts = item.identifier.split('_chain_')
                            if len(parts) == 2:
                                parent_id = parts[0]
                        elif item.type == 'DOMAIN':
                            # Find parent chain
                            # Domain IDs might be like "protein_id_domain_chain_id"
                            parts = item.identifier.split('_')
                            if len(parts) >= 3:
                                parent_id = f"{parts[0]}_chain_{parts[-1]}"
                        
                        group.add_member(
                            identifier=item.identifier,
                            member_type=item.type,
                            name=item.name,
                            parent_id=parent_id
                        )
                        break
        
        # Update outliner to show groups
        update_outliner_for_groups(context)
        
        # Report success
        if self.mode == 'CREATE':
            self.report({'INFO'}, f"Created group '{group.name}' with {len(group.members)} members")
        else:
            self.report({'INFO'}, f"Updated group '{group.name}' with {len(group.members)} members")
        
        return {'FINISHED'}


class PB_OT_toggle_group_member(Operator):
    """Toggle group membership for an item."""
    bl_idname = "pb.toggle_group_member"
    bl_label = "Toggle Group Member"
    bl_options = {'INTERNAL'}
    
    item_id: StringProperty()
    item_type: StringProperty()
    item_name: StringProperty()
    
    def execute(self, context):
        """Toggle the checkbox state."""
        # Get the operator that invoked the dialog
        create_op = context.active_operator
        if create_op and hasattr(create_op, 'item_states'):
            # Toggle state
            current_state = create_op.item_states.get(self.item_id, False)
            create_op.item_states[self.item_id] = not current_state
            
            # If this is a protein, toggle all its children
            if self.item_type == 'PROTEIN' and not current_state:
                # Check all chains and domains of this protein
                outliner_state = context.scene.protein_outliner_state
                for item in outliner_state.items:
                    if self.item_id in item.identifier and item.identifier != self.item_id:
                        create_op.item_states[item.identifier] = True
            
            # If unchecking a protein, uncheck its children
            elif self.item_type == 'PROTEIN' and current_state:
                outliner_state = context.scene.protein_outliner_state
                for item in outliner_state.items:
                    if self.item_id in item.identifier and item.identifier != self.item_id:
                        create_op.item_states[item.identifier] = False
        
        return {'FINISHED'}


class PB_OT_delete_group(Operator):
    """Delete a protein group."""
    bl_idname = "pb.delete_group"
    bl_label = "Delete Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    group_index: IntProperty()
    
    def execute(self, context):
        """Delete the group."""
        scene = context.scene
        
        if 0 <= self.group_index < len(scene.pb_groups):
            group_name = scene.pb_groups[self.group_index].name
            scene.pb_groups.remove(self.group_index)
            
            # Update outliner
            update_outliner_for_groups(context)
            
            self.report({'INFO'}, f"Deleted group '{group_name}'")
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        """Confirm deletion."""
        return context.window_manager.invoke_confirm(self, event)


# Classes to register
CLASSES = [
    VIEW3D_PT_pb_group_maker,
    PB_OT_create_edit_group,
    PB_OT_toggle_group_member,
    PB_OT_delete_group,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)