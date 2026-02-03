"""Brownian motion operators for ProteinBlender.

This module provides operators for configuring Brownian motion settings
on puppet keyframe segments using F-Curve Noise modifiers.

The Brownian motion system uses Blender's built-in noise modifiers to create
smooth, temporally correlated motion that:
- Looks physically plausible ("floaty" wandering)
- Is render-safe (no handler timing issues)
- Is deterministic when using a fixed seed
- Has no popping at segment boundaries (blend in/out)
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
    rebuild_all_brownian_modifiers,
    remove_brownian_noise_modifiers,
)


class PROTEINBLENDER_OT_brownian_settings(Operator):
    """Configure Brownian motion settings for a puppet keyframe segment.

    This creates F-Curve Noise modifiers on the puppet controller to produce
    smooth, temporally correlated Brownian motion.
    """
    bl_idname = "proteinblender.brownian_settings"
    bl_label = "Brownian Motion Settings"
    bl_options = {'REGISTER'}

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

    # Movement parameters
    movement_speed: FloatProperty(
        name="Speed",
        description="How fast the movement changes (0 = slow, gentle drift | 1 = fast, active motion)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    movement_distance: FloatProperty(
        name="Distance",
        description="Maximum displacement from keyframed position (Blender units)",
        min=0.0,
        max=10.0,
        default=1.0
    )

    # Rotation parameters
    rotation_speed: FloatProperty(
        name="Speed",
        description="How fast the rotation changes (0 = slow, gentle tumbling | 1 = fast, active spinning)",
        min=0.0,
        max=1.0,
        default=0.5,
        subtype='FACTOR'
    )

    rotation_distance: FloatProperty(
        name="Distance",
        description="Maximum rotation deviation (degrees, max 60)",
        min=0.0,
        max=60.0,
        default=30.0
    )

    # Reproducibility settings
    use_random_seed: BoolProperty(
        name="Random Seed",
        description="Use random seed (different motion each session) or fixed seed (reproducible renders)",
        default=True
    )

    seed: IntProperty(
        name="Seed Value",
        description="Fixed seed for reproducible motion. Same seed = identical motion across renders",
        default=12345,
        min=0
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
                self.movement_speed = settings.get('movement_speed', 0.5)
                self.movement_distance = settings.get('movement_distance', 1.0)
                self.rotation_speed = settings.get('rotation_speed', 0.5)
                self.rotation_distance = settings.get('rotation_distance', 30.0)
                self.use_random_seed = settings.get('use_random_seed', True)
                # Handle None seed value (stored when use_random_seed=True)
                stored_seed = settings.get('seed')
                self.seed = stored_seed if stored_seed is not None else 12345

        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        """Draw the settings popup UI."""
        layout = self.layout

        # Header with explanation
        col = layout.column()
        col.scale_y = 0.8
        col.label(text="F-Curve noise modifiers create smooth,", icon='INFO')
        col.label(text="temporally correlated 'floaty' motion.")

        layout.separator()

        # Movement parameters
        box = layout.box()
        box.label(text="Movement", icon='ORIENTATION_GLOBAL')

        col = box.column(align=True)
        col.prop(self, "movement_speed", text="Speed")
        row = col.row()
        row.prop(self, "movement_distance", text="Distance")
        row.label(text="BU")

        # Visual guide for speed
        row = box.row()
        row.scale_y = 0.6
        split = row.split(factor=0.5)
        left = split.row()
        left.alignment = 'LEFT'
        left.label(text="Slow drift")
        right = split.row()
        right.alignment = 'RIGHT'
        right.label(text="Fast motion")

        layout.separator()

        # Rotation parameters
        box = layout.box()
        box.label(text="Rotation", icon='ORIENTATION_GIMBAL')

        col = box.column(align=True)
        col.prop(self, "rotation_speed", text="Speed")
        row = col.row()
        row.prop(self, "rotation_distance", text="Distance")
        row.label(text="deg")

        # Visual guide for speed
        row = box.row()
        row.scale_y = 0.6
        split = row.split(factor=0.5)
        left = split.row()
        left.alignment = 'LEFT'
        left.label(text="Slow tumble")
        right = split.row()
        right.alignment = 'RIGHT'
        right.label(text="Fast spin")

        layout.separator()

        # Seed settings
        box = layout.box()
        box.label(text="Reproducibility", icon='FILE_REFRESH')

        row = box.row()
        row.prop(self, "use_random_seed")

        seed_row = box.row()
        seed_row.enabled = not self.use_random_seed
        seed_row.prop(self, "seed")

        # Explanation
        col = box.column()
        col.scale_y = 0.7
        if self.use_random_seed:
            col.label(text="Motion varies each session", icon='BLANK1')
        else:
            col.label(text="Same seed = identical renders", icon='BLANK1')

    def execute(self, context):
        """Save the Brownian motion settings and create noise modifiers."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            self.report({'ERROR'}, f"Controller object '{self.controller_object_name}' not found")
            return {'CANCELLED'}

        # Find previous keyframe to determine start frame
        prev_frame = find_previous_keyframe(controller_obj, self.frame_number)
        if prev_frame is None:
            self.report({'WARNING'}, "No previous keyframe found. Brownian motion requires a starting position.")
            return {'CANCELLED'}

        # CRITICAL: Keyframe the current position/rotation BEFORE applying Brownian motion
        # This preserves the object's current pose and prevents snap-back to frame 1
        # Store current transforms
        current_location = controller_obj.location.copy()
        current_rotation = controller_obj.rotation_euler.copy() if controller_obj.rotation_mode != 'QUATERNION' else controller_obj.rotation_quaternion.copy()

        # Insert keyframes at the current frame to preserve the current position
        controller_obj.keyframe_insert(data_path='location', frame=self.frame_number)
        if controller_obj.rotation_mode == 'QUATERNION':
            controller_obj.keyframe_insert(data_path='rotation_quaternion', frame=self.frame_number)
        else:
            controller_obj.keyframe_insert(data_path='rotation_euler', frame=self.frame_number)

        print(f"📍 Keyframed position at frame {self.frame_number}: loc={current_location}")

        # Build settings dictionary
        settings = {
            'enabled': True,
            'movement_speed': self.movement_speed,
            'movement_distance': self.movement_distance,
            'rotation_speed': self.rotation_speed,
            'rotation_distance': self.rotation_distance,
            'use_random_seed': self.use_random_seed,
            'seed': self.seed if not self.use_random_seed else None,
            'start_frame': prev_frame,
            'puppet_id': self.puppet_id,
        }

        # Save to controller object (this also creates the noise modifiers)
        save_brownian_metadata(controller_obj, self.frame_number, settings)

        self.report({'INFO'}, f"Brownian motion configured for '{self.puppet_name}' (frames {prev_frame}-{self.frame_number})")
        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_disable(Operator):
    """Disable Brownian motion for a puppet keyframe segment.

    This removes the F-Curve Noise modifiers for the specified segment.
    """
    bl_idname = "proteinblender.brownian_disable"
    bl_label = "Disable Brownian Motion"
    bl_options = {'REGISTER', 'UNDO'}

    puppet_id: StringProperty(name="Puppet ID")
    controller_object_name: StringProperty(name="Controller Object")
    frame_number: IntProperty(name="Frame", default=1, min=1)

    def execute(self, context):
        """Disable Brownian motion by removing noise modifiers and updating metadata."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            return {'CANCELLED'}

        # Get existing metadata
        metadata = get_brownian_metadata(controller_obj)
        frame_key = str(self.frame_number)

        if frame_key in metadata:
            # Get the segment range
            start_frame = metadata[frame_key].get('start_frame', 1)

            # Remove noise modifiers for this segment
            remove_brownian_noise_modifiers(controller_obj, start_frame, self.frame_number)

            # Mark as disabled in metadata (preserves settings for re-enabling)
            metadata[frame_key]['enabled'] = False
            controller_obj['pb_brownian_metadata'] = json.dumps(metadata)

        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_rebuild(Operator):
    """Rebuild all Brownian motion noise modifiers from stored metadata.

    Use this to regenerate the F-Curve noise modifiers if they were
    accidentally deleted or if upgrading from an older version.
    """
    bl_idname = "proteinblender.brownian_rebuild"
    bl_label = "Rebuild Brownian Motion"
    bl_description = "Regenerate F-Curve noise modifiers from stored metadata"
    bl_options = {'REGISTER', 'UNDO'}

    # Optional: specify a single puppet, or leave empty to rebuild all
    controller_object_name: StringProperty(
        name="Controller Object",
        description="Name of controller to rebuild (empty = all puppets)",
        default=""
    )

    def execute(self, context):
        """Rebuild noise modifiers for all puppets or a specific one."""
        scene = context.scene
        rebuilt_count = 0

        if self.controller_object_name:
            # Rebuild specific controller
            controller_obj = bpy.data.objects.get(self.controller_object_name)
            if controller_obj:
                rebuild_all_brownian_modifiers(controller_obj)
                rebuilt_count = 1
                self.report({'INFO'}, f"Rebuilt Brownian modifiers for '{controller_obj.name}'")
            else:
                self.report({'ERROR'}, f"Controller '{self.controller_object_name}' not found")
                return {'CANCELLED'}
        else:
            # Rebuild all puppets
            if hasattr(scene, 'outliner_items'):
                for item in scene.outliner_items:
                    if item.item_type == 'PUPPET' and item.controller_object_name:
                        controller_obj = bpy.data.objects.get(item.controller_object_name)
                        if controller_obj:
                            rebuild_all_brownian_modifiers(controller_obj)
                            rebuilt_count += 1

            if rebuilt_count > 0:
                self.report({'INFO'}, f"Rebuilt Brownian modifiers for {rebuilt_count} puppet(s)")
            else:
                self.report({'WARNING'}, "No puppets found to rebuild")

        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_clear_all(Operator):
    """Remove all Brownian motion from a puppet.

    This removes all F-Curve noise modifiers and clears the metadata.
    """
    bl_idname = "proteinblender.brownian_clear_all"
    bl_label = "Clear All Brownian Motion"
    bl_description = "Remove all Brownian motion from the selected puppet"
    bl_options = {'REGISTER', 'UNDO'}

    controller_object_name: StringProperty(
        name="Controller Object",
        description="Name of controller to clear"
    )

    def invoke(self, context, event):
        """Confirm before clearing."""
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        """Remove all Brownian noise modifiers and metadata."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            self.report({'ERROR'}, f"Controller '{self.controller_object_name}' not found")
            return {'CANCELLED'}

        # Remove all noise modifiers
        remove_brownian_noise_modifiers(controller_obj)

        # Clear metadata
        if 'pb_brownian_metadata' in controller_obj:
            del controller_obj['pb_brownian_metadata']

        self.report({'INFO'}, f"Cleared all Brownian motion from '{controller_obj.name}'")
        return {'FINISHED'}


# Classes to register
CLASSES = (
    PROTEINBLENDER_OT_brownian_settings,
    PROTEINBLENDER_OT_brownian_disable,
    PROTEINBLENDER_OT_brownian_rebuild,
    PROTEINBLENDER_OT_brownian_clear_all,
)


def register():
    """Register Brownian motion operators."""
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister Brownian motion operators."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
