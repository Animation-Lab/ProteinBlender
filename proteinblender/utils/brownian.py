"""Brownian motion calculation utilities for ProteinBlender.

This module provides functions to calculate Brownian motion displacements
based on physics-accurate random walk algorithms.

The key equation for Brownian motion is:
    displacement = normal_distribution(mean=0, std=sqrt(2 * D * dt))

Where:
    D = diffusion coefficient (related to intensity)
    dt = time step (related to time_scale)
"""

import math
import random
import json
from mathutils import Vector

from .animation import get_fcurves_from_action


def calculate_brownian_displacement(intensity, time_scale, bias, seed, frame):
    """Calculate Brownian displacement for a given frame.

    Args:
        intensity: Normalized intensity (0-1), maps to diffusion coefficient
        time_scale: Normalized time scale (0-1), affects jitter speed
        bias: Tuple of (x, y, z) bias values (0-1, centered at 0.5)
        seed: Random seed for reproducibility (None for random each time)
        frame: Current frame number (used with seed for frame-specific randomness)

    Returns:
        Vector: 3D displacement to add to base position
    """
    if intensity <= 0:
        return Vector((0, 0, 0))

    # Map normalized intensity to physical diffusion coefficient
    # At intensity=1.0, max displacement is noticeable but not extreme
    D = intensity * 0.5

    # Time scale affects effective time step
    # Higher time_scale = larger steps = more visible jitter
    dt = max(0.01, time_scale * 0.1)

    # Standard deviation for Gaussian distribution (physics formula)
    sigma = math.sqrt(2 * D * dt)

    # Set random seed for reproducibility
    if seed is not None:
        # Combine seed with frame for frame-dependent but reproducible randomness
        random.seed(seed + frame * 31)

    # Generate random displacement (3D Gaussian)
    dx = random.gauss(0, sigma)
    dy = random.gauss(0, sigma)
    dz = random.gauss(0, sigma)

    # Apply directional bias
    # bias values are 0-1 centered at 0.5, so (bias - 0.5) gives -0.5 to 0.5
    bias_scale = intensity * 0.05  # Scale bias effect with intensity
    dx += (bias[0] - 0.5) * bias_scale
    dy += (bias[1] - 0.5) * bias_scale
    dz += (bias[2] - 0.5) * bias_scale

    return Vector((dx, dy, dz))


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
            - intensity: float (0-1)
            - time_scale: float (0-1)
            - use_random_seed: bool
            - seed: int
            - bias_x, bias_y, bias_z: float (0-1)
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


def get_keyframed_location_at_frame(controller_obj, frame):
    """Get the keyframe-interpolated location at a specific frame.

    This evaluates what Blender's keyframe interpolation would give us
    at the specified frame, without any Brownian motion applied.

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
