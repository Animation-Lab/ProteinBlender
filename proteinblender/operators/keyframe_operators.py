"""Keyframe operators for animation functionality"""

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, IntProperty, CollectionProperty, StringProperty
from ..utils.scene_manager import ProteinBlenderScene


class PoseKeyframeSettings(PropertyGroup):
    """Property group for pose keyframe settings"""
    pose_index: IntProperty(name="Pose Index", default=-1)
    pose_name: StringProperty(name="Pose Name")
    puppet_ids: StringProperty(name="Puppet IDs")  # Comma-separated
    
    # Main checkbox to enable/disable this pose
    use_pose: BoolProperty(
        name="Use Pose",
        description="Apply this pose and keyframe it",
        default=False
    )
    
    # Transform checkboxes
    keyframe_location: BoolProperty(
        name="Location",
        description="Keyframe location",
        default=True
    )
    keyframe_rotation: BoolProperty(
        name="Rotation", 
        description="Keyframe rotation",
        default=True
    )
    keyframe_scale: BoolProperty(
        name="Scale",
        description="Keyframe scale",
        default=False
    )
    keyframe_color: BoolProperty(
        name="Color",
        description="Keyframe color and transparency",
        default=True
    )
    
    # Conflict tracking
    has_conflict: BoolProperty(
        name="Has Conflict",
        description="This pose conflicts with another selected pose",
        default=False
    )
    conflict_with: StringProperty(
        name="Conflicts With",
        description="Name of conflicting pose",
        default=""
    )


