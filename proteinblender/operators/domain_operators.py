import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.animation import (
    keyframe_transforms, 
    refresh_timeline, 
    delete_transform_keyframes
)
from mathutils import Vector
import random

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
        
        # Get the chain_id as an int
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
        print(f"Operator: Requesting domain creation for chain {scene.new_domain_chain} ({scene.new_domain_start}-{scene.new_domain_end})")
        
        # Create the domain using the MoleculeWrapper method (which now handles pivot setting)
        created = molecule.create_domain(
            chain_id=scene.new_domain_chain,  # Use the chain selected in UI
            start=scene.new_domain_start,  # Use the start value from UI
            end=scene.new_domain_end  # Use the end value from UI
        )

        # create_domain returns a LIST of created domain ids - the requested
        # domain first, followed by any auto-filled filler domains that span the
        # rest of the chain. Normalize so a bare-id or None return still works,
        # and focus the requested (first) domain in the UI. Previously this
        # treated the return as a single id, so `domain_id in molecule.domains`
        # hashed a list and raised TypeError on any partial-range domain.
        created_ids = created if isinstance(created, list) else ([created] if created else [])
        if not created_ids:
            self.report({'ERROR'}, "Failed to create domain via MoleculeWrapper")
            return {'CANCELLED'}
        domain_id = created_ids[0]

        # Automatically expand the new domain in the UI
        # (Pivot setting is now handled inside molecule.create_domain)
        if domain_id in molecule.domains:
            domain = molecule.domains[domain_id]
            if domain.object:
                try:
                    domain.object["domain_expanded"] = True
                    if hasattr(domain, "color"):
                         # Ensure UI color property reflects actual color if available
                        if hasattr(domain.object, "domain_color"):
                            domain.object.domain_color = domain.color
                            
                    # Make sure domain_name is properly set
                    if hasattr(domain.object, "domain_name"):
                        domain.object.domain_name = domain.name
                    else:
                        domain.object["domain_name"] = domain.name
                    
                    # Initialize the temp_domain_name property for editing
                    if hasattr(domain.object, "temp_domain_name"):
                        domain.object.temp_domain_name = domain.name
                        
                except Exception as e:
                    print(f"Warning: Could not set domain_expanded or initial color: {e}")
                    # Continue even if UI update fails slightly
                 
        self.report({'INFO'}, f"Domain {domain_id} created successfully.")
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
                        self.report({'ERROR'}, "Cannot change chain - would overlap with existing domain")
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

class MOLECULE_PB_OT_copy_domain(Operator):
    bl_idname = "molecule.copy_domain"
    bl_label = "Copy Domain"
    bl_description = "Create a copy of the selected domain"
    bl_options = {'REGISTER', 'UNDO'}
    
    domain_id: StringProperty(description="ID of the domain to copy")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find which molecule owns this domain
        molecule = None
        for mol_id, mol in scene_manager.molecules.items():
            if self.domain_id in mol.domains:
                molecule = mol
                break
        
        if not molecule:
            self.report({'ERROR'}, "Domain not found in any molecule")
            return {'CANCELLED'}
        
        # Call the copy_domain method (will be implemented in MoleculeWrapper)
        new_domain_id = molecule.copy_domain(self.domain_id)
        
        if new_domain_id:
            self.report({'INFO'}, f"Domain copied successfully")
            # Rebuild outliner to show the new copy
            from ..utils.scene_manager import build_outliner_hierarchy
            build_outliner_hierarchy(context)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to copy domain")
            return {'CANCELLED'}

