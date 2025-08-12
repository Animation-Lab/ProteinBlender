"""Pose properties for scene-level pose management"""

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty, FloatVectorProperty, CollectionProperty
from bpy.types import PropertyGroup


class GroupTransform(PropertyGroup):
    """Stores transform data for a single group in a pose"""
    group_id: StringProperty(name="Group ID", description="ID of the group")
    group_name: StringProperty(name="Group Name", description="Display name of the group")
    
    # Store transforms for each object in the group
    object_name: StringProperty(name="Object Name", description="Name of the object")
    location: FloatVectorProperty(name="Location", size=3)
    rotation_euler: FloatVectorProperty(name="Rotation", size=3, subtype='EULER')
    scale: FloatVectorProperty(name="Scale", size=3, default=(1, 1, 1))


class ScenePose(PropertyGroup):
    """A pose that captures positions of selected groups"""
    name: StringProperty(name="Pose Name", description="Name of this pose", default="New Pose")
    
    # Groups included in this pose
    group_ids: StringProperty(name="Group IDs", description="Comma-separated list of group IDs")
    group_names: StringProperty(name="Group Names", description="Comma-separated list of group names for display")
    
    # Transforms for all objects in the groups
    transforms: CollectionProperty(type=GroupTransform)
    
    # Screenshot/preview (for future implementation)
    preview_path: StringProperty(name="Preview Path", description="Path to preview image")
    
    # Metadata
    created_timestamp: StringProperty(name="Created", description="Creation timestamp")
    modified_timestamp: StringProperty(name="Modified", description="Last modified timestamp")


def register():
    """Register pose properties"""
    bpy.utils.register_class(GroupTransform)
    bpy.utils.register_class(ScenePose)
    
    # Add pose library to scene
    bpy.types.Scene.pose_library = CollectionProperty(
        type=ScenePose,
        name="Pose Library",
        description="Collection of saved poses"
    )
    
    # Active pose index for UI
    bpy.types.Scene.active_pose_index = IntProperty(
        name="Active Pose",
        description="Index of the currently selected pose",
        default=0,
        min=0
    )


def unregister():
    """Unregister pose properties"""
    # Remove properties from scene
    if hasattr(bpy.types.Scene, "pose_library"):
        del bpy.types.Scene.pose_library
    if hasattr(bpy.types.Scene, "active_pose_index"):
        del bpy.types.Scene.active_pose_index
    
    # Unregister classes
    bpy.utils.unregister_class(ScenePose)
    bpy.utils.unregister_class(GroupTransform)