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
            
        # Automatically expand the new domain
        if domain_id in molecule.domains:
            domain = molecule.domains[domain_id]
            
            if domain.object:
                try:
                    # Try to set the property directly
                    domain.object["domain_expanded"] = True
                    
                    # Also sync the domain_color property with the actual color used
                    if hasattr(domain, "color"):
                        # Set the domain_color property to match the actual color used in the node tree
                        domain.object.domain_color = domain.color
                except:
                    # If that fails, ensure the property exists first
                    if not hasattr(domain.object, "domain_expanded"):
                        # Register the property if needed
                        bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
                    # Then set it
                    domain.object.domain_expanded = True
                    
                    # And try setting the color again
                    if hasattr(domain, "color") and hasattr(domain.object, "domain_color"):
                        domain.object.domain_color = domain.color
                
                # Set the pivot point to the alpha carbon of the start residue
                self.set_pivot_to_alpha_carbon(context, molecule, domain)
            
        return {'FINISHED'}
    
    def set_pivot_to_alpha_carbon(self, context, molecule, domain):
        """Set the domain's pivot point to the alpha carbon of the start residue"""
        try:
            # Get the molecular object
            mol_obj = molecule.object
            if not mol_obj or not domain.object:
                print("DEBUG: Missing molecule or domain object")
                return
            
            # Log current position for debugging
            print(f"DEBUG: Current domain pivot (object origin) is at {domain.object.location}")
            
            # Check for the necessary attributes
            if not hasattr(mol_obj.data, "attributes"):
                print("DEBUG: No attributes on molecule data")
                return
                
            # Get attributes for finding alpha carbons
            attrs = mol_obj.data.attributes
            print(f"DEBUG: Available attributes: {list(attrs.keys())}")
            
            # Check for required attributes with correct names
            required_attrs = ["atom_name", "chain_id"]
            residue_attr = None
            
            # Determine which attribute contains residue numbers
            if "residue_number" in attrs:
                residue_attr = "residue_number"
                required_attrs.append("residue_number")
            elif "res_id" in attrs:
                residue_attr = "res_id"
                required_attrs.append("res_id")
            else:
                print(f"DEBUG: Missing residue number attribute. Available: {list(attrs.keys())}")
                return
            
            # Check if we have all required attributes
            for attr in required_attrs:
                if attr not in attrs:
                    print(f"DEBUG: Missing required attribute: {attr}. Available: {list(attrs.keys())}")
                    return
                
            # Get the domain info
            domain_chain_id = domain.chain_id
            start_res = domain.start
            print(f"DEBUG: Domain chain_id: '{domain_chain_id}', Looking for atom in residue {start_res}")
            
            # Get the attributes data
            atom_names = attrs["atom_name"].data
            chain_ids = attrs["chain_id"].data
            res_nums = attrs[residue_attr].data
            
            # Print some debug info about the first few atoms
            print(f"DEBUG: First 5 atoms - names, chains, residues:")
            for i in range(min(5, len(atom_names))):
                print(f"  Atom {i}: {atom_names[i].value}, Chain: {chain_ids[i].value}, Res: {res_nums[i].value}")
            
            # Determine if we have numeric or textual atom names by checking the first few atoms
            numeric_atom_names = False
            for i in range(min(10, len(atom_names))):
                try:
                    int(atom_names[i].value)
                    numeric_atom_names = True
                    break
                except (ValueError, TypeError):
                    pass
            
            print(f"DEBUG: Using {'numeric' if numeric_atom_names else 'textual'} atom naming convention")
            
            # Get chain ID to search for - try both numeric and string versions
            search_chain_ids = [domain_chain_id]
            if domain_chain_id.isalpha():
                # If domain chain is alphabetic, also try the numeric index
                try:
                    # A = 0, B = 1, etc.
                    numeric_chain = ord(domain_chain_id.upper()) - ord('A')
                    search_chain_ids.append(str(numeric_chain))
                    search_chain_ids.append(numeric_chain)
                except:
                    pass
            else:
                # If domain chain is numeric, also try the alphabetic version
                try:
                    # 0 = A, 1 = B, etc.
                    alpha_chain = chr(int(domain_chain_id) + ord('A'))
                    search_chain_ids.append(alpha_chain)
                except:
                    pass
            
            print(f"DEBUG: Searching for chain IDs: {search_chain_ids}")
            
            # If we have position attribute
            if "position" in attrs:
                positions = attrs["position"].data
                print(f"DEBUG: Position attribute found with {len(positions)} entries")
                
                # Strategy depends on if we have numeric or textual atom names
                alpha_carbon_pos = None
                alpha_carbon_idx = None
                
                if numeric_atom_names:
                    # For numeric atom names, we need to identify which number corresponds to the alpha carbon
                    # This is usually atom type 2 in PDB format, but to be sure, let's try to find it by finding 
                    # the second atom in the first peptide of the chain
                    ca_atom_indices = []
                    
                    # Group atoms by residue in the requested chain
                    residue_atoms = {}
                    for i in range(len(atom_names)):
                        chain_value = chain_ids[i].value
                        chain_str = str(chain_value)
                        
                        # Check if this atom is in one of our search chains
                        if chain_str in search_chain_ids or chain_value in search_chain_ids:
                            res_value = res_nums[i].value
                            if res_value not in residue_atoms:
                                residue_atoms[res_value] = []
                            residue_atoms[res_value].append(i)
                    
                    print(f"DEBUG: Found {len(residue_atoms)} residues in the target chain")
                    
                    # For each residue, identify the likely alpha carbon
                    for res_id, atom_indices in residue_atoms.items():
                        # In PDB format with numeric atom types, the alpha carbon is often the 2nd atom (index 1)
                        # of each amino acid (though this depends on the format and might not be reliable)
                        if len(atom_indices) >= 2:
                            ca_index = atom_indices[1]  # Try the second atom of each residue
                            ca_atom_indices.append((res_id, ca_index))
                    
                    # If we have the starting residue in our mapping
                    if start_res in residue_atoms and len(residue_atoms[start_res]) >= 2:
                        alpha_carbon_idx = residue_atoms[start_res][1]  # Use the second atom
                        alpha_carbon_pos = positions[alpha_carbon_idx].vector
                        print(f"DEBUG: Found likely alpha carbon at index {alpha_carbon_idx} for residue {start_res}, position: {alpha_carbon_pos}")
                
                else:
                    # For textual atom names, search for "CA"
                    for i in range(len(atom_names)):
                        atom_value = atom_names[i].value
                        chain_value = chain_ids[i].value
                        chain_str = str(chain_value)
                        res_value = res_nums[i].value
                        
                        # For debug, print when we find any CA atom
                        if atom_value == "CA":
                            print(f"DEBUG: Found CA at index {i}, Chain: {chain_value}, Res: {res_value}")
                        
                        # Check for CA atom in the correct chain and residue
                        if (atom_value == "CA" and 
                            (chain_str in search_chain_ids or chain_value in search_chain_ids) and
                            res_value == start_res):
                            # Found the alpha carbon at the start residue
                            alpha_carbon_pos = positions[i].vector
                            alpha_carbon_idx = i
                            print(f"DEBUG: Found matching CA atom at index {i} with position {alpha_carbon_pos}")
                            break
                
                # If we found the alpha carbon, set the domain's pivot point
                if alpha_carbon_pos is not None:
                    # Deselect all objects and select only the domain
                    bpy.ops.object.select_all(action='DESELECT')
                    domain.object.select_set(True)
                    context.view_layer.objects.active = domain.object
                    
                    # Store the original cursor location
                    orig_cursor_loc = context.scene.cursor.location.copy()
                    
                    # Set the 3D cursor to the alpha carbon position
                    context.scene.cursor.location = alpha_carbon_pos
                    print(f"DEBUG: Setting cursor to alpha carbon position: {alpha_carbon_pos}")
                    
                    # Set the object's origin to the 3D cursor position
                    bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
                    
                    # Report new pivot position
                    print(f"DEBUG: New domain pivot position: {domain.object.location}")
                    
                    # Restore the original cursor location
                    context.scene.cursor.location = orig_cursor_loc
                    
                    print(f"DEBUG: Successfully set domain pivot to alpha carbon of residue {start_res}")
                else:
                    print(f"DEBUG: Couldn't find alpha carbon for chain '{domain_chain_id}' at residue {start_res}")
                    # Try to find any atoms in this chain for debugging
                    atoms_in_chain = []
                    for i in range(len(atom_names)):
                        chain_value = chain_ids[i].value
                        chain_str = str(chain_value)
                        if chain_str in search_chain_ids or chain_value in search_chain_ids:
                            atoms_in_chain.append((i, res_nums[i].value, atom_names[i].value))
                            if len(atoms_in_chain) >= 10:  # Limit to first 10 found
                                break
                    
                    if atoms_in_chain:
                        print(f"DEBUG: First few atoms found in this chain:")
                        for idx, res, atom in atoms_in_chain:
                            print(f"  Atom {atom} in Residue {res} at position {positions[idx].vector}")
            else:
                print("DEBUG: No position attribute found")
        except Exception as e:
            print(f"DEBUG: Error setting pivot to alpha carbon: {str(e)}")
            import traceback
            traceback.print_exc()

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
            self.report({'INFO'}, "Pivot point updated")
        
        return {'FINISHED'}

# Register
def register():
    bpy.utils.register_class(MOLECULE_PB_OT_create_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.register_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_ui_values)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_color)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_style)
    bpy.utils.register_class(MOLECULE_PB_OT_toggle_pivot_edit)

def unregister():
    try:
        bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_pivot_edit)
        bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_style)
        bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_color)
        bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_ui_values)
        bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_domain_expanded)
        bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
        bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
        bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
        bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
        bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
    except Exception:
        pass
