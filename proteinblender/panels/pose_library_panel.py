"""Pose Library Panel for ProteinBlender - Simplified Group-Based System"""

import bpy
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, CollectionProperty, PointerProperty
from datetime import datetime


class GroupSelectionItem(PropertyGroup):
    """Helper class to store group selection state"""
    group_id: StringProperty(name="Group ID")
    group_name: StringProperty(name="Group Name")
    selected: BoolProperty(name="Selected", default=False)


class PROTEINBLENDER_OT_create_pose(Operator):
    """Create a new pose from selected groups"""
    bl_idname = "proteinblender.create_pose"
    bl_label = "Create Pose"
    bl_description = "Save current positions of selected groups as a new pose"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_name: StringProperty(
        name="Pose Name",
        description="Name for the new pose",
        default="New Pose"
    )
    
    def invoke(self, context, event):
        # Set default pose name based on count
        pose_count = 0
        if hasattr(context.scene, 'pose_library'):
            pose_count = len(context.scene.pose_library)
        self.pose_name = f"Pose {pose_count + 1}"
        
        # Store available groups as a simple list for this operator instance
        self.available_groups = []
        self.selected_groups = {}  # Dictionary to track selected state
        
        # Get available groups
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_type == 'GROUP' and item.item_id != "groups_separator":
                    self.available_groups.append({
                        'id': item.item_id,
                        'name': item.name
                    })
                    # Initialize all groups as selected by default
                    self.selected_groups[item.item_id] = True
        
        if not self.available_groups:
            self.report({'WARNING'}, "No groups available. Create groups first.")
            return {'CANCELLED'}
        
        # Store this instance for the toggle operator
        if not hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            PROTEINBLENDER_OT_create_pose._active_instances = {}
        PROTEINBLENDER_OT_create_pose._active_instances[str(id(self))] = self
        
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        
        # Pose name
        layout.prop(self, "pose_name")
        
        # Group selection with checkboxes
        layout.separator()
        layout.label(text="Select Groups to Include:", icon='GROUP')
        
        # Create a box for the group list
        box = layout.box()
        col = box.column(align=True)
        
        # Display each group as a checkbox using operator button toggles
        for group in self.available_groups:
            row = col.row(align=True)
            # Use toggle buttons to simulate checkboxes
            icon = 'CHECKBOX_HLT' if self.selected_groups.get(group['id'], False) else 'CHECKBOX_DEHLT'
            op = row.operator('proteinblender.toggle_group_selection', text=group['name'], icon=icon, emboss=False)
            op.group_id = group['id']
            op.operator_instance_id = str(id(self))  # Pass operator instance ID
        
        if not self.available_groups:
            col.label(text="No groups available", icon='INFO')
    
    def check(self, context):
        # This method is called when properties change
        return True
    
    def execute(self, context):
        scene = context.scene
        
        # Ensure pose_library exists
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        # Collect selected groups
        selected_ids = []
        selected_names = []
        
        for group in self.available_groups:
            if self.selected_groups.get(group['id'], False):
                selected_ids.append(group['id'])
                selected_names.append(group['name'])
        
        if not selected_ids:
            self.report({'WARNING'}, "No groups selected. Please select at least one group.")
            return {'CANCELLED'}
        
        # Clean up stored instance
        if hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            instance_id = str(id(self))
            if instance_id in PROTEINBLENDER_OT_create_pose._active_instances:
                del PROTEINBLENDER_OT_create_pose._active_instances[instance_id]
        
        # Create new pose
        pose = scene.pose_library.add()
        pose.name = self.pose_name
        pose.group_ids = ','.join(selected_ids)
        pose.group_names = ', '.join(selected_names)
        pose.created_timestamp = datetime.now().isoformat()
        pose.modified_timestamp = pose.created_timestamp
        
        # Capture transforms for each group
        print(f"\nDebug: Creating pose '{self.pose_name}'")
        print(f"Debug: Selected group IDs: {selected_ids}")
        
        for group_id in selected_ids:
            print(f"Debug: Processing group {group_id}")
            try:
                # Get objects in this group
                objects = self.get_group_objects(context, group_id)
                print(f"Debug: Group {group_id} has {len(objects)} objects")
                
                if not objects:
                    print(f"Debug: WARNING - No objects found for group {group_id}")
                    # Try to understand why
                    for item in context.scene.outliner_items:
                        if item.item_id == group_id and item.item_type == 'GROUP':
                            print(f"  Group members: {item.group_memberships}")
                            break
                
                for obj in objects:
                    transform = pose.transforms.add()
                    transform.group_id = group_id
                    # Find the group name
                    group_name = next((g['name'] for g in self.available_groups 
                                     if g['id'] == group_id), group_id)
                    transform.group_name = group_name
                    transform.object_name = obj.name
                    
                    # Store absolute positions (we'll calculate relative later if needed)
                    transform.location = obj.location.copy()
                    transform.rotation_euler = obj.rotation_euler.copy()
                    transform.scale = obj.scale.copy()
                    
                    # Calculate and print relative position to parent
                    parent_obj = obj.parent
                    if parent_obj:
                        # Calculate relative position to parent
                        relative_loc = obj.location - parent_obj.location
                        print(f"  Stored: {obj.name}")
                        print(f"    Absolute location: {list(obj.location)}")
                        print(f"    Parent: {parent_obj.name} at {list(parent_obj.location)}")
                        print(f"    Relative to parent: {list(relative_loc)}")
                    else:
                        print(f"  Stored: {obj.name}")
                        print(f"    Absolute location: {list(obj.location)}")
                        print(f"    No parent object")
            except Exception as e:
                print(f"Debug: ERROR processing group {group_id}: {e}")
                import traceback
                traceback.print_exc()
        
        # Capture screenshot preview
        self.capture_pose_preview(context, pose)
        
        # Set as active
        if hasattr(scene, 'active_pose_index'):
            scene.active_pose_index = len(scene.pose_library) - 1
        
        self.report({'INFO'}, f"Created pose '{self.pose_name}' with {len(selected_ids)} group(s)")
        return {'FINISHED'}
    
    def capture_pose_preview(self, context, pose):
        """Capture a preview image for the pose"""
        try:
            import os
            import tempfile
            from pathlib import Path
            
            # Create temp directory for pose previews if it doesn't exist
            temp_dir = Path(tempfile.gettempdir()) / "proteinblender_poses"
            temp_dir.mkdir(exist_ok=True)
            
            # Generate filename based on pose name and timestamp
            import time
            timestamp = str(int(time.time()))
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in pose.name)
            preview_file = temp_dir / f"pose_{safe_name}_{timestamp}.png"
            
            # Store current render settings
            old_path = context.scene.render.filepath
            old_format = context.scene.render.image_settings.file_format
            old_res_x = context.scene.render.resolution_x
            old_res_y = context.scene.render.resolution_y
            old_percentage = context.scene.render.resolution_percentage
            
            # Configure render for thumbnail
            context.scene.render.filepath = str(preview_file)
            context.scene.render.image_settings.file_format = 'PNG'
            context.scene.render.resolution_x = 256
            context.scene.render.resolution_y = 256
            context.scene.render.resolution_percentage = 100
            
            # Render viewport preview
            bpy.ops.render.opengl(write_still=True, view_context=True)
            
            # Restore render settings
            context.scene.render.filepath = old_path
            context.scene.render.image_settings.file_format = old_format
            context.scene.render.resolution_x = old_res_x
            context.scene.render.resolution_y = old_res_y
            context.scene.render.resolution_percentage = old_percentage
            
            # Store the preview path in the pose
            pose.preview_path = str(preview_file)
            
        except Exception as e:
            print(f"Warning: Could not capture pose preview: {e}")
    
    def get_group_objects(self, context, group_id):
        """Get all objects that belong to a group"""
        objects = []
        
        # Find group item
        group_item = None
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_id == group_id and item.item_type == 'GROUP':
                    group_item = item
                    break
        
        if not group_item or not hasattr(group_item, 'group_memberships'):
            print(f"Debug: No group found or no memberships for group {group_id}")
            return objects
        
        if not group_item.group_memberships:
            print(f"Debug: Empty memberships for group {group_id}")
            return objects
        
        # Parse member IDs and find corresponding objects
        member_ids = group_item.group_memberships.split(',')
        print(f"Debug: Group '{group_item.name}' has members: {member_ids}")
        
        # Import scene manager to access molecules
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        for member_id in member_ids:
            # Member IDs are in format: molecule_id_domain_id
            # where molecule_id might contain underscores (e.g., '3b75_001')
            # and domain_id is like 'chain_8' or a custom domain ID
            
            if '_' in member_id:
                # Try to intelligently parse the member_id
                # Look for patterns like 'XXX_###_chain_Y' or 'XXX_###_domain_id'
                
                # First, check if it contains '_chain_'
                if '_chain_' in member_id:
                    # Split at '_chain_' to separate molecule_id from chain identifier
                    parts = member_id.rsplit('_chain_', 1)
                    mol_id = parts[0]
                    domain_id = 'chain_' + parts[1]
                else:
                    # For custom domains, we need to find where molecule_id ends
                    # Molecule IDs typically follow pattern like '3b75_001'
                    # Try to find the last occurrence of a pattern like '_###_' (underscore, numbers, underscore)
                    import re
                    match = re.match(r'^(.+?_\d+)_(.+)$', member_id)
                    if match:
                        mol_id = match.group(1)
                        domain_id = match.group(2)
                    else:
                        # Fallback to splitting on last underscore
                        parts = member_id.rsplit('_', 1)
                        if len(parts) == 2:
                            mol_id = parts[0]
                            domain_id = parts[1]
                        else:
                            print(f"Debug: Could not parse member_id '{member_id}'")
                            continue
                
                print(f"Debug: Looking for mol_id='{mol_id}', domain_id='{domain_id}'")
                
                # Try to find the domain object (chains are domains too)
                if mol_id in scene_manager.molecules:
                    molecule = scene_manager.molecules[mol_id]
                    
                    # First try direct lookup
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        if domain.object:
                            objects.append(domain.object)
                            print(f"Debug: Found domain object '{domain.object.name}' for {member_id}")
                        else:
                            print(f"Debug: Domain {domain_id} has no object")
                    else:
                        # If domain_id is like 'chain_4', try to find the matching domain
                        if domain_id.startswith('chain_'):
                            chain_index = domain_id.replace('chain_', '')
                            print(f"Debug: Looking for chain index {chain_index}")
                            
                            # Find domain that starts with mol_id_chainindex_
                            found_domain = None
                            for dom_id, dom in molecule.domains.items():
                                # Check if domain ID starts with pattern like '3b75_001_4_'
                                if dom_id.startswith(f"{mol_id}_{chain_index}_"):
                                    found_domain = dom
                                    print(f"Debug: Matched chain_{chain_index} to domain {dom_id}")
                                    break
                            
                            if found_domain and found_domain.object:
                                objects.append(found_domain.object)
                                print(f"Debug: Found chain object '{found_domain.object.name}' for {member_id}")
                            else:
                                print(f"Debug: Could not find domain for chain_{chain_index}")
                                print(f"Debug: Available domains: {list(molecule.domains.keys())}")
                        else:
                            print(f"Debug: Domain {domain_id} not found in molecule {mol_id}")
                            print(f"Debug: Available domains: {list(molecule.domains.keys())}")
                else:
                    print(f"Debug: Molecule {mol_id} not found")
            
            # Fallback: look in outliner items for object_name
            # Check if we didn't find the object via domain lookup
            found_via_domain = False
            if objects and objects[-1] is not None:
                found_via_domain = True
            
            if not found_via_domain:
                for item in context.scene.outliner_items:
                    if item.item_id == member_id:
                        if item.object_name and item.object_name in bpy.data.objects:
                            obj = bpy.data.objects[item.object_name]
                            if obj not in objects:
                                objects.append(obj)
                                print(f"Debug: Found object via outliner '{obj.name}' for {member_id}")
                        else:
                            print(f"Debug: Outliner item {member_id} has object_name='{item.object_name}' but object not found in scene")
                        break
        
        print(f"Debug: Total objects found for group: {len(objects)}")
        return objects
    