class MOLECULE_PB_OT_delete_domain(Operator):
    bl_idname = "molecule.delete_domain"
    bl_label = "Delete Domain"
    bl_description = "Delete the selected domain"
    bl_options = {'REGISTER', 'UNDO'}

    domain_id: StringProperty()
    molecule_id: StringProperty()

    def invoke(self, context, event):
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()

        # Find which molecule owns this domain
        molecule = None
        mol_id = None

        # If molecule_id is provided, use it directly
        if self.molecule_id:
            molecule = scene_manager.molecules.get(self.molecule_id)
            mol_id = self.molecule_id
        else:
            # Otherwise search for the molecule that contains this domain
            for m_id, mol in scene_manager.molecules.items():
                if self.domain_id in mol.domains:
                    molecule = mol
                    mol_id = m_id
                    break

        if not molecule:
            self.report({'ERROR'}, "Domain not found in any molecule")
            return {'CANCELLED'}

        # Capture the chain_id before deletion for potential chain cleanup
        domain_to_delete = molecule.domains.get(self.domain_id)
        if not domain_to_delete:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}

        chain_id = domain_to_delete.chain_id

        # Capture state for undo
        scene_manager._capture_molecule_state(mol_id)

        # Delete the domain and check if chain should be removed
        result = molecule.delete_domain(self.domain_id)

        # If this was the last domain on the chain, clean up puppet memberships
        if result == "DELETE_CHAIN":
            self._remove_chain_from_puppets(context, mol_id, chain_id)
            self.report({'INFO'}, f"Deleted last domain on chain {chain_id}")
        else:
            self.report({'INFO'}, "Domain deleted successfully")

        # Rebuild outliner to reflect the deletion
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)

        # Cascade: remove any linker left dangling by the domain deletion.
        try:
            from ..linkers.linker_handlers import prune_dangling_linkers
            prune_dangling_linkers(context.scene, "domain deleted")
        except Exception:
            pass

        return {'FINISHED'}

    def _remove_chain_from_puppets(self, context, molecule_id, chain_id):
        """Remove chain from any puppet group memberships"""
        chain_outliner_id = f"{molecule_id}_chain_{chain_id}"

        # Remove from puppet memberships
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.puppet_memberships:
                members = set(item.puppet_memberships.split(','))

                # Remove chain outliner ID
                if chain_outliner_id in members:
                    members.remove(chain_outliner_id)
                    item.puppet_memberships = ','.join(members) if members else ""

class MOLECULE_PB_OT_keyframe_protein(Operator):
    bl_idname = "molecule.keyframe_protein"
    bl_label = "Keyframe Protein"
    bl_description = "Add keyframes for the protein and all its domains' transforms at the current frame"
    bl_options = {'REGISTER', 'UNDO'}
    
    keyframe_name: StringProperty(
        name="Name",
        description="Name for this keyframe",
        default=""
    )
    frame_number: IntProperty(
        name="Frame",
        description="Frame number to insert the keyframe",
        default=1,
        min=1
    )
    
    def invoke(self, context, event):
        scene = context.scene
        self.frame_number = scene.frame_current
        
        # Suggest the next numbered keyframe name
        suggestion = 1
        sel_id = scene.selected_molecule_id
        for item in scene.molecule_list_items:
            if item.identifier == sel_id:
                max_n = 0
                for kf in item.keyframes:
                    if kf.name.startswith("Frame "):
                        suffix = kf.name[len("Frame "):].strip()
                        if suffix.isdigit():
                            num = int(suffix)
                            if num > max_n:
                                max_n = num
                suggestion = max_n + 1 if max_n > 0 else 1
                break
        self.keyframe_name = f"Frame {suggestion}"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "keyframe_name")
        layout.prop(self, "frame_number")

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        frame_to_use = self.frame_number
        name_to_use = self.keyframe_name.strip() or f"Frame {frame_to_use}"
        
        # Collect all objects to keyframe: protein + all domain objects
        objects_to_keyframe = []
        if molecule.object:
            objects_to_keyframe.append(molecule.object)
        
        for domain_id, domain in molecule.domains.items():
            if domain.object:
                objects_to_keyframe.append(domain.object)
        
        # Keyframe all objects using quaternion rotation
        keyframed_count = 0
        for obj in objects_to_keyframe:
            keyframe_transforms(obj, frame_to_use)
            keyframed_count += 1
        
        keyframed_domains = len(molecule.domains)

        # Record keyframe in the UI list
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                new_kf = item.keyframes.add()
                new_kf.frame = frame_to_use
                new_kf.name = name_to_use
                item.active_keyframe_index = len(item.keyframes) - 1
                break
        
        refresh_timeline()
        
        self.report({'INFO'}, f"Added keyframes for {keyframed_count} objects ({1 if molecule.object else 0} protein + {keyframed_domains} domains) at frame {frame_to_use}")
        return {'FINISHED'}

