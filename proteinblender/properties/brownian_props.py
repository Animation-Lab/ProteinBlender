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

    # Jitter parameters
    jitter_interval: IntProperty(
        name="Interval",
        description="Frames between jitter events (1 = every frame, 10 = every 10th frame)",
        min=1,
        max=10,
        default=3
    )

    jitter_max_distance: FloatProperty(
        name="Max Distance",
        description="Maximum displacement from interpolated path (Blender units). Protein appears anywhere within this sphere",
        min=0.1,
        max=10.0,
        default=1.0
    )

    jitter_max_rotation: FloatProperty(
        name="Max Rotation",
        description="Maximum rotation per axis at each jitter event (degrees). Each axis is independently randomized",
        min=0.0,
        max=360.0,
        default=30.0,
        step=100,
        precision=0
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

    # Physical parameterization mode
    use_physical_params: BoolProperty(
        name="Physical Mode",
        description="Use physics-based parameters (molecular weight, temperature) instead of manual sliders",
        default=False
    )

    molecular_weight: FloatProperty(
        name="Molecular Weight",
        description="Protein molecular weight in kilodaltons (kDa). Examples: Insulin=5.8, BSA=66, IgG=150",
        min=1.0,
        max=10000.0,
        default=50.0,
        precision=1
    )

    temperature: FloatProperty(
        name="Temperature",
        description="Simulation temperature in Kelvin (room temp = 298 K, body temp = 310 K)",
        min=100.0,
        max=500.0,
        default=300.0,
        precision=1
    )

    viscosity_factor: FloatProperty(
        name="Viscosity Factor",
        description="Multiplier for solvent viscosity (1.0 = water at 20C, higher = more viscous)",
        min=0.1,
        max=100.0,
        default=1.0,
        precision=2
    )


def register():
    """Register Brownian motion properties"""
    bpy.utils.register_class(BrownianMotionSettings)


def unregister():
    """Unregister Brownian motion properties"""
    bpy.utils.unregister_class(BrownianMotionSettings)
