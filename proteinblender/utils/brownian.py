"""Brownian motion implementation using F-Curve Noise modifiers.

This module provides physics-plausible Brownian motion for protein puppets using
Blender's built-in F-Curve Noise modifiers. This approach produces temporally
correlated motion (smooth wandering) rather than per-frame white noise.

Key advantages of F-Curve Noise modifiers:
- Render-safe: Evaluated as part of Blender's animation system
- Temporally correlated: Produces smooth, coherent motion
- Deterministic: Phase parameter ensures reproducibility
- No handler timing issues: Works with motion blur and out-of-order frames

The noise modifier produces values using Blender's noise function:
    value = strength * noise(time * scale + phase)

We map user parameters as follows:
    - movement_speed / rotation_speed -> noise scale (inverted: higher speed = lower scale)
    - movement_distance -> noise strength for location (in Blender units)
    - rotation_distance -> noise strength for rotation (in degrees, converted to radians)
    - seed -> phase offset (deterministic per-puppet variation)
"""

import math
import json
import hashlib
from mathutils import Vector, Quaternion, Euler

from .animation import get_fcurves_from_action, USE_SLOTTED_ACTIONS


# ============================================================================
# Noise Modifier Configuration
# ============================================================================

# IMPORTANT: Blender's noise modifier scale parameter is INVERSE to intuition:
# - HIGHER scale = SLOWER, smoother motion (stretches noise pattern in time)
# - LOWER scale = FASTER, more jittery motion
#
# The noise modifier with blend_type='ADD' adds values in range [-0.5, 0.5] * strength
# So strength=2.0 gives ±1.0 units of displacement on top of the keyframed position

# Speed -> Noise Scale mapping (inverted: higher speed = lower scale = faster motion)
SPEED_SCALE_MIN = 5.0    # Scale when speed=1 (fastest motion)
SPEED_SCALE_MAX = 25.0   # Scale when speed=0 (slowest drift)

# Noise complexity - adds natural variation
NOISE_DEPTH = 2  # Octaves of detail for more organic motion

# Blend margin for smooth transitions at segment boundaries (in frames)
BLEND_MARGIN_FRAMES = 5



def _compute_phase_from_seed(seed, puppet_id, axis_index, is_rotation=False):
    """Compute a deterministic phase offset for noise modifier.

    Uses a hash of seed + puppet_id + axis to ensure:
    - Each puppet has different motion
    - Each axis (X/Y/Z) has independent noise
    - Motion is reproducible with the same seed

    Args:
        seed: User-provided seed value (or None for random)
        puppet_id: Unique identifier for the puppet
        axis_index: 0=X, 1=Y, 2=Z (or 0=W, 1=X, 2=Y, 3=Z for quaternion)
        is_rotation: Whether this is for rotation channels

    Returns:
        float: Phase offset in range [0, 1000]
    """
    if seed is None:
        # Random mode - use object name hash for consistency within session
        # but different each time the scene is reloaded
        import random
        return random.random() * 1000

    # Deterministic mode - hash the combined values
    hash_input = f"{seed}_{puppet_id}_{axis_index}_{'rot' if is_rotation else 'loc'}"
    hash_bytes = hashlib.md5(hash_input.encode()).digest()
    # Convert first 4 bytes to float in range [0, 1000]
    hash_int = int.from_bytes(hash_bytes[:4], byteorder='little')
    return (hash_int % 10000) / 10.0


def _map_speed_to_noise_scale(speed):
    """Map user speed (0-1) to noise modifier scale.

    IMPORTANT: Blender's scale is INVERSE to intuition:
    - Higher scale = SLOWER motion
    - Lower scale = FASTER motion

    So speed=1 gives LOW scale (fast motion)
       speed=0 gives HIGH scale (slow motion)

    Args:
        speed: User speed value 0-1 (0=slow drift, 1=fast motion)

    Returns:
        float: Noise modifier scale value
    """
    # Invert: speed=1 -> SPEED_SCALE_MIN, speed=0 -> SPEED_SCALE_MAX
    return SPEED_SCALE_MAX - speed * (SPEED_SCALE_MAX - SPEED_SCALE_MIN)