class PROTEINBLENDER_OT_apply_pose(Operator):
    """Apply a saved pose to restore group positions"""
    bl_idname = "proteinblender.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Restore groups to their saved positions in this pose"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def execute(self, context):
        scene = context.scene
        
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
        
        pose = scene.pose_library[self.pose_index]
        applied_count = 0
        not_found = []
        
        print(f"\nDebug: Applying pose '{pose.name}'")
        print(f"Debug: Pose has {len(pose.transforms)} transforms")
        
        # Apply transforms
        for transform in pose.transforms:
            print(f"Debug: Looking for object '{transform.object_name}'")
            obj = bpy.data.objects.get(transform.object_name)
            if obj:
                print(f"Debug: Found object '{obj.name}'")
                
                # Get parent info
                parent_obj = obj.parent
                if parent_obj:
                    from mathutils import Vector
                    current_relative = obj.location - parent_obj.location
                    saved_relative = Vector(transform.location) - parent_obj.location
                    print(f"  Parent: {parent_obj.name} at {list(parent_obj.location)}")
                    print(f"  Current relative position: {list(current_relative)}")
                    print(f"  Saved relative position: {list(saved_relative)}")
                else:
                    print(f"  No parent object")
                    print(f"  Current absolute position: {list(obj.location)}")
                    print(f"  Saved absolute position: {list(transform.location)}")
                
                # Apply the saved transform
                obj.location = transform.location
                obj.rotation_euler = transform.rotation_euler
                obj.scale = transform.scale
                applied_count += 1
                
                print(f"  Applied transform - new location: {list(obj.location)}")
            else:
                print(f"Debug: Object '{transform.object_name}' NOT FOUND")
                not_found.append(transform.object_name)
        
        if not_found:
            print(f"Debug: Could not find objects: {not_found}")
            print(f"Debug: Available objects: {[obj.name for obj in bpy.data.objects if 'domain' in obj.name.lower() or 'chain' in obj.name.lower()][:10]}")
        
        self.report({'INFO'}, f"Applied pose '{pose.name}' ({applied_count}/{len(pose.transforms)} objects)")
        return {'FINISHED'}


