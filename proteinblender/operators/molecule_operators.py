import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_PB_OT_select(Operator):
    bl_idname = "molecule.select"
    bl_label = "Select Molecule"
    bl_description = "Select this molecule"
    bl_order = 0
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        # Toggle collapse when clicking the active molecule
        if scene.selected_molecule_id == self.molecule_id:
            scene.selected_molecule_id = ""
            return {'FINISHED'}
        # Select this molecule
        scene.selected_molecule_id = self.molecule_id
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        
        if molecule:
            # Clear existing chain selections
            context.scene.chain_selections.clear()
            
            # Get unique chain IDs from the molecule's object
            if molecule.object and "chain_id" in molecule.object.data.attributes:
                chain_attr = molecule.object.data.attributes["chain_id"]
                chain_ids = sorted(set(value.value for value in chain_attr.data))
                
                # Create selection items for each chain
                for chain_id in chain_ids:
                    item = context.scene.chain_selections.add()
                    item.chain_id = str(chain_id)
                    item.is_selected = False
            
            # Set the edit identifier when selecting
            context.scene.edit_molecule_identifier = molecule.identifier
            
            # Initialize domain creation UI properties
            if chain_ids and len(chain_ids) > 0:
                first_chain = str(chain_ids[0])
                context.scene.new_domain_chain = first_chain
                
                # Get residue range for the first chain
                if hasattr(molecule, 'chain_residue_ranges') and molecule.chain_residue_ranges:
                    # Get the mapped chain (handle numeric vs. alphabetic chains)
                    mapped_chain = molecule.chain_mapping.get(
                        int(first_chain) if first_chain.isdigit() else first_chain, 
                        str(first_chain)
                    )
                    
                    # Get residue range for this chain
                    if mapped_chain in molecule.chain_residue_ranges:
                        min_res, max_res = molecule.chain_residue_ranges[mapped_chain]
                        context.scene.new_domain_start = min_res
                        context.scene.new_domain_end = max_res
            
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Select the molecule's object
            molecule.object.select_set(True)
            context.view_layer.objects.active = molecule.object
            
            # Get unique chain IDs from the molecule's object
            if molecule.object:
                # Get the geometry nodes modifier
                gn_mod = molecule.object.modifiers.get("MolecularNodes")
                if gn_mod and gn_mod.node_group:
                    # Create chain enum items
                    chain_items = []
                    # Get chain IDs from the molecule's attributes
                    chain_ids = set()  # Using a set to get unique chain IDs
                    if "chain_id" in molecule.object.data.attributes:
                        chain_attr = molecule.object.data.attributes["chain_id"]
                        for value in chain_attr.data:
                            chain_ids.add(value.value)
                    
                    # Create enum items for each chain
                    chain_items = [("NONE", "None", "None")]
                    chain_items.extend([(str(chain), f"Chain {chain}", f"Chain {chain}") 
                                      for chain in sorted(chain_ids)])
                    
                    # Update the enum property
                    bpy.types.Scene.selected_chain = EnumProperty(
                        name="Chain",
                        description="Selects the protein's chain",
                        items=chain_items,
                        default="NONE"
                    )
                    # Force a property update
                    context.scene.selected_chain = "NONE"
            
        return {'FINISHED'}

class MOLECULE_PB_OT_edit(Operator):
    bl_idname = "molecule.edit"
    bl_label = "Edit Molecule"
    bl_description = "Edit this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.show_molecule_edit_panel = True
        context.scene.selected_molecule_id = self.molecule_id
        return {'FINISHED'}

class MOLECULE_PB_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete this molecule"
    bl_options = {'REGISTER', 'UNDO'}
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        # Capture current state for potential undo restoration
        try:
            scene_manager._capture_molecule_state(self.molecule_id)
        except Exception:
            pass
        # Perform deletion
        scene_manager.delete_molecule(self.molecule_id)
        
        # Rebuild the outliner hierarchy to reflect the deletion
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)
        
        return {'FINISHED'}

