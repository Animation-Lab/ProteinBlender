"""Brownian motion implementation using baked jitter keyframes.

This module provides Brownian-style jitter motion for protein puppets by
pre-computing keyframes at evenly-spaced intervals. At each event frame,
the protein is placed at a random position within a sphere around the
linearly interpolated base path, with independent random rotation per axis.

The visual effect is like a dice bouncing on a table recorded at high FPS
but played back showing only every Nth frame -- jagged, disconnected,
unpredictable movements where you can't tell where it's going next.

Controls:
    - Interval (1-10): Frames between jitter events (deterministic spacing)
    - Max Distance (0.1-10 BU): Sphere radius for random position offset
    - Max Rotation (0-360 deg): Max random rotation per axis (independent)

Baked keyframes use keyframe_type='JITTER' to distinguish them from user
keyframes in the Dopesheet, allowing clean programmatic removal.
"""

import math
import json
import hashlib
import random as _random
from mathutils import Vector, Quaternion, Euler

from .animation import (
    get_fcurves_from_action,
    ensure_quaternion_mode,
    USE_SLOTTED_ACTIONS,
)


# ============================================================================
# Physical Constants and Scale
# ============================================================================

# Boltzmann constant in J/K
K_BOLTZMANN = 1.380649e-23

# Water viscosity at 20C in Pa*s
WATER_VISCOSITY_20C = 1.002e-3

# MolecularNodes world scale: 1 Angstrom = 0.01 Blender Units
MN_WORLD_SCALE = 0.01


# ============================================================================
# Seed / RNG Utilities
# ============================================================================

def _make_rng(seed, puppet_id, segment_start, segment_end):
    """Create a deterministic RNG for a specific Brownian segment.

    Args:
        seed: User seed value, or None for random
        puppet_id: Puppet identifier string
        segment_start: Start frame of segment
        segment_end: End frame of segment

    Returns:
        random.Random instance
    """
    rng = _random.Random()
    if seed is None:
        rng.seed()
    else:
        hash_input = f"{seed}_{puppet_id}_{segment_start}_{segment_end}"
        hash_bytes = hashlib.md5(hash_input.encode()).digest()
        rng.seed(int.from_bytes(hash_bytes[:8], byteorder='little'))
    return rng


# ============================================================================
# Physics Computations
# ============================================================================

def estimate_hydrodynamic_radius(mw_kda):
    """Estimate hydrodynamic radius from molecular weight.

    Uses empirical relation for globular proteins:
        R_h = 0.066 * MW_Da^0.395  (in nm)

    Args:
        mw_kda: Molecular weight in kilodaltons

    Returns:
        float: Hydrodynamic radius in nanometers
    """
    mw_da = mw_kda * 1000.0
    return 0.066 * (mw_da ** 0.395)


def compute_diffusion_coefficients(mw_kda, temp_k, visc_factor):
    """Compute translational and rotational diffusion coefficients.

    Uses Stokes-Einstein relations:
        D_trans = kT / (6 * pi * eta * R_h)
        D_rot   = kT / (8 * pi * eta * R_h^3)

    Args:
        mw_kda: Molecular weight in kilodaltons
        temp_k: Temperature in Kelvin
        visc_factor: Viscosity multiplier (1.0 = water at 20C)

    Returns:
        tuple: (D_trans in nm^2/s, D_rot in rad^2/s)
    """
    r_h_nm = estimate_hydrodynamic_radius(mw_kda)
    r_h_m = r_h_nm * 1e-9
    eta = WATER_VISCOSITY_20C * visc_factor

    d_trans_m2s = K_BOLTZMANN * temp_k / (6.0 * math.pi * eta * r_h_m)
    d_rot_rad2s = K_BOLTZMANN * temp_k / (8.0 * math.pi * eta * r_h_m ** 3)

    d_trans_nm2s = d_trans_m2s * 1e18  # m^2/s -> nm^2/s
    return d_trans_nm2s, d_rot_rad2s