# Operator to select and jump to a saved keyframe
class MOLECULE_PB_OT_select_keyframe(Operator):
    bl_idname = "molecule.select_keyframe"
    bl_label = "Select Keyframe"
    bl_description = "Select a saved keyframe and jump to that frame"
    keyframe_index: IntProperty()
    def execute(self, context):
        scene = context.scene
        # Find the active molecule list item
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                idx = self.keyframe_index
                if 0 <= idx < len(item.keyframes):
                    item.active_keyframe_index = idx
                    # Jump to the keyframe frame
                    scene.frame_current = item.keyframes[idx].frame
                break
        return {'FINISHED'}

# Operator to delete a saved keyframe
class MOLECULE_PB_OT_delete_keyframe(Operator):
    bl_idname = "molecule.delete_keyframe"
    bl_label = "Delete Keyframe"
    bl_description = "Delete a saved keyframe"
    keyframe_index: IntProperty()

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        try:
            for item in scene.molecule_list_items:
                if item.identifier == scene.selected_molecule_id:
                    idx = self.keyframe_index
                    if idx < 0 or idx >= len(item.keyframes):
                        self.report({'ERROR'}, f"Invalid keyframe index: {idx}")
                        return {'CANCELLED'}
                    
                    deleted_kf = item.keyframes[idx]
                    deleted_frame = deleted_kf.frame
                    
                    # Get objects to clean up
                    all_objects = [molecule.object] if molecule.object else []
                    for domain_id, domain in molecule.domains.items():
                        if domain.object:
                            all_objects.append(domain.object)
                    
                    objs_with_anim = [obj for obj in all_objects if obj and obj.animation_data and obj.animation_data.action]
                    
                    # Delete the keyframe at the deleted frame
                    for obj in objs_with_anim:
                        delete_transform_keyframes(obj, deleted_frame)
                    
                    # Remove from UI list
                    item.keyframes.remove(idx)
                    
                    # Adjust active index after deletion
                    if item.active_keyframe_index >= len(item.keyframes):
                        item.active_keyframe_index = max(len(item.keyframes) - 1, 0)
                    
                    refresh_timeline()
                    break
            
            self.report({'INFO'}, f"Deleted keyframe at frame {deleted_frame}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete keyframe: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class MOLECULE_PB_OT_edit_keyframe(Operator):
    bl_idname = "molecule.edit_keyframe"
    bl_label = "Edit Keyframe"
    bl_description = "Edit parameters of an existing keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    keyframe_index: IntProperty()
    keyframe_name: StringProperty(name="Name")
    frame_number: IntProperty(name="Frame", min=1)

    def invoke(self, context, event):
        scene = context.scene
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                kf = item.keyframes[self.keyframe_index]
                self.keyframe_name = kf.name
                self.frame_number = kf.frame
                break
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "keyframe_name")
        layout.prop(self, "frame_number")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                kf = item.keyframes[self.keyframe_index]
                old_frame = kf.frame
                
                # Delete old timeline keyframes if frame changed
                if old_frame != self.frame_number:
                    targets = [molecule.object] + list(molecule.object.children_recursive)
                    for obj in targets:
                        delete_transform_keyframes(obj, old_frame)
                    
                    # Re-keyframe at new frame
                    for obj in targets:
                        if obj:
                            keyframe_transforms(obj, self.frame_number)
                
                # Update properties
                kf.name = self.keyframe_name
                kf.frame = self.frame_number
                break
        
        refresh_timeline()
        return {'FINISHED'}