def _map_movement_distance_to_strength(distance_bu):
    """Map movement distance (Blender units) to noise modifier strength.

    With blend_type='ADD': noise adds values in range [-0.5, 0.5] * strength
    So to get X Blender units of max displacement: strength = X * 2

    Args:
        distance_bu: Maximum displacement in Blender units (0-10)

    Returns:
        float: Noise modifier strength value
    """
    return distance_bu * 2.0


def _map_rotation_distance_to_strength(degrees):
    """Map rotation distance (degrees) to noise modifier strength.

    Converts degrees to radians, then accounts for ADD blend type.
    With blend_type='ADD': noise adds values in range [-0.5, 0.5] * strength
    So to get X radians of max rotation: strength = X * 2

    Args:
        degrees: Maximum rotation in degrees (0-60)

    Returns:
        float: Noise modifier strength value
    """
    radians = math.radians(degrees)
    return radians * 2.0


# ============================================================================
# F-Curve and Modifier Management
# ============================================================================

def _ensure_fcurve_exists(obj, data_path, array_index=0):
    """Ensure an F-Curve exists for the given property, creating if needed.

    Args:
        obj: Blender object
        data_path: Property path (e.g., 'location', 'rotation_quaternion')
        array_index: Index for array properties (0=X, 1=Y, 2=Z)

    Returns:
        FCurve object, or None if creation failed
    """
    import bpy

    # Ensure animation data exists
    if not obj.animation_data:
        obj.animation_data_create()

    # Ensure action exists
    if not obj.animation_data.action:
        action = bpy.data.actions.new(name=f"{obj.name}_Action")
        obj.animation_data.action = action

    action = obj.animation_data.action

    # Handle Blender 4.4+ slotted actions
    if USE_SLOTTED_ACTIONS:
        from .animation import _get_channelbag

        # Ensure slot exists
        if not hasattr(obj.animation_data, 'action_slot') or not obj.animation_data.action_slot:
            if hasattr(action, 'slots') and len(action.slots) == 0:
                # Create a slot for this object
                slot = action.slots.new(for_id=obj)
                obj.animation_data.action_slot = slot
            elif hasattr(action, 'slots') and len(action.slots) > 0:
                obj.animation_data.action_slot = action.slots[0]

        # Ensure layer and strip exist
        if hasattr(action, 'layers') and len(action.layers) == 0:
            action.layers.new(name="Layer")

        if hasattr(action, 'layers') and len(action.layers) > 0:
            layer = action.layers[0]
            if hasattr(layer, 'strips') and len(layer.strips) == 0:
                layer.strips.new(type='KEYFRAME')

        channelbag = _get_channelbag(action, obj.animation_data)
        if channelbag:
            # Look for existing fcurve
            for fc in channelbag.fcurves:
                if fc.data_path == data_path and fc.array_index == array_index:
                    return fc
            # Create new fcurve
            return channelbag.fcurves.new(data_path, index=array_index)
    else:
        # Legacy Blender API
        fcurves = action.fcurves

        # Look for existing fcurve
        for fc in fcurves:
            if fc.data_path == data_path and fc.array_index == array_index:
                return fc

        # Create new fcurve
        return fcurves.new(data_path=data_path, index=array_index)

    return None


def _get_fcurve(obj, data_path, array_index=0):
    """Get an existing F-Curve for the given property.

    Args:
        obj: Blender object
        data_path: Property path (e.g., 'location', 'rotation_quaternion')
        array_index: Index for array properties (0=X, 1=Y, 2=Z)

    Returns:
        FCurve object, or None if not found
    """
    if not obj.animation_data or not obj.animation_data.action:
        return None

    fcurves = get_fcurves_from_action(obj.animation_data.action, obj.animation_data)

    for fc in fcurves:
        if fc.data_path == data_path and fc.array_index == array_index:
            return fc

    return None