def compute_jitter_from_physics(mw_kda, temp_k, visc_factor, fps, interval):
    """Compute max_distance and max_rotation from physics parameters.

    Uses Stokes-Einstein diffusion to determine physically appropriate
    jitter amplitudes for a given protein and time interval.

    Args:
        mw_kda: Molecular weight in kilodaltons
        temp_k: Temperature in Kelvin
        visc_factor: Viscosity multiplier
        fps: Scene frames per second
        interval: Frames between jitter events

    Returns:
        tuple: (max_distance in BU, max_rotation in degrees)
    """
    d_trans, d_rot = compute_diffusion_coefficients(mw_kda, temp_k, visc_factor)
    dt = interval / fps  # time per interval in seconds

    # RMS displacement over interval, then 3x for sphere radius (covers ~99.7%)
    rms_trans_nm = math.sqrt(2.0 * d_trans * dt)
    rms_trans_bu = rms_trans_nm * 10.0 * MN_WORLD_SCALE  # nm -> Angstrom -> BU
    max_distance = 3.0 * rms_trans_bu

    # RMS rotation over interval, then 3x for max angle
    rms_rot_rad = math.sqrt(2.0 * d_rot * dt)
    max_rotation_deg = math.degrees(3.0 * rms_rot_rad)

    return max(0.1, max_distance), min(360.0, max_rotation_deg)


# ============================================================================
# Event Frame Computation
# ============================================================================

def _compute_event_frames(start_frame, end_frame, interval):
    """Compute evenly-spaced event frames across a segment.

    Distributes events as uniformly as possible so the first event is
    approximately `interval` frames after start and the last event is
    approximately `interval` frames before end.

    Args:
        start_frame: First frame (user keyframe, included)
        end_frame: Last frame (user keyframe, included)
        interval: Desired frames between events

    Returns:
        list[int]: Sorted frame numbers including start and end
    """
    total = end_frame - start_frame
    if total <= 0:
        return [start_frame, end_frame] if start_frame != end_frame else [start_frame]

    n_intervals = max(1, round(total / interval))

    events = [start_frame]
    for i in range(1, n_intervals):
        frame = start_frame + round(i * total / n_intervals)
        if frame not in events and frame != end_frame:
            events.append(frame)
    events.append(end_frame)
    return events


# ============================================================================
# Jitter Generation
# ============================================================================

def _random_point_in_sphere(rng, radius):
    """Generate a uniform random point inside a sphere.

    Uses rejection sampling (cube -> sphere filter).

    Args:
        rng: random.Random instance
        radius: Sphere radius

    Returns:
        Vector: Random point within the sphere
    """
    while True:
        x = rng.uniform(-1, 1)
        y = rng.uniform(-1, 1)
        z = rng.uniform(-1, 1)
        if x * x + y * y + z * z <= 1.0:
            return Vector((x * radius, y * radius, z * radius))


def generate_jitter_translation(start_pos, end_pos, event_frames, max_distance, rng):
    """Generate jittered translation path around linearly interpolated base.

    At each intermediate event frame, the position is the linear interpolation
    between start and end, plus a random offset within a sphere of max_distance.
    Start and end positions are exact (no jitter).

    Args:
        start_pos: Starting position as Vector
        end_pos: Ending position as Vector
        event_frames: List of frame numbers [start, t1, t2, ..., end]
        max_distance: Sphere radius for random offset (Blender units)
        rng: random.Random instance

    Returns:
        list[Vector]: Position at each event frame
    """
    if len(event_frames) < 2:
        return [Vector(start_pos)]

    positions = [Vector(start_pos)]
    start = Vector(start_pos)
    end = Vector(end_pos)
    total_frames = event_frames[-1] - event_frames[0]

    for i in range(1, len(event_frames) - 1):
        t = (event_frames[i] - event_frames[0]) / total_frames
        base = start.lerp(end, t)
        offset = _random_point_in_sphere(rng, max_distance)
        positions.append(base + offset)

    positions.append(Vector(end_pos))
    return positions


