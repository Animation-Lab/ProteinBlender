import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene

# Ensure domain properties are registered
from ..core.domain import ensure_domain_properties_registered
ensure_domain_properties_registered()

class MOLECULE_PB_OT_create_domain(Operator):
    bl_idname = "molecule.create_domain"
    bl_label = "Create Domain"
    bl_description = "Create a new domain from the selected residue range"
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        # get the chain_id as an int
        chain_id_char = molecule.chain_mapping.get(int(scene.new_domain_chain) if scene.new_domain_chain.isdigit() else scene.new_domain_chain, str(scene.new_domain_chain))
        print(f"Checking overlap for chain {chain_id_char} ({scene.new_domain_start}-{scene.new_domain_end})")
        check_overlap = molecule._check_domain_overlap(
            chain_id_char, 
            scene.new_domain_start, 
            scene.new_domain_end
        )

        if check_overlap:
            self.report({'ERROR'}, "Domain overlaps with existing domain")
            return {'CANCELLED'}
        
        # Log the domain creation
        print(f"Creating primary domain for chain {scene.new_domain_chain} ({scene.new_domain_start}-{scene.new_domain_end})")
        
        # Create the domain with values from the UI
        domain_id = molecule.create_domain(
            chain_id=scene.new_domain_chain,  # Use the chain selected in UI
            start=scene.new_domain_start,  # Use the start value from UI
            end=scene.new_domain_end  # Use the end value from UI
        )
        
        if domain_id is None:
            self.report({'ERROR'}, "Failed to create domain")
            return {'CANCELLED'}
            
        # Automatically expand the new domain and set initial pivot
        if domain_id in molecule.domains:
            domain = molecule.domains[domain_id]
            
            if domain.object:
                # Set domain_expanded property
                try:
                    domain.object["domain_expanded"] = True
                    if hasattr(domain, "color"):
                        domain.object.domain_color = domain.color
                except:
                    if not hasattr(domain.object, "domain_expanded"):
                        bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
                    domain.object.domain_expanded = True
                    if hasattr(domain, "color") and hasattr(domain.object, "domain_color"):
                        domain.object.domain_color = domain.color
                
                # --- Set the initial pivot using the new robust method --- 
                print(f"Setting initial pivot for new domain {domain.name}")
                start_aa_pos = _find_residue_alpha_carbon_pos(context, molecule, domain, residue_target='START')
                
                if start_aa_pos:
                    if not _set_domain_origin_and_update_matrix(context, domain, start_aa_pos):
                        self.report({'WARNING'}, f"Could not set initial pivot for domain {domain.name}. Origin remains at default.")
                else:
                    self.report({'WARNING'}, f"Could not find Start AA Cα for domain {domain.name}. Origin remains at default.")
                # --- End initial pivot setting --- 
                 
        return {'FINISHED'}
    
    # --- Remove old pivot setting methods --- 
    # (set_pivot_to_alpha_carbon, _get_possible_chain_ids, 
    #  _check_numeric_atom_names, _find_alpha_carbon_numeric, 
    #  _find_alpha_carbon_textual are no longer needed here)

class MOLECULE_PB_OT_update_domain(Operator):
    bl_idname = "molecule.update_domain"
    bl_label = "Update Domain"
    bl_description = "Update the selected domain's parameters"
    
    domain_id: StringProperty()
    action: StringProperty(default='UPDATE')
    chain_id: StringProperty(default='')
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Handle different actions
        if self.action == 'SET_CHAIN':
            # Get the mapped chain
            try:
                author_chain_id = molecule.get_author_chain_id(int(self.chain_id) if self.chain_id.isdigit() else self.chain_id)
                
                # If chain has changed, update residue range to valid values for this chain
                if author_chain_id in molecule.chain_residue_ranges:
                    min_res, max_res = molecule.chain_residue_ranges[author_chain_id]
                    
                    # Check for overlaps
                    if molecule._check_domain_overlap(
                        self.chain_id, min_res, max_res,
                        exclude_domain_id=self.domain_id
                    ):
                        self.report({'ERROR'}, f"Cannot change chain - would overlap with existing domain")
                        return {'CANCELLED'}
                    
                    # Proceed with update
                    domain.chain_id = author_chain_id
                    domain.start = min_res
                    domain.end = max_res
                    return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Error updating chain: {str(e)}")
                return {'CANCELLED'}
        else:
            # Use domain properties directly instead of scene properties
            chain_id = domain.chain_id
            start = domain.start
            end = domain.end
            
            # Check if the residue range is valid
            if start > end:
                self.report({'ERROR'}, f"Invalid residue range: {start} > {end}")
                return {'CANCELLED'}
            
            # Check for overlaps with other domains (exclude this domain)
            if molecule._check_domain_overlap(
                chain_id, 
                start, 
                end,
                exclude_domain_id=self.domain_id
            ):
                self.report({'ERROR'}, f"Domain overlaps with existing domain in chain {chain_id}")
                return {'CANCELLED'}
                
            # Update the domain
            success = molecule.update_domain(
                domain_id=self.domain_id,
                chain_id=chain_id,
                start=start,
                end=end
            )
            
            if not success:
                self.report({'ERROR'}, "Failed to update domain")
                return {'CANCELLED'}
        
        return {'FINISHED'}