class MOLECULE_PB_OT_update_identifier(Operator):
    bl_idname = "molecule.update_identifier"
    bl_label = "Update Identifier"
    bl_description = "Update the molecule's identifier"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        old_id = scene.selected_molecule_id
        new_id = scene.edit_molecule_identifier
        
        if old_id == new_id or not new_id:
            return {'CANCELLED'}
            
        # Update molecule identifier
        molecule = scene_manager.molecules[old_id]
        molecule.identifier = new_id
        scene_manager.molecules[new_id] = scene_manager.molecules.pop(old_id)
        
        # Update UI list
        for item in scene.molecule_list_items:
            if item.identifier == old_id:
                item.identifier = new_id
                break
                
        # Update selected molecule id
        scene.selected_molecule_id = new_id
        
        return {'FINISHED'}

class MOLECULE_PB_OT_change_style(Operator):
    bl_idname = "molecule.change_style"
    bl_label = "Change Style"
    bl_description = "Change the molecule's visualization style"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        
        if molecule and molecule.object:
            from ..utils.molecularnodes.blender.nodes import change_style_node
            style = context.scene.molecule_style
            change_style_node(molecule.object, style)
            # Also update all domains to match the global style
            for domain in getattr(molecule, 'domains', {}).values():
                if hasattr(domain, 'object') and domain.object:
                    try:
                        domain.object.domain_style = style  # This triggers the callback and updates the node group
                    except Exception as e:
                        print(f"Failed to update style for domain {getattr(domain, 'name', '?')}: {e}")
        
        return {'FINISHED'}

class MOLECULE_PB_OT_select_protein_chain(Operator):
    bl_idname = "molecule.select_protein_chain"
    bl_label = "Select Chain"
    bl_description = "Selects the molecule's chain"


    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        molecule.select_protein_chain = context.scene.selected_chain

        

        '''
        if molecule and molecule.object:
            from ..utils.molecularnodes.blender.nodes import change_style_node
            change_style_node(molecule.object, context.scene.molecule_style)
        '''

        return {'FINISHED'}

class MOLECULE_PB_OT_move_protein_pivot(bpy.types.Operator):
    bl_idname = "molecule.move_protein_pivot"
    bl_label = "Move Protein Pivot to 3D Cursor"
    bl_description = "Move the protein's origin to the 3D cursor location"

    molecule_id: bpy.props.StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, "Molecule object not found.")
            return {'CANCELLED'}
        obj = molecule.object
        # Store original cursor location
        orig_cursor = context.scene.cursor.location.copy()
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
            self.report({'INFO'}, "Protein pivot moved to 3D cursor.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to move pivot: {e}")
        finally:
            context.scene.cursor.location = orig_cursor
        return {'FINISHED'}

class MOLECULE_PB_OT_snap_protein_pivot_center(bpy.types.Operator):
    bl_idname = "molecule.snap_protein_pivot_center"
    bl_label = "Snap Protein Pivot to Center"
    bl_description = "Snap the protein's origin to its bounding box center"

    molecule_id: bpy.props.StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, "Molecule object not found.")
            return {'CANCELLED'}
        obj = molecule.object
        try:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
            self.report({'INFO'}, "Protein pivot snapped to bounding box center.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to snap pivot: {e}")
        return {'FINISHED'}