def generate_jitter_rotation(start_quat, end_quat, event_frames, max_rotation_deg, rng):
    """Generate jittered rotation path around slerped base rotation.

    At each intermediate event frame, the rotation is the slerp between
    start and end, with independent random Euler angles added per axis.
    Start and end rotations are exact (no jitter).

    Args:
        start_quat: Starting rotation as Quaternion
        end_quat: Ending rotation as Quaternion
        event_frames: List of frame numbers [start, t1, t2, ..., end]
        max_rotation_deg: Max random angle per axis in degrees
        rng: random.Random instance

    Returns:
        list[Quaternion]: Rotation at each event frame
    """
    if len(event_frames) < 2:
        return [Quaternion(start_quat)]

    rotations = [Quaternion(start_quat)]
    sq = Quaternion(start_quat)
    sq.normalize()
    eq = Quaternion(end_quat)
    eq.normalize()

    # Ensure shortest path
    if sq.dot(eq) < 0:
        eq = Quaternion((-eq.w, -eq.x, -eq.y, -eq.z))

    total_frames = event_frames[-1] - event_frames[0]
    max_rad = math.radians(max_rotation_deg)

    for i in range(1, len(event_frames) - 1):
        t = (event_frames[i] - event_frames[0]) / total_frames
        base = sq.slerp(eq, t)

        # Independent random rotation on each axis
        rx = rng.uniform(-max_rad, max_rad)
        ry = rng.uniform(-max_rad, max_rad)
        rz = rng.uniform(-max_rad, max_rad)
        jitter_quat = Euler((rx, ry, rz)).to_quaternion()

        result = jitter_quat @ base
        result.normalize()
        rotations.append(result)

    rotations.append(Quaternion(end_quat))
    return rotations


# ============================================================================
# F-Curve and Keyframe Management
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

    if not obj.animation_data:
        obj.animation_data_create()

    if not obj.animation_data.action:
        action = bpy.data.actions.new(name=f"{obj.name}_Action")
        obj.animation_data.action = action

    action = obj.animation_data.action

    if USE_SLOTTED_ACTIONS:
        from .animation import _get_channelbag

        if not hasattr(obj.animation_data, 'action_slot') or not obj.animation_data.action_slot:
            if hasattr(action, 'slots') and len(action.slots) == 0:
                slot = action.slots.new(for_id=obj)
                obj.animation_data.action_slot = slot
            elif hasattr(action, 'slots') and len(action.slots) > 0:
                obj.animation_data.action_slot = action.slots[0]

        if hasattr(action, 'layers') and len(action.layers) == 0:
            action.layers.new(name="Layer")

        if hasattr(action, 'layers') and len(action.layers) > 0:
            layer = action.layers[0]
            if hasattr(layer, 'strips') and len(layer.strips) == 0:
                layer.strips.new(type='KEYFRAME')

        channelbag = _get_channelbag(action, obj.animation_data)
        if channelbag:
            for fc in channelbag.fcurves:
                if fc.data_path == data_path and fc.array_index == array_index:
                    return fc
            return channelbag.fcurves.new(data_path, index=array_index)
    else:
        fcurves = action.fcurves

        for fc in fcurves:
            if fc.data_path == data_path and fc.array_index == array_index:
                return fc

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