class MOLECULE_PB_OT_delete_domain(Operator):
    bl_idname = "molecule.delete_domain"
    bl_label = "Delete Domain"
    bl_description = "Delete the selected domain"
    
    domain_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain to be deleted
        if self.domain_id not in molecule.domains:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Delete the domain and get the ID of the domain that replaced it (if any)
        new_domain_id = molecule.delete_domain(self.domain_id)
        
        # If there's a replacement domain, select it to maintain UI continuity
        if new_domain_id and new_domain_id in molecule.domains:
            domain = molecule.domains.get(new_domain_id)
            if domain and domain.object:
                # Make the domain object the active object to help with UI continuity
                context.view_layer.objects.active = domain.object
        
        return {'FINISHED'}

class MOLECULE_PB_OT_keyframe_domain_location(Operator):
    bl_idname = "molecule.keyframe_domain_location"
    bl_label = "Keyframe Location"
    bl_description = "Add keyframe for domain location"
    
    def execute(self, context):
        obj = context.active_object
        if obj:
            obj.keyframe_insert(data_path="location")
        return {'FINISHED'}

class MOLECULE_PB_OT_keyframe_domain_rotation(Operator):
    bl_idname = "molecule.keyframe_domain_rotation"
    bl_label = "Keyframe Rotation"
    bl_description = "Add keyframe for domain rotation"
    
    def execute(self, context):
        obj = context.active_object
        if obj:
            obj.keyframe_insert(data_path="rotation_euler")
        return {'FINISHED'}

