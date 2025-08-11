"""Group Maker panel for creating and managing groups"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import StringProperty, EnumProperty
from ..utils.scene_manager import build_outliner_hierarchy, ProteinBlenderScene


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
        
        # Filter out groups and check for items already in groups
        valid_items = [item for item in selected_items 
                      if item.item_type not in ['GROUP'] and item.item_id != "groups_separator"]
        
        # Check if any selected items are already in groups
        items_with_groups = []
        for item in valid_items:
            if item.group_memberships:
                items_with_groups.append(item.name)
        
        if items_with_groups:
            # Build error message
            if len(items_with_groups) == 1:
                self.report({'ERROR'}, f'Cannot create group: "{items_with_groups[0]}" is already in a group')
            elif len(items_with_groups) <= 3:
                items_str = ', '.join([f'"{name}"' for name in items_with_groups])
                self.report({'ERROR'}, f'Cannot create group: {items_str} are already in groups')
            else:
                first_items = ', '.join([f'"{name}"' for name in items_with_groups[:2]])
                self.report({'ERROR'}, f'Cannot create group: {first_items} and {len(items_with_groups)-2} more items are already in groups')
            return {'CANCELLED'}
        
        if not valid_items:
            self.report({'WARNING'}, "No valid items selected to create a group")
            return {'CANCELLED'}
        
        # Generate default name
        # Count only actual groups, excluding the separator
        group_count = len([i for i in context.scene.outliner_items 
                          if i.item_type == 'GROUP' and i.item_id != "groups_separator"])
        self.group_name = f"Group {group_count + 1}"
        
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
        
        # Create group ID
        import uuid
        group_id = f"group_{uuid.uuid4().hex[:8]}"
        
        # Filter items that can be grouped (exclude groups themselves)
        items_to_group = []
        items_already_grouped = []
        for item in selected_items:
            if item.item_type != 'GROUP' and item.item_id != "groups_separator":
                # Check if already in a group
                if item.group_memberships:
                    items_already_grouped.append(item.name)
                else:
                    items_to_group.append(item)
        
        # If any items are already in groups, don't proceed
        if items_already_grouped:
            if len(items_already_grouped) == 1:
                self.report({'ERROR'}, f'Cannot create group: "{items_already_grouped[0]}" is already in a group')
            else:
                self.report({'ERROR'}, f'Cannot create group: {len(items_already_grouped)} selected items are already in groups')
            return {'CANCELLED'}
        
        if not items_to_group:
            self.report({'WARNING'}, "No valid items to group")
            return {'CANCELLED'}
        
        # Add group membership to selected items
        for item in items_to_group:
            # Get current memberships
            current_groups = item.group_memberships.split(',') if item.group_memberships else []
            # Add new group if not already a member
            if group_id not in current_groups:
                current_groups.append(group_id)
                item.group_memberships = ','.join(filter(None, current_groups))
            # Keep items selected - don't deselect them automatically
            # This prevents confusion where creating a group changes selection
        
        # Create the group item
        group_item = scene.outliner_items.add()
        group_item.item_type = 'GROUP'
        group_item.item_id = group_id
        group_item.name = self.group_name
        group_item.parent_id = ""
        group_item.indent_level = 0
        group_item.icon = 'GROUP'
        group_item.is_expanded = True
        group_item.is_selected = False  # Don't auto-select the new group
        
        # Store member IDs in the group's memberships field for easy access
        member_ids = [item.item_id for item in items_to_group]
        group_item.group_memberships = ','.join(member_ids)
        
        # Rebuild the outliner to reflect the new group
        build_outliner_hierarchy(context)
        
        self.report({'INFO'}, f"Created group: {self.group_name} with {len(items_to_group)} items")
        return {'FINISHED'}


class PROTEINBLENDER_OT_delete_group(Operator):
    """Delete a group"""
    bl_idname = "proteinblender.delete_group"
    bl_label = "Delete Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    group_id: StringProperty(
        name="Group ID",
        description="ID of the group to delete"
    )
    
    def invoke(self, context, event):
        # Find the group name for the confirmation message
        for item in context.scene.outliner_items:
            if item.item_id == self.group_id and item.item_type == 'GROUP':
                self.group_name = item.name
                break
        return context.window_manager.invoke_confirm(self, event)
    
    def draw(self, context):
        layout = self.layout
        group_name = getattr(self, 'group_name', 'this group')
        layout.label(text=f'Are you sure you want to delete "{group_name}"?')
    
    def execute(self, context):
        scene = context.scene
        
        # Find and remove the group
        group_item = None
        group_index = -1
        for i, item in enumerate(scene.outliner_items):
            if item.item_id == self.group_id and item.item_type == 'GROUP':
                group_item = item
                group_index = i
                break
        
        if not group_item:
            self.report({'ERROR'}, "Group not found")
            return {'CANCELLED'}
        
        # Remove group membership from all items
        for item in scene.outliner_items:
            if item.group_memberships:
                groups = item.group_memberships.split(',')
                if self.group_id in groups:
                    groups.remove(self.group_id)
                    item.group_memberships = ','.join(groups)
        
        # Remove the group item
        scene.outliner_items.remove(group_index)
        
        # Rebuild outliner
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)
        self.report({'INFO'}, f"Deleted group: {group_item.name}")
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_group(Operator):
    """Edit selected group"""
    bl_idname = "proteinblender.edit_group"
    bl_label = "Delete Group"
    bl_options = {'REGISTER', 'UNDO'}
    
    action: EnumProperty(
        name="Action",
        items=[
            ('EDIT', "DeleteGroup", "Edit group name and members"),
            ('ADD', "Add to Group", "Add selected items to group"),
            ('REMOVE', "Remove from Group", "Remove selected items from group"),
            ('RENAME', "Rename Group", "Rename the group"),
            ('DELETE', "Delete Group", "Delete the group"),  # Keep for backward compatibility
        ]
    )
    
    group_id: StringProperty(
        name="Group ID",
        description="ID of the group to edit"
    )
    
    new_name: StringProperty(
        name="Group Name",
        description="Name for the group"
    )
    
    # Properties to track item selection in edit dialog
    item_selections: bpy.props.CollectionProperty(
        type=bpy.types.PropertyGroup
    )
    
    def invoke(self, context, event):
        if self.action == 'EDIT':
            # Find the group
            group_item = None
            for item in context.scene.outliner_items:
                if item.item_id == self.group_id and item.item_type == 'GROUP':
                    group_item = item
                    self.new_name = item.name
                    break
            
            if not group_item:
                self.report({'ERROR'}, "Group not found")
                return {'CANCELLED'}
            
            # Clear and populate item selections
            self.item_selections.clear()
            
            # Get current group members
            current_members = set(group_item.group_memberships.split(',')) if group_item.group_memberships else set()
            
            # Add all selectable items
            scene_manager = ProteinBlenderScene.get_instance()
            for mol_id, molecule in scene_manager.molecules.items():
                # Add domains
                for domain_id, domain in molecule.domains.items():
                    if domain.object:
                        item_sel = self.item_selections.add()
                        item_sel.name = f"{domain.object.name}_{domain_id}"
                        item_sel['item_id'] = f"{mol_id}_{domain_id}"
                        item_sel['display_name'] = domain.name if hasattr(domain, 'name') else domain.object.name
                        item_sel['is_selected'] = f"{mol_id}_{domain_id}" in current_members
                        item_sel['item_type'] = 'DOMAIN'
                        item_sel['parent_name'] = getattr(molecule, 'name', molecule.identifier)
                
                # Add chains
                for chain_item in context.scene.outliner_items:
                    if chain_item.item_type == 'CHAIN' and chain_item.parent_id == mol_id:
                        item_sel = self.item_selections.add()
                        item_sel.name = f"{chain_item.name}_{chain_item.item_id}"
                        item_sel['item_id'] = chain_item.item_id
                        item_sel['display_name'] = chain_item.name
                        item_sel['is_selected'] = chain_item.item_id in current_members
                        item_sel['item_type'] = 'CHAIN'
                        item_sel['parent_name'] = getattr(molecule, 'name', molecule.identifier)
            
            return context.window_manager.invoke_props_dialog(self, width=400)
            
        elif self.action == 'RENAME':
            # Get selected group name
            for item in context.scene.outliner_items:
                if item.is_selected and item.item_type == 'GROUP':
                    self.new_name = item.name
                    break
            return context.window_manager.invoke_props_dialog(self)
        elif self.action == 'DELETE':
            # Fallback for when the dedicated delete operator isn't available
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)
    
    def draw(self, context):
        layout = self.layout
        
        if self.action == 'DELETE':
            # Show a clear delete confirmation message
            group_name = "this group"
            for item in context.scene.outliner_items:
                if item.item_id == self.group_id and item.item_type == 'GROUP':
                    group_name = f'"{item.name}"'
                    break
            layout.label(text=f"Are you sure you want to delete {group_name}?", icon='ERROR')
            return
        
        if self.action == 'EDIT':
            # Group name
            layout.prop(self, "new_name")
            layout.separator()
            
            # Create scrollable list of items
            box = layout.box()
            box.label(text="Group Members:", icon='GROUP')
            
            # Group items by parent
            items_by_parent = {}
            for item in self.item_selections:
                parent = item.get('parent_name', 'Unknown')
                if parent not in items_by_parent:
                    items_by_parent[parent] = []
                items_by_parent[parent].append(item)
            
            # Display hierarchically
            for parent_name, items in items_by_parent.items():
                col = box.column(align=True)
                col.label(text=parent_name, icon='MESH_DATA')
                
                for item in items:
                    row = col.row(align=True)
                    row.prop(item, '["is_selected"]', text=item.get('display_name', item.name))
                    
                col.separator()
                
        elif self.action == 'RENAME':
            layout.prop(self, "new_name")
    
    def execute(self, context):
        scene = context.scene
        
        if self.action == 'EDIT':
            # Find the group to edit
            group_item = None
            for item in scene.outliner_items:
                if item.item_id == self.group_id and item.item_type == 'GROUP':
                    group_item = item
                    break
            
            if not group_item:
                self.report({'ERROR'}, "Group not found")
                return {'CANCELLED'}
            
            # Update group name
            group_item.name = self.new_name
            
            # Update group members
            new_members = []
            for item_sel in self.item_selections:
                if item_sel.get('is_selected', False):
                    new_members.append(item_sel.get('item_id', ''))
            
            # Update group membership
            group_item.group_memberships = ','.join(filter(None, new_members))
            
            # Update item memberships
            # First, remove this group from all items
            for item in scene.outliner_items:
                if item.group_memberships:
                    groups = item.group_memberships.split(',')
                    if self.group_id in groups:
                        groups.remove(self.group_id)
                        item.group_memberships = ','.join(groups)
            
            # Then add group to selected items
            for member_id in new_members:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        groups = item.group_memberships.split(',') if item.group_memberships else []
                        if self.group_id not in groups:
                            groups.append(self.group_id)
                            item.group_memberships = ','.join(filter(None, groups))
                        break
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Updated group: {self.new_name}")
            
        elif self.action == 'DELETE':
            # Fallback implementation for when dedicated delete operator isn't available
            # Find and remove the group
            group_item = None
            group_index = -1
            for i, item in enumerate(scene.outliner_items):
                if item.item_id == self.group_id and item.item_type == 'GROUP':
                    group_item = item
                    group_index = i
                    break
            
            if not group_item:
                self.report({'ERROR'}, "Group not found")
                return {'CANCELLED'}
            
            # Remove group membership from all items
            for item in scene.outliner_items:
                if item.group_memberships:
                    groups = item.group_memberships.split(',')
                    if self.group_id in groups:
                        groups.remove(self.group_id)
                        item.group_memberships = ','.join(groups)
            
            # Remove the group item
            scene.outliner_items.remove(group_index)
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Deleted group: {group_item.name}")
            
        elif self.action == 'RENAME':
            # Find selected group
            selected_group = None
            for item in scene.outliner_items:
                if item.is_selected and item.item_type == 'GROUP':
                    selected_group = item
                    break
            
            if selected_group:
                selected_group.name = self.new_name
                self.report({'INFO'}, f"Renamed group to: {self.new_name}")
        
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
        
        # Create a box for the entire panel content
        box = layout.box()
        
        # Add panel title inside the box
        box.label(text="Group Maker", icon='GROUP')
        box.separator()
        
        # Get selected items and check their group memberships
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        # Filter out groups and separator from selection count
        ungrouped_items = [item for item in selected_items if item.item_type not in ['GROUP'] and item.item_id != "groups_separator"]
        
        # Check if any selected items are already in groups
        items_already_grouped = []
        group_names_dict = {}  # Map group IDs to names
        
        # First build a map of group IDs to names
        for item in scene.outliner_items:
            if item.item_type == 'GROUP':
                group_names_dict[item.item_id] = item.name
        
        # Check which items are already in groups
        for item in ungrouped_items:
            if item.group_memberships:
                group_ids = item.group_memberships.split(',')
                # Get the names of groups this item belongs to
                group_names = [group_names_dict.get(gid, gid) for gid in group_ids if gid]
                if group_names:
                    items_already_grouped.append((item.name, group_names))
        
        # Create New Group button - disable if items are already grouped
        col = box.column(align=True)
        row = col.row()
        row.scale_y = 1.5
        
        # Disable button if any selected items are already in groups
        row.enabled = len(items_already_grouped) == 0 and len(ungrouped_items) > 0
        row.operator("proteinblender.create_group", text="Create New Group", icon='GROUP')
        
        # Info section
        box.separator()
        info_box = box.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 0.8
        
        # Show warnings if items are already grouped
        if items_already_grouped:
            # Show warning icon and message
            warning_row = info_col.row()
            warning_row.alert = True
            warning_row.label(text="Cannot create group:", icon='ERROR')
            
            # List items that are already in groups
            for item_name, group_names in items_already_grouped[:3]:  # Show max 3 items
                if len(group_names) == 1:
                    info_col.label(text=f'  "{item_name}" is in {group_names[0]}', icon='DOT')
                else:
                    groups_str = ', '.join(group_names[:2])
                    if len(group_names) > 2:
                        groups_str += f' (+{len(group_names)-2} more)'
                    info_col.label(text=f'  "{item_name}" is in: {groups_str}', icon='DOT')
            
            # If there are more items, show count
            if len(items_already_grouped) > 3:
                info_col.label(text=f"  ...and {len(items_already_grouped)-3} more items", icon='DOT')
                
        elif ungrouped_items:
            # Show regular selection info
            info_col.label(text=f"{len(ungrouped_items)} items selected", icon='INFO')
            info_col.label(text="Ready to create group")
        else:
            # No items selected
            info_col.label(text="Select items to group", icon='INFO')
            info_col.label(text="Proteins, chains, or domains")
        
        # Add bottom spacing
        layout.separator()



# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_create_group,
    PROTEINBLENDER_OT_delete_group,
    PROTEINBLENDER_OT_edit_group,
    PROTEINBLENDER_PT_group_maker,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)