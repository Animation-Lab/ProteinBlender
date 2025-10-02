import bpy
from bpy.types import Panel, UIList, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy, update_outliner_visibility


class PROTEINBLENDER_UL_outliner(UIList):
    """Custom UIList for hierarchical protein display"""
    
    # Disable row selection by overriding these properties
    use_filter_show = False
    use_filter_sort_alpha = False
    use_filter_sort_reverse = False
    use_filter_invert = False
    
    def filter_items(self, context, data, propname):
        """Filter items based on parent expansion state"""
        items = getattr(data, propname)
        
        # Initialize with all items visible
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))
        
        # Hide items whose parents are collapsed
        for idx, item in enumerate(items):
            if not self._should_show_item_by_parent(items, idx):
                flt_flags[idx] = 0
        
        return flt_flags, flt_neworder
    
    def _should_show_item_by_parent(self, items, item_idx):
        """Check if item should be shown based on parent expansion state"""
        item = items[item_idx]
        
        # Separator is always shown
        if item.item_id == "puppets_separator":
            return True
        
        # Top-level items are always shown
        if item.indent_level == 0:
            return True
        
        # Check if parent is expanded
        if item.parent_id:
            # Find parent item
            for parent_idx, parent_item in enumerate(items):
                if parent_item.item_id == item.parent_id:
                    # If parent is not expanded, hide this item
                    if not parent_item.is_expanded:
                        return False
                    # Recursively check parent's visibility
                    return self._should_show_item_by_parent(items, parent_idx)
        
        return True
    
    def _are_all_group_members_selected(self, scene, group_item):
        """Check if all members of a group are selected"""
        member_ids = group_item.puppet_memberships.split(',') if group_item.puppet_memberships else []
        if not member_ids:
            return False
        
        # Check each member
        for member_id in member_ids:
            member_selected = False
            for item in scene.outliner_items:
                if item.item_id == member_id:
                    if not item.is_selected:
                        return False
                    member_selected = True
                    break
            if not member_selected:
                return False
        
        return True
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # Check if this is the separator
        if item.item_id == "puppets_separator":
            layout.label(text=item.name)
            return
        
        # Override the active state - we don't use row selection
        # Make the row non-interactive by disabling highlight
        layout.use_property_split = False
        layout.use_property_decorate = False
        
        # Visual hierarchy through indentation
        row = layout.row(align=True)
        
        # Indentation based on hierarchy level
        for i in range(item.indent_level):
            row.separator(factor=2.0)
        
        # Check if this is a reference item
        is_reference = item.item_id.startswith("group_") and "_ref_" in item.item_id
        
        # Expand/collapse for proteins, groups, and chains with domains
        show_expand = False
        
        if item.item_type in ['PROTEIN', 'PUPPET'] and not is_reference:
            show_expand = True
        elif item.item_type == 'CHAIN':
            # Show expand arrow for chains with domains (both original and reference items)
            # This allows collapsing/expanding domains in groups too
            show_expand = item.has_domains
        
        if show_expand:
            if item.is_expanded:
                icon = 'TRIA_DOWN'
            else:
                icon = 'TRIA_RIGHT'
            op = row.operator("proteinblender.toggle_expand", text="", icon=icon, emboss=False)
            op.item_id = item.item_id
        else:
            row.label(text="", icon='BLANK1')  # Spacing
            
        # Item label with appropriate icon
        row.label(text=item.name, icon=item.icon)
        
        # Add some space before the controls
        row.separator()
        
        # Handle different item types
        if item.item_type == 'PUPPET' and item.item_id == "puppets_separator":
            # Groups separator - no controls
            return
        
        # Add controls based on item type
        # For chains and domains, add copy button and optionally delete button
        if item.item_type in ['CHAIN', 'DOMAIN']:
            # Extract the actual domain ID from the item_id
            # For chains, item_id is like "molecule_id_chain_0" or just a domain_id for chain copies
            # For domains, item_id is the domain_id directly
            if item.item_type == 'CHAIN':
                scene_manager = ProteinBlenderScene.get_instance()
                
                # Check if this is a chain copy (item_id is a domain_id)
                is_chain_copy = False
                domain_for_chain = None
                
                # First check if item_id is directly a domain_id (for chain copies)
                for molecule_id, molecule in scene_manager.molecules.items():
                    if item.item_id in molecule.domains:
                        domain_for_chain = molecule.domains[item.item_id]
                        is_chain_copy = True
                        break
                
                # If not a chain copy, extract molecule_id and find the matching domain
                if not is_chain_copy:
                    parts = item.item_id.rsplit('_chain_', 1)
                    if len(parts) == 2:
                        molecule_id = parts[0]
                        chain_id = parts[1]
                        molecule = scene_manager.molecules.get(molecule_id)
                        if molecule:
                            # Find the domain that represents this chain (full chain domain)
                            for domain_id, domain in molecule.domains.items():
                                if str(domain.chain_id) == chain_id:
                                    domain_for_chain = domain
                                    break
                
                # Add buttons based on what we found
                if domain_for_chain:
                    # Add reset transform button for all chains/domains
                    reset_op = row.operator("molecule.reset_domain_transform", text="", icon='OBJECT_ORIGIN', emboss=False)
                    if reset_op:
                        if is_chain_copy:
                            reset_op.domain_id = item.item_id
                        else:
                            # Find the domain_id for this chain
                            for domain_id, domain in molecule.domains.items():
                                if domain == domain_for_chain:
                                    reset_op.domain_id = domain_id
                                    break
                    
                    # Add copy button for all chains
                    copy_op = row.operator("molecule.copy_domain", text="", icon='ADD', emboss=False)
                    if copy_op:
                        if is_chain_copy:
                            copy_op.domain_id = item.item_id
                        else:
                            # Find the domain_id for this chain
                            for domain_id, domain in molecule.domains.items():
                                if domain == domain_for_chain:
                                    copy_op.domain_id = domain_id
                                    break

                    # Add delete button
                    if hasattr(domain_for_chain, 'is_copy') and domain_for_chain.is_copy:
                        # For chain copies, use domain delete operator
                        delete_op = row.operator("molecule.delete_domain", text="", icon='TRASH', emboss=False)
                        if delete_op:
                            delete_op.domain_id = item.item_id
                    else:
                        # For regular chains, use chain delete operator
                        delete_op = row.operator("molecule.delete_chain", text="", icon='TRASH', emboss=False)
                        if delete_op:
                            delete_op.chain_id = chain_id
                            delete_op.molecule_id = molecule_id
            else:
                # For domains, use the item_id directly as domain_id
                domain_id = item.item_id
                # Need to check if this domain is a copy to show delete button
                scene_manager = ProteinBlenderScene.get_instance()
                # Find which molecule this domain belongs to
                for molecule_id, molecule in scene_manager.molecules.items():
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        
                        # Add reset transform button
                        reset_op = row.operator("molecule.reset_domain_transform", text="", icon='OBJECT_ORIGIN', emboss=False)
                        if reset_op:
                            reset_op.domain_id = domain_id
                        
                        # Add copy button
                        copy_op = row.operator("molecule.copy_domain", text="", icon='ADD', emboss=False)
                        if copy_op:
                            copy_op.domain_id = domain_id
                        
                        # Add delete button only if this is a copy
                        if hasattr(domain, 'is_copy') and domain.is_copy:
                            delete_op = row.operator("molecule.delete_domain", text="", icon='TRASH', emboss=False)
                            if delete_op:
                                delete_op.domain_id = domain_id
                        break
        
        # First: Delete button for proteins and groups
        elif item.item_type == 'PROTEIN':
            # Delete button (trash can) - use the existing molecule.delete operator
            delete_op = row.operator("molecule.delete", text="", icon='TRASH', emboss=False)
            if delete_op:
                delete_op.molecule_id = item.item_id
        elif item.item_type == 'PUPPET':
            # Delete button (trash can) - use the edit_puppet operator with DELETE action
            op = row.operator("proteinblender.edit_puppet", text="", icon='TRASH', emboss=False)
            if op:
                op.action = 'DELETE'
                op.puppet_id = item.item_id
        
        # Second: Selection checkbox for all items
        # For all items including puppets, use their own selection state
        # Puppet checkbox now only reflects the controller's selection state
        selection_icon = 'CHECKBOX_HLT' if item.is_selected else 'CHECKBOX_DEHLT'
        
        op = row.operator("proteinblender.outliner_select", text="", icon=selection_icon, emboss=False)
        op.item_id = item.item_id
        
        # Third: Visibility toggle for all items
        visibility_icon = 'HIDE_OFF' if item.is_visible else 'HIDE_ON'
        op = row.operator("proteinblender.toggle_visibility", text="", icon=visibility_icon)
        op.item_id = item.item_id
    




