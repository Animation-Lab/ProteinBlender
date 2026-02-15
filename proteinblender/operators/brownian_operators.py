"""Brownian motion operators for ProteinBlender.

This module provides operators for configuring Brownian motion settings
on puppet keyframe segments using baked jitter keyframes.

The system pre-computes JITTER keyframes at evenly-spaced intervals,
placing the protein at a random position within a sphere around the
interpolated path, with independent random rotation per axis. The effect
is jagged, disconnected motion like a dice bouncing on a table.
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
    rebuild_all_brownian_motion,
    rebuild_all_brownian_modifiers,  # legacy compat for v1 metadata
    clear_baked_brownian_keyframes,
    remove_brownian_noise_modifiers,
)
from ..utils.animation import ensure_quaternion_mode


class PROTEINBLENDER_OT_brownian_settings(Operator):
    """Configure Brownian motion settings for a puppet keyframe segment."""
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
        description="Maximum displacement sphere radius (Blender units)",
        min=0.1,
        max=10.0,
        default=1.0
    )

    jitter_max_rotation: FloatProperty(
        name="Max Rotation",
        description="Maximum random rotation per axis (degrees)",
        min=0.0,
        max=360.0,
        default=30.0,
        step=100,
        precision=0
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

    # Physical parameterization
    use_physical_params: BoolProperty(
        name="Physical Mode",
        description="Derive max distance and rotation from molecular weight (overrides manual sliders)",
        default=False
    )

    molecular_weight: FloatProperty(
        name="Molecular Weight (kDa)",
        description="Protein molecular weight. Examples: Insulin=5.8, BSA=66, IgG=150",
        min=1.0,
        max=10000.0,
        default=50.0,
        precision=1
    )

    temperature: FloatProperty(
        name="Temperature (K)",
        description="Simulation temperature (room temp = 298 K, body temp = 310 K)",
        min=100.0,
        max=500.0,
        default=300.0,
        precision=1
    )

    viscosity_factor: FloatProperty(
        name="Viscosity Factor",
        description="Solvent viscosity multiplier (1.0 = water at 20C)",
        min=0.1,
        max=100.0,
        default=1.0,
        precision=2
    )

    def invoke(self, context, event):
        """Initialize settings from existing metadata if available."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if controller_obj:
            metadata = get_brownian_metadata(controller_obj)
            frame_key = str(self.frame_number)

            if frame_key in metadata:
                settings = metadata[frame_key]
                self.jitter_interval = settings.get('jitter_interval', 3)
                self.jitter_max_distance = settings.get('jitter_max_distance', 1.0)
                self.jitter_max_rotation = settings.get('jitter_max_rotation', 30.0)
                self.use_random_seed = settings.get('use_random_seed', True)
                stored_seed = settings.get('seed')
                self.seed = stored_seed if stored_seed is not None else 12345
                self.use_physical_params = settings.get('use_physical_params', False)
                self.molecular_weight = settings.get('molecular_weight', 50.0)
                self.temperature = settings.get('temperature', 300.0)
                self.viscosity_factor = settings.get('viscosity_factor', 1.0)

        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        """Draw the settings popup UI."""
        layout = self.layout

        # Jitter parameters
        box = layout.box()
        box.label(text="Jitter", icon='MOD_NOISE')

        col = box.column(align=True)
        col.prop(self, "jitter_interval")

        # Physical mode toggle
        layout.separator()
        box = layout.box()
        box.label(text="Amplitude", icon='ORIENTATION_GLOBAL')
        box.prop(self, "use_physical_params")

        if self.use_physical_params:
            col = box.column(align=True)
            col.prop(self, "molecular_weight")
            col.prop(self, "temperature")
            col.prop(self, "viscosity_factor")

            info = box.column()
            info.scale_y = 0.7
            info.label(text="Max distance & rotation derived from physics", icon='INFO')
        else:
            col = box.column(align=True)
            row = col.row()
            row.prop(self, "jitter_max_distance")
            row.label(text="BU")
            row = col.row()
            row.prop(self, "jitter_max_rotation")
            row.label(text="deg")

        layout.separator()

        # Seed settings
        box = layout.box()
        box.label(text="Reproducibility", icon='FILE_REFRESH')

        row = box.row()
        row.prop(self, "use_random_seed")

        seed_row = box.row()
        seed_row.enabled = not self.use_random_seed
        seed_row.prop(self, "seed")

        col = box.column()
        col.scale_y = 0.7
        if self.use_random_seed:
            col.label(text="Motion varies each session", icon='BLANK1')
        else:
            col.label(text="Same seed = identical renders", icon='BLANK1')

    def execute(self, context):
        """Save the Brownian motion settings and bake JITTER keyframes."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            self.report({'ERROR'}, f"Controller object '{self.controller_object_name}' not found")
            return {'CANCELLED'}

        # Find previous keyframe to determine start frame
        prev_frame = find_previous_keyframe(controller_obj, self.frame_number)
        if prev_frame is None:
            self.report({'WARNING'}, "No previous keyframe found. Brownian motion requires a starting position.")
            return {'CANCELLED'}

        # Ensure quaternion mode
        ensure_quaternion_mode(controller_obj)

        # Keyframe the current position/rotation BEFORE applying jitter
        controller_obj.keyframe_insert(data_path='location', frame=self.frame_number)
        controller_obj.keyframe_insert(data_path='rotation_quaternion', frame=self.frame_number)

        # Build settings dictionary
        settings = {
            'enabled': True,
            'jitter_interval': self.jitter_interval,
            'jitter_max_distance': self.jitter_max_distance,
            'jitter_max_rotation': self.jitter_max_rotation,
            'use_random_seed': self.use_random_seed,
            'seed': self.seed if not self.use_random_seed else None,
            'start_frame': prev_frame,
            'puppet_id': self.puppet_id,
            'use_physical_params': self.use_physical_params,
            'molecular_weight': self.molecular_weight,
            'temperature': self.temperature,
            'viscosity_factor': self.viscosity_factor,
        }

        # Save to controller object (this also bakes the JITTER keyframes)
        save_brownian_metadata(controller_obj, self.frame_number, settings)

        self.report({'INFO'}, f"Brownian motion configured for '{self.puppet_name}' (frames {prev_frame}-{self.frame_number})")
        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_disable(Operator):
    """Disable Brownian motion for a puppet keyframe segment."""
    bl_idname = "proteinblender.brownian_disable"
    bl_label = "Disable Brownian Motion"
    bl_options = {'REGISTER', 'UNDO'}

    puppet_id: StringProperty(name="Puppet ID")
    controller_object_name: StringProperty(name="Controller Object")
    frame_number: IntProperty(name="Frame", default=1, min=1)

    def execute(self, context):
        """Disable Brownian motion by removing baked keyframes and updating metadata."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            return {'CANCELLED'}

        metadata = get_brownian_metadata(controller_obj)
        frame_key = str(self.frame_number)

        if frame_key in metadata:
            start_frame = metadata[frame_key].get('start_frame', 1)

            clear_baked_brownian_keyframes(controller_obj, start_frame, self.frame_number)
            remove_brownian_noise_modifiers(controller_obj, start_frame, self.frame_number)

            metadata[frame_key]['enabled'] = False
            controller_obj['pb_brownian_metadata'] = json.dumps(metadata)

        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_rebuild(Operator):
    """Rebuild all Brownian motion from stored metadata."""
    bl_idname = "proteinblender.brownian_rebuild"
    bl_label = "Rebuild Brownian Motion"
    bl_description = "Regenerate jitter keyframes from stored metadata"
    bl_options = {'REGISTER', 'UNDO'}

    controller_object_name: StringProperty(
        name="Controller Object",
        description="Name of controller to rebuild (empty = all puppets)",
        default=""
    )

    def execute(self, context):
        """Rebuild Brownian motion for all puppets or a specific one."""
        scene = context.scene
        rebuilt_count = 0

        if self.controller_object_name:
            controller_obj = bpy.data.objects.get(self.controller_object_name)
            if controller_obj:
                rebuild_all_brownian_modifiers(controller_obj)
                rebuilt_count = 1
                self.report({'INFO'}, f"Rebuilt Brownian motion for '{controller_obj.name}'")
            else:
                self.report({'ERROR'}, f"Controller '{self.controller_object_name}' not found")
                return {'CANCELLED'}
        else:
            if hasattr(scene, 'outliner_items'):
                for item in scene.outliner_items:
                    if item.item_type == 'PUPPET' and item.controller_object_name:
                        controller_obj = bpy.data.objects.get(item.controller_object_name)
                        if controller_obj:
                            rebuild_all_brownian_modifiers(controller_obj)
                            rebuilt_count += 1

            if rebuilt_count > 0:
                self.report({'INFO'}, f"Rebuilt Brownian motion for {rebuilt_count} puppet(s)")
            else:
                self.report({'WARNING'}, "No puppets found to rebuild")

        return {'FINISHED'}


class PROTEINBLENDER_OT_brownian_clear_all(Operator):
    """Remove all Brownian motion from a puppet."""
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
        """Remove all baked Brownian keyframes and metadata."""
        controller_obj = bpy.data.objects.get(self.controller_object_name)
        if not controller_obj:
            self.report({'ERROR'}, f"Controller '{self.controller_object_name}' not found")
            return {'CANCELLED'}

        metadata = get_brownian_metadata(controller_obj)

        for frame_key, settings in metadata.items():
            start_frame = settings.get('start_frame', 1)
            end_frame = int(frame_key)
            clear_baked_brownian_keyframes(controller_obj, start_frame, end_frame)

        remove_brownian_noise_modifiers(controller_obj)

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
