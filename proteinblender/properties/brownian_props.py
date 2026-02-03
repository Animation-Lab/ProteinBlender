"""Brownian motion properties for puppet animation"""

import bpy
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    CollectionProperty
)
from bpy.types import PropertyGroup


class BrownianMotionSettings(PropertyGroup):
    """Settings for Brownian motion on a puppet keyframe segment.

    These settings define how Brownian motion is applied between
    a previous keyframe and the current keyframe.
    """
    # Identification
    puppet_id: StringProperty(
        name="Puppet ID",
        description="ID of the puppet these settings apply to"
    )
    start_frame: IntProperty(
        name="Start Frame",
        description="Frame where this Brownian motion segment starts (previous keyframe)",
        default=1,
        min=1
    )
    end_frame: IntProperty(
        name="End Frame",
        description="Frame where this Brownian motion segment ends (current keyframe)",
        default=1,
        min=1
    )

    # Main toggle
    enabled: BoolProperty(
        name="Enable Brownian Motion",
        description="Enable Brownian motion for this keyframe segment",
        default=False
    )

    # Movement parameters
    movement_speed: FloatProperty(
        name="Movement Speed",
        description="How fast the movement changes (0 = slow, gentle drift | 1 = fast, active motion)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    movement_distance: FloatProperty(
        name="Movement Distance",
        description="Maximum displacement from keyframed position (Blender units)",
        min=0.0,
        max=10.0,
        default=1.0
    )

    # Rotation parameters
    rotation_speed: FloatProperty(
        name="Rotation Speed",
        description="How fast the rotation changes (0 = slow, gentle tumbling | 1 = fast, active spinning)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    rotation_distance: FloatProperty(
        name="Rotation Distance",
        description="Maximum rotation deviation (degrees, max 60)",
        min=0.0,
        max=60.0,
        default=30.0
    )

    # Random seed settings
    use_random_seed: BoolProperty(
        name="Random Seed",
        description="Use a random seed (different motion each playback) or fixed seed (reproducible)",
        default=True
    )

    seed: IntProperty(
        name="Seed Value",
        description="Fixed seed for reproducible motion (only used when Random Seed is unchecked)",
        default=12345,
        min=0
    )


def register():
    """Register Brownian motion properties"""
    bpy.utils.register_class(BrownianMotionSettings)


def unregister():
    """Unregister Brownian motion properties"""
    bpy.utils.unregister_class(BrownianMotionSettings)