class PROTEINBLENDER_OT_capture_pose(Operator):
    """Update pose with current group positions"""
    bl_idname = "proteinblender.capture_pose"
    bl_label = "Capture Pose"
    bl_description = "Update this pose with the current positions of its groups"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def execute(self, context):
        scene = context.scene
        
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
        
        pose = scene.pose_library[self.pose_index]
        
        # Clear existing transforms
        pose.transforms.clear()
        
        # Re-capture transforms for each group
        group_ids = pose.group_ids.split(',') if pose.group_ids else []
        
        for group_id in group_ids:
            # Get objects in this group
            objects = self.get_group_objects(context, group_id)
            
            for obj in objects:
                transform = pose.transforms.add()
                transform.group_id = group_id
                transform.object_name = obj.name
                transform.location = obj.location.copy()
                transform.rotation_euler = obj.rotation_euler.copy()
                transform.scale = obj.scale.copy()
        
        # Update timestamp
        pose.modified_timestamp = datetime.now().isoformat()
        
        # Update screenshot preview
        self.capture_pose_preview(context, pose)
        
        self.report({'INFO'}, f"Captured current positions for pose '{pose.name}'")
        return {'FINISHED'}
    
    def capture_pose_preview(self, context, pose):
        """Capture a preview image for the pose"""
        try:
            import os
            import tempfile
            from pathlib import Path
            
            # Create temp directory for pose previews if it doesn't exist
            temp_dir = Path(tempfile.gettempdir()) / "proteinblender_poses"
            temp_dir.mkdir(exist_ok=True)
            
            # Generate filename based on pose name and timestamp
            import time
            timestamp = str(int(time.time()))
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in pose.name)
            preview_file = temp_dir / f"pose_{safe_name}_{timestamp}.png"
            
            # Store current render settings
            old_path = context.scene.render.filepath
            old_format = context.scene.render.image_settings.file_format
            old_res_x = context.scene.render.resolution_x
            old_res_y = context.scene.render.resolution_y
            old_percentage = context.scene.render.resolution_percentage
            
            # Configure render for thumbnail
            context.scene.render.filepath = str(preview_file)
            context.scene.render.image_settings.file_format = 'PNG'
            context.scene.render.resolution_x = 256
            context.scene.render.resolution_y = 256
            context.scene.render.resolution_percentage = 100
            
            # Render viewport preview
            bpy.ops.render.opengl(write_still=True, view_context=True)
            
            # Restore render settings
            context.scene.render.filepath = old_path
            context.scene.render.image_settings.file_format = old_format
            context.scene.render.resolution_x = old_res_x
            context.scene.render.resolution_y = old_res_y
            context.scene.render.resolution_percentage = old_percentage
            
            # Store the preview path in the pose
            pose.preview_path = str(preview_file)
            
        except Exception as e:
            print(f"Warning: Could not capture pose preview: {e}")
    
    def get_group_objects(self, context, group_id):
        """Get all objects that belong to a group"""
        objects = []
        
        # Find group item
        group_item = None
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_id == group_id and item.item_type == 'GROUP':
                    group_item = item
                    break
        
        if not group_item or not hasattr(group_item, 'group_memberships'):
            print(f"Debug: No group found or no memberships for group {group_id}")
            return objects
        
        if not group_item.group_memberships:
            print(f"Debug: Empty memberships for group {group_id}")
            return objects
        
        # Parse member IDs and find corresponding objects
        member_ids = group_item.group_memberships.split(',')
        print(f"Debug: Group '{group_item.name}' has members: {member_ids}")
        
        # Import scene manager to access molecules
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        for member_id in member_ids:
            # Member IDs are in format: molecule_id_domain_id
            # where molecule_id might contain underscores (e.g., '3b75_001')
            # and domain_id is like 'chain_8' or a custom domain ID
            
            if '_' in member_id:
                # Try to intelligently parse the member_id
                # Look for patterns like 'XXX_###_chain_Y' or 'XXX_###_domain_id'
                
                # First, check if it contains '_chain_'
                if '_chain_' in member_id:
                    # Split at '_chain_' to separate molecule_id from chain identifier
                    parts = member_id.rsplit('_chain_', 1)
                    mol_id = parts[0]
                    domain_id = 'chain_' + parts[1]
                else:
                    # For custom domains, we need to find where molecule_id ends
                    # Molecule IDs typically follow pattern like '3b75_001'
                    # Try to find the last occurrence of a pattern like '_###_' (underscore, numbers, underscore)
                    import re
                    match = re.match(r'^(.+?_\d+)_(.+)$', member_id)
                    if match:
                        mol_id = match.group(1)
                        domain_id = match.group(2)
                    else:
                        # Fallback to splitting on last underscore
                        parts = member_id.rsplit('_', 1)
                        if len(parts) == 2:
                            mol_id = parts[0]
                            domain_id = parts[1]
                        else:
                            print(f"Debug: Could not parse member_id '{member_id}'")
                            continue
                
                print(f"Debug: Looking for mol_id='{mol_id}', domain_id='{domain_id}'")
                
                # Try to find the domain object (chains are domains too)
                if mol_id in scene_manager.molecules:
                    molecule = scene_manager.molecules[mol_id]
                    
                    # First try direct lookup
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        if domain.object:
                            objects.append(domain.object)
                            print(f"Debug: Found domain object '{domain.object.name}' for {member_id}")
                        else:
                            print(f"Debug: Domain {domain_id} has no object")
                    else:
                        # If domain_id is like 'chain_4', try to find the matching domain
                        if domain_id.startswith('chain_'):
                            chain_index = domain_id.replace('chain_', '')
                            print(f"Debug: Looking for chain index {chain_index}")
                            
                            # Find domain that starts with mol_id_chainindex_
                            found_domain = None
                            for dom_id, dom in molecule.domains.items():
                                # Check if domain ID starts with pattern like '3b75_001_4_'
                                if dom_id.startswith(f"{mol_id}_{chain_index}_"):
                                    found_domain = dom
                                    print(f"Debug: Matched chain_{chain_index} to domain {dom_id}")
                                    break
                            
                            if found_domain and found_domain.object:
                                objects.append(found_domain.object)
                                print(f"Debug: Found chain object '{found_domain.object.name}' for {member_id}")
                            else:
                                print(f"Debug: Could not find domain for chain_{chain_index}")
                                print(f"Debug: Available domains: {list(molecule.domains.keys())}")
                        else:
                            print(f"Debug: Domain {domain_id} not found in molecule {mol_id}")
                            print(f"Debug: Available domains: {list(molecule.domains.keys())}")
                else:
                    print(f"Debug: Molecule {mol_id} not found")
            
            # Fallback: look in outliner items for object_name
            # Check if we didn't find the object via domain lookup
            found_via_domain = False
            if objects and objects[-1] is not None:
                found_via_domain = True
            
            if not found_via_domain:
                for item in context.scene.outliner_items:
                    if item.item_id == member_id:
                        if item.object_name and item.object_name in bpy.data.objects:
                            obj = bpy.data.objects[item.object_name]
                            if obj not in objects:
                                objects.append(obj)
                                print(f"Debug: Found object via outliner '{obj.name}' for {member_id}")
                        else:
                            print(f"Debug: Outliner item {member_id} has object_name='{item.object_name}' but object not found in scene")
                        break
        
        print(f"Debug: Total objects found for group: {len(objects)}")
        return objects