class MOLECULE_PB_OT_toggle_domain_expanded(Operator):
    bl_idname = "molecule.toggle_domain_expanded"
    bl_label = "Toggle Domain Expanded"
    bl_description = "Toggle domain expanded state and load its values"
    
    domain_id: StringProperty()
    is_expanded: BoolProperty()
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain or not domain.object:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Toggle expanded state
        try:
            # Try to set the property directly
            domain.object["domain_expanded"] = self.is_expanded
        except:
            # If that fails, ensure the property exists first
            if not hasattr(domain.object, "domain_expanded"):
                # Register the property if needed
                bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
            # Then set it
            domain.object.domain_expanded = self.is_expanded
        
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_ui_values(Operator):
    bl_idname = "molecule.update_domain_ui_values"
    bl_label = "Update Domain UI"
    bl_description = "Update UI values to match domain values"
    bl_options = {'INTERNAL'}
    
    domain_id: StringProperty()
    
    def execute(self, context):
        # This operator is largely obsolete now since we're using direct domain properties
        # It's kept for backward compatibility but doesn't need to do anything
        print(f"UI values updated for domain {self.domain_id}")
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_color(Operator):
    bl_idname = "molecule.update_domain_color"
    bl_label = "Update Domain Color"
    bl_description = "Update the color of the selected domain"
    
    domain_id: StringProperty()
    color: FloatVectorProperty(
        size=4,
        min=0.0, max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the molecule and domain
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Get color
        color = scene.domain_color
        if hasattr(self, "color") and self.color[0] >= 0:  # Check if color parameter was provided
            color = self.color
            
        print(f"1 Updating color for domain {self.domain_id} to {color}")
        # Update domain color
        success = molecule.update_domain_color(self.domain_id, color)
        if not success:
            self.report({'ERROR'}, "Failed to update domain color")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_style(Operator):
    bl_idname = "molecule.update_domain_style"
    bl_label = "Update Domain Style"
    bl_description = "Change the visualization style of the domain"
    
    domain_id: StringProperty()
    style: StringProperty(default="ribbon")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain or not domain.object:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Update the domain's style
        try:
            print(f"Operator: Changing domain style for {self.domain_id} to {self.style}")
            
            # Update the style in the node network
            if domain.node_group:
                # Find style node
                style_node = None
                for node in domain.node_group.nodes:
                    if (node.bl_idname == 'GeometryNodeGroup' and 
                        node.node_tree and 
                        "Style" in node.node_tree.name):
                        style_node = node
                        break
                
                if style_node:
                    # Get the style node name from the style value
                    from ..utils.molecularnodes.blender.nodes import styles_mapping, append, swap
                    if self.style in styles_mapping:
                        style_node_name = styles_mapping[self.style]
                        # Swap the style node
                        swap(style_node, append(style_node_name))
                        
                        # Update the domain's style property
                        domain.style = self.style
                        
                        # Try to set the domain_style property, handling possible errors
                        try:
                            domain.object.domain_style = self.style
                        except (AttributeError, TypeError):
                            # Fall back to custom property if needed
                            domain.object["domain_style"] = self.style
                        
                        return {'FINISHED'}
                    else:
                        self.report({'ERROR'}, f"Invalid style: {self.style}")
                        return {'CANCELLED'}
                else:
                    self.report({'ERROR'}, "Style node not found in domain node group")
                    return {'CANCELLED'}
            else:
                self.report({'ERROR'}, "Domain node group not found")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Error updating domain style: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

def create_pivot_helper(context, location):
    # Create empty
    bpy.ops.object.empty_add(type='ARROWS', location=location)
    helper = context.active_object
    helper.name = "PivotHelper"
    
    # Make sure it's selectable and selected
    helper.hide_select = False
    helper.select_set(True)
    context.view_layer.objects.active = helper
    
    # Set display properties
    helper.empty_display_size = 1.0  # Adjust size as needed
    helper.show_in_front = True  # Make sure it's visible
    
    return helper

class MOLECULE_PB_OT_toggle_pivot_edit(Operator):
    bl_idname = "molecule.toggle_pivot_edit"
    bl_label = "Move Pivot"
    bl_description = "Move the pivot point (origin) of this domain"
    
    domain_id: StringProperty()
    _pivot_edit_active = {}  # Class variable to track pivot edit state per domain
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain or not domain.object:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Toggle pivot edit mode for this domain
        is_active = self._pivot_edit_active.get(self.domain_id, False)
        
        if not is_active:
            # Enter pivot edit mode
            self._pivot_edit_active[self.domain_id] = {
                'cursor_location': list(context.scene.cursor.location),
                'previous_tool': context.workspace.tools.from_space_view3d_mode(context.mode, create=False).idname,
                'mesh_location': domain.object.location.copy(),
                'mesh_rotation': domain.object.rotation_euler.copy(),
                'transform_orientation': context.scene.transform_orientation_slots[0].type,
                'pivot_point': context.tool_settings.transform_pivot_point
            }
            
            # Deselect everything first
            bpy.ops.object.select_all(action='DESELECT')
            
            # Create and set up helper empty
            helper = create_pivot_helper(context, domain.object.location)
            self._pivot_edit_active[self.domain_id]['helper'] = helper
            
            # Set up transform settings
            context.scene.transform_orientation_slots[0].type = 'GLOBAL'
            context.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
            
            # Switch to move tool to ensure gizmo is active
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = context.copy()
                            override['area'] = area
                            override['region'] = region
                            with context.temp_override(**override):
                                bpy.ops.wm.tool_set_by_id(name="builtin.move")
                    
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.show_gizmo = True
                            space.show_gizmo_tool = True
                            space.show_gizmo_object_translate = True
            
            domain.object["is_pivot_editing"] = True # Set flag on object
            
            self.report({'INFO'}, "Use the transform gizmo to position the new pivot point. Click 'Move Pivot' again to apply.")
            
        else:
            # Exit pivot edit mode
            stored_state = self._pivot_edit_active[self.domain_id]
            helper = stored_state['helper']
            
            # Use helper location as new pivot
            context.scene.cursor.location = helper.location
            
            # Select the domain object and set origin
            bpy.ops.object.select_all(action='DESELECT')
            domain.object.select_set(True)
            context.view_layer.objects.active = domain.object
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

            # Update the stored initial matrix after setting the new origin
            if domain.object:
                 domain.object["initial_matrix_local"] = [list(row) for row in domain.object.matrix_local]
                 print(f"Updated initial matrix for {domain.name} after pivot move.")
            
            # Delete the helper object
            bpy.ops.object.select_all(action='DESELECT')
            helper.select_set(True)
            context.view_layer.objects.active = helper
            bpy.ops.object.delete()
            
            # Restore previous state
            context.scene.cursor.location = stored_state['cursor_location']
            context.scene.transform_orientation_slots[0].type = stored_state['transform_orientation']
            context.tool_settings.transform_pivot_point = stored_state['pivot_point']
            
            del self._pivot_edit_active[self.domain_id]
            domain.object["is_pivot_editing"] = False # Unset flag on object
            self.report({'INFO'}, "Pivot point updated")
        
        return {'FINISHED'}

class MOLECULE_PB_OT_set_parent_domain(Operator):
    bl_idname = "molecule.set_parent_domain"
    bl_label = "Set Parent Domain"
    bl_description = "Set a parent domain for this domain"
    
    domain_id: StringProperty(description="The ID of the domain to set parent for")
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            layout.label(text="No molecule selected")
            return
            
        # Get the domain to be parented
        if self.domain_id not in molecule.domains:
            layout.label(text="Domain not found")
            return
        
        domain = molecule.domains[self.domain_id]
        
        # Create a box for the domain info
        box = layout.box()
        box.label(text=f"Setting parent for: {domain.name}")
        
        # Create a list of potential parent domains (excluding self and children)
        # First get all domains that aren't this one
        potential_parents = [(domain_id, d) for domain_id, d in molecule.domains.items() 
                           if domain_id != self.domain_id]
        
        # Add option to clear parent
        no_parent_row = layout.row()
        clear_op = no_parent_row.operator(
            "molecule.update_parent_domain",
            text="No Parent (Clear Parent)"
        )
        clear_op.domain_id = self.domain_id
        clear_op.parent_domain_id = ""  # Empty string means no parent
        
        layout.separator()
        layout.label(text="Select Parent Domain:")
        
        # List all potential parents
        for parent_id, parent_domain in potential_parents:
            row = layout.row()
            # Highlight current parent
            is_current_parent = (hasattr(domain, 'parent_domain_id') and 
                               domain.parent_domain_id == parent_id)
            
            parent_op = row.operator(
                "molecule.update_parent_domain",
                text=f"{parent_domain.name}: Chain {parent_domain.chain_id} ({parent_domain.start}-{parent_domain.end})",
                depress=is_current_parent
            )
            parent_op.domain_id = self.domain_id
            parent_op.parent_domain_id = parent_id
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
        
    def execute(self, context):
        # This is just a dialog launcher, the actual work is done by MOLECULE_PB_OT_update_parent_domain
        return {'FINISHED'}

class MOLECULE_PB_OT_update_parent_domain(Operator):
    bl_idname = "molecule.update_parent_domain"
    bl_label = "Update Parent Domain"
    bl_description = "Update the parent domain of this domain"
    
    domain_id: StringProperty(description="The ID of the domain to update parent for")
    parent_domain_id: StringProperty(description="The ID of the new parent domain (empty for no parent)")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        if not self.domain_id:
            self.report({'ERROR'}, "No domain ID specified")
            return {'CANCELLED'}
            
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, f"Domain not found: {self.domain_id}")
            return {'CANCELLED'}
            
        # Check for circular parenting
        if self.parent_domain_id and self._would_create_circular_parenting(molecule, self.domain_id, self.parent_domain_id):
            self.report({'ERROR'}, "Setting this parent would create a circular dependency.")
            return {'CANCELLED'}
            
        # Update the parent domain ID
        domain.set_parent(self.parent_domain_id if self.parent_domain_id else None)
        
        # Update the object hierarchy in Blender
        if domain.object:
            parent_object = None
            if self.parent_domain_id:
                parent_domain = molecule.domains.get(self.parent_domain_id)
                if parent_domain:
                    parent_object = parent_domain.object
                else:
                    # If parent domain doesn't exist, default to main molecule object
                    parent_object = molecule.object
            else:
                # No parent, so parent to the main molecule object
                parent_object = molecule.object
                
            if parent_object and domain.object.parent != parent_object:
                # Keep transform when parenting
                orig_matrix = domain.object.matrix_world.copy()
                domain.object.parent = parent_object
                domain.object.matrix_world = orig_matrix

        return {'FINISHED'}

    def _would_create_circular_parenting(self, molecule, child_id, parent_id):
        """Check if setting parent_id as the parent of child_id would create a loop."""
        # Start from the potential parent and traverse up the hierarchy
        current_id = parent_id
        visited = {child_id}  # Start with the child to detect immediate loop
        
        while current_id:
            if current_id in visited:
                # We found the child_id in the ancestor chain - loop detected
                return True
            
            visited.add(current_id)
            
            # Get the next parent
            current_domain = molecule.domains.get(current_id)
            if not current_domain:
                # Reached a domain that doesn't exist (shouldn't happen ideally)
                break
                
            # Get the parent ID from the domain object itself
            current_id = getattr(current_domain, 'parent_domain_id', None)

        # No loop found
        return False