class PROTEINBLENDER_OT_create_keyframe(Operator):
    """Create keyframes from poses"""
    bl_idname = "proteinblender.create_keyframe"
    bl_label = "Create Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    frame_number: IntProperty(
        name="Frame",
        description="Frame number for keyframe",
        default=1,
        min=1
    )
    
    pose_items: CollectionProperty(
        type=PoseKeyframeSettings,
        name="Pose Items",
        description="Collection of poses to keyframe"
    )
    
    def get_puppet_objects(self, context, puppet_id):
        """Get all Blender objects that belong to a puppet group"""
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
        print(f"Debug: Puppet '{puppet_item.name}' has members: {member_ids}")
        
        # Import scene manager to access molecules
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        for member_id in member_ids:
            # Member IDs are in format: molecule_id_domain_id
            if '_' in member_id:
                # Try to intelligently parse the member_id
                # First, check if it contains '_chain_'
                if '_chain_' in member_id:
                    # Split at '_chain_' to separate molecule_id from chain identifier
                    parts = member_id.rsplit('_chain_', 1)
                    mol_id = parts[0]
                    domain_id = 'chain_' + parts[1]
                else:
                    # For custom domains, find where molecule_id ends
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
                
                # Try to find the domain object
                if mol_id in scene_manager.molecules:
                    molecule = scene_manager.molecules[mol_id]
                    
                    # First try direct lookup
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        if domain.object:
                            objects.append(domain.object)
                            print(f"Debug: Found domain object '{domain.object.name}' for {member_id}")
                    else:
                        # If domain_id is like 'chain_4', try to find the matching domain
                        if domain_id.startswith('chain_'):
                            chain_index = domain_id.replace('chain_', '')
                            # Find domain that starts with mol_id_chainindex_
                            for dom_id, dom in molecule.domains.items():
                                if dom_id.startswith(f"{mol_id}_{chain_index}_"):
                                    if dom.object:
                                        objects.append(dom.object)
                                        print(f"Debug: Found chain object '{dom.object.name}' for {member_id}")
                                    break
            
            # Always check outliner items as fallback
            for item in context.scene.outliner_items:
                if item.item_id == member_id:
                    if item.object_name:
                        obj = bpy.data.objects.get(item.object_name)
                        if obj and obj not in objects:
                            objects.append(obj)
                            print(f"Debug: Found object via outliner '{obj.name}' for {member_id}")
                    break
        
        print(f"Debug: Total objects found for puppet: {len(objects)}")
        return objects
    
    def check_conflicts(self):
        """Check for puppet conflicts between selected poses"""
        # Clear previous conflict states
        for item in self.pose_items:
            item.has_conflict = False
            item.conflict_with = ""
        
        # Check each pair of selected poses
        selected_poses = [item for item in self.pose_items if item.use_pose]
        
        for i, pose_a in enumerate(selected_poses):
            puppets_a = set(pose_a.puppet_ids.split(',')) if pose_a.puppet_ids else set()
            
            for pose_b in selected_poses[i+1:]:
                puppets_b = set(pose_b.puppet_ids.split(',')) if pose_b.puppet_ids else set()
                
                # Check for overlap
                overlap = puppets_a & puppets_b
                if overlap:
                    pose_a.has_conflict = True
                    pose_b.has_conflict = True
                    
                    if not pose_a.conflict_with:
                        pose_a.conflict_with = pose_b.pose_name
                    else:
                        pose_a.conflict_with += f", {pose_b.pose_name}"
                    
                    if not pose_b.conflict_with:
                        pose_b.conflict_with = pose_a.pose_name
                    else:
                        pose_b.conflict_with += f", {pose_a.pose_name}"
    
    def invoke(self, context, event):
        scene = context.scene
        
        # Clear previous items
        self.pose_items.clear()
        
        # Set frame to current frame
        self.frame_number = scene.frame_current
        
        # Add poses from the pose library
        if hasattr(scene, 'pose_library'):
            for idx, pose in enumerate(scene.pose_library):
                item = self.pose_items.add()
                item.pose_index = idx
                item.pose_name = pose.name
                item.puppet_ids = pose.puppet_ids
                item.use_pose = False  # Unchecked by default
                item.keyframe_location = True
                item.keyframe_rotation = True
                item.keyframe_scale = False
        
        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self, width=500)
    
    def draw(self, context):
        layout = self.layout
        
        # Frame number input
        row = layout.row()
        row.label(text="Frame:")
        row.prop(self, "frame_number", text="")
        
        layout.separator()
        
        # Check for conflicts whenever UI is drawn
        self.check_conflicts()
        
        # Show conflict warning if any exist
        has_any_conflict = any(item.has_conflict for item in self.pose_items if item.use_pose)
        if has_any_conflict:
            box = layout.box()
            col = box.column()
            col.alert = True
            col.label(text="⚠ Warning: Conflicting poses selected", icon='ERROR')
            col.label(text="Poses controlling the same puppets cannot be applied together")
        
        # Pose rows
        box = layout.box()
        
        if not self.pose_items:
            box.label(text="No poses available", icon='INFO')
            box.label(text="Create poses in the Pose Library first")
        else:
            # Create a subtle header with icons
            header_row = box.row(align=False)
            header_row.scale_y = 0.8
            header_row.label(text="")  # Empty space for checkbox column
            
            # Pose name label - left aligned to match actual pose names
            header_row.label(text="Pose Name")
            
            # Spacer to push transform icons to the right
            header_row.separator(factor=2.0)
            
            # Transform type icons
            header_row.label(text="", icon='CON_LOCLIKE')  # Location icon
            header_row.label(text="", icon='CON_ROTLIKE')  # Rotation icon  
            header_row.label(text="", icon='CON_SIZELIKE')  # Scale icon
            header_row.label(text="", icon='COLOR')  # Color icon
            
            box.separator(factor=0.5)
            
            for item in self.pose_items:
                row = box.row(align=False)
                row.scale_y = 1.2  # Make rows slightly taller for better readability
                
                # Color the entire row if there's a conflict
                if item.has_conflict and item.use_pose:
                    row.alert = True
                
                # Checkbox for selecting the pose (always enabled)
                row.prop(item, "use_pose", text="")
                
                # Pose name with icon and puppet count (takes up space)
                name_col = row.column()
                name_col.alignment = 'LEFT'
                name_row = name_col.row(align=True)
                name_row.label(text=item.pose_name, icon='POSE_HLT')
                if item.puppet_ids:
                    puppet_count = len(item.puppet_ids.split(','))
                    name_row.label(text=f"({puppet_count} puppet{'s' if puppet_count > 1 else ''})")
                
                # Add spacer to push transform checkboxes to the right
                row.separator(factor=2.0)
                
                # Transform checkboxes - each in its own sub-row for proper enabling
                loc_row = row.row()
                loc_row.enabled = item.use_pose and not item.has_conflict
                loc_row.prop(item, "keyframe_location", text="")
                
                rot_row = row.row()
                rot_row.enabled = item.use_pose and not item.has_conflict
                rot_row.prop(item, "keyframe_rotation", text="")
                
                scale_row = row.row()
                scale_row.enabled = item.use_pose and not item.has_conflict
                scale_row.prop(item, "keyframe_scale", text="")
                
                color_row = row.row()
                color_row.enabled = item.use_pose and not item.has_conflict
                color_row.prop(item, "keyframe_color", text="")
                
                # Show conflict details below the row if needed
                if item.has_conflict and item.use_pose:
                    conflict_row = box.row()
                    conflict_row.alert = True
                    conflict_row.label(text=f"    ⚠ Conflicts with: {item.conflict_with}", icon='BLANK1')
        
        layout.separator()
        
        # Select all/none buttons
        row = layout.row(align=True)
        row.operator("proteinblender.keyframe_select_all_poses", text="Select All")
        row.operator("proteinblender.keyframe_select_none_poses", text="Select None")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Check for conflicts one more time
        self.check_conflicts()
        
        # Get selected poses without conflicts
        selected_poses = [item for item in self.pose_items 
                         if item.use_pose and not item.has_conflict]
        
        if not selected_poses:
            if any(item.has_conflict for item in self.pose_items if item.use_pose):
                self.report({'ERROR'}, "Cannot apply conflicting poses. Please resolve conflicts.")
            else:
                self.report({'WARNING'}, "No poses selected")
            return {'CANCELLED'}
        
        # Store current frame
        original_frame = scene.frame_current
        
        # Only change frame if necessary
        if original_frame != self.frame_number:
            scene.frame_set(self.frame_number)
        
        keyframed_count = 0
        applied_poses = []
        
        for pose_item in selected_poses:
            if pose_item.pose_index < 0 or pose_item.pose_index >= len(scene.pose_library):
                continue
            
            pose = scene.pose_library[pose_item.pose_index]
            applied_poses.append(pose.name)
            
            # If color keyframing is enabled, capture current colors BEFORE applying pose
            current_colors = {}
            if pose_item.keyframe_color:
                from ..panels.visual_setup_panel import get_object_color
                for transform in pose.transforms:
                    obj = bpy.data.objects.get(transform.object_name)
                    if obj:
                        color = get_object_color(obj)
                        if color:
                            current_colors[transform.object_name] = color
                            print(f"  Captured current color for {obj.name}: {color}")
            
            # First, apply the pose to set the transforms
            print(f"Applying pose '{pose.name}' before keyframing at frame {self.frame_number}")
            
            # Apply the pose transforms
            for transform in pose.transforms:
                obj = bpy.data.objects.get(transform.object_name)
                if obj:
                    obj.location = transform.location
                    obj.rotation_euler = transform.rotation_euler
                    obj.scale = transform.scale
                    
                    # For color: use current color if available, otherwise use pose color
                    if pose_item.keyframe_color:
                        if transform.object_name in current_colors:
                            # Use the current color (user's recent change)
                            color = current_colors[transform.object_name]
                            obj["pb_color"] = list(color)
                            from ..panels.visual_setup_panel import apply_color_to_object
                            apply_color_to_object(obj, color)
                            print(f"  Using current color for {obj.name}")
                        elif transform.has_color:
                            # Fall back to pose's stored color
                            obj["pb_color"] = list(transform.color)
                            from ..panels.visual_setup_panel import apply_color_to_object
                            apply_color_to_object(obj, transform.color)
                            print(f"  Using pose color for {obj.name}")
                    
                    print(f"  Applied transform to {obj.name}")
            
            # Collect all objects that are part of this pose's puppets
            objects_to_keyframe = []
            
            # Get puppet IDs from the pose
            if pose.puppet_ids:
                puppet_ids = pose.puppet_ids.split(',')
                
                for puppet_id in puppet_ids:
                    puppet_id = puppet_id.strip()
                    print(f"  Looking for objects in puppet: {puppet_id}")
                    
                    # Find puppet objects using the same logic as pose library panel
                    puppet_objects = self.get_puppet_objects(context, puppet_id)
                    
                    for obj in puppet_objects:
                        if obj not in objects_to_keyframe:
                            objects_to_keyframe.append(obj)
                            print(f"  Will keyframe: {obj.name}")
            
            # Collect parent objects that need keyframing
            parent_objects = set()
            
            # Insert keyframes for all affected objects with the pose transforms applied
            for obj in objects_to_keyframe:
                print(f"\n  Object: {obj.name}")
                print(f"    Current Location: {list(obj.location)}")
                print(f"    Current Rotation: {list(obj.rotation_euler)}")
                print(f"    Current Scale: {list(obj.scale)}")
                
                # Check if object has a parent
                if obj.parent:
                    print(f"    Parent: {obj.parent.name}")
                    print(f"    Parent Location: {list(obj.parent.location)}")
                    print(f"    World Location: {list(obj.matrix_world.translation)}")
                    # Add parent to list of objects to keyframe
                    parent_objects.add(obj.parent)
                else:
                    print(f"    No parent (world location = local location)")
                
                # Track what we're keyframing
                keyframed_properties = []
                
                if pose_item.keyframe_location:
                    obj.keyframe_insert(data_path="location", frame=self.frame_number)
                    keyframed_properties.append("location")
                    print(f"    ✓ Keyframed location at frame {self.frame_number}")
                    
                if pose_item.keyframe_rotation:
                    obj.keyframe_insert(data_path="rotation_euler", frame=self.frame_number)
                    keyframed_properties.append("rotation")
                    print(f"    ✓ Keyframed rotation at frame {self.frame_number}")
                    
                if pose_item.keyframe_scale:
                    obj.keyframe_insert(data_path="scale", frame=self.frame_number)
                    keyframed_properties.append("scale")
                    print(f"    ✓ Keyframed scale at frame {self.frame_number}")
                
                if pose_item.keyframe_color and "pb_color" in obj:
                    obj.keyframe_insert(data_path='["pb_color"]', frame=self.frame_number)
                    keyframed_properties.append("color")
                    print(f"    ✓ Keyframed color at frame {self.frame_number}")
                
                if keyframed_properties:
                    print(f"    Summary: Keyframed {', '.join(keyframed_properties)} for {obj.name}")
                else:
                    print(f"    Warning: No properties were keyframed for {obj.name}")
                    
                keyframed_count += 1
            
            # Also keyframe parent objects (the proteins themselves)
            for parent in parent_objects:
                print(f"\n  Parent Object: {parent.name}")
                print(f"    Current Location: {list(parent.location)}")
                print(f"    Current Rotation: {list(parent.rotation_euler)}")
                print(f"    Current Scale: {list(parent.scale)}")
                
                keyframed_properties = []
                
                if pose_item.keyframe_location:
                    parent.keyframe_insert(data_path="location", frame=self.frame_number)
                    keyframed_properties.append("location")
                    print(f"    ✓ Keyframed parent location at frame {self.frame_number}")
                    
                if pose_item.keyframe_rotation:
                    parent.keyframe_insert(data_path="rotation_euler", frame=self.frame_number)
                    keyframed_properties.append("rotation")
                    print(f"    ✓ Keyframed parent rotation at frame {self.frame_number}")
                    
                if pose_item.keyframe_scale:
                    parent.keyframe_insert(data_path="scale", frame=self.frame_number)
                    keyframed_properties.append("scale")
                    print(f"    ✓ Keyframed parent scale at frame {self.frame_number}")
                
                if keyframed_properties:
                    print(f"    Summary: Keyframed {', '.join(keyframed_properties)} for parent {parent.name}")
                    keyframed_count += 1
        
        # Restore original frame
        if original_frame != self.frame_number:
            scene.frame_set(original_frame)
        
        pose_names = ", ".join(applied_poses)
        self.report({'INFO'}, f"Keyframed {keyframed_count} objects from poses: {pose_names} at frame {self.frame_number}")
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_all_poses(Operator):
    """Select all poses for keyframing"""
    bl_idname = "proteinblender.keyframe_select_all_poses"
    bl_label = "Select All"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'pose_items'):
                        for item in op.pose_items:
                            item.use_pose = True
                            # Keep default transform settings
                        # Force a redraw to update conflict detection
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_none_poses(Operator):
    """Deselect all poses"""
    bl_idname = "proteinblender.keyframe_select_none_poses"
    bl_label = "Select None"
    
    def execute(self, context):
        # Get the active operator
        wm = context.window_manager
        if hasattr(wm, 'operators') and len(wm.operators) > 0:
            for op in reversed(wm.operators):
                if hasattr(op, 'bl_idname') and op.bl_idname == 'proteinblender.create_keyframe':
                    if hasattr(op, 'pose_items'):
                        for item in op.pose_items:
                            item.use_pose = False
                        # Force a redraw to update conflict detection
                        context.area.tag_redraw()
                    break
        return {'FINISHED'}


# Keep old operators for backwards compatibility but deprecated
class PROTEINBLENDER_OT_keyframe_select_all(Operator):
    """Deprecated - use keyframe_select_all_poses"""
    bl_idname = "proteinblender.keyframe_select_all"
    bl_label = "Select All (Deprecated)"
    
    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_all_poses()


class PROTEINBLENDER_OT_keyframe_select_none(Operator):
    """Deprecated - use keyframe_select_none_poses"""
    bl_idname = "proteinblender.keyframe_select_none"
    bl_label = "Select None (Deprecated)"
    
    def execute(self, context):
        return bpy.ops.proteinblender.keyframe_select_none_poses()


def register():
    """Register keyframe operators and properties"""
    # PoseKeyframeSettings is now registered with the main CLASSES in __init__.py
    pass


def unregister():
    """Unregister keyframe operators and properties"""
    # PoseKeyframeSettings is now unregistered with the main CLASSES in __init__.py
    pass