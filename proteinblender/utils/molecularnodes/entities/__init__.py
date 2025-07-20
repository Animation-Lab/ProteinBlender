from . import molecule

try:
    from . import trajectory
    from .trajectory.dna import MN_OT_Import_OxDNA_Trajectory
    trajectory_available = True
except ImportError as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Trajectory module not available: {e}")
    trajectory = None
    MN_OT_Import_OxDNA_Trajectory = None
    trajectory_available = False

from .density import MN_OT_Import_Map
from .ensemble import CellPack
from .ensemble import StarFile
from .ensemble.ui import MN_OT_Import_Cell_Pack, MN_OT_Import_Star_File
from .molecule.pdb import PDB
from .molecule.pdbx import BCIF, CIF
from .molecule.sdf import SDF
from .molecule.ui import fetch, load_local, parse

if trajectory_available:
    from .trajectory.trajectory import Trajectory
else:
    Trajectory = None

__all__ = [
    'molecule', 'trajectory', 'MN_OT_Import_Map', 'MN_OT_Import_OxDNA_Trajectory',
    'CellPack', 'StarFile', 'MN_OT_Import_Cell_Pack', 'MN_OT_Import_Star_File',
    'PDB', 'BCIF', 'CIF', 'SDF', 'fetch', 'load_local', 'parse', 'Trajectory', 'CLASSES'
]

CLASSES = [
    MN_OT_Import_Cell_Pack,
    MN_OT_Import_Map,
    MN_OT_Import_Star_File,
] + molecule.CLASSES

if trajectory_available:
    CLASSES.extend([MN_OT_Import_OxDNA_Trajectory])
    CLASSES.extend(trajectory.CLASSES)