def _remove_brownian_noise_modifiers(fcurve):
    """Remove all Brownian motion noise modifiers from an F-Curve.

    Brownian modifiers are identified by having 'pb_brownian' in their name.

    Args:
        fcurve: The F-Curve to clean
    """
    if not fcurve:
        return

    # Collect modifiers to remove (iterate in reverse to avoid index issues)
    to_remove = []
    for mod in fcurve.modifiers:
        if mod.type == 'NOISE' and hasattr(mod, 'name') and 'pb_brownian' in mod.name:
            to_remove.append(mod)

    for mod in to_remove:
        fcurve.modifiers.remove(mod)


def _add_brownian_noise_modifier(fcurve, settings, axis_index, is_rotation=False):
    """Add a Brownian motion noise modifier to an F-Curve.

    Args:
        fcurve: The F-Curve to add the modifier to
        settings: Dictionary with Brownian settings (speed, distance, etc.)
        axis_index: Axis index (0=X, 1=Y, 2=Z)
        is_rotation: Whether this is for rotation channels

    Returns:
        The created noise modifier, or None if failed
    """
    if not fcurve:
        return None

    # Create the noise modifier
    noise_mod = fcurve.modifiers.new(type='NOISE')

    # Extract settings based on whether this is rotation or movement
    if is_rotation:
        speed = settings.get('rotation_speed', 0.5)
        distance = settings.get('rotation_distance', 30.0)  # degrees
        strength = _map_rotation_distance_to_strength(distance)
    else:
        speed = settings.get('movement_speed', 0.5)
        distance = settings.get('movement_distance', 1.0)  # Blender units
        strength = _map_movement_distance_to_strength(distance)

    use_random_seed = settings.get('use_random_seed', True)
    seed = None if use_random_seed else settings.get('seed', 12345)
    puppet_id = settings.get('puppet_id', 'unknown')
    start_frame = settings.get('start_frame', 1)
    end_frame = int(settings.get('end_frame', 250))

    # Use ADD blend type to add noise on top of the keyframed position
    # This preserves the keyframed animation and adds Brownian motion on top
    noise_mod.blend_type = 'ADD'

    # Configure noise modifier parameters
    noise_mod.strength = strength
    noise_mod.scale = _map_speed_to_noise_scale(speed)

    # CRITICAL: Each axis needs a DIFFERENT phase value for independent motion
    # Otherwise all axes move in sync which looks unnatural
    noise_mod.phase = _compute_phase_from_seed(seed, puppet_id, axis_index, is_rotation)

    # No offset/bias - motion is centered around the keyframed position
    noise_mod.offset = 0.0

    # Depth adds octaves of detail for more natural, organic motion
    noise_mod.depth = NOISE_DEPTH

    # Set frame range restriction
    noise_mod.use_restricted_range = True
    noise_mod.frame_start = float(start_frame)
    noise_mod.frame_end = float(end_frame)

    # Set blend in/out for smooth transitions at segment boundaries
    noise_mod.blend_in = float(BLEND_MARGIN_FRAMES)
    noise_mod.blend_out = float(BLEND_MARGIN_FRAMES)

    return noise_mod


# ============================================================================
# Main API Functions
# ============================================================================