# New Operator Class for Resetting Transform
class MOLECULE_PB_OT_reset_domain_transform(Operator):
    bl_idname = "molecule.reset_domain_transform"
    bl_label = "Reset Domain Transform"
    bl_description = "Reset the location, rotation, and scale of this domain object to its initial state"
    
    domain_id: StringProperty()
    
    @classmethod
    def poll(cls, context):
        # Check if a molecule and the domain object exist
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule or not molecule.domains:
            return False
        # We don't know the domain_id here, so can't check specific domain object
        return True 

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, f"Domain not found: {self.domain_id}")
            return {'CANCELLED'}
            
        if not domain.object:
            self.report({'ERROR'}, f"Domain object not found for {self.domain_id}")
            return {'CANCELLED'}

        # Attempt to restore the initial matrix
        if "initial_matrix_local" in domain.object:
            try:
                # Retrieve the stored matrix (list of lists)
                stored_matrix_list = domain.object["initial_matrix_local"]
                # Convert back to a Matrix object
                from mathutils import Matrix
                initial_matrix = Matrix(stored_matrix_list)
                # --- DEBUG PRINT ADDED ---
                print(f"DEBUG: Resetting {domain.name}. Stored initial_matrix_local:\n{initial_matrix}")
                # --- END DEBUG --- 
                # Apply the matrix
                domain.object.matrix_local = initial_matrix
                self.report({'INFO'}, f"Reset transform for domain {domain.name} using stored matrix.")
            except Exception as e:
                self.report({'ERROR'}, f"Failed to restore initial matrix for {domain.name}: {e}. Falling back to default reset.")
                # Fallback to simple reset if stored matrix is invalid or missing
                domain.object.location = (0, 0, 0)
                domain.object.rotation_euler = (0, 0, 0)
                domain.object.scale = (1, 1, 1)
        else:
            # Fallback for domains created before this feature was added
            self.report({'WARNING'}, f"No initial matrix found for domain {domain.name}. Resetting to default transforms.")
            domain.object.location = (0, 0, 0)
            domain.object.rotation_euler = (0, 0, 0)
            domain.object.scale = (1, 1, 1)
        
        return {'FINISHED'}