class PROTEINBLENDER_OT_delete_pose(Operator):
    """Delete a saved pose"""
    bl_idname = "proteinblender.delete_pose"
    bl_label = "Delete Pose"
    bl_description = "Remove this pose from the library"
    bl_options = {'REGISTER', 'UNDO'}
    
    pose_index: IntProperty(name="Pose Index", default=0)
    
    def invoke(self, context, event):
        # Show confirmation dialog
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        scene = context.scene
        
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        if self.pose_index < 0 or self.pose_index >= len(scene.pose_library):
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
        
        pose_name = scene.pose_library[self.pose_index].name
        
        # Remove the pose
        scene.pose_library.remove(self.pose_index)
        
        # Adjust active index if needed
        if hasattr(scene, 'active_pose_index'):
            if scene.active_pose_index >= len(scene.pose_library):
                scene.active_pose_index = max(0, len(scene.pose_library) - 1)
        
        self.report({'INFO'}, f"Deleted pose '{pose_name}'")
        return {'FINISHED'}


# Placeholder operator to fix animation panel errors
class PROTEINBLENDER_OT_placeholder(Operator):
    """Placeholder for future functionality"""
    bl_idname = "proteinblender.placeholder"
    bl_label = "Coming Soon"
    bl_description = "This feature will be available in a future update"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        self.report({'INFO'}, "This feature is coming soon!")
        return {'FINISHED'}


