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
    
    @classmethod
    def description(cls, context, properties):
        """Dynamic tooltip based on selection state"""
        scene = context.scene
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        valid_items = [item for item in selected_items 
                      if item.item_type not in ['PUPPET'] 
                      and item.item_id != "puppets_separator"
                      and "_ref_" not in item.item_id]
        
        if not valid_items:
            return "Select chains or domains to create a puppet"
        
        # Check for conflicts
        puppet_names_dict = {}
        for item in scene.outliner_items:
            if item.item_type == 'PUPPET':
                puppet_names_dict[item.item_id] = item.name
        
        conflicts = []
        for item in valid_items:
            if item.puppet_memberships:
                puppet_ids = item.puppet_memberships.split(',')
                puppet_names = [puppet_names_dict.get(pid, pid) for pid in puppet_ids if pid]
                if puppet_names:
                    puppet_text = puppet_names[0] if len(puppet_names) == 1 else ', '.join(puppet_names)
                    conflicts.append(f"• {item.name} is in {puppet_text}")
        
        if conflicts:
            tooltip = "Cannot create puppet - items must be exclusive to one puppet\n\nConflicts:\n"
            tooltip += '\n'.join(conflicts[:5])
            if len(conflicts) > 5:
                tooltip += f"\n... and {len(conflicts)-5} more"
            return tooltip
        
        return f"Create a new puppet from {len(valid_items)} selected item{'s' if len(valid_items) > 1 else ''}"
    
    puppet_name: StringProperty(
        name="Puppet Name",
        description="Name for the new protein puppet",
        default="New Puppet"
    )
    
    def invoke(self, context, event):
        """Show dialog to get puppet name"""
        # Check if any items are selected
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "Select items to create a puppet")
            return {'CANCELLED'}
        
        # Filter out puppets, reference items, and check for items already in puppets
        valid_items = [item for item in selected_items 
                      if item.item_type not in ['PUPPET'] 
                      and item.item_id != "puppets_separator"
                      and "_ref_" not in item.item_id]
        
        # Check if any selected items are already in puppets
        items_with_puppets = []
        for item in valid_items:
            if item.puppet_memberships:
                items_with_puppets.append(item.name)
        
        if items_with_puppets:
            # Build error message
            if len(items_with_puppets) == 1:
                self.report({'ERROR'}, f'Cannot create puppet: "{items_with_puppets[0]}" is already in a puppet')
            elif len(items_with_puppets) <= 3:
                items_str = ', '.join([f'"{name}"' for name in items_with_puppets])
                self.report({'ERROR'}, f'Cannot create puppet: {items_str} are already in puppets')
            else:
                first_items = ', '.join([f'"{name}"' for name in items_with_puppets[:2]])
                self.report({'ERROR'}, f'Cannot create puppet: {first_items} and {len(items_with_puppets)-2} more items are already in puppets')
            return {'CANCELLED'}
        
        if not valid_items:
            self.report({'WARNING'}, "No valid items selected to create a puppet")
            return {'CANCELLED'}
        
        # Generate default name
        # Count only actual puppets, excluding the separator
        puppet_count = len([i for i in context.scene.outliner_items 
                          if i.item_type == 'PUPPET' and i.item_id != "puppets_separator"])
        self.puppet_name = f"Puppet {puppet_count + 1}"
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "puppet_name")
        
        # Show what will be puppeted
        selected_items = [item for item in context.scene.outliner_items if item.is_selected]
        layout.label(text=f"Creating puppet from {len(selected_items)} items", icon='INFO')
    
    def execute(self, context):
        scene = context.scene
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            return {'CANCELLED'}
        
        # Create puppet ID
        import uuid
        puppet_id = f"puppet_{uuid.uuid4().hex[:8]}"
        
        # Filter items that can be puppeted (exclude puppets themselves)
        items_to_puppet = []
        items_already_puppeted = []
        for item in selected_items:
            if item.item_type != 'PUPPET' and item.item_id != "puppets_separator" and "_ref_" not in item.item_id:
                # Check if already in a puppet
                if item.puppet_memberships:
                    items_already_puppeted.append(item.name)
                else:
                    items_to_puppet.append(item)
        
        # If any items are already in puppets, don't proceed
        if items_already_puppeted:
            if len(items_already_puppeted) == 1:
                self.report({'ERROR'}, f'Cannot create puppet: "{items_already_puppeted[0]}" is already in a puppet')
            else:
                self.report({'ERROR'}, f'Cannot create puppet: {len(items_already_puppeted)} selected items are already in puppets')
            return {'CANCELLED'}
        
        if not items_to_puppet:
            self.report({'WARNING'}, "No valid items to puppet")
            return {'CANCELLED'}
        
        # Add puppet membership to selected items
        for item in items_to_puppet:
            # Get current memberships
            current_puppets = item.puppet_memberships.split(',') if item.puppet_memberships else []
            # Add new puppet if not already a member
            if puppet_id not in current_puppets:
                current_puppets.append(puppet_id)
                item.puppet_memberships = ','.join(filter(None, current_puppets))
            # Keep items selected - don't deselect them automatically
            # This prevents confusion where creating a puppet changes selection
        
        # Create the puppet item
        puppet_item = scene.outliner_items.add()
        puppet_item.item_type = 'PUPPET'
        puppet_item.item_id = puppet_id
        puppet_item.name = self.puppet_name
        puppet_item.parent_id = ""
        puppet_item.indent_level = 0
        puppet_item.icon = 'ARMATURE_DATA'
        puppet_item.is_expanded = True
        puppet_item.is_selected = False  # Don't auto-select the new puppet
        
        # Store member IDs in the puppet's memberships field for easy access
        member_ids = [item.item_id for item in items_to_puppet]
        puppet_item.puppet_memberships = ','.join(member_ids)
        
        # Rebuild the outliner to reflect the new puppet
        build_outliner_hierarchy(context)
        
        self.report({'INFO'}, f"Created puppet: {self.puppet_name} with {len(items_to_puppet)} items")
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
        # Find the puppet name for the confirmation message
        for item in context.scene.outliner_items:
            if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                self.puppet_name = item.name
                break
        return context.window_manager.invoke_confirm(self, event)
    
    def draw(self, context):
        layout = self.layout
        puppet_name = getattr(self, 'puppet_name', 'this puppet')
        layout.label(text=f'Are you sure you want to delete "{puppet_name}"?')
    
    def execute(self, context):
        scene = context.scene
        
        # Find and remove the puppet
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
        
        # Remove puppet membership from all items
        for item in scene.outliner_items:
            if item.puppet_memberships:
                puppets = item.puppet_memberships.split(',')
                if self.puppet_id in puppets:
                    puppets.remove(self.puppet_id)
                    item.puppet_memberships = ','.join(puppets)
        
        # Remove the puppet item
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
        name="Puppet Name",
        description="Name for the puppet"
    )
    
    # Properties to track item selection in edit dialog
    item_selections: bpy.props.CollectionProperty(
        type=bpy.types.PropertyGroup
    )
    
    def invoke(self, context, event):
        if self.action == 'EDIT':
            # Find the puppet
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
            
            # Get current puppet members
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
            # Get selected puppet name
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
            puppet_name = "this puppet"
            for item in context.scene.outliner_items:
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_name = f'"{item.name}"'
                    break
            layout.label(text=f"Are you sure you want to delete {puppet_name}?", icon='ERROR')
            return
        
        if self.action == 'EDIT':
            # Puppet name
            layout.prop(self, "new_name")
            layout.separator()
            
            # Create scrollable list of items
            box = layout.box()
            box.label(text="Puppet Members:", icon='ARMATURE_DATA')
            
            # Puppet items by parent
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
            # Find the puppet to edit
            puppet_item = None
            for item in scene.outliner_items:
                if item.item_id == self.puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    break
            
            if not puppet_item:
                self.report({'ERROR'}, "Puppet not found")
                return {'CANCELLED'}
            
            # Update puppet name
            puppet_item.name = self.new_name
            
            # Update puppet members
            new_members = []
            for item_sel in self.item_selections:
                if item_sel.get('is_selected', False):
                    new_members.append(item_sel.get('item_id', ''))
            
            # Update puppet membership
            puppet_item.puppet_memberships = ','.join(filter(None, new_members))
            
            # Update item memberships
            # First, remove this puppet from all items
            for item in scene.outliner_items:
                if item.puppet_memberships:
                    puppets = item.puppet_memberships.split(',')
                    if self.puppet_id in puppets:
                        puppets.remove(self.puppet_id)
                        item.puppet_memberships = ','.join(puppets)
            
            # Then add puppet to selected items
            for member_id in new_members:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        puppets = item.puppet_memberships.split(',') if item.puppet_memberships else []
                        if self.puppet_id not in puppets:
                            puppets.append(self.puppet_id)
                            item.puppet_memberships = ','.join(filter(None, puppets))
                        break
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Updated puppet: {self.new_name}")
            
        elif self.action == 'DELETE':
            # Fallback implementation for when dedicated delete operator isn't available
            # Find and remove the puppet
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
            
            # Remove puppet membership from all items
            for item in scene.outliner_items:
                if item.puppet_memberships:
                    puppets = item.puppet_memberships.split(',')
                    if self.puppet_id in puppets:
                        puppets.remove(self.puppet_id)
                        item.puppet_memberships = ','.join(puppets)
            
            # Remove the puppet item
            scene.outliner_items.remove(puppet_index)
            
            # Rebuild outliner
            build_outliner_hierarchy(context)
            self.report({'INFO'}, f"Deleted puppet: {puppet_item.name}")
            
        elif self.action == 'RENAME':
            # Find selected puppet
            selected_puppet = None
            for item in scene.outliner_items:
                if item.is_selected and item.item_type == 'PUPPET':
                    selected_puppet = item
                    break
            
            if selected_puppet:
                selected_puppet.name = self.new_name
                self.report({'INFO'}, f"Renamed puppet to: {self.new_name}")
        
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
        
        # Get selected items and check their puppet memberships
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        # Filter out puppets, separator, and reference items from selection count
        unpuppeted_items = [item for item in selected_items 
                           if item.item_type not in ['PUPPET'] 
                           and item.item_id != "puppets_separator"
                           and "_ref_" not in item.item_id]
        
        # Check if any selected items are already in puppets
        items_already_puppeted = []
        puppet_names_dict = {}  # Map puppet IDs to names
        
        # First build a map of puppet IDs to names
        for item in scene.outliner_items:
            if item.item_type == 'PUPPET':
                puppet_names_dict[item.item_id] = item.name
        
        # Check which items are already in puppets
        for item in unpuppeted_items:
            if item.puppet_memberships:
                puppet_ids = item.puppet_memberships.split(',')
                # Get the names of puppets this item belongs to
                puppet_names = [puppet_names_dict.get(pid, pid) for pid in puppet_ids if pid]
                if puppet_names:
                    items_already_puppeted.append((item.name, puppet_names))
        
        # Create New Puppet button
        row = box.row()
        row.scale_y = 1.5
        
        # Enable button only if we have valid items and no conflicts
        row.enabled = len(items_already_puppeted) == 0 and len(unpuppeted_items) > 0
        
        # Create the button
        op = row.operator("proteinblender.create_puppet", text="Create New Puppet", icon='ARMATURE_DATA')



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