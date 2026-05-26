import bpy
from bpy.types import Panel, UIList, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy
from ..utils.chain_utils import get_chain_objects, get_chain_domains, chain_token_from_item


def _split_chain_is_visible(item, view_layer):
    """Visibility for a chain row that has no single backing object.

    Once a chain is split into domains its outliner row carries no
    ``object_name``, so visibility has to be aggregated from the domain
    objects. The chain reads as visible when any of its domains is visible —
    that keeps the eye toggle reversible (hide-all then show-all).
    """
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(item.parent_id) if scene_manager else None
    objects = get_chain_objects(molecule, item)
    if not objects:
        return True
    for obj in objects:
        try:
            if not obj.hide_get(view_layer=view_layer):
                return True
        except (ReferenceError, RuntimeError):
            continue
    return False


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

    def _generate_tooltip(self, context, item):
        """Generate tooltip text for an outliner item"""
        try:
            if item.item_type in ('PROTEIN', 'DNA_RNA'):
                # For proteins / DNA / RNA, show the molecule name
                scene_manager = ProteinBlenderScene.get_instance()
                if not scene_manager or not hasattr(scene_manager, 'molecules'):
                    return None
                molecule = scene_manager.molecules.get(item.item_id)
                if molecule:
                    if item.item_type == 'DNA_RNA':
                        return item.tooltip  # tooltip built during hierarchy build
                    tooltip_parts = [f"Protein: {item.name}"]
                    if hasattr(molecule, 'identifier'):
                        tooltip_parts.append(f"ID: {molecule.identifier}")
                    return "\n".join(tooltip_parts)

            elif item.item_type == 'CHAIN':
                # For chains, show protein name, chain name, and residue range
                scene_manager = ProteinBlenderScene.get_instance()
                if not scene_manager or not hasattr(scene_manager, 'molecules'):
                    return None

                # Extract molecule ID and chain ID from item_id
                # Format: "molecule_id_chain_X" or just domain_id for chain copies
                if '_chain_' in item.item_id:
                    parts = item.item_id.rsplit('_chain_', 1)
                    if len(parts) == 2:
                        molecule_id = parts[0]
                        chain_id = parts[1]
                        molecule = scene_manager.molecules.get(molecule_id)
                        if molecule:
                            tooltip_parts = []
                            # Add protein name
                            protein_name = getattr(molecule, 'name', molecule.identifier)
                            tooltip_parts.append(f"Protein: {protein_name}")
                            # Add chain name
                            tooltip_parts.append(f"Chain: {item.name}")
                            # Add residue range if available
                            if item.chain_start > 0 and item.chain_end > 0:
                                tooltip_parts.append(f"Residues: {item.chain_start}-{item.chain_end}")
                            return "\n".join(tooltip_parts)
                else:
                    # This is a chain copy (item_id is a domain_id)
                    for molecule_id, molecule in scene_manager.molecules.items():
                        if item.item_id in molecule.domains:
                            domain = molecule.domains[item.item_id]
                            tooltip_parts = []
                            # Add protein name
                            protein_name = getattr(molecule, 'name', molecule.identifier)
                            tooltip_parts.append(f"Protein: {protein_name}")
                            # Add chain/domain name
                            tooltip_parts.append(f"Chain: {item.name}")
                            # Add residue range
                            if hasattr(domain, 'start') and hasattr(domain, 'end'):
                                tooltip_parts.append(f"Residues: {domain.start}-{domain.end}")
                            return "\n".join(tooltip_parts)

            elif item.item_type == 'DOMAIN':
                # For domains, show protein name, chain name, domain name, and residue range
                scene_manager = ProteinBlenderScene.get_instance()
                if not scene_manager or not hasattr(scene_manager, 'molecules'):
                    return None

                # Find the domain in the molecules
                for molecule_id, molecule in scene_manager.molecules.items():
                    if item.item_id in molecule.domains:
                        domain = molecule.domains[item.item_id]
                        tooltip_parts = []

                        # Add protein name
                        protein_name = getattr(molecule, 'name', molecule.identifier)
                        tooltip_parts.append(f"Protein: {protein_name}")

                        # Add chain information if available
                        if hasattr(domain, 'chain_id'):
                            # Try to get the chain name from the molecule's chain mapping
                            chain_name = None
                            if hasattr(molecule, 'auth_chain_id_map') and molecule.auth_chain_id_map:
                                chain_name = molecule.auth_chain_id_map.get(domain.chain_id)
                            if not chain_name and hasattr(molecule, 'idx_to_label_asym_id_map') and molecule.idx_to_label_asym_id_map:
                                chain_name = molecule.idx_to_label_asym_id_map.get(domain.chain_id)

                            if chain_name:
                                tooltip_parts.append(f"Chain: {chain_name}")
                            else:
                                tooltip_parts.append(f"Chain: {domain.chain_id}")

                        # Add domain name
                        tooltip_parts.append(f"Domain: {item.name}")

                        # Add residue range
                        if item.domain_start > 0 and item.domain_end > 0:
                            tooltip_parts.append(f"Residues: {item.domain_start}-{item.domain_end}")
                        elif hasattr(domain, 'start') and hasattr(domain, 'end'):
                            tooltip_parts.append(f"Residues: {domain.start}-{domain.end}")

                        return "\n".join(tooltip_parts)

            elif item.item_type == 'PUPPET':
                # For puppets, show group name and member count
                member_ids = item.puppet_memberships.split(',') if item.puppet_memberships else []
                member_count = len([m for m in member_ids if m])  # Filter out empty strings
                return f"Puppet Group: {item.name}\nMembers: {member_count}"

        except Exception as e:
            # If tooltip generation fails, just return None to use regular label
            print(f"Tooltip generation error: {e}")
            return None

        return None  # No tooltip for other items
    
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

        if item.item_type in ['PROTEIN', 'PUPPET', 'DNA_RNA'] and not is_reference:
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

        # Item label with appropriate icon and tooltip
        # Check if this item has a tooltip stored (set during outliner build)
        has_tooltip = hasattr(item, 'tooltip') and item.tooltip

        # Use an operator for the label to show tooltip on hover
        if has_tooltip:
            try:
                op = row.operator("proteinblender.outliner_item_info", text=item.name, icon=item.icon, emboss=False)
                op.item_id = item.item_id
            except Exception as e:
                print(f"Error creating tooltip operator: {e}")
                row.label(text=item.name, icon=item.icon)
        else:
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

                # Resolve the molecule and the domain(s) this chain row maps to
                # through the shared resolver (handles full chains, copies and
                # the chain-index vs. chain-letter bridge in one place).
                molecule = scene_manager.molecules.get(item.parent_id)
                chain_domains = get_chain_domains(molecule, item)

                if chain_domains:
                    primary_domain_id, primary_domain = chain_domains[0]
                    is_chain_copy = getattr(primary_domain, 'is_copy', False)

                    # Reset transform — acts on the chain's primary domain
                    reset_op = row.operator("molecule.reset_domain_transform", text="", icon='OBJECT_ORIGIN', emboss=False)
                    if reset_op:
                        reset_op.domain_id = primary_domain_id

                    # Copy — duplicates the chain's primary domain
                    copy_op = row.operator("molecule.copy_domain", text="", icon='ADD', emboss=False)
                    if copy_op:
                        copy_op.domain_id = primary_domain_id

                    # Delete — a copy deletes itself; a real chain deletes the chain
                    if is_chain_copy:
                        delete_op = row.operator("molecule.delete_domain", text="", icon='TRASH', emboss=False)
                        if delete_op:
                            delete_op.domain_id = primary_domain_id
                    else:
                        delete_op = row.operator("molecule.delete_chain", text="", icon='TRASH', emboss=False)
                        if delete_op:
                            delete_op.chain_id = chain_token_from_item(item)
                            delete_op.molecule_id = item.parent_id
            else:
                # For domains, use the item_id directly as domain_id
                domain_id = item.item_id
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

                        # Add delete button for all domains
                        delete_op = row.operator("molecule.delete_domain", text="", icon='TRASH', emboss=False)
                        if delete_op:
                            delete_op.domain_id = domain_id
                            delete_op.molecule_id = molecule_id
                        break
        
        # First: Buttons for proteins and DNA/RNA
        elif item.item_type in ('PROTEIN', 'DNA_RNA'):
            # Center button (move to origin at center of mass)
            center_op = row.operator("molecule.center_protein", text="", icon='OBJECT_ORIGIN', emboss=False)
            if center_op:
                center_op.molecule_id = item.item_id

            if item.item_type == 'PROTEIN':
                # Duplicate button (create exact copy) - proteins only for now
                duplicate_op = row.operator("molecule.duplicate_protein", text="", icon='DUPLICATE', emboss=False)
                if duplicate_op:
                    duplicate_op.molecule_id = item.item_id

            # Delete button (trash can) - use the existing molecule.delete operator
            delete_op = row.operator("molecule.delete", text="", icon='TRASH', emboss=False)
            if delete_op:
                delete_op.molecule_id = item.item_id
        elif item.item_type == 'MEMBRANE':
            # Delete button — routes through the addon's own membrane
            # deleter (which also tears down lattice + hole children + the
            # per-membrane collection).
            delete_op = row.operator(
                "proteinblender.delete_membrane",
                text="", icon='TRASH', emboss=False,
            )
            if delete_op:
                delete_op.membrane_name = item.object_name
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
        # Read visibility directly from the Blender object (single source of truth)
        is_visible = self._get_item_visibility(context, item)
        visibility_icon = 'HIDE_OFF' if is_visible else 'HIDE_ON'
        op = row.operator("proteinblender.toggle_visibility", text="", icon=visibility_icon)
        op.item_id = item.item_id
    
    def _get_item_visibility(self, context, item):
        """Get visibility state directly from the Blender object."""
        if not item.object_name:
            # A split chain has no single object — aggregate from its domains.
            if item.item_type == 'CHAIN':
                return _split_chain_is_visible(item, context.view_layer)
            return True

        obj = bpy.data.objects.get(item.object_name)
        if not obj:
            return True

        try:
            return not obj.hide_get(view_layer=context.view_layer)
        except (ReferenceError, RuntimeError):
            return True
    




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
                    if item.reference_target_id:
                        actual_item_id = item.reference_target_id
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
                if "_ref_" in ref_item.item_id and ref_item.reference_target_id == actual_item_id and ref_item.item_id != self.item_id:
                    ref_item.is_selected = new_selection_state
        else:
            # The original was clicked - update all its references
            for ref_item in scene.outliner_items:
                if "_ref_" in ref_item.item_id and ref_item.reference_target_id == actual_item_id:
                    ref_item.is_selected = new_selection_state
        
        # Handle hierarchical selection
        if clicked_item.item_type in ('PROTEIN', 'DNA_RNA'):
            # Select/deselect all children (chains and domains / strands)
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
                        if "_ref_" in ref_item.item_id and ref_item.reference_target_id == item.item_id:
                            ref_item.is_selected = select_state
                    # Recursively select children
                    self.select_children(scene, item.item_id, select_state)


