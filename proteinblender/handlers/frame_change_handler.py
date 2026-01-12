"""Frame change handler for updating animated properties"""

import bpy
import random
from bpy.app.handlers import persistent
from mathutils import Vector

from ..utils.brownian import (
    get_brownian_settings_for_frame,
    calculate_brownian_displacement,
    get_keyframed_location_at_frame,
)


# Cache to store base (keyframed) locations for Brownian motion
# Key: object name, Value: base location Vector
_brownian_base_cache = {}


@persistent
def clear_brownian_cache_on_load(dummy):
    """Clear Brownian cache when a new file is loaded."""
    global _brownian_base_cache
    _brownian_base_cache.clear()


@persistent
def apply_brownian_motion(scene):
    """Apply Brownian motion to puppets on frame change.

    This handler runs after Blender has evaluated keyframes, allowing us to
    add Brownian displacement on top of the interpolated position.
    """
    frame = scene.frame_current

    # Check if we have outliner_items
    if not hasattr(scene, 'outliner_items'):
        return

    for item in scene.outliner_items:
        if item.item_type != 'PUPPET':
            continue

        if not item.controller_object_name:
            continue

        controller = bpy.data.objects.get(item.controller_object_name)
        if not controller:
            continue

        # Get Brownian settings for current frame
        settings = get_brownian_settings_for_frame(controller, frame)

        if not settings or not settings.get('enabled', False):
            # No Brownian motion for this frame - restore base location if cached
            cache_key = controller.name
            if cache_key in _brownian_base_cache:
                # Don't restore - let Blender's animation system handle it
                del _brownian_base_cache[cache_key]
            continue

        # Get the base location from keyframe interpolation
        # We need to read this BEFORE applying our displacement
        base_location = get_keyframed_location_at_frame(controller, frame)

        if base_location is None:
            # No keyframed location, use current location
            base_location = controller.location.copy()

        # Store the base location in cache
        cache_key = controller.name
        _brownian_base_cache[cache_key] = base_location

        # Calculate Brownian displacement
        intensity = settings.get('intensity', 0.3)
        time_scale = settings.get('time_scale', 0.5)
        use_random_seed = settings.get('use_random_seed', True)
        seed = None if use_random_seed else settings.get('seed', 12345)
        bias = (
            settings.get('bias_x', 0.5),
            settings.get('bias_y', 0.5),
            settings.get('bias_z', 0.5)
        )

        displacement = calculate_brownian_displacement(
            intensity, time_scale, bias, seed, frame
        )

        # Apply displacement additively
        controller.location = base_location + displacement


@persistent
def update_colors_on_frame_change(scene):
    """Update object colors from custom properties when frame changes"""
    # Import here to avoid circular imports
    from ..panels.visual_setup_panel import apply_color_to_object
    
    # Track which objects we've updated to avoid redundant updates
    updated_objects = set()
    
    # Check all objects for color properties
    for obj in bpy.data.objects:
        # Skip if already updated or no color property
        if obj in updated_objects or "pb_color" not in obj:
            continue
            
        # Get the interpolated color value at the current frame
        # Blender automatically interpolates custom properties if they're keyframed
        color = obj["pb_color"]
        
        # Apply the color to the object's visual representation
        if color and len(color) >= 3:
            # Convert to tuple (RGBA)
            if len(color) == 3:
                color = (*color, 1.0)  # Add alpha if not present
            else:
                color = tuple(color[:4])  # Ensure we have exactly 4 components
            
            apply_color_to_object(obj, color)
            updated_objects.add(obj)
            
            # Debug output (can be removed later)
            print(f"Frame {scene.frame_current}: Updated color for {obj.name} to {color}")


def register():
    """Register the frame change handlers"""
    # Remove any existing handlers to avoid duplicates
    unregister()

    # Add the handlers
    # Brownian motion should run first to modify positions
    bpy.app.handlers.frame_change_post.append(apply_brownian_motion)
    bpy.app.handlers.frame_change_post.append(update_colors_on_frame_change)

    # Register load handler to clear cache when loading new files
    bpy.app.handlers.load_post.append(clear_brownian_cache_on_load)

    print("Registered frame change handlers (Brownian motion, color update)")


def unregister():
    """Unregister the frame change handlers"""
    global _brownian_base_cache
    _brownian_base_cache.clear()

    # Remove color update handler
    handlers_to_remove = [h for h in bpy.app.handlers.frame_change_post
                         if h.__name__ == "update_colors_on_frame_change"]

    for handler in handlers_to_remove:
        bpy.app.handlers.frame_change_post.remove(handler)

    # Remove Brownian motion handler
    handlers_to_remove = [h for h in bpy.app.handlers.frame_change_post
                         if h.__name__ == "apply_brownian_motion"]

    for handler in handlers_to_remove:
        bpy.app.handlers.frame_change_post.remove(handler)

    # Remove load handler
    handlers_to_remove = [h for h in bpy.app.handlers.load_post
                         if h.__name__ == "clear_brownian_cache_on_load"]

    for handler in handlers_to_remove:
        bpy.app.handlers.load_post.remove(handler)

    print("Unregistered frame change handlers")