class MOLECULE_PB_OT_toggle_protein_pivot_edit(bpy.types.Operator):
    bl_idname = "molecule.toggle_protein_pivot_edit"
    bl_label = "Move/Set Protein Pivot"
    bl_description = "Interactively move the protein's pivot using a helper object."

    _pivot_edit_active = dict()  # Class-level dict to track state per molecule

    molecule_id: bpy.props.StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, "Molecule object not found.")
            return {'CANCELLED'}
        obj = molecule.object
        # Toggle logic: if already editing, finish and set pivot; else, start editing
        if self.molecule_id not in self._pivot_edit_active:
            # Start pivot edit mode (match domain logic)
            # Save state
            self._pivot_edit_active[self.molecule_id] = {
                'cursor_location': list(context.scene.cursor.location),
                'previous_tool': context.workspace.tools.from_space_view3d_mode(context.mode, create=False).idname,
                'object_location': obj.location.copy(),
                'object_rotation': obj.rotation_euler.copy(),
                'transform_orientation': context.scene.transform_orientation_slots[0].type,
                'pivot_point': context.tool_settings.transform_pivot_point
            }
            # Deselect all
            bpy.ops.object.select_all(action='DESELECT')
            # Create ARROWS empty at protein origin
            bpy.ops.object.empty_add(type='ARROWS', location=obj.location)
            helper = context.active_object
            helper.name = f"PB_PivotHelper_{self.molecule_id}"
            helper.empty_display_size = 1.0
            helper.show_in_front = True
            helper.hide_select = False
            helper.select_set(True)
            context.view_layer.objects.active = helper
            self._pivot_edit_active[self.molecule_id]['helper'] = helper
            # Set up transform settings
            context.scene.transform_orientation_slots[0].type = 'GLOBAL'
            context.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
            # Switch to move tool and show gizmo
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
            obj["is_pivot_editing"] = True
            self.report({'INFO'}, "Use the transform gizmo to move the helper. Click 'Set Pivot' to apply.")
            return {'FINISHED'}
        else:
            # Finish pivot edit mode
            stored_state = self._pivot_edit_active[self.molecule_id]
            helper = stored_state['helper']
            # Store location before deleting helper
            new_pivot_location = helper.location.copy()
            # Set origin to helper location
            context.scene.cursor.location = new_pivot_location
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
            # Delete helper
            bpy.ops.object.select_all(action='DESELECT')
            helper.select_set(True)
            context.view_layer.objects.active = helper
            bpy.ops.object.delete()
            # Restore previous selection/context
            context.scene.cursor.location = stored_state['cursor_location']
            context.scene.transform_orientation_slots[0].type = stored_state['transform_orientation']
            context.tool_settings.transform_pivot_point = stored_state['pivot_point']
            obj["is_pivot_editing"] = False
            del self._pivot_edit_active[self.molecule_id]
            self.report({'INFO'}, "Protein pivot updated.")
            return {'FINISHED'}

# Add operator to toggle visibility of molecule and its domains
class MOLECULE_PB_OT_toggle_visibility(Operator):
    bl_idname = "molecule.toggle_visibility"
    bl_label = "Toggle Molecule Visibility"
    bl_description = "Toggle visibility of this molecule and its domains"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        # Get the molecule wrapper
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        if not molecule or not molecule.object:
            return {'CANCELLED'}
        # Determine new visibility state (False = visible, True = hidden)
        new_state = not molecule.object.hide_viewport
        # Toggle main molecule
        molecule.object.hide_viewport = new_state
        # Also toggle all domains for this molecule
        for domain in getattr(molecule, 'domains', {}).values():
            if domain.object:
                domain.object.hide_viewport = new_state
        return {'FINISHED'}


class MOLECULE_PB_OT_center_protein(Operator):
    """Center protein at origin using center of mass"""
    bl_idname = "molecule.center_protein"
    bl_label = "Center Protein"
    bl_description = "Move protein pivot to center of mass and place at world origin"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Call the existing center of mass method
        success = molecule.set_protein_pivot_to_center_of_mass(context)

        if success:
            self.report({'INFO'}, f"Centered protein '{molecule.identifier}' at origin")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to center protein")
            return {'CANCELLED'}