class MOLECULE_PB_OT_toggle_domain_expanded(Operator):
    bl_idname = "molecule.toggle_domain_expanded"
    bl_label = "Toggle Domain Expanded State"
    bl_description = "Expand or collapse the domain settings in the UI"
    bl_options = {'INTERNAL'}

    domain_id: StringProperty()
    is_expanded: BoolProperty()

    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        if not molecule or self.domain_id not in molecule.domains:
            return {'CANCELLED'}

        domain = molecule.domains[self.domain_id]
        if domain.object:
            domain.object["domain_expanded"] = self.is_expanded
            
            # If expanding, pre-fill split domain UI values and set active splitting ID
            if self.is_expanded:
                context.scene.active_splitting_domain_id = self.domain_id
                # Ensure the domain properties (start, end) are accessible
                # DomainDefinition objects should have .start and .end attributes
                if hasattr(domain, 'start') and hasattr(domain, 'end'):
                    context.scene.split_domain_new_start = domain.start
                    context.scene.split_domain_new_end = domain.end
                else:
                    # Fallback or error if domain object doesn't have start/end as expected
                    # This might happen if the domain definition is somehow incomplete
                    print(f"Error: Domain {self.domain_id} definition is missing start/end attributes.")
                    # Set to a safe default or leave as is, depending on desired robustness
                    context.scene.split_domain_new_start = 1 
                    context.scene.split_domain_new_end = 1
            elif context.scene.active_splitting_domain_id == self.domain_id:
                # If collapsing the currently active splitting domain, clear the active ID
                context.scene.active_splitting_domain_id = ""

        # Refresh the UI by triggering a redraw of panels that might depend on these properties
        if context.area:
            context.area.tag_redraw()
        
        return {'FINISHED'}