class PROTEINBLENDER_OT_toggle_visibility(Operator):
    """Toggle visibility of outliner item (viewport and render)"""
    bl_idname = "proteinblender.toggle_visibility"
    bl_label = "Toggle Visibility"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        view_layer = context.view_layer
        
        # Don't allow interaction with separator
        if self.item_id == "puppets_separator":
            return {'CANCELLED'}
        
        # Resolve reference items to their actual item
        actual_item_id = self.item_id
        if "_ref_" in self.item_id:
            for ref_item in scene.outliner_items:
                if ref_item.item_id == self.item_id and ref_item.reference_target_id:
                    actual_item_id = ref_item.reference_target_id
                    break
        
        # Find the item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == actual_item_id:
                item = outliner_item
                break
        
        if not item:
            return {'CANCELLED'}
        
        # Get current visibility from the object (single source of truth)
        current_visible = self._get_object_visibility(item, view_layer)
        new_visibility = not current_visible
        
        # Apply visibility to all relevant objects
        self._set_visibility_for_item(context, item, new_visibility)
        
        # If this is a protein or puppet, update children too
        if item.item_type in ['PROTEIN', 'PUPPET', 'DNA_RNA']:
            self._update_children_visibility(context, item.item_id, new_visibility)

            # If this is a protein, also update puppets containing its chains
            if item.item_type == 'PROTEIN':
                self._update_puppet_visibility_for_protein(context, item.item_id, new_visibility)
        
        # Force UI redraw. context.area is None when invoked from a
        # script / MCP / headless context — fall back to tagging every
        # 3D and properties area.
        if context.area is not None:
            context.area.tag_redraw()
        else:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ("VIEW_3D", "PROPERTIES"):
                        area.tag_redraw()
        return {'FINISHED'}
    
    def _get_object_visibility(self, item, view_layer):
        """Get visibility state from the Blender object."""
        if not item.object_name:
            # A split chain has no single object — aggregate from its domains.
            if item.item_type == 'CHAIN':
                return _split_chain_is_visible(item, view_layer)
            return True
        obj = bpy.data.objects.get(item.object_name)
        if not obj:
            return True
        try:
            return not obj.hide_get(view_layer=view_layer)
        except (ReferenceError, RuntimeError):
            return True
    
    def _set_visibility_for_item(self, context, item, visible):
        """Set visibility on the Blender object(s) for this item."""
        view_layer = context.view_layer
        scene_manager = ProteinBlenderScene.get_instance()
        
        if item.item_type in ('PROTEIN', 'DNA_RNA'):
            molecule = scene_manager.molecules.get(item.item_id)
            if molecule and molecule.object:
                self._set_object_visibility(molecule.object, visible, view_layer)
                # Also set all domain objects
                for domain in molecule.domains.values():
                    if domain.object:
                        self._set_object_visibility(domain.object, visible, view_layer)

        elif item.item_type == 'CHAIN':
            molecule = scene_manager.molecules.get(item.parent_id)
            if molecule:
                # Outliner CHAIN items use the *numeric* chain index in
                # their item_id (e.g. "3b75_001_chain_0"), but the
                # MoleculeWrapper's domain.chain_id stores the chain
                # *letter* (e.g. "A"). Translate via the wrapper's
                # idx_to_label_asym_id_map before comparing, otherwise
                # the loop matches nothing and the visibility toggle is
                # a silent no-op.
                raw = item.item_id.split('_chain_')[-1]
                chain_letter = None
                try:
                    raw_int = int(raw)
                except ValueError:
                    raw_int = None
                if (raw_int is not None
                        and hasattr(molecule, 'idx_to_label_asym_id_map')
                        and raw_int in molecule.idx_to_label_asym_id_map):
                    chain_letter = molecule.idx_to_label_asym_id_map[raw_int]
                if chain_letter is None:
                    chain_letter = raw  # already a letter, or no mapping available

                for domain in molecule.domains.values():
                    domain_chain = getattr(domain, 'chain_id', None)
                    if domain_chain is not None and str(domain_chain) == str(chain_letter):
                        if domain.object:
                            self._set_object_visibility(domain.object, visible, view_layer)
                            
        elif item.item_type == 'DOMAIN':
            if item.object_name:
                obj = bpy.data.objects.get(item.object_name)
                if obj:
                    self._set_object_visibility(obj, visible, view_layer)
                    
        elif item.item_type == 'PUPPET':
            # For puppets, update the controller object
            if item.controller_object_name:
                obj = bpy.data.objects.get(item.controller_object_name)
                if obj:
                    self._set_object_visibility(obj, visible, view_layer)

        elif item.item_type == 'MEMBRANE':
            # Hide the root + every child (lattice, hole controllers).
            root = bpy.data.objects.get(item.object_name)
            if root:
                self._set_object_visibility(root, visible, view_layer)
                for child in root.children:
                    self._set_object_visibility(child, visible, view_layer)

    def _set_object_visibility(self, obj, visible, view_layer):
        """Set both viewport and render visibility on an object."""
        try:
            obj.hide_set(not visible, view_layer=view_layer)
            obj.hide_render = not visible
        except (ReferenceError, RuntimeError):
            pass
    
    def _update_children_visibility(self, context, parent_id, visibility):
        """Recursively update visibility of all children."""
        scene = context.scene
        
        for item in scene.outliner_items:
            if item.parent_id == parent_id:
                self._set_visibility_for_item(context, item, visibility)
                self._update_children_visibility(context, item.item_id, visibility)
        
        # For puppets, also update members
        parent_item = None
        for item in scene.outliner_items:
            if item.item_id == parent_id:
                parent_item = item
                break
        
        if parent_item and parent_item.item_type == 'PUPPET' and parent_item.puppet_memberships:
            member_ids = parent_item.puppet_memberships.split(',')
            for member_id in member_ids:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        self._set_visibility_for_item(context, item, visibility)
                        break
    
    def _update_puppet_visibility_for_protein(self, context, protein_id, visibility):
        """Update visibility of puppets that contain chains from this protein."""
        scene = context.scene
        
        # Find all chain IDs belonging to this protein
        protein_chain_ids = [
            item.item_id for item in scene.outliner_items
            if item.parent_id == protein_id and item.item_type == 'CHAIN'
        ]
        
        # Update puppets containing these chains
        for puppet in scene.outliner_items:
            if puppet.item_type == 'PUPPET' and puppet.item_id != "puppets_separator":
                member_ids = puppet.puppet_memberships.split(',') if puppet.puppet_memberships else []
                if any(chain_id in member_ids for chain_id in protein_chain_ids):
                    self._set_visibility_for_item(context, puppet, visibility)


