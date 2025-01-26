from .file_io import get_protein_file
import json
import bpy
from typing import Dict, Optional
from .molecularnodes.entities import fetch, load_local
from ..core.molecule_manager import MoleculeManager, MoleculeWrapper

class ProteinBlenderScene:
    _instance = None

    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Initialize the singleton instance
        self.molecule_manager = MoleculeManager()
        self.active_molecule: Optional[str] = None
        self.display_settings = {}


    @property
    def molecules(self) -> Dict[str, MoleculeWrapper]:
        return self.molecule_manager.molecules

    def set_active_molecule(self, molecule_id):
        """Set the active molecule."""
        self.active_molecule = molecule_id

    def add_molecule(self, molecule):
        """Add a molecule to the scene."""
        self.molecule_manager.add_molecule(molecule)
        self.active_molecule = molecule.identifier

    def remove_molecule(self, identifier):
        """Remove a molecule from the scene."""
        self.molecule_manager.remove_molecule(identifier)
        if self.active_molecule == identifier:
            self.active_molecule = next(iter(self.molecules)) if self.molecules else None

    def to_json(self):
        """Convert the scene to JSON."""
        return json.dumps({
            'molecules': {id: molecule.to_json() for id, molecule in self.molecules.items()},
            'active_molecule': self.active_molecule,
            'display_settings': self.display_settings
        })

    def create_molecule_from_id(self, identifier: str, import_method: str = 'PDB') -> bool:
        """Create a new molecule from an identifier (PDB ID or UniProt ID)"""
        try:
            # Ensure MNSession is initialized
            if not hasattr(bpy.context.scene, "MNSession"):
                from ..utils.molecularnodes.addon import register as register_mn
                register_mn()
            
            if import_method == 'PDB':
                molecule = self.molecule_manager.import_from_pdb(identifier)
            else:  # AlphaFold
                molecule = self.molecule_manager.import_from_pdb(
                    identifier, 
                    database="alphafold",
                    color="plddt"
                )
            
            print(f"Successfully created molecule: {identifier}")  # Debug print
            print(f"Current molecules: {list(self.molecules.keys())}")  # Debug print
            
            # Set as active molecule
            self.active_molecule = identifier
            
            # Force UI refresh
            self._refresh_ui()
            
            return True
            
        except Exception as e:
            print(f"Error creating molecule: {str(e)}")
            return False

    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
        if identifier in self.molecules:
            # Remove from scene
            molecule = self.molecules[identifier]
            bpy.data.objects.remove(molecule.object, do_unlink=True)
            del self.molecules[identifier]
            
            # Update UI list
            scene = bpy.context.scene
            for i, item in enumerate(scene.molecule_list_items):
                if item.identifier == identifier:
                    scene.molecule_list_items.remove(i)
                    break
                    
            return True
        return False

    def _refresh_ui(self):
        """Force a redraw of all UI areas"""
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ['PROPERTIES', 'VIEW_3D']:
                    area.tag_redraw()

    @classmethod
    def from_json(cls, json_str):
        """Create a ProteinBlenderScene instance from JSON."""
        data = json.loads(json_str)
        scene = cls()
        scene.molecule_manager.molecules = {
            id: Molecule.from_json(molecule_json) 
            for id, molecule_json in data['molecules'].items()
        }
        scene.active_molecule = data['active_molecule']
        scene.display_settings = data['display_settings']
        return scene 