# Helper function to find Alpha Carbon position
def _find_residue_alpha_carbon_pos(context, molecule, domain, residue_target):
    """
    Finds the 3D coordinates of the Alpha Carbon (CA) for a specific residue.
    For START, searches forward from domain.start until a CA is found.
    For END, searches backward from domain.end until a CA is found.

    Returns:
        mathutils.Vector: The coordinates if found, otherwise None.
    """
    try:
        mol_obj = molecule.object
        if not mol_obj or not domain.object or not hasattr(mol_obj.data, "attributes"):
            print("Error: Molecule object, domain object, or attributes not found.")
            return None

        attrs = mol_obj.data.attributes
        print(f"DEBUG: Available attributes on {mol_obj.name}.data: {list(attrs.keys())}") # Print available attributes

        # Determine residue number attribute
        residue_attr_name = None
        if "residue_number" in attrs:
            residue_attr_name = "residue_number"
        elif "res_id" in attrs:
            residue_attr_name = "res_id"
        else:
            print("Error: Residue number attribute ('residue_number' or 'res_id') not found.")
            return None

        # Check for required attributes
        required_attrs = ["atom_name", "chain_id", residue_attr_name, "position"]
        if not all(attr in attrs for attr in required_attrs):
            print(f"Error: Missing one or more required attributes: {required_attrs}")
            return None

        # Get domain info
        domain_chain_id = domain.chain_id
        start_res = domain.start
        end_res = domain.end
        print(f"Searching for Cα for {residue_target} in chain '{domain_chain_id}', range {start_res}-{end_res}")

        # --- Helper functions nested inside for clarity ---
        def get_possible_chain_ids(chain_id):
            search_ids = [chain_id]
            if isinstance(chain_id, str) and chain_id.isalpha():
                try:
                    numeric_chain = ord(chain_id.upper()) - ord('A')
                    search_ids.append(str(numeric_chain))
                    search_ids.append(numeric_chain)
                except Exception: pass
            elif isinstance(chain_id, (str, int)) and str(chain_id).isdigit():
                try:
                    int_chain_id = int(chain_id)
                    alpha_chain = chr(int_chain_id + ord('A'))
                    search_ids.append(alpha_chain)
                    search_ids.append(int_chain_id)
                    search_ids.append(str(int_chain_id))
                except Exception: pass
            return list(set(filter(None.__ne__, search_ids)))
        # --- End of nested helpers ---

        search_chain_ids = get_possible_chain_ids(domain_chain_id)
        print(f"Possible chain IDs to search: {search_chain_ids}")

        # Get attribute data arrays
        atom_names_data = attrs["atom_name"].data # Keep for potential future use, but not for CA check
        chain_ids_data = attrs["chain_id"].data
        res_nums_data = attrs[residue_attr_name].data
        positions_data = attrs["position"].data
        # --- Get the correct attribute for Cα --- 
        is_alpha_carbon_attr = attrs.get("is_alpha_carbon")
        if not is_alpha_carbon_attr:
            print("Error: 'is_alpha_carbon' attribute not found.")
            return None
        is_alpha_carbon_data = is_alpha_carbon_attr.data
        # --- End Get Attribute --- 

        # Determine search range based on target
        residue_search_range = None
        if residue_target == 'START':
            residue_search_range = range(start_res, end_res + 1)
        elif residue_target == 'END':
            residue_search_range = range(end_res, start_res - 1, -1) # Iterate backwards
        else:
            print(f"Error: Invalid residue_target '{residue_target}'")
            return None

        print(f"Residue search order: {list(residue_search_range)}")

        # --- Search for the first CA encountered in the specified range order ---
        for target_res_num in residue_search_range:
            print(f"Checking residue {target_res_num}...")
            # Iterate through all atoms in the structure
            for atom_idx in range(len(positions_data)):
                try:
                    # Check if this atom belongs to the current target residue and chain
                    atom_res_num = res_nums_data[atom_idx].value
                    if atom_res_num != target_res_num:
                        continue 
                    
                    chain_id_val = chain_ids_data[atom_idx].value
                    in_target_chain = False
                    if chain_id_val in search_chain_ids:
                        in_target_chain = True
                        
                    if not in_target_chain:
                        continue 
                        
                    # --- Check using the is_alpha_carbon attribute --- 
                    if is_alpha_carbon_data[atom_idx].value: # Check the boolean value
                        # Found the first CA in the search order!
                        pos = positions_data[atom_idx].vector
                        print(f"Found Cα for target '{residue_target}' in residue {target_res_num} at index {atom_idx} using 'is_alpha_carbon' attribute, position {pos}")
                        return pos # Return the position
                    # --- End Check --- 
                        
                except (AttributeError, IndexError, ValueError, TypeError) as e_inner:
                    continue # Skip malformed atom data
            
            # If we finished checking all atoms for target_res_num and didn't find CA, continue to the next residue in the range
            print(f"No Cα found in residue {target_res_num} (checked 'is_alpha_carbon').")

        # If we finish the loop without finding any CA in the entire range
        print(f"Error: No Alpha Carbon (CA) found using 'is_alpha_carbon' attribute within range {start_res}-{end_res} for chain {domain_chain_id}.")
        return None

    except Exception as e:
        print(f"Error in _find_residue_alpha_carbon_pos: {e}")
        import traceback
        traceback.print_exc()
        return None