def _get_transform_at_frame(controller_obj, frame, data_path):
    """Evaluate F-Curve values at a specific frame.

    Args:
        controller_obj: Blender object
        frame: Frame number to evaluate
        data_path: 'location' or 'rotation_quaternion'

    Returns:
        Vector (for location) or Quaternion (for rotation_quaternion)
    """
    if data_path == 'location':
        n_channels = 3
    elif data_path == 'rotation_quaternion':
        n_channels = 4
    else:
        return None

    values = []
    for i in range(n_channels):
        fc = _get_fcurve(controller_obj, data_path, i)
        if fc:
            values.append(fc.evaluate(frame))
        elif data_path == 'location':
            values.append(controller_obj.location[i])
        elif data_path == 'rotation_quaternion':
            values.append(controller_obj.rotation_quaternion[i])

    if data_path == 'location':
        return Vector(values)
    elif data_path == 'rotation_quaternion':
        q = Quaternion(values)
        q.normalize()
        return q


def _insert_brownian_keyframes(controller_obj, event_frames, positions, rotations):
    """Batch insert jitter keyframes with LINEAR interpolation.

    Uses JITTER keyframe type to distinguish from user keyframes.
    Uses 'FAST' option to skip per-insert handle recalculation.
    Skips first and last frames (those are user keyframes).

    Args:
        controller_obj: Blender object
        event_frames: List of frame numbers [start, t1, t2, ..., end]
        positions: list[Vector] of positions (one per event frame)
        rotations: list[Quaternion] of rotations (one per event frame)
    """
    n_events = len(event_frames)

    # Insert location keyframes (skip first and last - those are user keyframes)
    for axis in range(3):
        fc = _ensure_fcurve_exists(controller_obj, 'location', axis)
        if not fc:
            continue
        for i in range(1, n_events - 1):
            frame = event_frames[i]
            value = positions[i][axis]
            kf = fc.keyframe_points.insert(frame, value, options={'FAST'}, keyframe_type='JITTER')
            kf.interpolation = 'LINEAR'
        fc.update()

    # Insert rotation keyframes (skip first and last - those are user keyframes)
    for axis in range(4):
        fc = _ensure_fcurve_exists(controller_obj, 'rotation_quaternion', axis)
        if not fc:
            continue
        for i in range(1, n_events - 1):
            frame = event_frames[i]
            value = rotations[i][axis]
            kf = fc.keyframe_points.insert(frame, value, options={'FAST'}, keyframe_type='JITTER')
            kf.interpolation = 'LINEAR'
        fc.update()


def clear_baked_brownian_keyframes(controller_obj, start_frame, end_frame):
    """Remove JITTER-typed keyframes in the specified frame range.

    Only removes keyframes with type 'JITTER', preserving user keyframes.
    Iterates in reverse for safe removal.

    Args:
        controller_obj: Blender object
        start_frame: Start of range (inclusive)
        end_frame: End of range (inclusive)
    """
    if not controller_obj or not controller_obj.animation_data:
        return

    action = controller_obj.animation_data.action
    if not action:
        return

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    for fcurve in fcurves:
        if fcurve.data_path not in ('location', 'rotation_quaternion'):
            continue

        # Collect JITTER keyframes in range
        to_remove = []
        for kf in fcurve.keyframe_points:
            kf_frame = int(round(kf.co.x))
            if start_frame < kf_frame < end_frame and kf.type == 'JITTER':
                to_remove.append(kf)

        # Remove in reverse order
        for kf in reversed(to_remove):
            fcurve.keyframe_points.remove(kf)

        if to_remove:
            fcurve.update()


# ============================================================================
# Main Baking API
# ============================================================================

