"""Pose Library Panel for ProteinBlender - Simplified Group-Based System"""

import bpy
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, CollectionProperty, PointerProperty
from datetime import datetime


class GroupSelectionItem(PropertyGroup):
    """Helper class to store puppet selection state"""
    puppet_id: StringProperty(name="Puppet ID")
    puppet_name: StringProperty(name="Puppet Name")
    selected: BoolProperty(name="Selected", default=False)


class PROTEINBLENDER_OT_create_pose(Operator):
    """Create a new pose from selected puppets"""
    bl_idname = "proteinblender.create_pose"
    bl_label = "Create Pose"
    bl_description = "Save current positions of selected puppets as a new pose"
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
        
        # Store available puppets as a simple list for this operator instance
        self.available_puppets = []
        self.selected_puppets = {}  # Dictionary to track selected state
        
        # Get available puppets
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                    self.available_puppets.append({
                        'id': item.item_id,
                        'name': item.name
                    })
                    # Initialize all puppets as selected by default
                    self.selected_puppets[item.item_id] = True
        
        if not self.available_puppets:
            self.report({'WARNING'}, "No puppets available. Create puppets first.")
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
        
        # Create a box for the puppet list
        box = layout.box()
        col = box.column(align=True)
        
        # Display each puppet as a checkbox using operator button toggles
        for puppet in self.available_puppets:
            row = col.row(align=True)
            # Use toggle buttons to simulate checkboxes
            icon = 'CHECKBOX_HLT' if self.selected_puppets.get(puppet['id'], False) else 'CHECKBOX_DEHLT'
            op = row.operator('proteinblender.toggle_puppet_selection', text=puppet['name'], icon=icon, emboss=False)
            op.puppet_id = puppet['id']
            op.operator_instance_id = str(id(self))  # Pass operator instance ID
        
        if not self.available_puppets:
            col.label(text="No puppets available", icon='INFO')
    
    def check(self, context):
        # This method is called when properties change
        return True
    
    def execute(self, context):
        scene = context.scene
        
        # Ensure pose_library exists
        if not hasattr(scene, 'pose_library'):
            self.report({'ERROR'}, "Pose library not initialized")
            return {'CANCELLED'}
        
        # Collect selected puppets
        selected_ids = []
        selected_names = []
        
        for puppet in self.available_puppets:
            if self.selected_puppets.get(puppet['id'], False):
                selected_ids.append(puppet['id'])
                selected_names.append(puppet['name'])
        
        if not selected_ids:
            self.report({'WARNING'}, "No puppets selected. Please select at least one puppet.")
            return {'CANCELLED'}
        
        # Clean up stored instance
        if hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            instance_id = str(id(self))
            if instance_id in PROTEINBLENDER_OT_create_pose._active_instances:
                del PROTEINBLENDER_OT_create_pose._active_instances[instance_id]
        
        # Create new pose
        pose = scene.pose_library.add()
        pose.name = self.pose_name
        pose.puppet_ids = ','.join(selected_ids)
        pose.puppet_names = ', '.join(selected_names)
        pose.created_timestamp = datetime.now().isoformat()
        pose.modified_timestamp = pose.created_timestamp
        
        # Capture transforms for each puppet
        print(f"\nDebug: Creating pose '{self.pose_name}'")
        print(f"Debug: Selected puppet IDs: {selected_ids}")
        
        for puppet_id in selected_ids:
            print(f"Debug: Processing puppet {puppet_id}")
            try:
                # Get objects in this puppet
                objects = self.get_puppet_objects(context, puppet_id)
                print(f"Debug: Group {puppet_id} has {len(objects)} objects")
                
                if not objects:
                    print(f"Debug: WARNING - No objects found for puppet {puppet_id}")
                    # Try to understand why
                    for item in context.scene.outliner_items:
                        if item.item_id == puppet_id and item.item_type == 'PUPPET':
                            print(f"  Group members: {item.puppet_memberships}")
                            break
                
                for obj in objects:
                    transform = pose.transforms.add()
                    transform.puppet_id = puppet_id
                    # Find the puppet name
                    puppet_name = next((g['name'] for g in self.available_puppets 
                                     if g['id'] == puppet_id), puppet_id)
                    transform.puppet_name = puppet_name
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
                print(f"Debug: ERROR processing puppet {puppet_id}: {e}")
                import traceback
                traceback.print_exc()
        
        # Capture screenshot preview
        self.capture_pose_preview(context, pose)
        
        # Set as active
        if hasattr(scene, 'active_pose_index'):
            scene.active_pose_index = len(scene.pose_library) - 1
        
        self.report({'INFO'}, f"Created pose '{self.pose_name}' with {len(selected_ids)} puppet(s)")
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
            
            # Load the image into Blender's data so it's available for display
            # This must be done here, not during drawing
            try:
                # Check if image already exists and remove it
                img_name = f"pose_preview_{safe_name}"
                if img_name in bpy.data.images:
                    old_img = bpy.data.images[img_name]
                    bpy.data.images.remove(old_img)
                
                # Load the new image
                img = bpy.data.images.load(str(preview_file))
                img.name = img_name
                # Generate preview for UI display
                img.preview_ensure()
            except Exception as e:
                print(f"Warning: Could not load preview into Blender: {e}")
            
        except Exception as e:
            print(f"Warning: Could not capture pose preview: {e}")
    
    def get_puppet_objects(self, context, puppet_id):
        """Get all objects that belong to a puppet"""
        objects = []
        
        # Find puppet item
        puppet_item = None
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_id == puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    break
        
        if not puppet_item or not hasattr(puppet_item, 'puppet_memberships'):
            print(f"Debug: No puppet found or no memberships for puppet {puppet_id}")
            return objects
        
        if not puppet_item.puppet_memberships:
            print(f"Debug: Empty memberships for puppet {puppet_id}")
            return objects
        
        # Parse member IDs and find corresponding objects
        member_ids = puppet_item.puppet_memberships.split(',')
        print(f"Debug: Group '{puppet_item.name}' has members: {member_ids}")
        
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
                        mol_id = match.puppet(1)
                        domain_id = match.puppet(2)
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
        
        print(f"Debug: Total objects found for puppet: {len(objects)}")
        return objects
    