class MOLECULE_PB_OT_duplicate_protein(Operator):
    """Create an exact duplicate of the protein with all domains and properties"""
    bl_idname = "molecule.duplicate_protein"
    bl_label = "Duplicate Protein"
    bl_description = "Create a complete copy of this protein including all domains, colors, styles, and transforms"
    bl_options = {'REGISTER', 'UNDO'}

    molecule_id: StringProperty()

    def execute(self, context):
        from mathutils import Vector
        scene_manager = ProteinBlenderScene.get_instance()
        source_molecule = scene_manager.molecules.get(self.molecule_id)

        if not source_molecule or not source_molecule.object:
            self.report({'ERROR'}, "Source molecule not found")
            return {'CANCELLED'}

        try:
            # 1. Generate unique identifier for the duplicate
            base_id = source_molecule.identifier
            counter = 1
            new_identifier = f"{base_id}_copy_{counter}"
            while new_identifier in scene_manager.molecules:
                counter += 1
                new_identifier = f"{base_id}_copy_{counter}"

            print(f"Duplicating protein '{base_id}' as '{new_identifier}'")

            # 2. Duplicate the main protein object and its mesh data
            source_obj = source_molecule.object

            # Save source object's transform data before copying
            source_location = source_obj.location.copy()
            source_rotation = source_obj.rotation_euler.copy()
            source_scale = source_obj.scale.copy()

            new_protein_obj = source_obj.copy()
            new_protein_obj.data = source_obj.data.copy()
            new_protein_obj.name = f"{new_identifier}_protein"

            # Link to scene (use same collection as source)
            if source_obj.users_collection:
                source_obj.users_collection[0].objects.link(new_protein_obj)
            else:
                context.scene.collection.objects.link(new_protein_obj)

            # Ensure new protein has exact same transform as source
            new_protein_obj.location = source_location
            new_protein_obj.rotation_euler = source_rotation
            new_protein_obj.scale = source_scale

            # 3. Copy modifiers from source protein
            new_protein_obj.modifiers.clear()
            for mod in source_obj.modifiers:
                new_mod = new_protein_obj.modifiers.new(name=mod.name, type=mod.type)
                # Copy modifier properties
                for prop in mod.bl_rna.properties:
                    if not prop.is_readonly:
                        try:
                            setattr(new_mod, prop.identifier, getattr(mod, prop.identifier))
                        except:
                            pass

            # 4. Create new MoleculeWrapper
            # We need to create a Molecule object first
            from ..utils.molecularnodes.entities.molecule.molecule import Molecule
            from ..core.molecule_wrapper import MoleculeWrapper

            # Create a minimal Molecule object wrapping the new protein
            new_mol_obj = Molecule(new_protein_obj.name)
            new_mol_obj.object = new_protein_obj
            new_mol_obj.array = source_molecule.molecule.array  # Share the same biotite array

            # Create MoleculeWrapper
            new_molecule = MoleculeWrapper(new_mol_obj, new_identifier)
            new_molecule.style = source_molecule.style

            # 5. CRITICAL: Store the offset between source protein location and origin
            # We'll temporarily move the new protein to match source protein's position
            # during domain creation, then move everything together to preserve exact transforms
            source_to_origin_offset = source_location.copy()

            # Move new protein to source location BEFORE creating domains
            # This ensures domains are created with correct relative positions
            new_protein_obj.location = source_location
            context.view_layer.update()

            print(f"  Temporarily positioned new protein at source location: {source_location}")

            # 6. Save source domain data (we'll use LOCAL transforms since parent will match)
            source_domain_data = {}
            for source_domain_id, source_domain in source_molecule.get_sorted_domains().items():
                if source_domain.object:
                    # Save domain properties and LOCAL transforms (relative to parent)
                    source_domain_data[source_domain_id] = {
                        'name': source_domain.name,
                        'chain_id': source_domain.chain_id,
                        'start': source_domain.start,
                        'end': source_domain.end,
                        'color': source_domain.color,
                        'style': source_domain.style,
                        'local_location': source_domain.object.location.copy(),
                        'local_rotation': source_domain.object.rotation_euler.copy(),
                        'local_scale': source_domain.object.scale.copy(),
                        'matrix_parent_inverse': source_domain.object.matrix_parent_inverse.copy(),
                    }

            # 7. Copy all domains with their properties
            domain_mapping = {}  # Maps source_domain_id -> new_domain_id

            for source_domain_id, domain_data in source_domain_data.items():
                source_domain = source_molecule.domains[source_domain_id]

                print(f"  Copying domain: {domain_data['name']}")

                # Create new domain with same parameters
                # Need to convert chain_id to numeric format for create_domain
                numeric_chain_id = str(domain_data['chain_id'])
                if not numeric_chain_id.isdigit():
                    # Find numeric equivalent
                    for num_id, auth_id in source_molecule.chain_mapping.items():
                        if auth_id == domain_data['chain_id']:
                            numeric_chain_id = str(num_id)
                            break

                result = new_molecule.create_domain(
                    chain_id=numeric_chain_id,
                    start=domain_data['start'],
                    end=domain_data['end'],
                    name=domain_data['name']
                )

                # create_domain returns a list of domain IDs (due to auto-fill), take the first one
                if not result:
                    print(f"    Warning: Failed to create domain {source_domain.name}")
                    continue

                # Handle both list and string return types
                if isinstance(result, list):
                    new_domain_id = result[0] if result else None
                else:
                    new_domain_id = result

                if not new_domain_id:
                    print(f"    Warning: No domain ID returned for {source_domain.name}")
                    continue

                domain_mapping[source_domain_id] = new_domain_id
                new_domain = new_molecule.domains[new_domain_id]

                # 8. Copy color and style properties
                new_domain.color = domain_data['color']
                new_domain.style = domain_data['style']

                # 9. Copy LOCAL transforms from source domain
                # Since both parent proteins are at the same location, local transforms should match
                new_domain.object.location = domain_data['local_location']
                new_domain.object.rotation_euler = domain_data['local_rotation']
                new_domain.object.scale = domain_data['local_scale']

                # Also copy the matrix_parent_inverse to ensure exact transform preservation
                new_domain.object.matrix_parent_inverse = domain_data['matrix_parent_inverse']

                # 10. Copy color from geometry nodes (RGB values and alpha)
                self._copy_domain_color(source_domain.object, new_domain.object)

                # 11. Apply style to the domain's node group
                if new_domain.style != 'ribbon':  # ribbon is default, only change if different
                    try:
                        from ..utils.molecularnodes.blender.nodes import styles_mapping, append, swap
                        # Find the style node in the new domain's node group
                        if new_domain.node_group:
                            for node in new_domain.node_group.nodes:
                                if (node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name):
                                    if new_domain.style in styles_mapping:
                                        style_node_name = styles_mapping[new_domain.style]
                                        swap(node, append(style_node_name))
                                    break
                    except Exception as e:
                        print(f"    Warning: Could not apply style {new_domain.style}: {e}")

                # 12. Copy custom properties
                if hasattr(source_domain, 'is_copy'):
                    new_domain.is_copy = source_domain.is_copy
                if hasattr(source_domain, 'copy_number'):
                    new_domain.copy_number = source_domain.copy_number
                if hasattr(source_domain, 'original_domain_id'):
                    new_domain.original_domain_id = source_domain.original_domain_id

                print(f"    ✓ Copied domain '{source_domain.name}' -> '{new_domain_id}'")

            # 13. Force scene update to ensure all objects are properly initialized
            context.view_layer.update()

            # 14. Final verification - protein should still be at source location
            print(f"✓ Duplicated protein '{new_identifier}' created at same location as source")
            print(f"  Source location: {source_location}")
            print(f"  New protein location: {new_protein_obj.location}")

            # Verify location is correct
            current_location = new_protein_obj.location.copy()
            if (current_location - source_location).length > 0.0001:
                print(f"  Warning: Small location drift detected ({(current_location - source_location).length:.6f} units)")
            else:
                print(f"  ✓ Location verified: exactly matches source")

            # 15. Force final scene update
            context.view_layer.update()

            # 16. Add to scene manager (directly to molecules dict since MoleculeManager doesn't have add_molecule)
            scene_manager.molecules[new_identifier] = new_molecule

            # 17. Rebuild outliner to show the new protein
            from ..utils.scene_manager import build_outliner_hierarchy
            build_outliner_hierarchy(context)

            # 18. Re-center the duplicated protein at origin (as if user clicked the re-center button)
            print(f"Re-centering duplicated protein '{new_identifier}' at origin...")
            bpy.ops.molecule.center_protein(molecule_id=new_identifier)
            print(f"  ✓ Duplicated protein centered at origin")

            self.report({'INFO'}, f"Duplicated protein '{base_id}' with {len(domain_mapping)} domains")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to duplicate protein: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

    def _copy_domain_color(self, source_obj, target_obj):
        """Copy color from source domain's geometry nodes to target domain"""
        try:
            # Find source geometry nodes modifier
            source_mod = None
            for mod in source_obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    source_mod = mod
                    break

            # Find target geometry nodes modifier
            target_mod = None
            for mod in target_obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    target_mod = mod
                    break

            if not source_mod or not target_mod:
                return

            source_tree = source_mod.node_group
            target_tree = target_mod.node_group

            # Look for Custom Combine Color node in source
            source_color_node = None
            for node in source_tree.nodes:
                if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                    source_color_node = node
                    break

            # Look for or create Custom Combine Color node in target
            target_color_node = None
            for node in target_tree.nodes:
                if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
                    target_color_node = node
                    break

            if source_color_node and target_color_node:
                # Copy RGB values
                target_color_node.inputs['Red'].default_value = source_color_node.inputs['Red'].default_value
                target_color_node.inputs['Green'].default_value = source_color_node.inputs['Green'].default_value
                target_color_node.inputs['Blue'].default_value = source_color_node.inputs['Blue'].default_value

            # Also copy alpha from material if present
            self._copy_material_alpha(source_obj, target_obj, source_tree, target_tree)

        except Exception as e:
            print(f"Warning: Could not copy domain color: {e}")

    def _copy_material_alpha(self, source_obj, target_obj, source_tree, target_tree):
        """Copy alpha value from source material to target material"""
        try:
            # Find Style node in both trees
            source_style_node = None
            target_style_node = None

            for node in source_tree.nodes:
                if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                    source_style_node = node
                    break

            for node in target_tree.nodes:
                if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                    target_style_node = node
                    break

            if not source_style_node or not target_style_node:
                return

            # Get materials
            source_mat_input = source_style_node.inputs.get("Material")
            target_mat_input = target_style_node.inputs.get("Material")

            if not source_mat_input or not target_mat_input:
                return

            source_mat = source_mat_input.default_value
            target_mat = target_mat_input.default_value

            if not source_mat or not target_mat:
                return

            # Find Principled BSDF in both materials
            if source_mat.use_nodes and target_mat.use_nodes:
                source_bsdf = None
                target_bsdf = None

                for node in source_mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        source_bsdf = node
                        break

                for node in target_mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        target_bsdf = node
                        break

                if source_bsdf and target_bsdf:
                    # Copy alpha value
                    target_bsdf.inputs['Alpha'].default_value = source_bsdf.inputs['Alpha'].default_value

        except Exception as e:
            print(f"Warning: Could not copy material alpha: {e}")