def apply_brownian_noise_modifiers(controller_obj, settings):
    """Apply F-Curve noise modifiers to a controller object for Brownian motion.

    This creates noise modifiers on the controller's location and rotation F-Curves
    to produce smooth, temporally correlated Brownian motion.

    Args:
        controller_obj: The puppet controller Empty object
        settings: Dictionary with Brownian settings:
            - enabled: bool
            - movement_speed: float (0-1, 0=slow drift, 1=fast motion)
            - movement_distance: float (0-10, max displacement in Blender units)
            - rotation_speed: float (0-1, 0=slow tumbling, 1=fast spinning)
            - rotation_distance: float (0-60, max rotation in degrees)
            - use_random_seed: bool
            - seed: int (used when use_random_seed is False)
            - start_frame: int
            - end_frame: int (same as the frame key in metadata)
            - puppet_id: str
    """
    if not controller_obj:
        return

    if not settings.get('enabled', False):
        return

    # Use Euler rotation mode for Brownian motion
    # Quaternions have a bias toward identity when noise is added to components independently
    # Euler angles (X, Y, Z) are truly independent axes, so noise on each axis creates
    # unbiased tumbling in all directions
    if controller_obj.rotation_mode == 'QUATERNION':
        # Convert to Euler for Brownian motion
        controller_obj.rotation_mode = 'XYZ'
        # The rotation_euler will be automatically set from the quaternion

    # Debug: Print the actual values being used
    movement_speed = settings.get('movement_speed', 0.5)
    movement_distance = settings.get('movement_distance', 1.0)
    rotation_speed = settings.get('rotation_speed', 0.5)
    rotation_distance = settings.get('rotation_distance', 30.0)

    loc_strength = _map_movement_distance_to_strength(movement_distance)
    rot_strength = _map_rotation_distance_to_strength(rotation_distance)
    loc_scale = _map_speed_to_noise_scale(movement_speed)
    rot_scale = _map_speed_to_noise_scale(rotation_speed)

    print(f"🌊 Brownian Motion Settings for '{controller_obj.name}':")
    print(f"   Movement: speed={movement_speed:.2f} -> scale={loc_scale:.2f}, distance={movement_distance:.2f} BU -> strength={loc_strength:.2f}")
    print(f"   Rotation: speed={rotation_speed:.2f} -> scale={rot_scale:.2f}, distance={rotation_distance:.2f}° -> strength={rot_strength:.2f}")

    # Apply noise to location channels (X, Y, Z)
    axis_names = ['X', 'Y', 'Z']
    start_frame = settings.get('start_frame', 1)
    end_frame = int(settings.get('end_frame', 250))

    for axis_index in range(3):
        fcurve = _ensure_fcurve_exists(controller_obj, 'location', axis_index)
        if fcurve:
            # Debug: Show existing keyframes
            kf_frames = [int(kf.co.x) for kf in fcurve.keyframe_points]
            print(f"   Location {axis_names[axis_index]} has {len(fcurve.keyframe_points)} keyframes at frames: {kf_frames}")

            # Ensure keyframes exist at both start and end frames (required for proper interpolation)
            has_start_kf = any(abs(kf.co.x - start_frame) < 0.5 for kf in fcurve.keyframe_points)
            has_end_kf = any(abs(kf.co.x - end_frame) < 0.5 for kf in fcurve.keyframe_points)

            if not has_start_kf:
                current_value = controller_obj.location[axis_index]
                fcurve.keyframe_points.insert(start_frame, current_value)
                print(f"   -> Inserted keyframe at start frame {start_frame}")

            if not has_end_kf:
                current_value = controller_obj.location[axis_index]
                fcurve.keyframe_points.insert(end_frame, current_value)
                print(f"   -> Inserted keyframe at end frame {end_frame}")

            mod = _add_brownian_noise_modifier(fcurve, settings, axis_index, is_rotation=False)
            if mod:
                print(f"   Location {axis_names[axis_index]}: strength={mod.strength:.2f}, scale={mod.scale:.2f}, phase={mod.phase:.2f}")

    # Apply noise to rotation channels (Euler X, Y, Z)
    # Using Euler angles ensures unbiased rotation in all directions
    # Each axis gets independent noise, so the molecule tumbles freely without
    # any preference to stay "upright"
    for axis_index in range(3):
        fcurve = _ensure_fcurve_exists(controller_obj, 'rotation_euler', axis_index)
        if fcurve:
            # Debug: Show existing keyframes
            kf_frames = [int(kf.co.x) for kf in fcurve.keyframe_points]
            print(f"   Rotation {axis_names[axis_index]} has {len(fcurve.keyframe_points)} keyframes at frames: {kf_frames}")

            # Ensure keyframes exist at both start and end frames (required for proper interpolation)
            has_start_kf = any(abs(kf.co.x - start_frame) < 0.5 for kf in fcurve.keyframe_points)
            has_end_kf = any(abs(kf.co.x - end_frame) < 0.5 for kf in fcurve.keyframe_points)

            if not has_start_kf:
                current_value = controller_obj.rotation_euler[axis_index]
                fcurve.keyframe_points.insert(start_frame, current_value)
                print(f"   -> Inserted keyframe at start frame {start_frame}")

            if not has_end_kf:
                current_value = controller_obj.rotation_euler[axis_index]
                fcurve.keyframe_points.insert(end_frame, current_value)
                print(f"   -> Inserted keyframe at end frame {end_frame}")

            mod = _add_brownian_noise_modifier(fcurve, settings, axis_index, is_rotation=True)
            if mod:
                print(f"   Rotation {axis_names[axis_index]}: strength={mod.strength:.2f}, scale={mod.scale:.2f}, phase={mod.phase:.2f}")