def bake_brownian_keyframes(controller_obj, settings):
    """Generate and insert jitter keyframes for a segment.

    This is the main entry point for creating Brownian motion. It:
    1. Reads start/end transforms from existing user keyframes
    2. Computes evenly-spaced event frames at the requested interval
    3. Generates jittered positions/rotations around the interpolated base path
    4. Inserts JITTER keyframes with LINEAR interpolation

    Args:
        controller_obj: The puppet controller Empty object
        settings: Dictionary with Brownian settings:
            - enabled: bool
            - start_frame: int
            - end_frame: int
            - puppet_id: str
            - jitter_interval: int (1-10)
            - jitter_max_distance: float (BU)
            - jitter_max_rotation: float (degrees)
            - use_physical_params: bool
            - molecular_weight, temperature, viscosity_factor: floats (physical mode)
            - use_random_seed: bool
            - seed: int or None
    """
    import bpy

    if not controller_obj:
        return

    if not settings.get('enabled', False):
        return

    start_frame = settings.get('start_frame', 1)
    end_frame = int(settings.get('end_frame', 250))
    n_frames = end_frame - start_frame + 1

    if n_frames < 3:
        print(f"Brownian: Segment too short ({n_frames} frames), skipping")
        return

    # Ensure quaternion rotation mode
    ensure_quaternion_mode(controller_obj)

    # Get start and end transforms from user keyframes
    start_pos = _get_transform_at_frame(controller_obj, start_frame, 'location')
    end_pos = _get_transform_at_frame(controller_obj, end_frame, 'location')
    start_quat = _get_transform_at_frame(controller_obj, start_frame, 'rotation_quaternion')
    end_quat = _get_transform_at_frame(controller_obj, end_frame, 'rotation_quaternion')

    if start_pos is None or end_pos is None:
        print("Brownian: Could not read start/end positions")
        return
    if start_quat is None or end_quat is None:
        print("Brownian: Could not read start/end rotations")
        return

    # Get jitter parameters
    interval = settings.get('jitter_interval', 3)
    use_physical = settings.get('use_physical_params', False)

    if use_physical:
        mw = settings.get('molecular_weight', 50.0)
        temp = settings.get('temperature', 300.0)
        visc = settings.get('viscosity_factor', 1.0)
        fps = bpy.context.scene.render.fps
        max_distance, max_rotation = compute_jitter_from_physics(
            mw, temp, visc, fps, interval
        )
    else:
        max_distance = settings.get('jitter_max_distance', 1.0)
        max_rotation = settings.get('jitter_max_rotation', 30.0)

    # Create RNG
    use_random_seed = settings.get('use_random_seed', True)
    seed = None if use_random_seed else settings.get('seed', 12345)
    puppet_id = settings.get('puppet_id', 'unknown')
    rng = _make_rng(seed, puppet_id, start_frame, end_frame)

    # Compute evenly-spaced event frames
    event_frames = _compute_event_frames(start_frame, end_frame, interval)

    # Generate jittered paths
    positions = generate_jitter_translation(
        start_pos, end_pos, event_frames, max_distance, rng
    )
    rotations = generate_jitter_rotation(
        start_quat, end_quat, event_frames, max_rotation, rng
    )

    # Insert keyframes
    _insert_brownian_keyframes(controller_obj, event_frames, positions, rotations)

    n_inserted = len(event_frames) - 2
    print(f"Brownian: Baked {n_inserted} JITTER keyframes across {n_frames} frames "
          f"(interval={interval})")
    print(f"  max_distance={max_distance:.3f} BU, max_rotation={max_rotation:.1f} deg")


def rebuild_all_brownian_motion(controller_obj):
    """Clear and rebake all Brownian motion segments from metadata.

    Args:
        controller_obj: The puppet controller Empty object
    """
    if not controller_obj:
        return

    metadata = get_brownian_metadata(controller_obj)

    # First clear all existing JITTER keyframes for all segments
    for frame_key, settings in metadata.items():
        start_frame = settings.get('start_frame', 1)
        end_frame = int(frame_key)
        clear_baked_brownian_keyframes(controller_obj, start_frame, end_frame)

    # Then rebake all enabled segments
    for frame_key, settings in metadata.items():
        if settings.get('enabled', False):
            settings_with_end = settings.copy()
            settings_with_end['end_frame'] = int(frame_key)
            bake_brownian_keyframes(controller_obj, settings_with_end)


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
    """Save Brownian motion settings and bake keyframes.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Frame number (end frame of the segment)
        settings: Dictionary with Brownian settings
    """
    if not controller_obj:
        return

    metadata = get_brownian_metadata(controller_obj)

    settings_to_save = settings.copy()
    settings_to_save['version'] = 2

    metadata[str(frame)] = settings_to_save
    controller_obj['pb_brownian_metadata'] = json.dumps(metadata)

    # Clear existing baked keyframes for this segment and rebake
    start_frame = settings.get('start_frame', 1)
    clear_baked_brownian_keyframes(controller_obj, start_frame, frame)

    if settings.get('enabled', False):
        settings_with_end = settings_to_save.copy()
        settings_with_end['end_frame'] = frame
        bake_brownian_keyframes(controller_obj, settings_with_end)