class PROTEINBLENDER_OT_toggle_expand(Operator):
    """Toggle expand/collapse state of outliner item"""
    bl_idname = "proteinblender.toggle_expand"
    bl_label = "Toggle Expand"
    bl_options = {'REGISTER', 'UNDO'}

    
    item_id: StringProperty()
    
    def execute(self, context):
        # Don't allow interaction with separator
        if self.item_id == "puppets_separator":
            return {'CANCELLED'}
            
        scene = context.scene
        item_type = None
        is_reference = "_ref_" in self.item_id
        new_state = None
        
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                item.is_expanded = not item.is_expanded
                item_type = item.item_type
                break
        
        # If we toggled a chain, we need to rebuild the hierarchy to show/hide domains
        # This includes reference chains in groups
        if item_type == 'CHAIN':
            from ..utils.scene_manager import build_outliner_hierarchy
            build_outliner_hierarchy(context)
        else:
            # For other types, just redraw UI
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
                    
        return {'FINISHED'}


class PROTEINBLENDER_OT_outliner_select(Operator):
    """Handle outliner selection with hierarchy rules"""
    bl_idname = "proteinblender.outliner_select"
    bl_label = "Select Item"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        
        # Don't allow interaction with separator
        if self.item_id == "puppets_separator":
            return {'CANCELLED'}
        
        # Find the clicked item
        clicked_item = None
        actual_item_id = self.item_id
        reference_item = None

        # Check if this is a reference item
        if "_ref_" in self.item_id:
            # Find the reference item that was clicked
            for item in scene.outliner_items:
                if item.item_id == self.item_id:
                    reference_item = item
                    if item.puppet_memberships:
                        actual_item_id = item.puppet_memberships  # Original ID stored here
                    break

        # Find the actual item to select
        for item in scene.outliner_items:
            if item.item_id == actual_item_id:
                clicked_item = item
                break

        if not clicked_item:
            return {'CANCELLED'}

        # Remove this block - it's redundant and interferes with proper toggling

        # Toggle selection state based on what was clicked
        if reference_item:
            # If a reference was clicked, toggle based on the reference's state
            new_selection_state = not reference_item.is_selected
            reference_item.is_selected = new_selection_state
            clicked_item.is_selected = new_selection_state
        else:
            # If the original was clicked, toggle based on the original's state
            new_selection_state = not clicked_item.is_selected
            clicked_item.is_selected = new_selection_state
        
        # Update all references to keep them in sync
        if "_ref_" in self.item_id:
            # A reference was clicked - already updated both reference and original above
            # Now update any other references to the same item
            for ref_item in scene.outliner_items:
                if "_ref_" in ref_item.item_id and ref_item.puppet_memberships == actual_item_id and ref_item.item_id != self.item_id:
                    ref_item.is_selected = new_selection_state
        else:
            # The original was clicked - update all its references
            for ref_item in scene.outliner_items:
                if "_ref_" in ref_item.item_id and ref_item.puppet_memberships == actual_item_id:
                    ref_item.is_selected = new_selection_state
        
        # Handle hierarchical selection
        if clicked_item.item_type == 'PROTEIN':
            # Select/deselect all children (chains and domains)
            self.select_children(scene, clicked_item.item_id, new_selection_state)
        elif clicked_item.item_type == 'CHAIN':
            # Check if this chain has domains
            has_domains = False
            for item in scene.outliner_items:
                if item.parent_id == clicked_item.item_id and item.item_type == 'DOMAIN':
                    has_domains = True
                    break
            
            # If chain has domains, don't auto-select children
            # The chain checkbox should only reflect if ALL domains are selected
            if not has_domains and new_selection_state:
                # Only chains without domains should select their children (if any)
                self.select_children(scene, clicked_item.item_id, new_selection_state)
        elif clicked_item.item_type == 'PUPPET':
            # Toggle the puppet's selection state first
            clicked_item.is_selected = new_selection_state

            # Sync the puppet's Empty controller with its checkbox state
            from ..handlers.selection_sync import sync_outliner_to_blender_selection
            sync_outliner_to_blender_selection(context, clicked_item.item_id)

            # Don't automatically select/deselect children - puppet checkbox only controls the controller
            # This allows independent selection of puppet members
            
            # Update UI immediately
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
            
            return {'FINISHED'}
        # Note: We don't automatically select/deselect children for chains anymore
        # This allows independent chain selection without affecting parent
        
        # Update parent chain selection based on children
        if clicked_item.item_type == 'DOMAIN':
            # Always update parent chain selection when domain selection changes
            parent_chain_id = clicked_item.parent_id
            if parent_chain_id:
                self.update_parent_chain_selection(scene, parent_chain_id)
        
        # Update UI immediately for responsive feedback
        # Force immediate redraw for better checkbox responsiveness
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        
        # Also update the current area
        context.area.tag_redraw()
        
        # Sync to Blender selection (do this after UI update for better responsiveness)
        from ..handlers.selection_sync import sync_outliner_to_blender_selection
        sync_outliner_to_blender_selection(context, actual_item_id)
        
        # Sync color picker to match selected item's color
        from ..panels.visual_setup_panel import sync_color_to_selection
        sync_color_to_selection(context)
        
        # Initialize domain maker values based on selection
        if hasattr(scene, 'domain_maker_start'):
            if clicked_item.item_type == 'CHAIN':
                # Always update to the chain's range when selecting a chain
                scene.domain_maker_start = clicked_item.chain_start
                # Set end to a reasonable default within the chain
                if clicked_item.chain_end > clicked_item.chain_start:
                    scene.domain_maker_end = min(clicked_item.chain_start + 50, clicked_item.chain_end)
                else:
                    scene.domain_maker_end = clicked_item.chain_end
            elif clicked_item.item_type == 'DOMAIN':
                # Set to domain's current range
                scene.domain_maker_start = clicked_item.domain_start
                scene.domain_maker_end = clicked_item.domain_end
        
        return {'FINISHED'}
    
    def update_parent_chain_selection(self, scene, chain_id):
        """Update chain selection based on whether all its domains are selected"""
        # Find the chain item
        chain_item = None
        for item in scene.outliner_items:
            if item.item_id == chain_id and item.item_type == 'CHAIN':
                chain_item = item
                break
        
        if not chain_item:
            return
        
        # Count selected vs total domains
        total_domains = 0
        selected_domains = 0
        
        for item in scene.outliner_items:
            if item.parent_id == chain_id and item.item_type == 'DOMAIN':
                total_domains += 1
                if item.is_selected:
                    selected_domains += 1
        
        # Chain is selected only if all its domains are selected
        # and there's at least one domain
        if total_domains > 0:
            chain_item.is_selected = (selected_domains == total_domains)
        else:
            # If no domains, chain selection is independent
            pass
    
    def select_children(self, scene, parent_id, select_state):
        """Recursively select/deselect all children of an item and sync to Blender"""
        # Import sync function
        from ..handlers.selection_sync import sync_outliner_to_blender_selection
        
        # Find the parent item to check if it's a group
        parent_item = None
        for item in scene.outliner_items:
            if item.item_id == parent_id:
                parent_item = item
                break
        
        if parent_item and parent_item.item_type == 'PUPPET':
            # Groups should NOT automatically select their members
            # This prevents unexpected selection cascades
            # If you want to select all group members, use a dedicated operator
            return
        else:
            # For non-groups, use parent-child relationship
            for item in scene.outliner_items:
                if item.parent_id == parent_id:
                    # Skip reference items - they'll be updated by their originals
                    if "_ref_" in item.item_id:
                        continue
                        
                    item.is_selected = select_state
                    # Sync this item to Blender (especially important for domains)
                    sync_outliner_to_blender_selection(bpy.context, item.item_id)
                    # Update all references to this item (one-way only)
                    for ref_item in scene.outliner_items:
                        if "_ref_" in ref_item.item_id and ref_item.puppet_memberships == item.item_id:
                            ref_item.is_selected = select_state
                    # Recursively select children
                    self.select_children(scene, item.item_id, select_state)


