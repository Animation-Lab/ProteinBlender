"""Domain management operators with auto-split functionality"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, EnumProperty
from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy
from ..utils.chain_utils import (
    chain_match_tokens,
    get_chain_objects,
    normalize_domain_residue_range,
)
from .visual_edit import VisualEditMixin


def _is_identity_matrix(m, tol=1e-6):
    """True if 4x4 matrix *m* is within *tol* of the identity (a no-op delta)."""
    from mathutils import Matrix
    ident = Matrix.Identity(4)
    return all(abs(m[i][j] - ident[i][j]) < tol for i in range(4) for j in range(4))


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
    
    def update_preview_range(self, context):
        """Update the geometry node range in real-time"""
        # Try to get the node from scene properties (persistent across operator instances)
        if "pb_preview_object" not in context.scene:
            print("No preview object stored in scene")
            return
            
        # Retrieve the stored references
        obj_name = context.scene.get("pb_preview_object")
        mod_name = context.scene.get("pb_preview_modifier")
        node_name = context.scene.get("pb_preview_node")
        
        if not all([obj_name, mod_name, node_name]):
            print("Missing stored references")
            return
        
        # Find the object
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            print(f"Could not find object '{obj_name}'")
            return
        
        # Find the modifier
        modifier = obj.modifiers.get(mod_name)
        if not modifier or modifier.type != 'NODES' or not modifier.node_group:
            print(f"Could not find geometry nodes modifier '{mod_name}'")
            return
        
        # Find the node
        node = modifier.node_group.nodes.get(node_name)
        if not node:
            print(f"Could not find node '{node_name}'")
            return
        
        print(f"Updating preview range: Start={self.split_start}, End={self.split_end}")
        
        # Update the Min/Max inputs of the Select Res ID Range node
        try:
            # Update Min
            if "Min" in node.inputs:
                old_min = node.inputs["Min"].default_value
                node.inputs["Min"].default_value = self.split_start
                print(f"  Updated Min: {old_min} -> {self.split_start}")
            else:
                print(f"  Warning: Could not find Min input in node")
            
            # Update Max
            if "Max" in node.inputs:
                old_max = node.inputs["Max"].default_value  
                node.inputs["Max"].default_value = self.split_end
                print(f"  Updated Max: {old_max} -> {self.split_end}")
            else:
                print(f"  Warning: Could not find Max input in node")
            
            # Force depsgraph update
            if context.view_layer:
                context.view_layer.update()
                
        except Exception as e:
            print(f"  Error updating node values: {e}")
        
        # Force viewport and node editor update
        for area in context.screen.areas:
            if area.type in {'VIEW_3D', 'NODE_EDITOR'}:
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
        
        # Initialize instance attributes
        self.original_visibility = {}
        self.preview_active = False
        self.target_node_tree = None
        self.target_res_node = None
        
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
            if hasattr(self, 'preview_active') and self.preview_active:
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
            # Isolate the chain's object: the resolver returns the full-chain
            # object (or the chain's domain objects once split) and handles the
            # chain-index vs. chain-letter bridge.
            molecule = scene_manager.molecules.get(molecule_id)
            chain_objects = get_chain_objects(molecule, selected_item)
            if chain_objects:
                target_object = chain_objects[0]
        else:  # DOMAIN
            # Find parent chain
            for chain_item in context.scene.outliner_items:
                if chain_item.item_id == selected_item.parent_id:
                    molecule_id = chain_item.parent_id
                    chain_id = chain_item.chain_id
                    break

            # A domain row's item_id is the domain id, so look it up directly.
            molecule = scene_manager.molecules.get(molecule_id)
            if molecule:
                domain = molecule.domains.get(selected_item.item_id)
                if domain and domain.object:
                    target_object = domain.object
        
        if not target_object or not molecule_id:
            print(f"Could not find target object for preview. molecule_id={molecule_id}, chain_id={chain_id}")
            return
        
        # Hide all protein objects from the same molecule except the one being split
        molecule = scene_manager.molecules.get(molecule_id)
        if molecule:
            # Note: We don't hide the parent molecule object to maintain proper parent-child relationships
            # The parent molecule doesn't have visible geometry anyway (domains have the actual geometry)
            
            # Hide all domain objects except the target
            for domain_id, domain in molecule.domains.items():
                if domain.object:
                    self.original_visibility[domain.object.name] = domain.object.hide_viewport
                    if domain.object != target_object:
                        domain.object.hide_viewport = True
                    else:
                        domain.object.hide_viewport = False
        
        # Find the geometry node tree and Select Res ID Range node
        # Since we have isolated a single object, just find ANY Select Res ID Range node in it
        if target_object and target_object.modifiers:
            print(f"Looking for Select Res ID Range node in object: {target_object.name}")
            
            for modifier in target_object.modifiers:
                if modifier.type == 'NODES' and modifier.node_group:
                    self.target_node_tree = modifier.node_group
                    
                    # Simply find ANY Select Res ID Range node in this tree
                    # Since this is the isolated object, it should be the right one
                    for node in self.target_node_tree.nodes:
                        if node.type == 'GROUP' and node.node_tree:
                            # Check if this is a Select Res ID Range node
                            if "Select Res ID Range" in node.node_tree.name:
                                self.target_res_node = node
                                self.preview_active = True

                                # Store node reference in scene properties for persistence
                                context.scene["pb_preview_object"] = target_object.name
                                context.scene["pb_preview_modifier"] = modifier.name
                                context.scene["pb_preview_node"] = node.name

                                # Set initial values
                                if "Min" in node.inputs:
                                    node.inputs["Min"].default_value = self.split_start

                                if "Max" in node.inputs:
                                    node.inputs["Max"].default_value = self.split_end

                                # Force update
                                if context.view_layer:
                                    context.view_layer.update()

                                return  # We found it, done!
                    break  # Only check the first geometry nodes modifier
    
    def cleanup_preview_mode(self, context):
        """Restore original visibility states and reset node values"""
        scene = context.scene
        
        # Try to reset node values using stored references
        if all(k in scene for k in ["pb_preview_object", "pb_preview_modifier", "pb_preview_node"]):
            obj = bpy.data.objects.get(scene.get("pb_preview_object"))
            if obj and obj.modifiers:
                modifier = obj.modifiers.get(scene.get("pb_preview_modifier"))
                if modifier and modifier.node_group:
                    node = modifier.node_group.nodes.get(scene.get("pb_preview_node"))
                    if node:
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
                                if "Min" in node.inputs:
                                    node.inputs["Min"].default_value = original_start
                                if "Max" in node.inputs:
                                    node.inputs["Max"].default_value = original_end
                                break
        
        # Clean up scene properties
        for prop in ["pb_preview_object", "pb_preview_modifier", "pb_preview_node"]:
            if prop in scene:
                del scene[prop]
                print(f"Cleaned up scene property: {prop}")
        
        # Restore original visibility
        if hasattr(self, 'original_visibility'):
            for obj_name, visibility in self.original_visibility.items():
                if obj_name in bpy.data.objects:
                    bpy.data.objects[obj_name].hide_viewport = visibility
        
        # Reset preview state if attributes exist
        if hasattr(self, 'preview_active'):
            self.preview_active = False
        if hasattr(self, 'target_node_tree'):
            self.target_node_tree = None
        if hasattr(self, 'target_res_node'):
            self.target_res_node = None
        if hasattr(self, 'original_visibility'):
            self.original_visibility = {}
        
        # Force viewport update
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    
    def execute(self, context):
        # Cleanup preview mode first
        self.cleanup_preview_mode(context)
        
        scene = context.scene
        
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
        # Blender's Operator.cancel callback is a notification hook and must
        # return None. Returning an operator result set makes RNA emit a Python
        # callback error every time the user presses Escape in this dialog.
        return None


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

        # self.chain_id may arrive as the chain *index* ("2") from the outliner
        # while existing domains store the chain *letter* ("D"). Resolve every
        # form once so the matches below work regardless of convention.
        chain_tokens = chain_match_tokens(molecule, self.chain_id)

        # Capture molecule state before making changes (for undo/redo support)
        scene_manager.refresh_domain_refs_before_destructive_op(self.molecule_id)
        
        # Log existing domains before split
        print(f"Existing domains before split:")
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id'):
                print(f"  Domain {domain_id}: chain={domain.chain_id}, range={domain.start}-{domain.end}, name={domain.name}")
        
        # Validate range
        if not self.validate_split_range(molecule):
            return {'CANCELLED'}
        
        # Auto-generate domains to cover full chain
        domains = self.auto_generate_domains(molecule)
        
        # Find and remove domains that are being split
        # This includes both full-chain domains and partial domains that match our split range
        domains_to_remove = []
        chain_start, chain_end = self.get_chain_range(molecule)

        # Track the parent domain's style before removal
        parent_domain_style = None

        # Capture how the object being split maps its atoms into the world -
        # its matrix_world AND its geometry-nodes pivot. The user may have
        # moved/rotated the chain in the viewport; the new pieces are fresh
        # copies of the MOLECULE object and would snap back to the imported pose
        # unless we carry that mapping onto them. We keep the pivot too because a
        # domain's world mapping is `matrix_world @ (co - pivot)`, and matching
        # only matrix_world would leave pieces off by the pivot difference.
        split_source_matrix_world = None
        split_source_pivot = None

        print(f"Looking for domains to remove for chain {self.chain_id}, split range {self.split_start}-{self.split_end}")

        for domain_id, domain in molecule.domains.items():
            # Check if this domain belongs to our chain
            if hasattr(domain, 'chain_id'):
                print(f"Checking domain {domain_id}: chain_id={domain.chain_id}, range={domain.start}-{domain.end}")

                # Match on any of the chain's identity forms (index or letter)
                if str(domain.chain_id) in chain_tokens:
                    # Remove domains that overlap with our split range
                    # This includes:
                    # 1. Domains that span our entire split range (the domain being split)
                    # 2. Full-chain domains when splitting from chain level
                    # 3. Any domain that would conflict with our new domains

                    # Check if this domain contains or equals our split range
                    if (domain.start <= self.split_start and domain.end >= self.split_end):
                        # Capture the style from the domain being split
                        # First try to read from the property, then fallback to reading from geometry nodes
                        if hasattr(domain, 'style'):
                            parent_domain_style = domain.style
                            print(f"Captured style '{parent_domain_style}' from parent domain property")

                        # If style property seems to be default, read actual style from geometry nodes
                        if domain.object and (not parent_domain_style or parent_domain_style in ['ribbon', 'surface']):
                            from ..core.visual_style import get_object_style
                            actual_style = get_object_style(domain.object)
                            if actual_style:
                                parent_domain_style = actual_style
                                print(f"Read actual style '{parent_domain_style}' from parent domain's geometry nodes")

                        # This domain is the one being split - remember how it
                        # maps atoms to the world so the pieces inherit its pose.
                        if domain.object and split_source_matrix_world is None:
                            from ..core import domain_space
                            split_source_matrix_world = domain.object.matrix_world.copy()
                            split_source_pivot = domain_space.get_pivot(domain.object)

                        domains_to_remove.append(domain_id)
                        print(f"Will remove domain that contains split range: {domain.name} ({domain.start}-{domain.end})")
                    # Also check for any domains that would overlap with our split
                    elif ((domain.start >= self.split_start and domain.start <= self.split_end) or
                          (domain.end >= self.split_start and domain.end <= self.split_end)):
                        # Also capture style from overlapping domains
                        if parent_domain_style is None:
                            if hasattr(domain, 'style'):
                                parent_domain_style = domain.style
                                print(f"Captured style '{parent_domain_style}' from overlapping domain property")

                            # If style property seems to be default, read actual style from geometry nodes
                            if domain.object and (not parent_domain_style or parent_domain_style in ['ribbon', 'surface']):
                                from ..core.visual_style import get_object_style
                                actual_style = get_object_style(domain.object)
                                if actual_style:
                                    parent_domain_style = actual_style
                                    print(f"Read actual style '{parent_domain_style}' from overlapping domain's geometry nodes")

                        domains_to_remove.append(domain_id)
                        print(f"Will remove overlapping domain: {domain.name} ({domain.start}-{domain.end})")
        
        # Remove the domains
        print(f"Removing {len(domains_to_remove)} domains")
        for domain_id in domains_to_remove:
            if domain_id in molecule.domains:
                domain = molecule.domains[domain_id]
                # Remove the domain's Blender object if it exists
                if hasattr(domain, 'object') and domain.object:
                    try:
                        obj_name = domain.object.name
                        bpy.data.objects.remove(domain.object, do_unlink=True)
                        print(f"Removed Blender object {obj_name} for domain {domain_id}")
                    except (ReferenceError, RuntimeError):
                        self.report({'WARNING'}, f"Could not remove Blender object for domain {domain_id}")
                # Remove from molecule's domains
                del molecule.domains[domain_id]
                print(f"Removed domain {domain_id} from molecule")
        
        # Check if the chain being split was in any groups
        chain_groups = []
        chain_outliner_id = f"{self.molecule_id}_chain_{self.chain_id}"
        
        print(f"Looking for chain with outliner ID: {chain_outliner_id}")
        
        # Find groups that contain this chain
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.puppet_memberships:
                member_ids = item.puppet_memberships.split(',')
                print(f"Group '{item.name}' has members: {member_ids}")
                if chain_outliner_id in member_ids:
                    chain_groups.append(item)
                    print(f"Chain was in group: {item.name}")
        
        # Create the new domains
        created_domains = []
        created_outliner_ids = []  # Track outliner IDs for group updates
        all_created_domain_ids = []  # Track all created domain IDs in order for pivot setting

        for i, (start, end) in enumerate(domains):
            domain_name = f"Residues {start}-{end}"  # More descriptive name
            
            # Check if this exact domain already exists for this chain
            domain_exists = False
            domain_outliner_id = None
            
            for domain_id, domain in molecule.domains.items():
                if (hasattr(domain, 'chain_id') and str(domain.chain_id) in chain_tokens and
                    domain.start == start and domain.end == end):
                    domain_exists = True
                    # Domain ID already includes molecule ID, so use it directly
                    domain_outliner_id = domain_id
                    print(f"Domain {domain_name} already exists, skipping creation")
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
                        all_created_domain_ids.append(domain_id)

                        # Apply the parent domain's style if we captured one
                        if parent_domain_style and domain_id in molecule.domains:
                            domain = molecule.domains[domain_id]
                            domain.style = parent_domain_style
                            print(f"Applied inherited style '{parent_domain_style}' to {domain_name}")

                            # Also apply the style to the visual object
                            if domain.object:
                                from ..core.visual_style import apply_style_to_object
                                apply_style_to_object(domain.object, parent_domain_style)

                    print(f"Created {domain_name}")
                else:
                    self.report({'WARNING'}, f"Failed to create domain {start}-{end}")
        
        # Reference for the move/rotate transfer below: how a FRESH piece maps
        # atoms to the world before we touch its pivots. Every piece is an
        # identical copy of the molecule object, so any one of them defines the
        # "imported pose" mapping we need to compare the split source against.
        split_ref_matrix_world = None
        split_ref_pivot = None
        if split_source_matrix_world is not None and all_created_domain_ids:
            from ..core import domain_space
            ref_domain = molecule.domains.get(all_created_domain_ids[0])
            if ref_domain and ref_domain.object:
                split_ref_matrix_world = ref_domain.object.matrix_world.copy()
                split_ref_pivot = domain_space.get_pivot(ref_domain.object)

        # Set intelligent pivots for the split domains
        if len(all_created_domain_ids) >= 2:
            print(f"Setting intelligent pivots for {len(all_created_domain_ids)} split domains")
            molecule.set_domain_split_pivots(bpy.context, all_created_domain_ids, self.chain_id)

        # Carry the split chain's move/rotate onto the new pieces. A domain maps
        # a mesh coord to the world as `matrix_world @ (co - pivot)`, so the
        # rigid delta that takes a fresh piece's mapping to the split source's
        # mapping is
        #     delta = (src_mw @ T(-src_pivot)) @ (ref_mw @ T(-ref_pivot))^-1
        # Computing it in this render space (not from matrix_world alone) makes
        # it EXACTLY identity when the source draws its atoms where a fresh piece
        # would - e.g. an unmoved chain, or a chain on a re-centred copy whose
        # matrix_world differs but whose rendered position matches. It is the
        # genuine move+rotate only when the user actually moved the chain.
        # Applied AFTER the pivots are set, as a rigid premultiply, it preserves
        # each piece's pivot-based rendering and just relocates it as a unit.
        if (split_source_matrix_world is not None and split_ref_matrix_world is not None):
            from mathutils import Matrix
            from ..core import domain_space
            src_map = split_source_matrix_world @ Matrix.Translation(-split_source_pivot)
            ref_map = split_ref_matrix_world @ Matrix.Translation(-split_ref_pivot)
            delta = src_map @ ref_map.inverted()
            if not _is_identity_matrix(delta):
                bpy.context.view_layer.update()
                for domain_id in all_created_domain_ids:
                    domain = molecule.domains.get(domain_id)
                    if domain and domain.object:
                        domain.object.matrix_world = delta @ domain.object.matrix_world
                        # Refresh the reset-transform baseline to the moved pose.
                        domain.object["initial_matrix_local"] = [
                            list(row) for row in domain.object.matrix_local]
                bpy.context.view_layer.update()

        # Update group memberships BEFORE rebuilding outliner
        # IMPORTANT: We keep the chain in the group, not individual domains
        # The hierarchy will show domains under the chain.
        #
        # The chain ROW stays a member, but the chain's single object that was
        # parented to the puppet controller has just been deleted and replaced
        # by the new split-piece objects (parented to the molecule). Unless we
        # re-parent those pieces to the controller, moving the puppet moves only
        # the chains that were never split - the split pieces stay put. Re-parent
        # each new piece with keep-transform, exactly as create_puppet does, so
        # the whole chain follows the puppet again.
        if chain_groups:
            print(f"Found {len(chain_groups)} groups containing the chain")
            for puppet_item in chain_groups:
                controller = bpy.data.objects.get(puppet_item.controller_object_name)
                if controller is None:
                    print(f"  Puppet '{puppet_item.name}' has no controller object; "
                          f"cannot re-parent split pieces")
                    continue
                for domain_id in all_created_domain_ids:
                    domain = molecule.domains.get(domain_id)
                    obj = domain.object if domain else None
                    if obj is None or obj.parent == controller:
                        continue
                    world = obj.matrix_world.copy()
                    obj.parent = controller
                    obj.matrix_world = world  # keep_transform: stay put on re-parent
                    print(f"  Re-parented split piece '{obj.name}' to controller "
                          f"'{controller.name}'")

        # Rebuild outliner to show new domains and updated groups
        build_outliner_hierarchy(context)
        
        # No need to update domain group memberships individually
        # They will be shown under their parent chain in the group view
        
        # Log final state
        print(f"Domains after split:")
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id') and str(domain.chain_id) in chain_tokens:
                print(f"  Domain {domain_id}: range={domain.start}-{domain.end}, name={domain.name}")
        
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
        
        # The public domain UI is one-based. Imported terminal caps can carry
        # residue 0 (for example 1ATN Chain A's ACE cap), but they must not
        # become standalone complementary domains when the user splits 1-N.
        return normalize_domain_residue_range((chain_start, chain_end))
    
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
        
        print(f"Auto-generated domains: {domains}")
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
        scene_manager.refresh_domain_refs_before_destructive_op(molecule_id)
        
        # Calculate merged domain range using actual domains
        merged_start = actual_domain_items[0].domain_start
        merged_end = actual_domain_items[-1].domain_end
        merged_name = f"Residues {merged_start}-{merged_end}"
        
        # Collect groups that contain any of the domains being merged
        affected_groups = {}  # group_id -> set of domain outliner IDs in this group
        # Use the actual domain IDs, not the reference IDs
        domain_outliner_ids = [item.item_id for item in actual_domain_items]
        
        for group_item in scene.outliner_items:
            if group_item.item_type == 'PUPPET' and group_item.puppet_memberships:
                member_ids = set(group_item.puppet_memberships.split(','))
                domains_in_group = set(domain_outliner_ids) & member_ids
                if domains_in_group:
                    affected_groups[group_item.item_id] = domains_in_group
                    print(f"Group '{group_item.name}' contains {len(domains_in_group)} of the merging domains")
        
        # parent_chain.chain_id is the chain *index* from the outliner while
        # domains store the chain *letter*; chain_match_tokens bridges both
        # forms (the single matching rule lives in chain_utils).
        chain_tokens = chain_match_tokens(molecule, parent_chain.chain_id)

        # Remove the old domains (use actual domain items)
        for domain_item in actual_domain_items:
            # Find the actual domain in molecule
            domain_to_remove = None
            for domain_id, domain in molecule.domains.items():
                if (hasattr(domain, 'start') and hasattr(domain, 'end') and
                    domain.start == domain_item.domain_start and
                    domain.end == domain_item.domain_end and
                    str(domain.chain_id) in chain_tokens):
                    domain_to_remove = domain_id
                    break

            if domain_to_remove:
                domain = molecule.domains[domain_to_remove]
                # Remove the domain's Blender object if it exists
                if hasattr(domain, 'object') and domain.object:
                    bpy.data.objects.remove(domain.object, do_unlink=True)
                # Remove from molecule's domains
                del molecule.domains[domain_to_remove]
                print(f"Removed domain: {domain_item.name}")
        
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
            print(f"Created merged domain: {merged_name}")
            
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
                print("Domains cover entire chain - will add chain to groups")
                
                # The chain might already be in the groups, but we'll ensure it's there
                for group_id in affected_groups.keys():
                    # Find the group
                    group_item = None
                    for item in scene.outliner_items:
                        if item.item_type == 'PUPPET' and item.item_id == group_id:
                            group_item = item
                            break
                    
                    if group_item:
                        # Get current members
                        current_members = set(group_item.puppet_memberships.split(',')) if group_item.puppet_memberships else set()
                        
                        # Add the chain if not already present
                        chain_outliner_id = f"{molecule_id}_chain_{parent_chain.chain_id}"
                        if chain_outliner_id not in current_members:
                            current_members.add(chain_outliner_id)
                            # Update the group
                            group_item.puppet_memberships = ','.join(filter(None, current_members))
                            print(f"Added chain to group '{group_item.name}'")
                        else:
                            print(f"Chain already in group '{group_item.name}'")
        else:
            # The source domains are already gone at this point, but there is no
            # merged domain to take their place and nothing below applies to a
            # failed merge - covers_entire_chain is only bound in the branch
            # above. Stop here rather than fall through.
            self.report({'ERROR'}, "Failed to create merged domain")
            build_outliner_hierarchy(context)
            return {'CANCELLED'}

        # Rebuild outliner
        build_outliner_hierarchy(context)
        
        # Update chain's group membership if needed
        if affected_groups and covers_entire_chain:
            for item in context.scene.outliner_items:
                if item.item_id == f"{molecule_id}_chain_{parent_chain.chain_id}":
                    # Update chain's group membership
                    item_groups = set(item.puppet_memberships.split(',')) if item.puppet_memberships else set()
                    item_groups.update(affected_groups.keys())
                    item.puppet_memberships = ','.join(filter(None, item_groups))
                    print(f"Updated chain group memberships")
                    break
        
        return {'FINISHED'}


class PROTEINBLENDER_OT_rename_domain(VisualEditMixin, Operator):
    """Rename and restyle a domain (or a chain copy) from the Protein Outliner"""
    bl_idname = "proteinblender.rename_domain"
    bl_label = "Edit Domain"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(
        name="New Name",
        description="New name for the chain or domain"
    )

    # Outliner item_id to rename, and its type. When empty, invoke() falls back
    # to the selected CHAIN/DOMAIN row so the operator still works from a menu.
    target_item_id: StringProperty()
    item_type: StringProperty(default="")
    # Back-compat alias: older callers passed the domain_id directly.
    domain_id: StringProperty()

    def _find_row(self, scene, item_id):
        return next((it for it in scene.outliner_items
                     if it.item_id == item_id), None)

    def _selected_row(self, scene):
        return next((it for it in scene.outliner_items
                     if it.is_selected and it.item_type in ('CHAIN', 'DOMAIN')),
                    None)

    def visual_row(self, context):
        """The row the Visual Set-up block edits, if the target has one."""
        target_id = self.target_item_id or self.domain_id
        return self._find_row(context.scene, target_id) if target_id else None

    def visual_objects(self, context):
        """The objects to restyle, row or no row.

        A full-chain auto-domain has no DOMAIN row of its own - it renders as
        the CHAIN row - so the usual row-to-objects resolution comes back
        empty for it. It is still a domain with an object to restyle, and the
        rename half of this dialog already works off the bare id, so the
        Visual Set-up half resolves the same way rather than silently doing
        nothing.
        """
        objects = super().visual_objects(context)
        if objects:
            return objects

        target_id = self.target_item_id or self.domain_id
        if not target_id:
            return []
        for molecule in ProteinBlenderScene.get_instance().molecules.values():
            domain = getattr(molecule, 'domains', {}).get(target_id)
            if domain is not None and getattr(domain, 'object', None):
                return [domain.object]
        return []

    def invoke(self, context, event):
        scene = context.scene
        wanted = self.target_item_id or self.domain_id
        row = self._find_row(scene, wanted) if wanted else self._selected_row(scene)
        if row is not None:
            self.target_item_id = row.item_id
            if not self.item_type:
                self.item_type = row.item_type
            self.new_name = row.name
        elif wanted:
            # A domain id with no outliner row (a full-chain auto-domain renders
            # as its CHAIN row, not its own DOMAIN row) - still renameable.
            self.target_item_id = wanted
            if not self.item_type:
                self.item_type = 'DOMAIN'
        else:
            self.report({'WARNING'}, "Please select a chain or domain to rename")
            return {'CANCELLED'}
        self.begin_visual_edit(context)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def check(self, context):
        """Re-lay-out when a field changes: the force-field spacing slider
        only exists while the toggle is on."""
        return True

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")
        self.draw_visual_setup(layout, context)

    def _rename_chain(self, scene, item):
        """Persist a chain rename on the molecule's list item as JSON so it
        survives the outliner rebuild and a .blend save."""
        import json
        list_item = next((it for it in scene.molecule_list_items
                          if it.identifier == item.parent_id), None)
        if list_item is None:
            return
        try:
            names = json.loads(list_item.chain_custom_names) if list_item.chain_custom_names else {}
        except Exception:
            names = {}
        key = str(item.chain_id)
        if self.new_name.strip():
            names[key] = self.new_name
        else:
            names.pop(key, None)  # blank restores the default Chain <letter>
        list_item.chain_custom_names = json.dumps(names)

    def _rename_domain(self, domain_id):
        """Persist a domain rename on the wrapper so it survives save/load."""
        scene_manager = ProteinBlenderScene.get_instance()
        for molecule in scene_manager.molecules.values():
            domain = getattr(molecule, 'domains', {}).get(domain_id)
            if domain is not None:
                domain.name = self.new_name
                if hasattr(molecule, '_mirror_domains_to_property_group'):
                    try:
                        molecule._mirror_domains_to_property_group()
                    except Exception:
                        pass
                break

    def execute(self, context):
        scene = context.scene
        target_id = self.target_item_id or self.domain_id
        if not target_id:
            row = self._selected_row(scene)
            if row is None:
                self.report({'ERROR'}, "No chain or domain to rename")
                self.end_visual_edit()
                return {'CANCELLED'}
            target_id = row.item_id
        row = self._find_row(scene, target_id)
        item_type = self.item_type or (row.item_type if row else 'DOMAIN')

        # Persist to the underlying model first (chains and domains store their
        # names in different places). A full-chain auto-domain has no DOMAIN row
        # (it shows as the CHAIN row), so the domain path works off the id alone.
        if item_type == 'CHAIN':
            if row is None:
                self.report({'ERROR'}, "Chain not found")
                self.end_visual_edit()
                return {'CANCELLED'}
            self._rename_chain(scene, row)
        else:
            self._rename_domain(target_id)

        # Colour / style / force field, before the rebuild: the block resolves
        # its objects through the row, and the rebuild replaces every row.
        # Untouched fields apply nothing - see commit_visual_edit.
        self.commit_visual_edit(context)
        self.end_visual_edit()

        # Rebuild the outliner so the rename reaches every derived field, not
        # just the row label. Rows carry a pre-rendered `tooltip` built from
        # the row name, and writing `it.name` alone left the tooltip quoting
        # the old name until some unrelated action happened to trigger a
        # rebuild. The rebuild re-derives both from the model, where the rename
        # has already been persisted (chain_custom_names / domain.name), so it
        # preserves the new name rather than reverting it.
        build_outliner_hierarchy(context)

        # A full-chain auto-domain has no DOMAIN row of its own, so the rebuild
        # has nothing to re-derive for it; reflect the label directly.
        if self.new_name.strip():
            for it in scene.outliner_items:
                if it.item_id == target_id and it.name != self.new_name:
                    it.name = self.new_name

        # Redraw UI. context.area is None when called from a script/MCP/
        # headless context — fall back to tagging every 3D view.
        if context.area is not None:
            context.area.tag_redraw()
        else:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in ("VIEW_3D", "PROPERTIES"):
                        area.tag_redraw()
        return {'FINISHED'}

    def cancel(self, context):
        # Colour and style edits were applied live and stay applied; this only
        # lets go of the dialog so a stale instance cannot take a later
        # property callback.
        self.end_visual_edit()


# Operator classes to register