def remove_brownian_noise_modifiers(controller_obj, start_frame=None, end_frame=None):
    """Remove Brownian noise modifiers from a controller object.

    Args:
        controller_obj: The puppet controller Empty object
        start_frame: Optional start frame to match (removes only modifiers in this range)
        end_frame: Optional end frame to match
    """
    if not controller_obj or not controller_obj.animation_data:
        return

    action = controller_obj.animation_data.action
    if not action:
        return

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    for fcurve in fcurves:
        # Only process location and rotation fcurves
        if fcurve.data_path not in ('location', 'rotation_quaternion', 'rotation_euler'):
            continue

        # Collect modifiers to remove
        to_remove = []
        for mod in fcurve.modifiers:
            if mod.type != 'NOISE':
                continue

            # Check if this is within the specified frame range (if provided)
            if start_frame is not None and end_frame is not None:
                if mod.use_restricted_range:
                    # Only remove modifiers that match this exact segment
                    # (same start and end frame)
                    if int(mod.frame_start) == int(start_frame) and int(mod.frame_end) == int(end_frame):
                        to_remove.append(mod)
                else:
                    # Unrestricted modifier - remove if any range specified
                    to_remove.append(mod)
            else:
                # No range specified - remove all noise modifiers
                to_remove.append(mod)

        for mod in to_remove:
            fcurve.modifiers.remove(mod)


def rebuild_all_brownian_modifiers(controller_obj):
    """Rebuild all Brownian noise modifiers from stored metadata.

    This removes all existing noise modifiers and recreates them from
    the pb_brownian_metadata stored on the controller object.

    Args:
        controller_obj: The puppet controller Empty object
    """
    if not controller_obj:
        return

    # Remove all existing noise modifiers
    remove_brownian_noise_modifiers(controller_obj)

    # Get metadata and rebuild
    metadata = get_brownian_metadata(controller_obj)

    for frame_key, settings in metadata.items():
        if settings.get('enabled', False):
            # Add end_frame to settings (it's the key)
            settings_with_end = settings.copy()
            settings_with_end['end_frame'] = int(frame_key)
            apply_brownian_noise_modifiers(controller_obj, settings_with_end)


def update_brownian_for_segment(controller_obj, end_frame, settings):
    """Update Brownian motion for a specific segment.

    Removes any existing modifiers for this segment and applies new ones
    based on the provided settings.

    Args:
        controller_obj: The puppet controller Empty object
        end_frame: The end frame of the segment (keyframe where settings are defined)
        settings: Dictionary with Brownian settings
    """
    if not controller_obj:
        return

    start_frame = settings.get('start_frame', 1)

    # Remove existing modifiers for this segment
    remove_brownian_noise_modifiers(controller_obj, start_frame, end_frame)

    # Apply new modifiers if enabled
    if settings.get('enabled', False):
        settings_with_end = settings.copy()
        settings_with_end['end_frame'] = end_frame
        apply_brownian_noise_modifiers(controller_obj, settings_with_end)


