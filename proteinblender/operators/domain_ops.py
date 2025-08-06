"""Domain management operators with auto-split functionality"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, EnumProperty
from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy


class PROTEINBLENDER_OT_split_domain_popup(Operator):
    """Split domain/chain with popup for range selection"""
    bl_idname = "proteinblender.split_domain_popup"
    bl_label = "Split Domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    item_id: StringProperty(
        name="Item ID",
        description="ID of the item to split"
    )
    
    item_type: EnumProperty(
        name="Item Type",
        items=[
            ('CHAIN', 'Chain', 'Split a chain'),
            ('DOMAIN', 'Domain', 'Split a domain')
        ]
    )
    
    # Store original visibility states
    original_visibility: dict = {}
    preview_active: bool = False
    target_node_tree = None
    target_res_node = None
    
    def update_preview_range(self, context):
        """Update the geometry node range in real-time"""
        if not self.preview_active or not self.target_res_node:
            return
        
        # Update the Min/Max inputs of the Select Res ID Range node
        if "Min" in self.target_res_node.inputs:
            self.target_res_node.inputs["Min"].default_value = self.split_start
        if "Max" in self.target_res_node.inputs:
            self.target_res_node.inputs["Max"].default_value = self.split_end
        
        # Force viewport update
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    split_start: IntProperty(
        name="Start",
        description="Start residue for split",
        min=1,
        max=10000,
        default=1,
        update=update_preview_range
    )
    
    split_end: IntProperty(
        name="End", 
        description="End residue for split",
        min=1,
        max=10000,
        default=50,
        update=update_preview_range
    )
    
    def invoke(self, context, event):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find the selected item
        selected_item = None
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                selected_item = item
                break
        
        if not selected_item:
            return {'CANCELLED'}
        
        # Get the range for this item - use the actual item type, not the passed property
        actual_type = selected_item.item_type
        if actual_type == 'CHAIN':
            min_val = selected_item.chain_start
            max_val = selected_item.chain_end
        else:  # DOMAIN
            min_val = selected_item.domain_start
            max_val = selected_item.domain_end
        
        # Update our item_type to match the actual type
        self.item_type = actual_type
        
        # Set default values to something reasonable within the valid range
        self.split_start = min_val
        # For the end value, try to set it to min + 50, but not beyond max
        if max_val - min_val > 50:
            self.split_end = min_val + 50
        else:
            # If range is small, set to midpoint
            self.split_end = min_val + (max_val - min_val) // 2
            if self.split_end == min_val:
                self.split_end = min_val + 1  # Ensure end > start
        
        # Setup preview mode
        self.setup_preview_mode(context, selected_item)
        
        # Show popup
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Find the selected item to get valid range
        selected_item = None
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                selected_item = item
                break
        
        if selected_item:
            # Use the actual item type from the item
            actual_type = selected_item.item_type
            if actual_type == 'CHAIN':
                min_val = selected_item.chain_start
                max_val = selected_item.chain_end
            else:  # DOMAIN
                min_val = selected_item.domain_start
                max_val = selected_item.domain_end
            
            layout.label(text=f"Split {selected_item.name}")
            layout.label(text=f"Valid range: {min_val}-{max_val}")
            
            # Add preview mode indicator
            if self.preview_active:
                box = layout.box()
                box.label(text="Preview Mode Active", icon='VIEW3D')
                box.label(text="Adjust sliders to see real-time changes")
            
            layout.separator()
            
            col = layout.column()
            col.prop(self, "split_start")
            col.prop(self, "split_end")
            
            # Validation warnings
            if self.split_start < min_val or self.split_start > max_val:
                layout.label(text=f"Start must be {min_val}-{max_val}", icon='ERROR')
            if self.split_end < min_val or self.split_end > max_val:
                layout.label(text=f"End must be {min_val}-{max_val}", icon='ERROR')
            if self.split_start >= self.split_end:
                layout.label(text="Start must be less than End", icon='ERROR')
            if self.split_start == min_val and self.split_end == max_val:
                layout.label(text="Range covers entire item", icon='ERROR')
    
    def setup_preview_mode(self, context, selected_item):
        """Setup the preview mode by isolating the domain and connecting to geometry nodes"""
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Store original visibility states and hide other objects
        self.original_visibility = {}
        
        # Get the molecule and domain/chain object
        molecule_id = None
        target_object = None
        chain_id = None
        
        if selected_item.item_type == 'CHAIN':
            molecule_id = selected_item.parent_id
            chain_id = selected_item.chain_id
            # For chains, we need to find or create a temporary domain object for the full chain
            molecule = scene_manager.molecules.get(molecule_id)
            if molecule:
                # Look for an existing domain that covers the full chain
                for domain_id, domain in molecule.domains.items():
                    if (hasattr(domain, 'chain_id') and str(domain.chain_id) == str(chain_id) and
                        domain.start == selected_item.chain_start and 
                        domain.end == selected_item.chain_end):
                        if domain.object:
                            target_object = domain.object
                            break
                
                # If no full-chain domain exists, find any domain for this chain
                if not target_object:
                    for domain_id, domain in molecule.domains.items():
                        if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(chain_id):
                            if domain.object:
                                target_object = domain.object
                                break
        else:  # DOMAIN
            # Find parent chain
            for chain_item in context.scene.outliner_items:
                if chain_item.item_id == selected_item.parent_id:
                    molecule_id = chain_item.parent_id
                    chain_id = chain_item.chain_id
                    break
            
            # Find the domain in the molecule
            molecule = scene_manager.molecules.get(molecule_id)
            if molecule:
                # Look for domain by matching properties
                for domain_id, domain in molecule.domains.items():
                    if (hasattr(domain, 'start') and hasattr(domain, 'end') and
                        domain.start == selected_item.domain_start and 
                        domain.end == selected_item.domain_end and
                        str(domain.chain_id) == str(chain_id)):
                        if domain.object:
                            target_object = domain.object
                            break
        
        if not target_object or not molecule_id:
            print(f"Could not find target object for preview. molecule_id={molecule_id}, chain_id={chain_id}")
            return
        
        # Hide all protein objects from the same molecule except the one being split
        molecule = scene_manager.molecules.get(molecule_id)
        if molecule:
            # Hide the parent molecule object
            if molecule.molecule and molecule.molecule.object:
                self.original_visibility[molecule.molecule.object.name] = molecule.molecule.object.hide_viewport
                molecule.molecule.object.hide_viewport = True
            
            # Hide all domain objects except the target
            for domain_id, domain in molecule.domains.items():
                if domain.object:
                    self.original_visibility[domain.object.name] = domain.object.hide_viewport
                    if domain.object != target_object:
                        domain.object.hide_viewport = True
                    else:
                        domain.object.hide_viewport = False
        
        # Find the geometry node tree and Select Res ID Range node
        if target_object.modifiers:
            for modifier in target_object.modifiers:
                if modifier.type == 'NODES' and modifier.node_group:
                    self.target_node_tree = modifier.node_group
                    # Find the Select Res ID Range node
                    for node in self.target_node_tree.nodes:
                        if node.type == 'GROUP' and node.node_tree and "Select Res ID Range" in node.node_tree.name:
                            self.target_res_node = node
                            self.preview_active = True
                            # Set initial values
                            if "Min" in node.inputs:
                                node.inputs["Min"].default_value = self.split_start
                            if "Max" in node.inputs:
                                node.inputs["Max"].default_value = self.split_end
                            break
                    break
    
    def cleanup_preview_mode(self, context):
        """Restore original visibility states and reset node values"""
        # Reset the node to its original values if we have a reference
        if self.target_res_node:
            scene = context.scene
            # Find the original item to get its actual range
            for item in scene.outliner_items:
                if item.item_id == self.item_id:
                    if item.item_type == 'CHAIN':
                        original_start = item.chain_start
                        original_end = item.chain_end
                    else:  # DOMAIN
                        original_start = item.domain_start
                        original_end = item.domain_end
                    
                    # Reset the node values
                    if "Min" in self.target_res_node.inputs:
                        self.target_res_node.inputs["Min"].default_value = original_start
                    if "Max" in self.target_res_node.inputs:
                        self.target_res_node.inputs["Max"].default_value = original_end
                    break
        
        # Restore original visibility
        for obj_name, visibility in self.original_visibility.items():
            if obj_name in bpy.data.objects:
                bpy.data.objects[obj_name].hide_viewport = visibility
        
        # Reset preview state
        self.preview_active = False
        self.target_node_tree = None
        self.target_res_node = None
        self.original_visibility = {}
        
        # Force viewport update
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    def execute(self, context):
        # Cleanup preview mode first
        self.cleanup_preview_mode(context)
        
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find the item
        selected_item = None
        for item in scene.outliner_items:
            if item.item_id == self.item_id:
                selected_item = item
                break
        
        if not selected_item:
            return {'CANCELLED'}
        
        # Get the valid range for clamping - use actual item type
        actual_type = selected_item.item_type
        if actual_type == 'CHAIN':
            min_val = selected_item.chain_start
            max_val = selected_item.chain_end
        else:  # DOMAIN
            min_val = selected_item.domain_start
            max_val = selected_item.domain_end
        
        # Clamp values to valid range
        clamped_start = max(min_val, min(self.split_start, max_val))
        clamped_end = max(min_val, min(self.split_end, max_val))
        
        # Validate clamped values
        if clamped_start >= clamped_end:
            self.report({'ERROR'}, "Invalid range: start must be less than end")
            return {'CANCELLED'}
        
        if clamped_start == min_val and clamped_end == max_val:
            self.report({'ERROR'}, "Cannot split: range covers entire item")
            return {'CANCELLED'}
        
        # Get molecule and chain info - use actual item type
        if actual_type == 'CHAIN':
            molecule_id = selected_item.parent_id
            chain_id = selected_item.chain_id
        else:  # DOMAIN
            # For domains, get parent chain
            parent_chain = None
            for item in scene.outliner_items:
                if item.item_id == selected_item.parent_id:
                    parent_chain = item
                    break
            if parent_chain:
                molecule_id = parent_chain.parent_id
                chain_id = parent_chain.chain_id
            else:
                self.report({'ERROR'}, "Could not find parent chain")
                return {'CANCELLED'}
        
        # Call the split operator with clamped values
        bpy.ops.proteinblender.split_domain(
            chain_id=chain_id,
            molecule_id=molecule_id,
            split_start=clamped_start,
            split_end=clamped_end
        )
        
        return {'FINISHED'}
    
    def cancel(self, context):
        """Handle cancellation of the operator"""
        self.cleanup_preview_mode(context)
        return {'CANCELLED'}


class PROTEINBLENDER_OT_split_domain(Operator):
    """Split domain with auto-generation of complementary domains"""
    bl_idname = "proteinblender.split_domain"
    bl_label = "Split Domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Properties for the split operation
    chain_id: StringProperty(
        name="Chain ID",
        description="ID of the chain to split"
    )
    
    molecule_id: StringProperty(
        name="Molecule ID",
        description="ID of the molecule"
    )
    
    split_start: IntProperty(
        name="Start",
        description="Start residue of new domain",
        min=1,
        default=1
    )
    
    split_end: IntProperty(
        name="End",
        description="End residue of new domain",
        min=1,
        default=50
    )
    
    def invoke(self, context, event):
        """Show dialog to get split parameters"""
        # Get selected chain from outliner
        scene = context.scene
        selected_item = None
        
        # Find selected chain or domain
        for item in scene.outliner_items:
            if item.is_selected and item.item_type in ['CHAIN', 'DOMAIN']:
                selected_item = item
                break
        
        if not selected_item:
            self.report({'WARNING'}, "Please select a chain or domain to split")
            return {'CANCELLED'}
        
        # Get parent molecule
        if selected_item.item_type == 'CHAIN':
            self.chain_id = selected_item.chain_id
            self.molecule_id = selected_item.parent_id
        else:  # DOMAIN
            # Find parent chain
            for chain_item in scene.outliner_items:
                if chain_item.item_id == selected_item.parent_id:
                    self.chain_id = chain_item.chain_id
                    self.molecule_id = chain_item.parent_id
                    break
        
        # Set default values based on chain
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if molecule:
            # Get chain residue range
            # For now, use a default range
            self.split_start = 1
            self.split_end = 50
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        """Draw the dialog"""
        layout = self.layout
        
        col = layout.column()
        col.label(text=f"Split Chain {self.chain_id}")
        
        row = col.row(align=True)
        row.prop(self, "split_start", text="Start")
        row.prop(self, "split_end", text="End")
        
        col.label(text="Auto-generates complementary domains", icon='INFO')
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}
        
        # Capture molecule state before making changes (for undo/redo support)
        scene_manager._capture_molecule_state(self.molecule_id)
        
        # Log existing domains before split
        self.report({'INFO'}, f"Existing domains before split:")
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id'):
                self.report({'INFO'}, f"  Domain {domain_id}: chain={domain.chain_id}, range={domain.start}-{domain.end}, name={domain.name}")
        
        # Validate range
        if not self.validate_split_range(molecule):
            return {'CANCELLED'}
        
        # Auto-generate domains to cover full chain
        domains = self.auto_generate_domains(molecule)
        
        # Find and remove domains that are being split
        # This includes both full-chain domains and partial domains that match our split range
        domains_to_remove = []
        chain_start, chain_end = self.get_chain_range(molecule)
        
        self.report({'INFO'}, f"Looking for domains to remove for chain {self.chain_id}, split range {self.split_start}-{self.split_end}")
        
        for domain_id, domain in molecule.domains.items():
            # Check if this domain belongs to our chain
            if hasattr(domain, 'chain_id'):
                self.report({'INFO'}, f"Checking domain {domain_id}: chain_id={domain.chain_id}, range={domain.start}-{domain.end}")
                
                # Compare chain IDs as strings to handle type mismatches
                if str(domain.chain_id) == str(self.chain_id):
                    # Remove domains that overlap with our split range
                    # This includes:
                    # 1. Domains that span our entire split range (the domain being split)
                    # 2. Full-chain domains when splitting from chain level
                    # 3. Any domain that would conflict with our new domains
                    
                    # Check if this domain contains or equals our split range
                    if (domain.start <= self.split_start and domain.end >= self.split_end):
                        domains_to_remove.append(domain_id)
                        self.report({'INFO'}, f"Will remove domain that contains split range: {domain.name} ({domain.start}-{domain.end})")
                    # Also check for any domains that would overlap with our split
                    elif ((domain.start >= self.split_start and domain.start <= self.split_end) or
                          (domain.end >= self.split_start and domain.end <= self.split_end)):
                        domains_to_remove.append(domain_id)
                        self.report({'INFO'}, f"Will remove overlapping domain: {domain.name} ({domain.start}-{domain.end})")
        
        # Remove the domains
        self.report({'INFO'}, f"Removing {len(domains_to_remove)} domains")
        for domain_id in domains_to_remove:
            if domain_id in molecule.domains:
                domain = molecule.domains[domain_id]
                # Remove the domain's Blender object if it exists
                if hasattr(domain, 'object') and domain.object:
                    try:
                        bpy.data.objects.remove(domain.object, do_unlink=True)
                        self.report({'INFO'}, f"Removed Blender object for domain {domain_id}")
                    except:
                        self.report({'WARNING'}, f"Could not remove Blender object for domain {domain_id}")
                # Remove from molecule's domains
                del molecule.domains[domain_id]
                self.report({'INFO'}, f"Removed domain {domain_id} from molecule")
        
        # Check if the chain being split was in any groups
        chain_groups = []
        chain_outliner_id = f"{self.molecule_id}_chain_{self.chain_id}"
        
        # Debug: print the chain ID we're looking for
        self.report({'INFO'}, f"Looking for chain with outliner ID: {chain_outliner_id}")
        
        # Find groups that contain this chain
        for item in context.scene.outliner_items:
            if item.item_type == 'GROUP' and item.group_memberships:
                member_ids = item.group_memberships.split(',')
                self.report({'INFO'}, f"Group '{item.name}' has members: {member_ids}")
                if chain_outliner_id in member_ids:
                    chain_groups.append(item)
                    self.report({'INFO'}, f"Chain was in group: {item.name}")
        
        # Create the new domains
        created_domains = []
        created_outliner_ids = []  # Track outliner IDs for group updates
        
        for i, (start, end) in enumerate(domains):
            domain_name = f"Residues {start}-{end}"  # More descriptive name
            
            # Check if this exact domain already exists for this chain
            domain_exists = False
            domain_outliner_id = None
            
            for domain_id, domain in molecule.domains.items():
                if (hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id) and
                    domain.start == start and domain.end == end):
                    domain_exists = True
                    # Domain ID already includes molecule ID, so use it directly
                    domain_outliner_id = domain_id
                    self.report({'INFO'}, f"Domain {domain_name} already exists, skipping creation")
                    created_domains.append(domain_id)
                    created_outliner_ids.append(domain_outliner_id)
                    break
            
            if not domain_exists:
                # Create domain using the molecule's create_domain method
                # The method expects: chain_id_int_str, start, end, name, auto_fill_chain, parent_domain_id
                created_domain_ids = molecule._create_domain_with_params(
                    self.chain_id,  # chain_id_int_str
                    start,          # start
                    end,            # end
                    domain_name,    # name
                    False,          # auto_fill_chain
                    None            # parent_domain_id
                )
                
                if created_domain_ids:
                    created_domains.extend(created_domain_ids)
                    # Domain IDs already include molecule ID, use them directly
                    for domain_id in created_domain_ids:
                        created_outliner_ids.append(domain_id)
                    self.report({'INFO'}, f"Created {domain_name}")
                else:
                    self.report({'WARNING'}, f"Failed to create domain {start}-{end}")
        
        # Update group memberships BEFORE rebuilding outliner
        # IMPORTANT: We keep the chain in the group, not individual domains
        # The hierarchy will show domains under the chain
        if chain_groups:
            self.report({'INFO'}, f"Found {len(chain_groups)} groups containing the chain")
            self.report({'INFO'}, f"Chain will remain in groups, with domains shown as children")
            
            # We don't need to update group memberships here because:
            # 1. The chain stays in the group
            # 2. The domains will be shown as children of the chain in the group view
        
        # Rebuild outliner to show new domains and updated groups
        build_outliner_hierarchy(context)
        
        # No need to update domain group memberships individually
        # They will be shown under their parent chain in the group view
        
        # Log final state
        self.report({'INFO'}, f"Domains after split:")
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id):
                self.report({'INFO'}, f"  Domain {domain_id}: range={domain.start}-{domain.end}, name={domain.name}")
        
        return {'FINISHED'}
    
    def validate_split_range(self, molecule):
        """Validate that the split range is valid"""
        if self.split_start >= self.split_end:
            self.report({'ERROR'}, "Start must be less than end")
            return False
        
        # Get actual chain range
        chain_start, chain_end = self.get_chain_range(molecule)
        
        if self.split_start < chain_start:
            self.report({'ERROR'}, f"Start residue must be at least {chain_start}")
            return False
            
        if self.split_end > chain_end:
            self.report({'ERROR'}, f"End residue must be at most {chain_end}")
            return False
        
        return True
    
    def get_chain_range(self, molecule):
        """Get the actual residue range for this chain"""
        chain_start = 1
        chain_end = 200  # Default fallback
        
        # Try to get the actual chain range
        if hasattr(molecule, 'chain_residue_ranges') and molecule.chain_residue_ranges:
            # Try multiple ways to find the correct chain range
            chain_id_int = int(self.chain_id) if self.chain_id.isdigit() else None
            
            # Method 1: Use idx_to_label_asym_id_map
            if hasattr(molecule, 'idx_to_label_asym_id_map') and chain_id_int is not None:
                if chain_id_int in molecule.idx_to_label_asym_id_map:
                    label_asym_id = molecule.idx_to_label_asym_id_map[chain_id_int]
                    if label_asym_id in molecule.chain_residue_ranges:
                        chain_start, chain_end = molecule.chain_residue_ranges[label_asym_id]
            
            # Method 2: Try direct string lookup
            if (chain_start, chain_end) == (1, 200) and self.chain_id in molecule.chain_residue_ranges:
                chain_start, chain_end = molecule.chain_residue_ranges[self.chain_id]
        
        return chain_start, chain_end
    
    def auto_generate_domains(self, molecule):
        """Generate domain ranges to cover the full chain"""
        # Get actual chain residue range from molecule data
        chain_start, chain_end = self.get_chain_range(molecule)
        
        domains = []
        
        # Always create the three domains for a split:
        # 1. Before split (if exists)
        if self.split_start > chain_start:
            domains.append((chain_start, self.split_start - 1))
        
        # 2. The split domain itself
        domains.append((self.split_start, self.split_end))
        
        # 3. After split (if exists)
        if self.split_end < chain_end:
            domains.append((self.split_end + 1, chain_end))
        
        self.report({'INFO'}, f"Auto-generated domains: {domains}")
        return domains


class PROTEINBLENDER_OT_merge_domains(Operator):
    """Merge selected domains"""
    bl_idname = "proteinblender.merge_domains"
    bl_label = "Merge Domains"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find selected domains and remove duplicates
        # (user might have selected both actual domain and its group reference)
        domains_dict = {}  # Track unique domains by their actual ID
        
        for item in scene.outliner_items:
            if item.is_selected and item.item_type == 'DOMAIN':
                # Get the actual domain ID and item
                if "_ref_" in item.item_id:
                    # This is a reference - extract actual domain ID
                    parts = item.item_id.split("_ref_", 1)
                    if len(parts) == 2:
                        actual_domain_id = parts[1]
                        # Find the actual domain item
                        for actual_item in scene.outliner_items:
                            if actual_item.item_id == actual_domain_id:
                                if actual_domain_id not in domains_dict:
                                    domains_dict[actual_domain_id] = actual_item
                                break
                else:
                    # This is an actual domain
                    if item.item_id not in domains_dict:
                        domains_dict[item.item_id] = item
        
        # Get unique selected domains
        selected_domains = list(domains_dict.values())
        actual_domain_items = selected_domains  # They're all actual items now
        
        if len(selected_domains) < 2:
            self.report({'WARNING'}, "Select at least 2 domains to merge")
            return {'CANCELLED'}
        
        # Use actual domain items for parent chain check
        parent_chains = set()
        for item in actual_domain_items:
            parent_id = item.parent_id
            parent_chains.add(parent_id)
        
        if len(parent_chains) > 1:
            self.report({'WARNING'}, "Can only merge domains from the same chain")
            return {'CANCELLED'}
        
        # Sort actual domains by start position
        actual_domain_items.sort(key=lambda d: d.domain_start)
        
        # Check if they're adjacent
        for i in range(len(actual_domain_items) - 1):
            if actual_domain_items[i].domain_end + 1 != actual_domain_items[i+1].domain_start:
                self.report({'WARNING'}, "Domains must be adjacent to merge")
                return {'CANCELLED'}
        
        # Get parent chain and molecule
        parent_chain_id = list(parent_chains)[0]
        parent_chain = None
        for item in scene.outliner_items:
            if item.item_id == parent_chain_id:
                parent_chain = item
                break
        
        if not parent_chain:
            self.report({'ERROR'}, "Could not find parent chain")
            return {'CANCELLED'}
        
        molecule_id = parent_chain.parent_id
        molecule = scene_manager.molecules.get(molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "Could not find parent molecule")
            return {'CANCELLED'}
        
        # Capture molecule state before making changes (for undo/redo support)
        scene_manager._capture_molecule_state(molecule_id)
        
        # Calculate merged domain range using actual domains
        merged_start = actual_domain_items[0].domain_start
        merged_end = actual_domain_items[-1].domain_end
        merged_name = f"Residues {merged_start}-{merged_end}"
        
        # Collect groups that contain any of the domains being merged
        affected_groups = {}  # group_id -> set of domain outliner IDs in this group
        # Use the actual domain IDs, not the reference IDs
        domain_outliner_ids = [item.item_id for item in actual_domain_items]
        
        for group_item in scene.outliner_items:
            if group_item.item_type == 'GROUP' and group_item.group_memberships:
                member_ids = set(group_item.group_memberships.split(','))
                domains_in_group = set(domain_outliner_ids) & member_ids
                if domains_in_group:
                    affected_groups[group_item.item_id] = domains_in_group
                    self.report({'INFO'}, f"Group '{group_item.name}' contains {len(domains_in_group)} of the merging domains")
        
        # Remove the old domains (use actual domain items)
        for domain_item in actual_domain_items:
            # Find the actual domain in molecule
            domain_to_remove = None
            for domain_id, domain in molecule.domains.items():
                if (hasattr(domain, 'start') and hasattr(domain, 'end') and
                    domain.start == domain_item.domain_start and 
                    domain.end == domain_item.domain_end and
                    str(domain.chain_id) == parent_chain.chain_id):
                    domain_to_remove = domain_id
                    break
            
            if domain_to_remove:
                domain = molecule.domains[domain_to_remove]
                # Remove the domain's Blender object if it exists
                if hasattr(domain, 'object') and domain.object:
                    bpy.data.objects.remove(domain.object, do_unlink=True)
                # Remove from molecule's domains
                del molecule.domains[domain_to_remove]
                self.report({'INFO'}, f"Removed domain: {domain_item.name}")
        
        # Create the merged domain
        created_domain_ids = molecule._create_domain_with_params(
            parent_chain.chain_id,  # chain_id_int_str
            merged_start,           # start
            merged_end,             # end
            merged_name,            # name
            False,                  # auto_fill_chain
            None                    # parent_domain_id
        )
        
        if created_domain_ids:
            self.report({'INFO'}, f"Created merged domain: {merged_name}")
            
            # Check if all domains cover the entire chain
            chain_start, chain_end = merged_start, merged_end
            if hasattr(molecule, 'chain_residue_ranges'):
                # Get actual chain range
                chain_id_int = int(parent_chain.chain_id) if parent_chain.chain_id.isdigit() else None
                if hasattr(molecule, 'idx_to_label_asym_id_map') and chain_id_int is not None:
                    if chain_id_int in molecule.idx_to_label_asym_id_map:
                        label_asym_id = molecule.idx_to_label_asym_id_map[chain_id_int]
                        if label_asym_id in molecule.chain_residue_ranges:
                            chain_start, chain_end = molecule.chain_residue_ranges[label_asym_id]
                elif parent_chain.chain_id in molecule.chain_residue_ranges:
                    chain_start, chain_end = molecule.chain_residue_ranges[parent_chain.chain_id]
            
            # Check if the merged domain covers the entire chain
            covers_entire_chain = (merged_start == chain_start and merged_end == chain_end)
            
            # For groups, we only track chains, not individual domains
            # So we only need to update if merging creates a full chain
            if affected_groups and covers_entire_chain:
                self.report({'INFO'}, "Domains cover entire chain - will add chain to groups")
                
                # The chain might already be in the groups, but we'll ensure it's there
                for group_id in affected_groups.keys():
                    # Find the group
                    group_item = None
                    for item in scene.outliner_items:
                        if item.item_type == 'GROUP' and item.item_id == group_id:
                            group_item = item
                            break
                    
                    if group_item:
                        # Get current members
                        current_members = set(group_item.group_memberships.split(',')) if group_item.group_memberships else set()
                        
                        # Add the chain if not already present
                        chain_outliner_id = f"{molecule_id}_chain_{parent_chain.chain_id}"
                        if chain_outliner_id not in current_members:
                            current_members.add(chain_outliner_id)
                            # Update the group
                            group_item.group_memberships = ','.join(filter(None, current_members))
                            self.report({'INFO'}, f"Added chain to group '{group_item.name}'")
                        else:
                            self.report({'INFO'}, f"Chain already in group '{group_item.name}'")
        else:
            self.report({'ERROR'}, "Failed to create merged domain")
        
        # Rebuild outliner
        build_outliner_hierarchy(context)
        
        # Update chain's group membership if needed
        if affected_groups and covers_entire_chain:
            for item in context.scene.outliner_items:
                if item.item_id == f"{molecule_id}_chain_{parent_chain.chain_id}":
                    # Update chain's group membership
                    item_groups = set(item.group_memberships.split(',')) if item.group_memberships else set()
                    item_groups.update(affected_groups.keys())
                    item.group_memberships = ','.join(filter(None, item_groups))
                    self.report({'INFO'}, f"Updated chain group memberships")
                    break
        
        return {'FINISHED'}


class PROTEINBLENDER_OT_rename_domain(Operator):
    """Rename selected domain"""
    bl_idname = "proteinblender.rename_domain"
    bl_label = "Rename Domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    new_name: StringProperty(
        name="New Name",
        description="New name for the domain"
    )
    
    domain_id: StringProperty()
    
    def invoke(self, context, event):
        scene = context.scene
        
        # Find selected domain
        for item in scene.outliner_items:
            if item.is_selected and item.item_type == 'DOMAIN':
                self.domain_id = item.item_id
                self.new_name = item.name
                break
        
        if not self.domain_id:
            self.report({'WARNING'}, "Please select a domain to rename")
            return {'CANCELLED'}
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")
    
    def execute(self, context):
        scene = context.scene
        
        # Update domain name in outliner
        for item in scene.outliner_items:
            if item.item_id == self.domain_id:
                item.name = self.new_name
                break
        
        # TODO: Update actual domain object name
        
        # Redraw UI
        context.area.tag_redraw()
        return {'FINISHED'}


# Operator classes to register
CLASSES = [
    PROTEINBLENDER_OT_split_domain_popup,
    PROTEINBLENDER_OT_split_domain,
    PROTEINBLENDER_OT_merge_domains,
    PROTEINBLENDER_OT_rename_domain,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)