class PROTEINBLENDER_OT_outliner_item_info(Operator):
    """Display information about this outliner item"""
    bl_idname = "proteinblender.outliner_item_info"
    bl_label = "Item Info"
    bl_options = {'INTERNAL'}

    item_id: StringProperty()
    tooltip_text: StringProperty()

    @classmethod
    def description(cls, context, properties):
        """Dynamic tooltip based on the item"""
        try:
            # Try to get the tooltip from the item_id by looking it up in the outliner
            if hasattr(properties, 'item_id') and properties.item_id:
                scene = context.scene
                for item in scene.outliner_items:
                    if item.item_id == properties.item_id:
                        if hasattr(item, 'tooltip') and item.tooltip:
                            return item.tooltip
                        break

            # Fallback: try to use tooltip_text property if set
            if hasattr(properties, 'tooltip_text') and properties.tooltip_text:
                return properties.tooltip_text
        except Exception:
            pass

        return "Outliner item"

    def execute(self, context):
        # This operator is just for showing tooltips, so it does nothing when clicked
        return {'FINISHED'}


class PROTEINBLENDER_PT_outliner(Panel):
    """PB outliner panel — shows proteins, DNA/RNA and membranes"""
    bl_label = "PB Outliner"
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
        box.label(text="PB Outliner", icon='OUTLINER')
        box.separator()

        # Check if outliner items exist
        if len(scene.outliner_items) == 0:
            box.label(text="Nothing loaded yet", icon='INFO')
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
    PROTEINBLENDER_OT_outliner_item_info,
    PROTEINBLENDER_PT_outliner,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)