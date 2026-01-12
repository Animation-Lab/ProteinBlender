"""Brownian motion operators for ProteinBlender.

This module provides operators for configuring Brownian motion settings
on puppet keyframe segments.
"""

import bpy
import json
from bpy.types import Operator
from bpy.props import (
    FloatProperty,
    BoolProperty,
    IntProperty,
    StringProperty,
)

from ..utils.brownian import (
    get_brownian_metadata,
    save_brownian_metadata,
    find_previous_keyframe,
)


class PROTEINBLENDER_OT_brownian_settings(Operator):
    """Configure Brownian motion settings for a puppet keyframe"""
    bl_idname = "proteinblender.brownian_settings"
    bl_label = "Brownian Motion Settings"
    bl_options = {'REGISTER', 'UNDO'}

    # Puppet identification (passed from keyframe dialog)
    puppet_id: StringProperty(
        name="Puppet ID",
        description="ID of the puppet to configure"
    )
    puppet_name: StringProperty(
        name="Puppet Name",
        description="Name of the puppet (for display)"
    )
    controller_object_name: StringProperty(
        name="Controller Object",
        description="Name of the controller Empty object"
    )
    frame_number: IntProperty(
        name="Frame",
        description="Frame number for this keyframe",
        default=1,
        min=1
    )

    # Brownian motion parameters (normalized 0-1)
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

    use_random_seed: BoolProperty(
        name="Random Seed",
        description="Use random seed (different each playback) or fixed seed (reproducible)",
        default=True
    )

    seed: IntProperty(
        name="Seed Value",
        description="Fixed seed for reproducible motion (only used when Random Seed is unchecked)",
        default=12345,
        min=0
    )

    bias_x: FloatProperty(
        name="X",
        description="Directional drift along X axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    bias_y: FloatProperty(
        name="Y",
        description="Directional drift along Y axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    bias_z: FloatProperty(
        name="Z",
        description="Directional drift along Z axis (0.5 = no drift)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    def invoke(self, context, event):
        """Initialize settings from existing metadata if available."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if controller_obj:
            # Try to load existing settings for this frame
            metadata = get_brownian_metadata(controller_obj)
            frame_key = str(self.frame_number)

            if frame_key in metadata:
                settings = metadata[frame_key]
                self.intensity = settings.get('intensity', 0.3)
                self.time_scale = settings.get('time_scale', 0.5)
                self.use_random_seed = settings.get('use_random_seed', True)
                # Handle None seed value (stored when use_random_seed=True)
                stored_seed = settings.get('seed')
                self.seed = stored_seed if stored_seed is not None else 12345
                self.bias_x = settings.get('bias_x', 0.5)
                self.bias_y = settings.get('bias_y', 0.5)
                self.bias_z = settings.get('bias_z', 0.5)

        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        """Draw the settings popup UI."""
        layout = self.layout

        # Motion parameters
        box = layout.box()
        box.label(text="Motion Parameters", icon='FORCE_TURBULENCE')

        col = box.column(align=True)
        col.prop(self, "intensity")
        col.prop(self, "time_scale")

        layout.separator()

        # Seed settings
        box = layout.box()
        box.label(text="Reproducibility", icon='FILE_REFRESH')

        row = box.row()
        row.prop(self, "use_random_seed")

        seed_row = box.row()
        seed_row.enabled = not self.use_random_seed
        seed_row.prop(self, "seed")

        layout.separator()

        # Directional bias
        box = layout.box()
        box.label(text="Directional Bias", icon='ORIENTATION_GLOBAL')
        box.label(text="(0.5 = no drift)", icon='INFO')

        col = box.column(align=True)
        col.prop(self, "bias_x")
        col.prop(self, "bias_y")
        col.prop(self, "bias_z")

    def execute(self, context):
        """Save the Brownian motion settings."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            self.report({'ERROR'}, f"Controller object '{self.controller_object_name}' not found")
            return {'CANCELLED'}

        # Find previous keyframe to determine start frame
        prev_frame = find_previous_keyframe(controller_obj, self.frame_number)
        if prev_frame is None:
            self.report({'WARNING'}, "No previous keyframe found. Brownian motion requires a starting position.")
            return {'CANCELLED'}

        # Build settings dictionary
        settings = {
            'enabled': True,
            'intensity': self.intensity,
            'time_scale': self.time_scale,
            'use_random_seed': self.use_random_seed,
            'seed': self.seed if not self.use_random_seed else None,
            'bias_x': self.bias_x,
            'bias_y': self.bias_y,
            'bias_z': self.bias_z,
            'start_frame': prev_frame,
            'puppet_id': self.puppet_id,
        }

        # Save to controller object
        save_brownian_metadata(controller_obj, self.frame_number, settings)

        self.report({'INFO'}, f"Brownian motion settings saved for '{self.puppet_name}' (frames {prev_frame}-{self.frame_number})")
        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_disable(Operator):
    """Disable Brownian motion for a puppet keyframe"""
    bl_idname = "proteinblender.brownian_disable"
    bl_label = "Disable Brownian Motion"
    bl_options = {'REGISTER', 'UNDO'}

    puppet_id: StringProperty(name="Puppet ID")
    controller_object_name: StringProperty(name="Controller Object")
    frame_number: IntProperty(name="Frame", default=1, min=1)

    def execute(self, context):
        """Disable Brownian motion by setting enabled to False."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            return {'CANCELLED'}

        # Get existing metadata
        metadata = get_brownian_metadata(controller_obj)
        frame_key = str(self.frame_number)

        if frame_key in metadata:
            # Mark as disabled rather than deleting (preserves settings)
            metadata[frame_key]['enabled'] = False
            controller_obj['pb_brownian_metadata'] = json.dumps(metadata)

        return {'FINISHED'}


# Classes to register
CLASSES = (
    PROTEINBLENDER_OT_brownian_settings,
    PROTEINBLENDER_OT_brownian_disable,
)


def register():
    """Register Brownian motion operators."""
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister Brownian motion operators."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