class MOLECULE_PB_OT_delete_chain(Operator):
    """Delete a chain and all its domains from a protein"""
    bl_idname = "molecule.delete_chain"
    bl_label = "Delete Chain"
    bl_description = "Delete this chain and all its domains"
    bl_options = {'REGISTER', 'UNDO'}

    chain_id: StringProperty()
    molecule_id: StringProperty()

    def invoke(self, context, event):
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)

        if not molecule:
            self.report({'ERROR'}, "Molecule not found")
            return {'CANCELLED'}

        # Capture state for undo (reuse existing pattern)
        scene_manager._capture_molecule_state(self.molecule_id)

        # Find all domains belonging to this chain
        domains_to_delete = []
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(self.chain_id):
                domains_to_delete.append(domain_id)

        if not domains_to_delete:
            self.report({'WARNING'}, f"No domains found for chain {self.chain_id}")
            return {'CANCELLED'}

        # Delete each domain using cleanup (reuse existing cleanup method)
        for domain_id in domains_to_delete:
            domain = molecule.domains[domain_id]
            # Call cleanup to remove object and node groups
            domain.cleanup()
            # Remove from molecule's domains dictionary
            del molecule.domains[domain_id]

        # Remove chain from puppet memberships
        self._remove_chain_from_puppets(context, self.molecule_id, self.chain_id)

        # Rebuild outliner (reuse existing function)
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)

        self.report({'INFO'}, f"Deleted chain {self.chain_id} and {len(domains_to_delete)} domain(s)")
        return {'FINISHED'}

    def _remove_chain_from_puppets(self, context, molecule_id, chain_id):
        """Remove chain from any puppet group memberships"""
        # The chain's outliner ID is in the format "molecule_id_chain_X"
        chain_outliner_id = f"{molecule_id}_chain_{chain_id}"

        # Also check for individual domain IDs that might be in puppets
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(molecule_id)
        if not molecule:
            return

        # Collect all domain IDs for this chain
        domain_ids_in_chain = []
        for domain_id, domain in molecule.domains.items():
            if hasattr(domain, 'chain_id') and str(domain.chain_id) == str(chain_id):
                domain_ids_in_chain.append(domain_id)

        # Remove from puppet memberships
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.puppet_memberships:
                members = set(item.puppet_memberships.split(','))
                modified = False

                # Remove chain outliner ID
                if chain_outliner_id in members:
                    members.remove(chain_outliner_id)
                    modified = True

                # Remove any domain IDs from this chain
                for domain_id in domain_ids_in_chain:
                    if domain_id in members:
                        members.remove(domain_id)
                        modified = True

                if modified:
                    item.puppet_memberships = ','.join(members) if members else ""