class PROTEINBLENDER_OT_toggle_visibility(Operator):
    """Toggle visibility of outliner item"""
    bl_idname = "proteinblender.toggle_visibility"
    bl_label = "Toggle Visibility"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        
        # Don't allow interaction with separator
        if self.item_id == "puppets_separator":
            return {'CANCELLED'}
        
        # Check if this is a reference item
        actual_item_id = self.item_id
        if "_ref_" in self.item_id:
            # Extract the original item ID from the reference
            for ref_item in scene.outliner_items:
                if ref_item.item_id == self.item_id and ref_item.puppet_memberships:
                    actual_item_id = ref_item.puppet_memberships
                    break
        
        # Find the actual item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == actual_item_id:
                item = outliner_item
                break
        
        if not item:
            return {'CANCELLED'}
        
        # For reference items, update the reference visibility to match the actual item
        if "_ref_" in self.item_id:
            for ref_item in scene.outliner_items:
                if ref_item.item_id == self.item_id:
                    ref_item.is_visible = item.is_visible
                    break
        
        # Toggle visibility
        new_visibility = not item.is_visible
        item.is_visible = new_visibility
        update_outliner_visibility(actual_item_id, new_visibility)
        
        # Update all references to this item (both ways)
        # If this is a reference, update the original too
        if "_ref_" in self.item_id:
            # Update the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == actual_item_id:
                    orig_item.is_visible = new_visibility
                    break
        
        # Update all references to this item
        for ref_item in scene.outliner_items:
            if "_ref_" in ref_item.item_id and ref_item.puppet_memberships == actual_item_id:
                ref_item.is_visible = new_visibility
        
        # If this is a protein or group, update all children visibility too
        if item.item_type in ['PROTEIN', 'PUPPET']:
            # For groups, also update all reference items
            if item.item_type == 'PUPPET':
                for ref_item in scene.outliner_items:
                    if ref_item.parent_id == item.item_id and "_ref_" in ref_item.item_id:
                        ref_item.is_visible = new_visibility
            self.update_children_visibility(scene, actual_item_id, new_visibility)

            # If this is a protein, also hide/show puppets that contain its chains
            if item.item_type == 'PROTEIN':
                self.update_puppet_visibility_for_protein(scene, actual_item_id, new_visibility)
        # Note: Chains don't automatically update children visibility
        
        # Update UI
        context.area.tag_redraw()
        return {'FINISHED'}
    
    def update_puppet_visibility_for_protein(self, scene, protein_id, visibility):
        """Update visibility of puppets that contain chains from this protein"""
        # First, find all chain IDs that belong to this protein
        protein_chain_ids = []
        for item in scene.outliner_items:
            if item.parent_id == protein_id and item.item_type == 'CHAIN':
                protein_chain_ids.append(item.item_id)

        # Now check all puppets to see if they contain any of these chains
        for puppet in scene.outliner_items:
            if puppet.item_type == 'PUPPET' and puppet.item_id != "puppets_separator":
                # Get the puppet's member IDs
                member_ids = puppet.puppet_memberships.split(',') if puppet.puppet_memberships else []

                # Check if any of the puppet's members are chains from this protein
                has_protein_chains = any(chain_id in member_ids for chain_id in protein_chain_ids)

                if has_protein_chains:
                    # Update puppet visibility to match the protein
                    puppet.is_visible = visibility
                    update_outliner_visibility(puppet.item_id, visibility)

                    # Also update all reference items under this puppet
                    for ref_item in scene.outliner_items:
                        if ref_item.parent_id == puppet.item_id and "_ref_" in ref_item.item_id:
                            ref_item.is_visible = visibility
                            # Update the actual visibility of the referenced item
                            if ref_item.puppet_memberships:
                                update_outliner_visibility(ref_item.puppet_memberships, visibility)

    def update_children_visibility(self, scene, parent_id, visibility):
        """Recursively update visibility of all children"""
        # Find the parent item to check if it's a group
        parent_item = None
        for item in scene.outliner_items:
            if item.item_id == parent_id:
                parent_item = item
                break
        
        if parent_item and parent_item.item_type == 'PUPPET':
            # For groups, update members by their membership
            member_ids = parent_item.puppet_memberships.split(',') if parent_item.puppet_memberships else []
            for member_id in member_ids:
                update_outliner_visibility(member_id, visibility)
                # If it's a protein, also update its children
                for item in scene.outliner_items:
                    if item.item_id == member_id and item.item_type == 'PROTEIN':
                        self.update_children_visibility(scene, member_id, visibility)
                        break
        else:
            # For non-groups, use parent-child relationship
            for item in scene.outliner_items:
                if item.parent_id == parent_id:
                    update_outliner_visibility(item.item_id, visibility)
                    # Recursively update children
                    self.update_children_visibility(scene, item.item_id, visibility)


class PROTEINBLENDER_PT_outliner(Panel):
    """Protein outliner panel"""
    bl_label = "Protein Outliner"
    bl_idname = "PROTEINBLENDER_PT_outliner"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 1  # Display order (after importer)
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content
        box = layout.box()
        
        # Add panel title inside the box
        box.label(text="Protein Outliner", icon='OUTLINER')
        box.separator()
        
        # Check if outliner items exist
        if len(scene.outliner_items) == 0:
            box.label(text="No proteins loaded", icon='INFO')
            return
        
        # UIList inside the box - disable row selection by not tracking index
        # We use a dummy property that doesn't get updated to prevent row selection
        box.template_list(
            "PROTEINBLENDER_UL_outliner", "",
            scene, "outliner_items",
            scene, "outliner_index",
            rows=10,
            maxrows=20,
            type='DEFAULT',
            columns=1
        )
        
        # Add bottom spacing
        layout.separator()


# Operator and panel classes to register
CLASSES = [
    PROTEINBLENDER_UL_outliner,
    PROTEINBLENDER_OT_toggle_expand,
    PROTEINBLENDER_OT_outliner_select,
    PROTEINBLENDER_OT_toggle_visibility,
    PROTEINBLENDER_PT_outliner,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)