class PROTEINBLENDER_PT_pose_library(Panel):
    """Panel for managing group poses"""
    bl_label = "Protein Pose Library"
    bl_idname = "PROTEINBLENDER_PT_pose_library"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 5  # Position after Group Maker
    
    # NO POLL METHOD - ALWAYS SHOW THE PANEL
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Create a box for the entire panel content (matching other panels)
        main_box = layout.box()
        
        # Add panel title inside the box
        main_box.label(text="Protein Pose Library", icon='ARMATURE_DATA')
        main_box.separator()
        
        # ALWAYS SHOW THE CREATE BUTTON - NO CONDITIONS
        header_row = main_box.row()
        header_row.scale_y = 1.2
        header_row.operator("proteinblender.create_pose", text="Create Pose", icon='ADD')
        
        # Check if pose_library exists
        if not hasattr(scene, 'pose_library'):
            error_box = main_box.box()
            error_box.label(text="Pose system not initialized", icon='ERROR')
            return
        
        # Check if there are poses
        if not scene.pose_library or len(scene.pose_library) == 0:
            info_box = main_box.box()
            info_box.label(text="No poses saved yet", icon='INFO')
            info_box.label(text="Click 'Create Pose' to save group positions")
            return
        
        main_box.separator()
        
        # Grid layout for pose cards
        grid = main_box.grid_flow(
            row_major=True,
            columns=2,  # 2 columns for better fit
            even_columns=True,
            even_rows=False,
            align=True
        )
        
        # Display each pose as a card
        for idx, pose in enumerate(scene.pose_library):
            # Create a box for each pose
            pose_box = grid.box()
            pose_col = pose_box.column()
            
            # Header with pose name
            header = pose_col.row()
            active_idx = getattr(scene, 'active_pose_index', 0)
            header.label(text=pose.name, icon='LAYER_ACTIVE' if idx == active_idx else 'LAYER_USED')
            
            # Groups label
            if pose.group_names:
                groups_box = pose_col.box()
                groups_box.scale_y = 0.8
                groups_box.label(text="Groups:", icon='GROUP')
                # Split long group lists into multiple lines
                group_names = pose.group_names.split(', ')
                for i in range(0, len(group_names), 2):
                    row = groups_box.row()
                    row.scale_y = 0.8
                    row.label(text=', '.join(group_names[i:i+2]))
            
            # Screenshot preview
            screenshot_box = pose_col.box()
            screenshot_box.scale_y = 3.0
            
            # Check if preview exists and display it
            if pose.preview_path:
                import os
                if os.path.exists(pose.preview_path):
                    # Try to load and display the preview image
                    try:
                        # Load image if not already loaded
                        import bpy.path
                        img_name = f"pose_preview_{idx}"
                        if img_name not in bpy.data.images:
                            img = bpy.data.images.load(pose.preview_path)
                            img.name = img_name
                        else:
                            img = bpy.data.images[img_name]
                            # Reload to get updates
                            img.reload()
                        
                        # Display using template_preview
                        screenshot_box.template_preview(img, show_buttons=False)
                    except Exception as e:
                        # Fallback to icon if image can't be loaded
                        screenshot_row = screenshot_box.row()
                        screenshot_row.alignment = 'CENTER'
                        screenshot_row.label(text="", icon='IMAGE_DATA')
                else:
                    # Preview file doesn't exist
                    screenshot_row = screenshot_box.row()
                    screenshot_row.alignment = 'CENTER'
                    screenshot_row.label(text="", icon='IMAGE_DATA')
            else:
                # No preview path set
                screenshot_row = screenshot_box.row()
                screenshot_row.alignment = 'CENTER'
                screenshot_row.label(text="", icon='IMAGE_DATA')
            
            # Action buttons
            button_row = pose_col.row(align=True)
            
            # Apply button
            apply_op = button_row.operator(
                "proteinblender.apply_pose",
                text="Apply"
            )
            apply_op.pose_index = idx
            
            # Capture button
            capture_op = button_row.operator(
                "proteinblender.capture_pose",
                text="Capture"
            )
            capture_op.pose_index = idx
            
            # Delete button
            delete_op = button_row.operator(
                "proteinblender.delete_pose",
                text="Delete",
                icon='X'
            )
            delete_op.pose_index = idx
            
            # Timestamp info
            if pose.modified_timestamp:
                info_row = pose_col.row()
                info_row.scale_y = 0.6
                info_row.label(text=f"Modified: {pose.modified_timestamp[:10]}")


