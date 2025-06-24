import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene
from mathutils import Vector
import random

# Ensure domain properties are registered
from ..core.domain import ensure_domain_properties_registered
ensure_domain_properties_registered()

def bake_brownian(op, context, molecule, start_frame, end_frame, intensity, frequency, seed, resolution):
    """Bake Brownian motion keyframes between two frames using linear interpolation + jitter"""
    random.seed(seed)
    scene = context.scene
    
    # Collect all objects to animate: protein + all domain objects
    objects_to_animate = []
    if molecule.object:
        objects_to_animate.append(molecule.object)
    
    # Add all domain objects
    for domain_id, domain in molecule.domains.items():
        if domain.object:
            objects_to_animate.append(domain.object)
    
    # For each object, store starting and ending transforms
    object_transforms = {}
    
    # Sample starting transforms
    scene.frame_current = start_frame
    context.view_layer.update()
    for obj in objects_to_animate:
        object_transforms[obj.name] = {
            'start_loc': obj.location.copy(),
            'start_rot': obj.rotation_euler.copy(),
            'start_scale': obj.scale.copy()
        }
    
    # Sample ending transforms
    scene.frame_current = end_frame
    context.view_layer.update()
    for obj in objects_to_animate:
        object_transforms[obj.name].update({
            'end_loc': obj.location.copy(),
            'end_rot': obj.rotation_euler.copy(),
            'end_scale': obj.scale.copy()
        })
    
    duration = end_frame - start_frame
    for f in range(start_frame + resolution, end_frame, resolution):
        t = (f - start_frame) / duration
        scene.frame_current = f
        
        # Apply Brownian motion to each object
        for obj in objects_to_animate:
            transforms = object_transforms[obj.name]
            start_loc = transforms['start_loc']
            start_rot = transforms['start_rot']
            start_scale = transforms['start_scale']
            end_loc = transforms['end_loc']
            end_rot = transforms['end_rot']
            end_scale = transforms['end_scale']
            
            # Linear interpolation
            loc = start_loc.lerp(end_loc, t)
            rot = start_rot.copy()
            rot.x += (end_rot.x - start_rot.x) * t
            rot.y += (end_rot.y - start_rot.y) * t
            rot.z += (end_rot.z - start_rot.z) * t
            scale = start_scale.lerp(end_scale, t)
            
            # Jitter (use different random values for each object)
            random.seed(seed + hash(obj.name))  # Different seed per object for variety
            loc += Vector((random.uniform(-intensity, intensity),
                           random.uniform(-intensity, intensity),
                           random.uniform(-intensity, intensity)))
            rot.x += random.uniform(-intensity, intensity)
            rot.y += random.uniform(-intensity, intensity)
            rot.z += random.uniform(-intensity, intensity)
            
            # Apply and keyframe
            obj.location = loc
            obj.rotation_euler = rot
            obj.scale = scale
            obj.keyframe_insert(data_path="location", frame=f)
            obj.keyframe_insert(data_path="rotation_euler", frame=f)
            obj.keyframe_insert(data_path="scale", frame=f)
    
    # Restore end frame
    scene.frame_current = end_frame
    context.view_layer.update()

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
        domain_id = molecule.create_domain(
            chain_id=scene.new_domain_chain,  # Use the chain selected in UI
            start=scene.new_domain_start,  # Use the start value from UI
            end=scene.new_domain_end  # Use the end value from UI
        )
        
        if domain_id is None:
            self.report({'ERROR'}, "Failed to create domain via MoleculeWrapper")
            return {'CANCELLED'}
            
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