class MOLECULE_PB_OT_split_domain(Operator):
    bl_idname = "molecule.split_domain"
    bl_label = "Split Domain"
    bl_description = "Split an existing domain into new segments"

    domain_id: StringProperty(description="ID of the domain to split")

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)

        if not molecule:
            self.report({'ERROR'}, "No molecule selected for domain splitting.")
            return {'CANCELLED'}

        if not self.domain_id or self.domain_id not in molecule.domains:
            self.report({'ERROR'}, f"Domain ID '{self.domain_id}' not found in selected molecule.")
            return {'CANCELLED'}

        original_domain = molecule.domains[self.domain_id]

        # Get new start and end from scene properties
        new_start = scene.split_domain_new_start
        new_end = scene.split_domain_new_end

        # Validate new start and end against the original domain's range
        if not (original_domain.start <= new_start <= new_end <= original_domain.end):
            self.report({'ERROR'}, f"New range ({new_start}-{new_end}) must be within original domain range ({original_domain.start}-{original_domain.end}).")
            return {'CANCELLED'}
        
        if new_start == original_domain.start and new_end == original_domain.end:
            self.report({'INFO'}, "Split range is identical to the original domain. No action taken.")
            return {'CANCELLED'} # Or FINISHED, depending on desired behavior for no-op

        # Call the MoleculeWrapper method to perform the split
        # The split_domain method will handle creating new domains and managing gaps.
        new_domain_ids = molecule.split_domain(
            original_domain_id=self.domain_id,
            split_start=new_start,
            split_end=new_end
        )

        if new_domain_ids:
            self.report({'INFO'}, f"Domain {self.domain_id} split into: {', '.join(new_domain_ids)}.")
            # Optionally, select the first new domain or expand it in the UI
            if new_domain_ids[0] in molecule.domains and molecule.domains[new_domain_ids[0]].object:
                molecule.domains[new_domain_ids[0]].object["domain_expanded"] = True
        else:
            self.report({'ERROR'}, "Failed to split domain.")
            return {'CANCELLED'}

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
        name="Color",
        subtype='COLOR',
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
            
        # Get color. The scene-level domain colour picker is registered as
        # `temp_domain_color` (there is no `scene.domain_color`; reading it
        # raised AttributeError and broke this operator). An explicit `color`
        # operator argument still overrides it below.
        # Snapshot to a plain tuple: assigning the live RNA property array would
        # store a reference that reverts to the operator default once execute()
        # returns, so the domain would lose the colour just set.
        color = tuple(scene.temp_domain_color)
        if hasattr(self, "color") and self.color[0] >= 0:  # Check if color parameter was provided
            color = tuple(self.color)
            
        print(f"1 Updating color for domain {self.domain_id} to {color}")
        # Update domain color
        success = molecule.update_domain_color(self.domain_id, color)
        if not success:
            self.report({'ERROR'}, "Failed to update domain color")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_name(Operator):
    bl_idname = "molecule.update_domain_name"
    bl_label = "Update Domain Name"
    bl_description = "Update the name of the selected domain"
    
    domain_id: StringProperty()
    name: StringProperty(default="")
    
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
        
        # Skip update if name hasn't changed
        if domain.name == self.name:
            return {'CANCELLED'}
            
        # Update the domain name
        domain.name = self.name
        
        # Also update the name in the object if it exists
        if domain.object:
            # Try setting the domain_name property first
            try:
                if hasattr(domain.object, "domain_name"):
                    domain.object.domain_name = self.name
                else:
                    domain.object["domain_name"] = self.name
                
                # Update the temp property used for editing
                if hasattr(domain.object, "temp_domain_name"):
                    domain.object.temp_domain_name = self.name
            except Exception as e:
                print(f"Warning: Could not set domain_name: {e}")
            
            # Update the object name to include the new domain name
            current_name = domain.object.name
            if "_" in current_name:
                # Extract the domain-specific part (after the domain name)
                suffix = current_name.split("_", 1)[1]
                # Create new name with the updated domain name
                domain.object.name = f"{self.name}_{suffix}"
            else:
                # If no underscore, just set the name directly
                domain.object.name = self.name
        
        self.report({'INFO'}, f"Domain name updated to '{self.name}'")
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
            
        # Update the parent domain ID using the molecule wrapper's method
        # Instead of calling domain.set_parent() which doesn't exist
        molecule._set_domain_parent(domain, self.parent_domain_id if self.parent_domain_id else None)

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
    bl_options = {'REGISTER', 'UNDO'}
    
    domain_id: StringProperty()

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Debug: Check if domain_id is being passed
        if not self.domain_id:
            self.report({'ERROR'}, "No domain_id provided to reset operator")
            return {'CANCELLED'}
        
        # Find which molecule owns this domain
        molecule = None
        domain = None
        for mol_id, mol in scene_manager.molecules.items():
            if self.domain_id in mol.domains:
                molecule = mol
                domain = mol.domains[self.domain_id]
                break
        
        if not molecule or not domain:
            self.report({'ERROR'}, f"Domain '{self.domain_id}' not found in any molecule")
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
                
                # Apply the matrix to reset the transform
                domain.object.matrix_local = initial_matrix
                
                # Force viewport update to show the change immediately
                context.view_layer.update()
                
                self.report({'INFO'}, f"Reset transform for domain {domain.name}")
                return {'FINISHED'}
                
            except Exception as e:
                print(f"Error restoring initial matrix: {e}")
                # Fall through to fallback method below
        
        # Fallback: If no stored matrix or it failed, compute relative position
        # This is better than resetting to (0,0,0) which puts it at world origin
        if domain.object.parent:
            # Domain has a parent, so reset to identity transform relative to parent
            domain.object.location = (0, 0, 0)
            domain.object.rotation_euler = (0, 0, 0)
            domain.object.scale = (1, 1, 1)
            self.report({'INFO'}, f"Reset {domain.name} relative to parent")
        else:
            # No parent, reset to world origin
            domain.object.location = (0, 0, 0)
            domain.object.rotation_euler = (0, 0, 0)
            domain.object.scale = (1, 1, 1)
            self.report({'INFO'}, f"Reset {domain.name} to origin")
        
        # Force viewport update
        context.view_layer.update()
        
        return {'FINISHED'}

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

        # Find the Cα position using the helper function on the molecule object
        # This now returns world space coordinates with our fix
        alpha_carbon_pos = molecule._find_residue_alpha_carbon_pos(context, domain, self.target_residue)

        if alpha_carbon_pos is None:
            self.report({'ERROR'}, f"Could not find Alpha Carbon for {self.target_residue} residue ({domain.start if self.target_residue == 'START' else domain.end}).")
            return {'CANCELLED'}

        # Set the origin using the world space position from the above helper
        if not molecule._set_domain_origin_and_update_matrix(context, domain, alpha_carbon_pos):
            self.report({'ERROR'}, "Failed to set domain origin.")
            return {'CANCELLED'}

        # Report success
        self.report({'INFO'}, f"Set pivot to {self.target_residue} residue's Alpha Carbon.")
        return {'FINISHED'}