# --- New Helper: Set Origin and Update Matrix ---
def _set_domain_origin_and_update_matrix(context, domain, target_pos):
    """Sets the domain object's origin to target_pos and updates initial_matrix_local."""
    if not domain or not domain.object or target_pos is None:
        print("Error: Invalid domain, object, or target position for setting origin.")
        return False

    orig_cursor_loc = context.scene.cursor.location.copy()
    try:
        # Set cursor to target position
        context.scene.cursor.location = target_pos

        # Ensure the domain object is selected and active
        bpy.ops.object.select_all(action='DESELECT')
        domain.object.select_set(True)
        context.view_layer.objects.active = domain.object

        # Set origin to cursor
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

        # Update the stored initial matrix
        domain.object["initial_matrix_local"] = [list(row) for row in domain.object.matrix_local]
        print(f"Set origin and updated initial matrix for {domain.name}.")
        return True

    except Exception as e:
        print(f"Error in _set_domain_origin_and_update_matrix: {e}")
        return False
    finally:
        # Restore cursor location
        context.scene.cursor.location = orig_cursor_loc
# --- End New Helper --- 

# --- New Operator ---
class MOLECULE_PB_OT_snap_pivot_to_residue(Operator):
    """Snaps the domain's pivot point (origin) to the Alpha Carbon of the start or end residue."""
    bl_idname = "molecule.snap_pivot_to_residue"
    bl_label = "Snap Pivot to Residue"
    bl_description = "Set domain pivot to the Cα atom of the start or end residue"
    bl_options = {'REGISTER', 'UNDO'}

    domain_id: StringProperty(description="The ID of the domain to modify")
    target_residue: EnumProperty(
        name="Target Residue",
        description="Which residue's Alpha Carbon to snap the pivot to",
        items=[('START', 'Start', 'Snap to the first residue of the domain'),
               ('END', 'End', 'Snap to the last residue of the domain')],
        default='START'
    )

    @classmethod
    def poll(cls, context):
        # Check if a molecule and domain are selected/valid
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        # Cannot check domain_id here as it's instance-specific
        return molecule is not None

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)

        if not molecule:
            self.report({'ERROR'}, "No molecule selected.")
            return {'CANCELLED'}

        domain = molecule.domains.get(self.domain_id)
        if not domain or not domain.object:
            self.report({'ERROR'}, f"Domain '{self.domain_id}' or its object not found.")
            return {'CANCELLED'}

        # Find the Cα position using the helper function
        alpha_carbon_pos = _find_residue_alpha_carbon_pos(context, molecule, domain, self.target_residue)

        if alpha_carbon_pos is None:
            self.report({'ERROR'}, f"Could not find Alpha Carbon for {self.target_residue} residue ({domain.start if self.target_residue == 'START' else domain.end}).")
            return {'CANCELLED'}

        # --- Set the origin ---
        orig_cursor_loc = context.scene.cursor.location.copy()
        try:
            context.scene.cursor.location = alpha_carbon_pos

            # Ensure the domain object is selected and active
            bpy.ops.object.select_all(action='DESELECT')
            domain.object.select_set(True)
            context.view_layer.objects.active = domain.object

            # Set origin to cursor
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

            # --- IMPORTANT: Update the stored initial matrix ---
            domain.object["initial_matrix_local"] = [list(row) for row in domain.object.matrix_local]
            print(f"Updated initial matrix for {domain.name} after snapping pivot to {self.target_residue} AA.")

            self.report({'INFO'}, f"Pivot snapped to {self.target_residue} residue's Cα.")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to set origin: {e}")
            return {'CANCELLED'}
        finally:
            # Restore cursor location
            context.scene.cursor.location = orig_cursor_loc

        return {'FINISHED'}

# List of all operator classes in this file
classes = (
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_update_domain,
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_domain_location,
    MOLECULE_PB_OT_keyframe_domain_rotation,
    MOLECULE_PB_OT_toggle_domain_expanded,
    MOLECULE_PB_OT_update_domain_ui_values,
    MOLECULE_PB_OT_update_domain_color,
    MOLECULE_PB_OT_update_domain_style,
    MOLECULE_PB_OT_toggle_pivot_edit,
    MOLECULE_PB_OT_set_parent_domain,
    MOLECULE_PB_OT_update_parent_domain,
    MOLECULE_PB_OT_reset_domain_transform,
    MOLECULE_PB_OT_snap_pivot_to_residue
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