class PROTEINBLENDER_OT_toggle_group_selection(Operator):
    """Toggle group selection in pose creation dialog"""
    bl_idname = "proteinblender.toggle_group_selection"
    bl_label = "Toggle Group Selection"
    bl_options = {'INTERNAL'}
    
    group_id: StringProperty()
    operator_instance_id: StringProperty()
    
    def execute(self, context):
        # Find the create_pose operator instance by ID
        if hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            instances = PROTEINBLENDER_OT_create_pose._active_instances
            if self.operator_instance_id in instances:
                instance = instances[self.operator_instance_id]
                # Toggle the selection state
                current = instance.selected_groups.get(self.group_id, False)
                instance.selected_groups[self.group_id] = not current
                # Force redraw
                for area in context.screen.areas:
                    area.tag_redraw()
                return {'FINISHED'}
        
        return {'CANCELLED'}


# Register classes
CLASSES = [
    GroupSelectionItem,  # Register the helper class first
    PROTEINBLENDER_OT_toggle_group_selection,  # Add toggle operator
    PROTEINBLENDER_OT_create_pose,
    PROTEINBLENDER_OT_apply_pose,
    PROTEINBLENDER_OT_capture_pose,
    PROTEINBLENDER_OT_delete_pose,
    PROTEINBLENDER_OT_placeholder,  # Added placeholder operator
    PROTEINBLENDER_PT_pose_library,
]


def register():
    """Register pose library panel classes"""
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister pose library panel classes"""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)