class PROTEINBLENDER_OT_apply_pose(Operator):
    """Apply a saved pose to restore puppet positions"""
    bl_idname = "proteinblender.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Restore puppets to their saved positions in this pose"
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
    """Update pose with current puppet positions"""
    bl_idname = "proteinblender.capture_pose"
    bl_label = "Capture Pose"
    bl_description = "Update this pose with the current positions of its puppets"
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
        
        # Re-capture transforms for each puppet
        puppet_ids = pose.puppet_ids.split(',') if pose.puppet_ids else []
        
        for puppet_id in puppet_ids:
            # Get objects in this puppet
            objects = self.get_puppet_objects(context, puppet_id)
            
            for obj in objects:
                transform = pose.transforms.add()
                transform.puppet_id = puppet_id
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
            
            # Load the image into Blender's data so it's available for display
            # This must be done here, not during drawing
            try:
                # Check if image already exists and remove it
                img_name = f"pose_preview_{safe_name}"
                if img_name in bpy.data.images:
                    old_img = bpy.data.images[img_name]
                    bpy.data.images.remove(old_img)
                
                # Load the new image
                img = bpy.data.images.load(str(preview_file))
                img.name = img_name
                # Generate preview for UI display
                img.preview_ensure()
            except Exception as e:
                print(f"Warning: Could not load preview into Blender: {e}")
            
        except Exception as e:
            print(f"Warning: Could not capture pose preview: {e}")
    
    def get_puppet_objects(self, context, puppet_id):
        """Get all objects that belong to a puppet"""
        objects = []
        
        # Find puppet item
        puppet_item = None
        if hasattr(context.scene, 'outliner_items'):
            for item in context.scene.outliner_items:
                if item.item_id == puppet_id and item.item_type == 'PUPPET':
                    puppet_item = item
                    break
        
        if not puppet_item or not hasattr(puppet_item, 'puppet_memberships'):
            print(f"Debug: No puppet found or no memberships for puppet {puppet_id}")
            return objects
        
        if not puppet_item.puppet_memberships:
            print(f"Debug: Empty memberships for puppet {puppet_id}")
            return objects
        
        # Parse member IDs and find corresponding objects
        member_ids = puppet_item.puppet_memberships.split(',')
        print(f"Debug: Group '{puppet_item.name}' has members: {member_ids}")
        
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
                        mol_id = match.puppet(1)
                        domain_id = match.puppet(2)
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
        
        print(f"Debug: Total objects found for puppet: {len(objects)}")
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
    """Panel for managing puppet poses"""
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
            info_box.label(text="Click 'Create Pose' to save puppet positions")
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
            
            # Puppets label
            if pose.puppet_names:
                puppets_box = pose_col.box()
                puppets_box.scale_y = 0.8
                puppets_box.label(text="Puppets:", icon='ARMATURE_DATA')
                # Split long puppet lists into multiple lines
                puppet_names = pose.puppet_names.split(', ')
                for i in range(0, len(puppet_names), 2):
                    row = puppets_box.row()
                    row.scale_y = 0.8
                    row.label(text=', '.join(puppet_names[i:i+2]))
            
            # Screenshot preview
            screenshot_box = pose_col.box()
            
            # Try to display the preview image
            preview_shown = False
            
            # Look for the image in Blender's loaded images
            # The image should have been loaded when the pose was created
            if pose.preview_path:
                import os
                # Normalize the preview path for comparison
                preview_path_normalized = os.path.normpath(pose.preview_path)
                
                # Find image by comparing normalized paths
                for img in bpy.data.images:
                    # Skip images without filepath
                    if not img.filepath:
                        continue
                    
                    # Compare normalized paths
                    img_path_normalized = os.path.normpath(img.filepath)
                    
                    if preview_path_normalized == img_path_normalized:
                        # Found the image!
                        if img.preview and img.preview.icon_id > 0:
                            # Use template_icon for a single large preview
                            # This method is designed specifically for displaying large icons
                            screenshot_box.template_icon(icon_value=img.preview.icon_id, scale=5.0)
                            
                            preview_shown = True
                            break
            
            # If no preview shown, display placeholder with proper scaling
            if not preview_shown:
                # Use a centered layout with a large placeholder icon
                col = screenshot_box.column()
                col.alignment = 'CENTER'
                row = col.row()
                row.alignment = 'CENTER'
                row.scale_x = 3.0
                row.scale_y = 3.0
                row.label(text="", icon='IMAGE_DATA')
            
            # Action buttons
            button_row = pose_col.row(align=True)
            
            # Apply button
            apply_op = button_row.operator(
                "proteinblender.apply_pose",
                text="Apply"
            )
            apply_op.pose_index = idx
            
            # Update button (formerly Capture)
            capture_op = button_row.operator(
                "proteinblender.capture_pose",
                text="Update"
            )
            capture_op.pose_index = idx
            
            # Delete button with only trash icon
            delete_op = button_row.operator(
                "proteinblender.delete_pose",
                text="",
                icon='TRASH'
            )
            delete_op.pose_index = idx
            
            # Timestamp info
            if pose.modified_timestamp:
                info_row = pose_col.row()
                info_row.scale_y = 0.6
                info_row.label(text=f"Modified: {pose.modified_timestamp[:10]}")


class PROTEINBLENDER_OT_toggle_puppet_selection(Operator):
    """Toggle puppet selection in pose creation dialog"""
    bl_idname = "proteinblender.toggle_puppet_selection"
    bl_label = "Toggle Puppet Selection"
    bl_options = {'INTERNAL'}
    
    puppet_id: StringProperty()
    operator_instance_id: StringProperty()
    
    def execute(self, context):
        # Find the create_pose operator instance by ID
        if hasattr(PROTEINBLENDER_OT_create_pose, '_active_instances'):
            instances = PROTEINBLENDER_OT_create_pose._active_instances
            if self.operator_instance_id in instances:
                instance = instances[self.operator_instance_id]
                # Toggle the selection state
                current = instance.selected_puppets.get(self.puppet_id, False)
                instance.selected_puppets[self.puppet_id] = not current
                # Force redraw
                for area in context.screen.areas:
                    area.tag_redraw()
                return {'FINISHED'}
        
        return {'CANCELLED'}


# Register classes
CLASSES = [
    GroupSelectionItem,  # Register the helper class first
    PROTEINBLENDER_OT_toggle_puppet_selection,  # Add toggle operator
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