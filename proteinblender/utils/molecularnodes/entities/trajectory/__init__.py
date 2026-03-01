"""Trajectory module for MolecularNodes.

This module handles molecular dynamics trajectory import and playback.
It requires MDAnalysis which depends on scipy. On some Blender versions
(especially 5.0), scipy may fail to load due to DLL issues. In that case,
trajectory features are disabled but the rest of the addon works normally.
"""

import logging

logger = logging.getLogger(__name__)

# Track whether trajectory features are available
TRAJECTORY_AVAILABLE = False
selections = None
ui = None
load = None
Trajectory = None
CLASSES = []

# First, check if MDAnalysis itself is available before trying to import any
# submodules that depend on it. This prevents DLL load errors on Blender 5.0.
try:
    import MDAnalysis as _mda_test
    _MDA_AVAILABLE = True
    del _mda_test
except ImportError as e:
    _MDA_AVAILABLE = False
    logger.warning(
        f"MDAnalysis not available: {e}. "
        "This is typically caused by scipy/MDAnalysis compatibility issues with Blender 5.0. "
        "Trajectory features will be disabled but all other ProteinBlender features will work normally."
    )

# Only attempt to import submodules if MDAnalysis is available
if _MDA_AVAILABLE:
    try:
        from . import selections
    except ImportError as e:
        logger.warning(f"Failed to import selections module: {e}")
        selections = None

    try:
        from . import ui
        from .ui import load
        from .trajectory import Trajectory
        CLASSES = ui.CLASSES
        TRAJECTORY_AVAILABLE = True
    except ImportError as e:
        logger.warning(
            f"Trajectory features disabled due to dependency error: {e}. "
            "All other ProteinBlender features will work normally."
        )
        # Provide empty placeholders
        ui = None
        load = None
        Trajectory = None
        CLASSES = []

__all__ = ['selections', 'ui', 'load', 'Trajectory', 'CLASSES', 'TRAJECTORY_AVAILABLE']