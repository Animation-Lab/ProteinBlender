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
