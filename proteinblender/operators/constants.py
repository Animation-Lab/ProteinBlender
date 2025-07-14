"""Constants for ProteinBlender operators.

This module defines constants used across various operators to avoid magic numbers
and improve maintainability.
"""

# Display settings
EMPTY_DISPLAY_SIZE = 1.0  # Default size for empty objects
PIVOT_DISPLAY_SIZE = 0.5  # Display size for pivot empties

# Animation settings
BROWNIAN_MOTION_DEFAULT_INTENSITY = 0.5  # Default intensity for Brownian motion
BROWNIAN_MOTION_DEFAULT_FREQUENCY = 1.0  # Default frequency for Brownian motion  
BROWNIAN_MOTION_DEFAULT_RESOLUTION = 2  # Default frame resolution for Brownian motion
BROWNIAN_MOTION_DEFAULT_SEED = 0  # Default random seed

# UI settings
DIALOG_WIDTH = 400  # Default width for dialog boxes
OPERATOR_DESCRIPTION_WIDTH = 300  # Width for operator descriptions in UI

# Keyframe settings
DEFAULT_KEYFRAME_INTERPOLATION = 'LINEAR'  # Default interpolation type for keyframes

# Domain settings
DOMAIN_DEFAULT_NAME = "New Domain"
POSE_DEFAULT_NAME = "New Pose"

# File extensions
SUPPORTED_EXTENSIONS = [
    ".pdb", ".ent", ".cif", ".mmcif", ".bcif", ".pdbx", ".gz"
]