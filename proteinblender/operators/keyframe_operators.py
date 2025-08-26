"""Keyframe operators for animation functionality"""

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import BoolProperty, IntProperty, CollectionProperty, StringProperty
from ..utils.scene_manager import ProteinBlenderScene


class KeyframeTransformSettings(PropertyGroup):
    """Property group for transform settings in keyframe creation"""
    item_id: StringProperty(name="Item ID")
    item_name: StringProperty(name="Item Name")
    item_type: StringProperty(name="Item Type")  # 'protein', 'pose', 'puppet'
    
    keyframe_location: BoolProperty(name="Location", default=True)
    keyframe_rotation: BoolProperty(name="Rotation", default=True)
    keyframe_scale: BoolProperty(name="Scale", default=False)
    
    is_enabled: BoolProperty(name="Enabled", default=True)


class PROTEINBLENDER_OT_create_keyframe(Operator):
    """Create keyframes for selected proteins, poses, and puppets"""
    bl_idname = "proteinblender.create_keyframe"
    bl_label = "Create Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    frame_number: IntProperty(
        name="Frame",
        description="Frame number for keyframe (defaults to current frame)",
        default=1,
        min=1
    )
    
    def invoke(self, context, event):
        scene = context.scene
        
        # Clear previous items using the scene property
        scene.keyframe_dialog_items.clear()
        
        # Set frame to current frame
        self.frame_number = scene.frame_current
        
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Add proteins and their poses
        for molecule_id, molecule in scene_manager.molecules.items():
            # Add main protein entry
            item = scene.keyframe_dialog_items.add()
            item.item_id = molecule_id
            item.item_name = molecule.identifier
            item.item_type = 'protein'
            item.is_enabled = True
            
            # Get molecule item from scene property for poses
            molecule_item = None
            for scene_item in scene.molecule_list_items:
                if scene_item.identifier == molecule.identifier:
                    molecule_item = scene_item
                    break
            
            # Add poses for this molecule
            if molecule_item and molecule_item.poses:
                for pose_idx, pose in enumerate(molecule_item.poses):
                    pose_item = scene.keyframe_dialog_items.add()
                    pose_item.item_id = f"{molecule_id}_pose_{pose_idx}"
                    pose_item.item_name = f"  └─ {pose.name}"
                    pose_item.item_type = 'pose'
                    pose_item.is_enabled = False  # Disabled by default
        
        # Add puppets (skip separator items)
        for outliner_item in scene.outliner_items:
            if (outliner_item.item_type == 'PUPPET' and 
                outliner_item.item_id != "puppets_separator" and
                outliner_item.name and 
                not outliner_item.name.startswith("─")):
                puppet_item = scene.keyframe_dialog_items.add()
                puppet_item.item_id = outliner_item.item_id
                puppet_item.item_name = outliner_item.name
                puppet_item.item_type = 'puppet'
                puppet_item.is_enabled = True
        
        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Frame number input
        row = layout.row()
        row.label(text="Frame:")
        row.prop(self, "frame_number", text="")
        
        layout.separator()
        
        # Header row with proper spacing
        header = layout.row()
        col = header.column()
        col.alignment = 'LEFT'
        col.label(text="Item")
        
        col = header.column()
        col.alignment = 'CENTER'
        col.label(text="Location")
        
        col = header.column()
        col.alignment = 'CENTER'
        col.label(text="Rotation")
        
        col = header.column()
        col.alignment = 'CENTER'
        col.label(text="Scale")
        
        layout.separator()
        
        # Item rows - use scene property
        box = layout.box()
        
        # Track if we need to add a separator for puppets
        has_proteins = False
        has_puppets = False
        for item in scene.keyframe_dialog_items:
            if item.item_type in ['protein', 'pose']:
                has_proteins = True
            elif item.item_type == 'puppet':
                has_puppets = True
        
        # Draw items
        last_type = None
        for item in scene.keyframe_dialog_items:
            # Add separator between proteins/poses and puppets
            if last_type in ['protein', 'pose'] and item.item_type == 'puppet':
                box.separator()
                # Add puppets label
                row = box.row()
                row.label(text="——— Puppets ———")
            
            row = box.row(align=False)
            
            # Item name column with enable checkbox
            col = row.column()
            col.alignment = 'LEFT'
            sub = col.row(align=True)
            sub.prop(item, "is_enabled", text="")
            
            # Add appropriate icon and indentation
            if item.item_type == 'pose':
                sub.label(text="    " + item.item_name)
            elif item.item_type == 'protein':
                sub.label(text=item.item_name, icon='RNA')
            elif item.item_type == 'puppet':
                sub.label(text=item.item_name, icon='GROUP')
            
            # Transform checkbox columns
            col = row.column()
            col.alignment = 'CENTER'
            col.enabled = item.is_enabled
            col.prop(item, "keyframe_location", text="")
            
            col = row.column()
            col.alignment = 'CENTER'
            col.enabled = item.is_enabled
            col.prop(item, "keyframe_rotation", text="")
            
            col = row.column()
            col.alignment = 'CENTER'
            col.enabled = item.is_enabled
            col.prop(item, "keyframe_scale", text="")
            
            last_type = item.item_type
        
        layout.separator()
        
        # Select all/none buttons
        row = layout.row(align=True)
        row.operator("proteinblender.keyframe_select_all", text="Select All")
        row.operator("proteinblender.keyframe_select_none", text="Select None")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Store current frame
        original_frame = scene.frame_current
        
        # Only change frame if necessary
        if original_frame != self.frame_number:
            scene.frame_set(self.frame_number)
        
        keyframed_count = 0
        
        for item in scene.keyframe_dialog_items:
            if not item.is_enabled:
                continue
            
            objects_to_keyframe = []
            
            if item.item_type == 'protein':
                # Keyframe the main protein and all its domains
                molecule = scene_manager.molecules.get(item.item_id)
                if molecule and molecule.object:
                    objects_to_keyframe.append(molecule.object)
                    
                    # Add all domain objects
                    for domain in molecule.domains.values():
                        if domain.object:
                            objects_to_keyframe.append(domain.object)
            
            elif item.item_type == 'pose':
                # Extract molecule_id and pose_index from item_id
                parts = item.item_id.split('_pose_')
                if len(parts) == 2:
                    molecule_id = parts[0]
                    pose_idx = int(parts[1])
                    
                    molecule = scene_manager.molecules.get(molecule_id)
                    if molecule:
                        # Get molecule item for poses
                        for scene_item in scene.molecule_list_items:
                            if scene_item.identifier == molecule.identifier:
                                if 0 <= pose_idx < len(scene_item.poses):
                                    pose = scene_item.poses[pose_idx]
                                    
                                    # NOTE: Don't apply the pose here - assume it's already applied
                                    # The user should have already applied the pose they want to keyframe
                                    
                                    # Keyframe the affected domains with their CURRENT transforms
                                    for transform in pose.domain_transforms:
                                        domain = molecule.domains.get(transform.domain_id)
                                        if domain and domain.object:
                                            objects_to_keyframe.append(domain.object)
                                break
            
            elif item.item_type == 'puppet':
                # Debug print
                print(f"Processing puppet: {item.item_name} (ID: {item.item_id})")
                
                # Find all items that belong to this puppet
                for outliner_item in scene.outliner_items:
                    # Check if this item belongs to the puppet
                    if outliner_item.puppet_memberships and item.item_id in outliner_item.puppet_memberships.split(','):
                        print(f"  Found member: {outliner_item.name} (type: {outliner_item.item_type})")
                        
                        if outliner_item.item_type == 'DOMAIN':
                            # Find the actual domain object
                            for molecule in scene_manager.molecules.values():
                                for domain in molecule.domains.values():
                                    if domain.name == outliner_item.name and domain.object:
                                        print(f"    Adding domain object: {domain.object.name}")
                                        objects_to_keyframe.append(domain.object)
                        elif outliner_item.item_type == 'CHAIN':
                            # For chains, we need to find the corresponding object
                            # Chain items have an object_name property
                            if outliner_item.object_name:
                                obj = bpy.data.objects.get(outliner_item.object_name)
                                if obj:
                                    print(f"    Adding chain object: {obj.name}")
                                    objects_to_keyframe.append(obj)
            
            # Insert keyframes for all collected objects with their CURRENT transforms
            for obj in objects_to_keyframe:
                # The keyframe_insert will capture the object's current transform
                # No need to modify anything - just keyframe the current state
                if item.keyframe_location:
                    obj.keyframe_insert(data_path="location", frame=self.frame_number)
                if item.keyframe_rotation:
                    obj.keyframe_insert(data_path="rotation_euler", frame=self.frame_number)
                if item.keyframe_scale:
                    obj.keyframe_insert(data_path="scale", frame=self.frame_number)
                keyframed_count += 1
                print(f"Keyframed {obj.name} at frame {self.frame_number} - Loc: {obj.location}, Rot: {obj.rotation_euler}")
        
        # Restore original frame
        scene.frame_set(original_frame)
        
        self.report({'INFO'}, f"Created keyframes for {keyframed_count} objects at frame {self.frame_number}")
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_all(Operator):
    """Select all items and transforms for keyframing"""
    bl_idname = "proteinblender.keyframe_select_all"
    bl_label = "Select All"
    
    def execute(self, context):
        scene = context.scene
        for item in scene.keyframe_dialog_items:
            item.is_enabled = True
            item.keyframe_location = True
            item.keyframe_rotation = True
            item.keyframe_scale = True
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_select_none(Operator):
    """Deselect all items for keyframing"""
    bl_idname = "proteinblender.keyframe_select_none"
    bl_label = "Select None"
    
    def execute(self, context):
        scene = context.scene
        for item in scene.keyframe_dialog_items:
            item.is_enabled = False
        return {'FINISHED'}


def register():
    """Register keyframe operators and properties"""
    # NOTE: The operator classes are already registered via the CLASSES tuple
    # in operators/__init__.py, so we only need to register the PropertyGroup
    # and add the Scene property here
    
    # Register the PropertyGroup - use try/except for safety
    try:
        bpy.utils.register_class(KeyframeTransformSettings)
    except ValueError:
        # Already registered, that's fine
        pass
    
    # Add collection property to Scene
    if not hasattr(bpy.types.Scene, 'keyframe_dialog_items'):
        bpy.types.Scene.keyframe_dialog_items = CollectionProperty(
            type=KeyframeTransformSettings,
            name="Keyframe Dialog Items"
        )


def unregister():
    """Unregister keyframe operators and properties"""
    # Remove scene property
    if hasattr(bpy.types.Scene, 'keyframe_dialog_items'):
        del bpy.types.Scene.keyframe_dialog_items
    
    # Unregister the PropertyGroup - use try/except for safety
    try:
        bpy.utils.unregister_class(KeyframeTransformSettings)
    except (ValueError, RuntimeError):
        # Already unregistered or never registered, that's fine
        pass