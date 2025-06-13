# proteinblender/core/__init__.py
from .domain import Domain
from .molecule_wrapper import MoleculeWrapper
from .molecule_manager import MoleculeManager

CLASSES = (
    Domain,
    MoleculeWrapper,
    MoleculeManager,
)
