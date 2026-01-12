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

    # Normalized parameters (0-1 range)
    intensity: FloatProperty(
        name="Intensity",
        description="Overall magnitude of the Brownian motion (0 = none, 1 = maximum)",
        min=0.0,
        max=1.0,
        default=0.3,
        subtype='FACTOR'
    )

    time_scale: FloatProperty(
        name="Time Scale",
        description="How fast the jitter feels (0 = slow, 1 = fast)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
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

    # Directional bias (0.5 = no bias, 0 = negative bias, 1 = positive bias)
    bias_x: FloatProperty(
        name="Bias X",
        description="Directional drift along X axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    bias_y: FloatProperty(
        name="Bias Y",
        description="Directional drift along Y axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    bias_z: FloatProperty(
        name="Bias Z",
        description="Directional drift along Z axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )


def register():
    """Register Brownian motion properties"""
    bpy.utils.register_class(BrownianMotionSettings)


def unregister():
    """Unregister Brownian motion properties"""
    bpy.utils.unregister_class(BrownianMotionSettings)
