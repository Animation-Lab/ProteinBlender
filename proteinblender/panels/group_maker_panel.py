"""Puppet Maker panel for creating and managing protein puppets"""

import bpy
from bpy.types import Panel, Operator
from bpy.props import StringProperty, EnumProperty
from ..utils.scene_manager import build_outliner_hierarchy, ProteinBlenderScene


class PROTEINBLENDER_OT_create_puppet(Operator):
    """Create a new protein puppet from selected items"""
    bl_idname = "proteinblender.create_puppet"
    bl_label = "Create New Puppet"
    bl_options = {'REGISTER', 'UNDO'}
    
    puppet_name: StringProperty(
        name="Puppet Name",
        description="Name for the new protein puppet",
        default="New Puppet"
    )
    
    def invoke(self, context, event):
        """Show dialog to get group name"""
        # Check if any items are selected
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "Select items to create a puppet")
            return {'CANCELLED'}
        
        # Filter out groups and check for items already in puppets
        valid_items = [item for item in selected_items 
                      if item.item_type not in ['PUPPET'] and item.item_id != "puppets_separator"]
        
        # Check if any selected items are already in puppets
        items_with_groups = []
        for item in valid_items:
            if item.puppet_memberships:
                items_with_groups.append(item.name)
        
        if items_with_groups:
            # Build error message
            if len(items_with_groups) == 1:
                self.report({'ERROR'}, f'Cannot create puppet: "{items_with_groups[0]}" is already in a puppet')
            elif len(items_with_groups) <= 3:
                items_str = ', '.join([f'"{name}"' for name in items_with_groups])
                self.report({'ERROR'}, f'Cannot create puppet: {items_str} are already in puppets')
            else:
                first_items = ', '.join([f'"{name}"' for name in items_with_groups[:2]])
                self.report({'ERROR'}, f'Cannot create puppet: {first_items} and {len(items_with_groups)-2} more items are already in puppets')
            return {'CANCELLED'}
        
        if not valid_items:
            self.report({'WARNING'}, "No valid items selected to create a puppet")
            return {'CANCELLED'}
        
        # Generate default name
        # Count only actual groups, excluding the separator
        puppet_count = len([i for i in context.scene.outliner_items 
                          if i.item_type == 'PUPPET' and i.item_id != "puppets_separator"])
        self.puppet_name = f"Puppet {puppet_count + 1}"
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "puppet_name")
        
        # Show what will be grouped
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        layout.label(text=f"Creating puppet from {len(selected_items)} items", icon='INFO')
    
    def execute(self, context):
        scene = context.scene
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            return {'CANCELLED'}
        
        # Create group ID
        import uuid
        puppet_id = f"puppet_{uuid.uuid4().hex[:8]}"
        
        # Filter items that can be grouped (exclude groups themselves)
        items_to_group = []
        items_already_grouped = []
        for item in selected_items:
            if item.item_type != 'PUPPET' and item.item_id != "puppets_separator":
                # Check if already in a puppet
                if item.puppet_memberships:
                    items_already_grouped.append(item.name)
                else:
                    items_to_group.append(item)
        
        # If any items are already in puppets, don't proceed
        if items_already_grouped:
            if len(items_already_grouped) == 1:
                self.report({'ERROR'}, f'Cannot create puppet: "{items_already_grouped[0]}" is already in a puppet')
            else:
                self.report({'ERROR'}, f'Cannot create puppet: {len(items_already_grouped)} selected items are already in puppets')
            return {'CANCELLED'}
        
        if not items_to_group:
            self.report({'WARNING'}, "No valid items to puppet")
            return {'CANCELLED'}
        
        # Add group membership to selected items
        for item in items_to_group:
            # Get current memberships
            current_groups = item.puppet_memberships.split(',') if item.puppet_memberships else []
            # Add new group if not already a member
            if puppet_id not in current_groups:
                current_groups.append(puppet_id)
                item.puppet_memberships = ','.join(filter(None, current_groups))
            # Keep items selected - don't deselect them automatically
            # This prevents confusion where creating a group changes selection
        
        # Create the group item
        puppet_item = scene.outliner_items.add()
        puppet_item.item_type = 'PUPPET'
        puppet_item.item_id = puppet_id
        puppet_item.name = self.puppet_name
        puppet_item.parent_id = ""
        puppet_item.indent_level = 0
        puppet_item.icon = 'ARMATURE_DATA'
        puppet_item.is_expanded = True
        puppet_item.is_selected = False  # Don't auto-select the new group
        
        # Store member IDs in the group's memberships field for easy access
        member_ids = [item.item_id for item in items_to_group]
        puppet_item.puppet_memberships = ','.join(member_ids)
        
        # Rebuild the outliner to reflect the new group
        build_outliner_hierarchy(context)
        
        self.report({'INFO'}, f"Created puppet: {self.puppet_name} with {len(items_to_group)} items")
        return {'FINISHED'}