def remove_brownian_metadata(controller_obj, frame):
    """Remove Brownian motion settings for a specific frame.

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
        clear_baked_brownian_keyframes(controller_obj, start_frame, frame)
        del metadata[frame_key]
        controller_obj['pb_brownian_metadata'] = json.dumps(metadata)


def get_brownian_settings_for_frame(controller_obj, frame):
    """Get Brownian settings that apply to a given frame.

    Args:
        controller_obj: The puppet controller Empty object
        frame: Current frame to get settings for

    Returns:
        dict or None
    """
    metadata = get_brownian_metadata(controller_obj)
    if not metadata:
        return None

    applicable_settings = None
    best_end_frame = None

    for frame_key, settings in metadata.items():
        if not settings.get('enabled', False):
            continue

        end_frame = int(frame_key)
        start_frame = settings.get('start_frame', 1)

        if start_frame <= frame <= end_frame:
            if best_end_frame is None or end_frame > best_end_frame:
                applicable_settings = settings.copy()
                applicable_settings['end_frame'] = end_frame
                best_end_frame = end_frame

    return applicable_settings


def find_previous_keyframe(controller_obj, current_frame):
    """Find the previous location keyframe before the current frame.

    Only considers non-JITTER keyframes (user keyframes).

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
        if 'location' not in fcurve.data_path:
            continue

        for kf in fcurve.keyframe_points:
            kf_frame = int(kf.co.x)
            if kf.type == 'JITTER':
                continue
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
# Legacy Compatibility
# ============================================================================

def remove_brownian_noise_modifiers(controller_obj, start_frame=None, end_frame=None):
    """Remove old-style Brownian noise modifiers from F-Curves.

    Kept for backwards compatibility with version 1 metadata.

    Args:
        controller_obj: The puppet controller Empty object
        start_frame: Optional start frame to match
        end_frame: Optional end frame to match
    """
    if not controller_obj or not controller_obj.animation_data:
        return

    action = controller_obj.animation_data.action
    if not action:
        return

    fcurves = get_fcurves_from_action(action, controller_obj.animation_data)

    for fcurve in fcurves:
        if fcurve.data_path not in ('location', 'rotation_quaternion', 'rotation_euler'):
            continue

        to_remove = []
        for mod in fcurve.modifiers:
            if mod.type != 'NOISE':
                continue

            if start_frame is not None and end_frame is not None:
                if mod.use_restricted_range:
                    if int(mod.frame_start) == int(start_frame) and int(mod.frame_end) == int(end_frame):
                        to_remove.append(mod)
                else:
                    to_remove.append(mod)
            else:
                to_remove.append(mod)

        for mod in to_remove:
            fcurve.modifiers.remove(mod)


def rebuild_all_brownian_modifiers(controller_obj):
    """Legacy: Rebuild from metadata, handling v1 noise modifiers.

    For version 1 metadata, removes old noise modifiers first.
    Then rebuilds all segments using the current baked approach.
    """
    if not controller_obj:
        return

    metadata = get_brownian_metadata(controller_obj)

    has_v1 = any(
        not settings.get('version') or settings.get('version', 1) < 2
        for settings in metadata.values()
    )

    if has_v1:
        remove_brownian_noise_modifiers(controller_obj)

    rebuild_all_brownian_motion(controller_obj)