# New dialog operator that looks like a text field but opens a dialog
class MOLECULE_PB_OT_update_domain_name_dialog(Operator):
    bl_idname = "molecule.update_domain_name_dialog"
    bl_label = "Edit Domain Name"
    bl_description = "Edit the name of this domain"
    
    domain_id: StringProperty()
    name: StringProperty(name="Name", description="Enter new name for the domain")
    
    def invoke(self, context, event):
        # Get the current domain name
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        if molecule and self.domain_id in molecule.domains:
            domain = molecule.domains[self.domain_id]
            self.name = domain.name
        
        # Show the dialog
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
    
    def execute(self, context):
        # Call the standard update operator with the new name
        bpy.ops.molecule.update_domain_name(domain_id=self.domain_id, name=self.name)
        return {'FINISHED'}

# Operator to initialize temp_domain_name (called from UI when needed)
class MOLECULE_PB_OT_initialize_domain_temp_name(Operator):
    bl_idname = "molecule.initialize_domain_temp_name"
    bl_label = "Initialize Domain Name Field"
    bl_description = "Initialize the domain name editing field"
    bl_options = {'INTERNAL'}  # Internal operator, not shown in UI
    
    domain_id: StringProperty(description="The ID of the domain to initialize")
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        
        if not molecule or self.domain_id not in molecule.domains:
            return {'CANCELLED'}
            
        domain = molecule.domains[self.domain_id]
        if domain.object and hasattr(domain.object, "temp_domain_name"):
            # Only set the temp name if it's empty
            if not domain.object.temp_domain_name:
                domain.object.temp_domain_name = domain.name
                
        return {'FINISHED'}

# List of all operator classes in this file
classes = (
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_update_domain,
    MOLECULE_PB_OT_copy_domain,
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_protein,
    MOLECULE_PB_OT_toggle_domain_expanded,
    MOLECULE_PB_OT_update_domain_ui_values,
    MOLECULE_PB_OT_update_domain_color,
    MOLECULE_PB_OT_update_domain_name,
    MOLECULE_PB_OT_update_domain_style,
    MOLECULE_PB_OT_toggle_pivot_edit,
    MOLECULE_PB_OT_set_parent_domain,
    MOLECULE_PB_OT_update_parent_domain,
    MOLECULE_PB_OT_reset_domain_transform,
    MOLECULE_PB_OT_snap_pivot_to_residue,
    MOLECULE_PB_OT_update_domain_name_dialog,
    MOLECULE_PB_OT_initialize_domain_temp_name,
    MOLECULE_PB_OT_select_keyframe,
    MOLECULE_PB_OT_delete_keyframe,
    MOLECULE_PB_OT_edit_keyframe,
    MOLECULE_PB_OT_split_domain
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

