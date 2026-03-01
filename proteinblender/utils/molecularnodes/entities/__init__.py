"""MolecularNodes entities module.

This module provides various molecular entity types including molecules,
trajectories, ensembles, and density maps. Trajectory features require
MDAnalysis/scipy which may not be available on all Blender versions.
"""

import logging
logger = logging.getLogger(__name__)

from . import molecule

# Try to import trajectory module with fallback
# The trajectory/__init__.py handles MDAnalysis availability checks internally
trajectory_available = False
trajectory = None
MN_OT_Import_OxDNA_Trajectory = None
Trajectory = None

try:
    from . import trajectory
    # Check if trajectory module loaded successfully AND has the TRAJECTORY_AVAILABLE flag set
    if trajectory is not None and hasattr(trajectory, 'TRAJECTORY_AVAILABLE'):
        trajectory_available = trajectory.TRAJECTORY_AVAILABLE
        # Get Trajectory from the trajectory module (may be None if MDAnalysis unavailable)
        Trajectory = getattr(trajectory, 'Trajectory', None)
    else:
        trajectory_available = False
        Trajectory = None

    if trajectory_available:
        # Import oxDNA operator - may be None even if trajectory_available is True
        try:
            from .trajectory.dna import MN_OT_Import_OxDNA_Trajectory
            # MN_OT_Import_OxDNA_Trajectory might be None if oxDNA deps failed
            if MN_OT_Import_OxDNA_Trajectory is None:
                logger.info("oxDNA trajectory import not available")
        except ImportError as e:
            logger.info(f"oxDNA trajectory import not available: {e}")
            MN_OT_Import_OxDNA_Trajectory = None

except ImportError as e:
    logger.warning(f"Trajectory module not available: {e}")
    trajectory = None
    MN_OT_Import_OxDNA_Trajectory = None
    trajectory_available = False
    Trajectory = None

from .density import MN_OT_Import_Map
from .ensemble import CellPack
from .ensemble import StarFile
from .ensemble.ui import MN_OT_Import_Cell_Pack, MN_OT_Import_Star_File
from .molecule.pdb import PDB
from .molecule.pdbx import BCIF, CIF
from .molecule.sdf import SDF
from .molecule.ui import fetch, load_local, parse

__all__ = [
    'molecule', 'trajectory', 'MN_OT_Import_Map', 'MN_OT_Import_OxDNA_Trajectory',
    'CellPack', 'StarFile', 'MN_OT_Import_Cell_Pack', 'MN_OT_Import_Star_File',
    'PDB', 'BCIF', 'CIF', 'SDF', 'fetch', 'load_local', 'parse', 'Trajectory', 'CLASSES',
    'trajectory_available'
]

CLASSES = [
    MN_OT_Import_Cell_Pack,
    MN_OT_Import_Map,
    MN_OT_Import_Star_File,
] + molecule.CLASSES

if trajectory_available:
    # Only add operator if it's actually defined (not None)
    if MN_OT_Import_OxDNA_Trajectory is not None:
        CLASSES.append(MN_OT_Import_OxDNA_Trajectory)
    # Add trajectory classes if available
    if trajectory is not None and hasattr(trajectory, 'CLASSES'):
        CLASSES.extend(trajectory.CLASSES)