# ============================================================================
# Metadata Storage Functions
# ============================================================================

def get_brownian_metadata(controller_obj):
    """Get Brownian motion metadata from controller object.

    Args:
        controller_obj: The puppet controller Empty object

    Returns:
        dict: Brownian motion metadata, or empty dict if not found
    """
    if not controller_obj or 'pb_brownian_metadata' not in controller_obj:
        return {}

    try:
        metadata_str = controller_obj['pb_brownian_metadata']
        return json.loads(metadata_str)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: Failed to load Brownian metadata: {e}")
        return {}


def save_brownian_metadata(controller_obj, frame, settings):
    """Save Brownian motion settings to controller object.

    Also updates the F-Curve noise modifiers to reflect the new settings.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame number (end frame of the segment)
        settings: Dictionary with Brownian settings
    """
    if not controller_obj:
        return

    # Get existing metadata or create new
    metadata = get_brownian_metadata(controller_obj)

    # Store settings for this frame
    metadata[str(frame)] = settings

    # Save as JSON custom property
    controller_obj['pb_brownian_metadata'] = json.dumps(metadata)

    # Update the F-Curve noise modifiers
    update_brownian_for_segment(controller_obj, frame, settings)


def remove_brownian_metadata(controller_obj, frame):
    """Remove Brownian motion settings for a specific frame.

    Also removes the corresponding F-Curve noise modifiers.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame number to remove settings for
    """
    if not controller_obj:
        return

    metadata = get_brownian_metadata(controller_obj)
    frame_key = str(frame)

    if frame_key in metadata:
        start_frame = metadata[frame_key].get('start_frame', 1)

        # Remove the noise modifiers for this segment
        remove_brownian_noise_modifiers(controller_obj, start_frame, frame)

        # Remove from metadata
        del metadata[frame_key]
        controller_obj['pb_brownian_metadata'] = json.dumps(metadata)


def get_brownian_settings_for_frame(controller_obj, frame):
    """Get Brownian settings that apply to a given frame.

    Finds the keyframe segment that contains the given frame and returns
    the Brownian settings for that segment.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Current frame to get settings for

    Returns:
        dict: Settings dictionary with keys:
            - enabled: bool
            - movement_speed: float (0-1, 0=slow drift, 1=fast motion)
            - movement_distance: float (0-10, max displacement in Blender units)
            - rotation_speed: float (0-1, 0=slow tumbling, 1=fast spinning)
            - rotation_distance: float (0-60, max rotation in degrees)
            - use_random_seed: bool
            - seed: int
            - start_frame: int
            - end_frame: int
        Or None if no Brownian motion applies to this frame
    """
    metadata = get_brownian_metadata(controller_obj)
    if not metadata:
        return None

    # Find which segment this frame belongs to
    # Segments are defined by their end frame (the keyframe where settings were set)
    applicable_settings = None
    best_end_frame = None

    for frame_key, settings in metadata.items():
        if not settings.get('enabled', False):
            continue

        end_frame = int(frame_key)
        start_frame = settings.get('start_frame', 1)

        # Check if current frame is within this segment
        if start_frame <= frame <= end_frame:
            # Use the segment with the highest end_frame (most recent applicable)
            if best_end_frame is None or end_frame > best_end_frame:
                applicable_settings = settings.copy()
                applicable_settings['end_frame'] = end_frame
                best_end_frame = end_frame

    return applicable_settings


def find_previous_keyframe(controller_obj, current_frame):
    """Find the previous location keyframe before the current frame.

    Args:
        controller_obj: The puppet controller Empty object
        current_frame: Current frame number

    Returns:
        int: Frame number of previous keyframe, or None if not found
    """
    if not controller_obj or not controller_obj.animation_data:
        return None

    action = controller_obj.animation_data.action
    if not action:
        return None

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    previous_frame = None

    for fcurve in fcurves:
        # Only check location fcurves
        if 'location' not in fcurve.data_path:
            continue

        for kf in fcurve.keyframe_points:
            kf_frame = int(kf.co.x)
            if kf_frame < current_frame:
                if previous_frame is None or kf_frame > previous_frame:
                    previous_frame = kf_frame

    return previous_frame