class PROTEINBLENDER_OT_delete_puppet(Operator):
    """Delete a puppet"""
    bl_idname = "proteinblender.delete_puppet"
    bl_label = "Delete Puppet"
    bl_options = {'REGISTER', 'UNDO'}
    
    puppet_id: StringProperty(
        name="Puppet ID",
        description="ID of the puppet to delete"
    )
    
    def invoke(self, context, event):
        # Find the group name for the confirmation message
        for item in context.scene.outliner_items:
            if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                self.puppet_name = item.name
                break
        return context.window_manager.invoke_confirm(self, event)
    
    def draw(self, context):
        layout = self.layout
        puppet_name = getattr(self, 'puppet_name', 'this group')
        layout.label(text=f'Are you sure you want to delete "{puppet_name}"?')
    
    def execute(self, context):
        scene = context.scene
        
        # Find and remove the group
        puppet_item = None
        puppet_index = -1
        for i, item in enumerate(scene.outliner_items):
            if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                puppet_item = item
                puppet_index = i
                break
        
        if not puppet_item:
            self.report({'ERROR'}, "Puppet not found")
            return {'CANCELLED'}
        
        # Remove group membership from all items
        for item in scene.outliner_items:
            if item.puppet_memberships:
                groups = item.puppet_memberships.split(',')
                if self.puppet_id in puppets:
                    groups.remove(self.puppet_id)
                    item.puppet_memberships = ','.join(groups)
        
        # Remove the group item
        scene.outliner_items.remove(puppet_index)
        
        # Rebuild outliner
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)
        self.report({'INFO'}, f"Deleted puppet: {puppet_item.name}")
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_puppet(Operator):
    """Edit selected puppet"""
    bl_idname = "proteinblender.edit_puppet"
    bl_label = "Delete Puppet"
    bl_options = {'REGISTER', 'UNDO'}
    
    action: EnumProperty(
        name="Action",
        items=[
            ('EDIT', "DeletePuppet", "Edit puppet name and members"),
            ('ADD', "Add to Puppet", "Add selected items to puppet"),
            ('REMOVE', "Remove from Puppet", "Remove selected items from puppet"),
            ('RENAME', "Rename Puppet", "Rename the puppet"),
            ('DELETE', "Delete Puppet", "Delete the puppet"),  # Keep for backward compatibility
        ]
    )
    
    puppet_id: StringProperty(
        name="Puppet ID",
        description="ID of the puppet to edit"
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
            puppet_item = None
            for item in context.scene.outliner_items:
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    self.new_name = item.name
                    break
            
            if not puppet_item:
                self.report({'ERROR'}, "Puppet not found")
                return {'CANCELLED'}
            
            # Clear and populate item selections
            self.item_selections.clear()
            
            # Get current group members
            current_members = set(puppet_item.puppet_memberships.split(',')) if puppet_item.puppet_memberships else set()
            
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
                if item.is_selected and item.item_type == 'PUPPET':
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
            puppet_name = "this group"
            for item in context.scene.outliner_items:
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_name = f'"{item.name}"'
                    break
            layout.label(text=f"Are you sure you want to delete {puppet_name}?", icon='ERROR')
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
            puppet_item = None
            for item in scene.outliner_items:
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    break
            
            if not puppet_item:
                self.report({'ERROR'}, "Puppet not found")
                return {'CANCELLED'}
            
            # Update group name
            puppet_item.name = self.new_name
            
            # Update group members
            new_members = []
            for item_sel in self.item_selections:
                if item_sel.get('is_selected', False):
                    new_members.append(item_sel.get('item_id', ''))
            
            # Update group membership
            puppet_item.puppet_memberships = ','.join(filter(None, new_members))
            
            # Update item memberships
            # First, remove this group from all items
            for item in scene.outliner_items:
                if item.puppet_memberships:
                    groups = item.puppet_memberships.split(',')
                    if self.puppet_id in puppets:
                        groups.remove(self.puppet_id)
                        item.puppet_memberships = ','.join(groups)
            
            # Then add group to selected items
            for member_id in new_members:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        groups = item.puppet_memberships.split(',') if item.puppet_memberships else []
                        if self.puppet_id not in puppets:
                            groups.append(self.puppet_id)
                            item.puppet_memberships = ','.join(filter(None, groups))
                        break
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Updated puppet: {self.new_name}")
            
        elif self.action == 'DELETE':
            # Fallback implementation for when dedicated delete operator isn't available
            # Find and remove the group
            puppet_item = None
            puppet_index = -1
            for i, item in enumerate(scene.outliner_items):
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    puppet_index = i
                    break
            
            if not puppet_item:
                self.report({'ERROR'}, "Puppet not found")
                return {'CANCELLED'}
            
            # Remove group membership from all items
            for item in scene.outliner_items:
                if item.puppet_memberships:
                    groups = item.puppet_memberships.split(',')
                    if self.puppet_id in puppets:
                        groups.remove(self.puppet_id)
                        item.puppet_memberships = ','.join(groups)
            
            # Remove the group item
            scene.outliner_items.remove(puppet_index)
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Deleted puppet: {puppet_item.name}")
            
        elif self.action == 'RENAME':
            # Find selected group
            selected_group = None
            for item in scene.outliner_items:
                if item.is_selected and item.item_type == 'PUPPET':
                    selected_group = item
                    break
            
            if selected_group:
                selected_group.name = self.new_name
                self.report({'INFO'}, f"Renamed group to: {self.new_name}")
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}