class MOLECULE_PB_OT_keyframe_protein(Operator):
    bl_idname = "molecule.keyframe_protein"
    bl_label = "Keyframe Protein"
    bl_description = "Add keyframes for the protein and all its domains' transforms at the current frame"
    bl_options = {'REGISTER', 'UNDO'}
    # Dialog properties
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
    use_brownian_motion: BoolProperty(
        name="Use Brownian Motion",
        description="Use Brownian motion for animation to this keyframe from the previous keyframe",
        default=True
    )
    intensity: FloatProperty(
        name="Intensity",
        description="Max random offset magnitude",
        default=0.5,
        min=0.0
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Frequency of motion",
        default=0.4,
        min=0.0
    )
    seed: IntProperty(
        name="Seed",
        description="Random seed for reproducibility",
        default=0,
        min=0
    )
    resolution: IntProperty(
        name="Resolution",
        description="Frame step for Brownian bake",
        default=2,
        min=1
    )
    def invoke(self, context, event):
        scene = context.scene
        # Default to current frame for keyframe insertion
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
        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "keyframe_name")
        layout.prop(self, "frame_number")
        
        # Show Brownian motion toggle only for keyframes after the first one
        sel_id = context.scene.selected_molecule_id
        has_previous_keyframe = False
        for item in context.scene.molecule_list_items:
            if item.identifier == sel_id and len(item.keyframes) > 0:
                has_previous_keyframe = True
                break
        
        if has_previous_keyframe:
            layout.separator()
            layout.prop(self, "use_brownian_motion")
        
        # Brownian motion parameters (only show if enabled)
        if not has_previous_keyframe or self.use_brownian_motion:
            col = layout.column()
            col.enabled = not has_previous_keyframe or self.use_brownian_motion
            col.prop(self, "intensity")
            col.prop(self, "frequency")
            col.prop(self, "seed")
            col.prop(self, "resolution")

    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        
        # Use dialog inputs
        frame_to_use = self.frame_number
        name_to_use = self.keyframe_name.strip() or f"Frame {frame_to_use}"
        
        # Collect all objects to keyframe: protein + all domain objects
        objects_to_keyframe = []
        if molecule.object:
            objects_to_keyframe.append(molecule.object)
        
        # Add all domain objects to capture their poses
        for domain_id, domain in molecule.domains.items():
            if domain.object:
                objects_to_keyframe.append(domain.object)
        
        # Keyframe all objects (protein and domain transforms)
        keyframed_count = 0
        for obj in objects_to_keyframe:
            obj.keyframe_insert(data_path="location", frame=frame_to_use)
            obj.keyframe_insert(data_path="rotation_euler", frame=frame_to_use)
            obj.keyframe_insert(data_path="scale", frame=frame_to_use)
            # Adjust interpolation
            if obj.animation_data and obj.animation_data.action:
                for fcurve in obj.animation_data.action.fcurves:
                    for kp in fcurve.keyframe_points:
                        if kp.co.x == frame_to_use:
                            kp.interpolation = 'BEZIER'
            keyframed_count += 1
        
        keyframed_domains = len(molecule.domains)

        # Record keyframe in the UI list
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                # Create new keyframe entry and store parameters
                new_kf = item.keyframes.add()
                new_kf.frame = frame_to_use
                new_kf.name = name_to_use
                new_kf.use_brownian_motion = self.use_brownian_motion
                new_kf.intensity = self.intensity
                new_kf.frequency = self.frequency
                new_kf.seed = self.seed
                new_kf.resolution = self.resolution
                item.active_keyframe_index = len(item.keyframes) - 1
                # Bake Brownian motion if there's a previous keyframe and brownian motion is enabled
                prev_idx = item.active_keyframe_index - 1
                if prev_idx >= 0 and new_kf.use_brownian_motion:
                    prev_kf = item.keyframes[prev_idx]
                    bake_brownian(
                        self, context, molecule,
                        prev_kf.frame, new_kf.frame,
                        new_kf.intensity, new_kf.frequency,
                        new_kf.seed, new_kf.resolution
                    )
                break
        
        # Force timeline refresh to show new keyframes
        self._refresh_timeline()
        
        self.report({'INFO'}, f"Added keyframes for {keyframed_count} objects ({1 if molecule.object else 0} protein + {keyframed_domains} domains) at frame {frame_to_use}")
        return {'FINISHED'}
    
    def _refresh_timeline(self):
        """Force refresh of Blender's timeline and UI"""
        import bpy
        # Update the scene to refresh the timeline
        bpy.context.view_layer.update()
        # Force redraw of timeline and other areas
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ['TIMELINE', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'VIEW_3D', 'PROPERTIES']:
                    area.tag_redraw()
        
        # Also update the scene frame to trigger refresh
        current_frame = bpy.context.scene.frame_current
        bpy.context.scene.frame_set(current_frame)

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
            # Find and delete both UI entry and timeline keyframes
            for item in scene.molecule_list_items:
                if item.identifier == scene.selected_molecule_id:
                    idx = self.keyframe_index
                    if idx < 0 or idx >= len(item.keyframes):
                        self.report({'ERROR'}, f"Invalid keyframe index: {idx}")
                        return {'CANCELLED'}
                    
                    # Get surrounding keyframes before removing the current one
                    prev_kf = item.keyframes[idx-1] if idx > 0 else None
                    next_kf = item.keyframes[idx+1] if idx < len(item.keyframes) - 1 else None
                    deleted_kf = item.keyframes[idx]  # Store reference to deleted keyframe
                    
                    # Store the frame number of the keyframe we're deleting
                    deleted_frame = deleted_kf.frame
                    
                    # Get objects to clean up - collect all objects first
                    all_objects = [molecule.object] if molecule.object else []
                    for domain_id, domain in molecule.domains.items():
                        if domain.object:
                            all_objects.append(domain.object)
                    
                    objs_with_anim = [obj for obj in all_objects if obj and obj.animation_data and obj.animation_data.action]
                    
                    # COMPREHENSIVE CLEANUP: Remove ALL intermediate frames involving the deleted keyframe
                    
                    # 1. If there's a previous keyframe, clean up the prev->deleted segment
                    if prev_kf:
                        # The resolution used for prev->deleted was the deleted keyframe's resolution
                        res = deleted_kf.resolution
                        self._safe_delete_keyframes_in_range(objs_with_anim, prev_kf.frame + res, deleted_frame, res)
                    
                    # 2. If there's a next keyframe, clean up the deleted->next segment  
                    if next_kf:
                        # The resolution used for deleted->next was the next keyframe's resolution
                        res = next_kf.resolution
                        self._safe_delete_keyframes_in_range(objs_with_anim, deleted_frame + res, next_kf.frame, res)
                    
                    # 3. Delete the keyframe at the deleted frame itself
                    self._safe_delete_keyframes_at_frame(objs_with_anim, deleted_frame, refresh=False)
                    
                    # Remove the deleted keyframe from UI list
                    item.keyframes.remove(idx)
                    
                    # 4. If we have both prev and next, re-bake the new prev->next segment
                    if prev_kf and next_kf and next_kf.use_brownian_motion:
                        bake_brownian(
                            self, context, molecule,
                            prev_kf.frame, next_kf.frame,
                            next_kf.intensity, next_kf.frequency,
                            next_kf.seed, next_kf.resolution
                        )
                    
                    # 5. Final cleanup of any orphaned keyframes
                    self._cleanup_orphaned_keyframes(objs_with_anim, item.keyframes)
                    
                    # Adjust active index after deletion
                    if item.active_keyframe_index >= len(item.keyframes):
                        item.active_keyframe_index = max(len(item.keyframes) - 1, 0)
                    
                    # Final timeline refresh
                    self._refresh_timeline()
                    break
            
            self.report({'INFO'}, f"Deleted keyframe at frame {deleted_frame}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete keyframe: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def _safe_delete_keyframes_in_range(self, objects, start_frame, end_frame, step):
        """Safely delete keyframes in a frame range, skipping objects without animation data"""
        # Validate inputs
        if start_frame >= end_frame or step <= 0:
            return
            
        # Delete keyframes frame by frame within the range
        for f in range(start_frame, end_frame, step):
            # Skip if we've reached or exceeded the end frame
            if f >= end_frame:
                break
            self._safe_delete_keyframes_at_frame(objects, f)
    
    def _safe_delete_keyframes_at_frame(self, objects, frame, refresh=True):
        """Safely delete keyframes at a specific frame, skipping objects without animation data"""
        for obj in objects:
            if not (obj and obj.animation_data and obj.animation_data.action):
                continue
                
            # List of data paths to try deleting
            data_paths = ["location", "rotation_euler", "scale"]
            
            for data_path in data_paths:
                try:
                    obj.keyframe_delete(data_path=data_path, frame=frame)
                except RuntimeError:
                    # Keyframe doesn't exist at this frame - this is expected and not an error
                    pass
                except Exception as e:
                    # Log unexpected errors but don't stop processing
                    print(f"Unexpected error deleting {data_path} keyframe at frame {frame} for object {obj.name}: {str(e)}")
            
            # Also try deleting quaternion rotation if it exists
            try:
                obj.keyframe_delete(data_path="rotation_quaternion", frame=frame)
            except RuntimeError:
                pass  # Quaternion rotation not used or doesn't exist
            except Exception as e:
                print(f"Unexpected error deleting rotation_quaternion keyframe at frame {frame} for object {obj.name}: {str(e)}")
        
        # Force timeline refresh only when requested
        if refresh:
            self._refresh_timeline()
    
    def _cleanup_orphaned_keyframes(self, objects, remaining_keyframes):
        """Clean up any keyframes that don't belong to the remaining keyframe list"""
        # 1. Build the set of all valid frames (main keyframes and baked intermediate frames)
        valid_frames = set()
        for kf in remaining_keyframes:
            valid_frames.add(kf.frame)
        
        if len(remaining_keyframes) >= 2:
            for i in range(len(remaining_keyframes) - 1):
                start_kf = remaining_keyframes[i]
                end_kf = remaining_keyframes[i+1]
                if end_kf.use_brownian_motion:
                    res = end_kf.resolution
                    if res > 0:
                        for f in range(start_kf.frame + res, end_kf.frame, res):
                            valid_frames.add(f)

        # 2. For each object, find all frames that exist but shouldn't, and remove them.
        for obj in objects:
            if not (obj and obj.animation_data and obj.animation_data.action):
                continue
            
            action = obj.animation_data.action
            
            # Find all frames present in the animation data for this object
            present_frames = set()
            for fcurve in action.fcurves:
                if fcurve.data_path in ["location", "rotation_euler", "scale", "rotation_quaternion"]:
                    for kf in fcurve.keyframe_points:
                        present_frames.add(int(kf.co.x))
            
            # Determine which frames are orphaned
            orphaned_frames = present_frames - valid_frames
            
            # Remove the keyframes at these orphaned frames
            if orphaned_frames:
                for frame in orphaned_frames:
                    self._safe_delete_keyframes_at_frame([obj], frame, refresh=False)

    def _refresh_timeline(self):
        """Force refresh of Blender's timeline and UI"""
        import bpy
        # Update the scene to refresh the timeline
        bpy.context.view_layer.update()
        # Force redraw of timeline and other areas
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ['TIMELINE', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'VIEW_3D', 'PROPERTIES']:
                    area.tag_redraw()
        
        # Also update the scene frame to trigger refresh
        current_frame = bpy.context.scene.frame_current
        bpy.context.scene.frame_set(current_frame)

class MOLECULE_PB_OT_edit_keyframe(Operator):
    bl_idname = "molecule.edit_keyframe"
    bl_label = "Edit Keyframe"
    bl_description = "Edit parameters of an existing keyframe and re-bake Brownian motion"
    bl_options = {'REGISTER', 'UNDO'}
    keyframe_index: IntProperty()
    keyframe_name: StringProperty(name="Name")
    frame_number: IntProperty(name="Frame", min=1)
    use_brownian_motion: BoolProperty(name="Use Brownian Motion")
    intensity: FloatProperty(name="Intensity", min=0.0)
    frequency: FloatProperty(name="Frequency", min=0.0)
    seed: IntProperty(name="Seed", min=0)
    resolution: IntProperty(name="Resolution", min=1)

    def invoke(self, context, event):
        scene = context.scene
        # Load existing values
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                kf = item.keyframes[self.keyframe_index]
                self.keyframe_name = kf.name
                self.frame_number = kf.frame
                self.use_brownian_motion = kf.use_brownian_motion
                self.intensity = kf.intensity
                self.frequency = kf.frequency
                self.seed = kf.seed
                self.resolution = kf.resolution
                break
        return context.window_manager.invoke_props_dialog(self)
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "keyframe_name")
        layout.prop(self, "frame_number")
        
        # Show Brownian motion toggle only for keyframes that aren't the first one
        if self.keyframe_index > 0:
            layout.separator()
            layout.prop(self, "use_brownian_motion")
        
        # Brownian motion parameters (only show if enabled)
        if self.keyframe_index == 0 or self.use_brownian_motion:
            col = layout.column()
            col.enabled = self.keyframe_index == 0 or self.use_brownian_motion
            col.prop(self, "intensity")
            col.prop(self, "frequency")
            col.prop(self, "seed")
            col.prop(self, "resolution")
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
        # Find and update the keyframe entry
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                kf = item.keyframes[self.keyframe_index]
                old_frame = kf.frame
                # Delete old timeline keyframes
                targets = [molecule.object] + list(molecule.object.children_recursive)
                for obj in targets:
                    try:
                        obj.keyframe_delete(data_path="location", frame=old_frame)
                        obj.keyframe_delete(data_path="rotation_euler", frame=old_frame)
                        obj.keyframe_delete(data_path="scale", frame=old_frame)
                    except:
                        pass
                # Update properties
                kf.name = self.keyframe_name
                kf.frame = self.frame_number
                kf.use_brownian_motion = self.use_brownian_motion
                kf.intensity = self.intensity
                kf.frequency = self.frequency
                kf.seed = self.seed
                kf.resolution = self.resolution
                
                # Clear intermediate keyframes for segments that will be re-baked
                prev_idx = self.keyframe_index - 1
                next_idx = self.keyframe_index + 1
                
                # Re-bake Brownian before this keyframe (if enabled)
                if prev_idx >= 0:
                    prev_kf = item.keyframes[prev_idx]
                    # Clear intermediate keyframes
                    kf._clear_intermediate_keyframes(molecule, prev_kf.frame, kf.frame)
                    if kf.use_brownian_motion:
                        bake_brownian(
                            self, context, molecule,
                            prev_kf.frame, kf.frame,
                            kf.intensity, kf.frequency,
                            kf.seed, kf.resolution
                        )
                
                # Re-bake Brownian after this keyframe (if next keyframe has brownian enabled)
                if next_idx < len(item.keyframes):
                    next_kf = item.keyframes[next_idx]
                    # Clear intermediate keyframes
                    next_kf._clear_intermediate_keyframes(molecule, kf.frame, next_kf.frame)
                    if next_kf.use_brownian_motion:
                        bake_brownian(
                            self, context, molecule,
                            kf.frame, next_kf.frame,
                            next_kf.intensity, next_kf.frequency,
                            next_kf.seed, next_kf.resolution
                        )
                break
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

