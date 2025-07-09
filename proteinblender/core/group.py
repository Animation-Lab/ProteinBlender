import bpy
from typing import Dict, Optional, List
from ..core.molecule_wrapper import MoleculeWrapper

class MoleculeGroup:
    """A group of molecules in the scene."""

    def __init__(self, name: str):
        self.name: str = name
        self.molecules: Dict[str, MoleculeWrapper] = {}
        self.is_expanded: bool = True

    def add_molecule(self, molecule: MoleculeWrapper):
        """Add a molecule to the group."""
        self.molecules[molecule.identifier] = molecule

    def remove_molecule(self, identifier: str):
        """Remove a molecule from the group."""
        if identifier in self.molecules:
            del self.molecules[identifier]

    @property
    def is_empty(self) -> bool:
        """Check if the group is empty."""
        return not self.molecules 