class PROTEINBLENDER_PT_puppet_maker(Panel):
    """Puppet Maker panel for creating and managing protein puppets"""
    bl_label = "Protein Puppet Maker"
    bl_idname = "PROTEINBLENDER_PT_puppet_maker"
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
        box.label(text="Protein Puppet Maker", icon='ARMATURE_DATA')
        box.separator()
        
        # Get selected items and check their group memberships
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        # Filter out groups and separator from selection count
        ungrouped_items = [item for item in selected_items if item.item_type not in ['PUPPET'] and item.item_id != "puppets_separator"]
        
        # Check if any selected items are already in puppets
        items_already_grouped = []
        puppet_names_dict = {}  # Map group IDs to names
        
        # First build a map of group IDs to names
        for item in scene.outliner_items:
            if item.item_type == 'PUPPET':
                puppet_names_dict[item.item_id] = item.name
        
        # Check which items are already in puppets
        for item in ungrouped_items:
            if item.puppet_memberships:
                puppet_ids = item.puppet_memberships.split(',')
                # Get the names of puppets this item belongs to
                puppet_names = [puppet_names_dict.get(pid, pid) for pid in puppet_ids if pid]
                if puppet_names:
                    items_already_grouped.append((item.name, puppet_names))
        
        # Create New Group button - disable if items are already grouped
        col = box.column(align=True)
        row = col.row()
        row.scale_y = 1.5
        
        # Disable button if any selected items are already in puppets
        row.enabled = len(items_already_grouped) == 0 and len(ungrouped_items) > 0
        row.operator("proteinblender.create_puppet", text="Create New Puppet", icon='ARMATURE_DATA')
        
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
            warning_row.label(text="Cannot create puppet:", icon='ERROR')
            
            # List items that are already in puppets
            for item_name, puppet_names in items_already_grouped[:3]:  # Show max 3 items
                if len(puppet_names) == 1:
                    info_col.label(text=f'  "{item_name}" is in {puppet_names[0]}', icon='DOT')
                else:
                    groups_str = ', '.join(puppet_names[:2])
                    if len(puppet_names) > 2:
                        groups_str += f' (+{len(puppet_names)-2} more)'
                    info_col.label(text=f'  "{item_name}" is in: {groups_str}', icon='DOT')
            
            # If there are more items, show count
            if len(items_already_grouped) > 3:
                info_col.label(text=f"  ...and {len(items_already_grouped)-3} more items", icon='DOT')
                
        elif ungrouped_items:
            # Show regular selection info
            info_col.label(text=f"{len(ungrouped_items)} items selected", icon='INFO')
            info_col.label(text="Ready to create puppet")
        else:
            # No items selected
            info_col.label(text="Select items to puppet", icon='INFO')
            info_col.label(text="Proteins, chains, or domains")
        
        # Add bottom spacing
        layout.separator()



# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_create_puppet,
    PROTEINBLENDER_OT_delete_puppet,
    PROTEINBLENDER_OT_edit_puppet,
    PROTEINBLENDER_PT_puppet_maker,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)