def has_brownian_motion_enabled(controller_obj, frame):
    """Check if Brownian motion is enabled for a given frame.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame to check

    Returns:
        bool: True if Brownian motion should be applied at this frame
    """
    settings = get_brownian_settings_for_frame(controller_obj, frame)
    return settings is not None and settings.get('enabled', False)


# ============================================================================
# Legacy Functions (kept for backwards compatibility but no longer used)
# ============================================================================

def get_keyframed_location_at_frame(controller_obj, frame):
    """Get the keyframe-interpolated location at a specific frame.

    This evaluates what Blender's keyframe interpolation would give us
    at the specified frame, without any Brownian motion applied.

    Note: With F-Curve noise modifiers, the noise IS part of the F-Curve
    evaluation, so this function now returns the location INCLUDING noise.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame number to evaluate

    Returns:
        Vector: Interpolated location, or None if no keyframes exist
    """
    if not controller_obj or not controller_obj.animation_data:
        return None

    action = controller_obj.animation_data.action
    if not action:
        return None

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    location = [None, None, None]

    for fcurve in fcurves:
        if fcurve.data_path == 'location':
            idx = fcurve.array_index
            if 0 <= idx <= 2:
                location[idx] = fcurve.evaluate(frame)

    # If we got all three components, return as Vector
    if all(v is not None for v in location):
        return Vector(location)

    return None


def get_keyframed_rotation_at_frame(controller_obj, frame):
    """Get the keyframe-interpolated rotation at a specific frame.

    This evaluates what Blender's keyframe interpolation would give us
    at the specified frame, without any Brownian motion applied.

    Note: With F-Curve noise modifiers, the noise IS part of the F-Curve
    evaluation, so this function now returns the rotation INCLUDING noise.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame number to evaluate

    Returns:
        Quaternion: Interpolated rotation, or None if no keyframes exist
    """
    if not controller_obj or not controller_obj.animation_data:
        return None

    action = controller_obj.animation_data.action
    if not action:
        return None

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    # Check for quaternion rotation keyframes first
    quat = [None, None, None, None]
    euler = [None, None, None]

    for fcurve in fcurves:
        if fcurve.data_path == 'rotation_quaternion':
            idx = fcurve.array_index
            if 0 <= idx <= 3:
                quat[idx] = fcurve.evaluate(frame)
        elif fcurve.data_path == 'rotation_euler':
            idx = fcurve.array_index
            if 0 <= idx <= 2:
                euler[idx] = fcurve.evaluate(frame)

    # Prefer quaternion if available
    if all(v is not None for v in quat):
        return Quaternion(quat)

    # Fall back to euler
    if all(v is not None for v in euler):
        return Euler(euler).to_quaternion()

    return None


# ============================================================================
# Deprecated Functions (from original white-noise implementation)
# ============================================================================

def calculate_brownian_displacement(intensity, time_scale, bias, seed, frame):
    """DEPRECATED: Calculate Brownian displacement for a given frame.

    This function is kept for backwards compatibility but is no longer used.
    The new implementation uses F-Curve noise modifiers instead.
    """
    import warnings
    warnings.warn(
        "calculate_brownian_displacement is deprecated. "
        "Brownian motion is now handled by F-Curve noise modifiers.",
        DeprecationWarning
    )
    return Vector((0, 0, 0))


def calculate_brownian_rotation(intensity, time_scale, seed, frame):
    """DEPRECATED: Calculate Brownian rotational displacement for a given frame.

    This function is kept for backwards compatibility but is no longer used.
    The new implementation uses F-Curve noise modifiers instead.
    """
    import warnings
    warnings.warn(
        "calculate_brownian_rotation is deprecated. "
        "Brownian motion is now handled by F-Curve noise modifiers.",
        DeprecationWarning
    )
    return Euler((0, 0, 0))
