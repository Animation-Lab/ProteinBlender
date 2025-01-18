from .file_io import get_protein_file
from .molecule import Molecule
import json
import bpy

class ProteinBlenderScene:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize the singleton instance
            cls._instance.molecules = {}  # Dictionary of molecule_id: Molecule instances
            cls._instance.active_molecule = None
            cls._instance.display_settings = {}
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Skip initialization if instance already exists
        pass

    def set_active_molecule(self, molecule_id):
        """Set the active molecule."""
        self.active_molecule = molecule_id

    def add_molecule(self, molecule):
        """Add a molecule to the scene."""
        self.molecules[molecule.identifier] = molecule
        self.active_molecule = molecule.identifier

    def remove_molecule(self, identifier):
        """Remove a molecule from the scene."""
        if identifier in self.molecules:
            del self.molecules[identifier]
            if self.active_molecule == identifier:
                self.active_molecule = next(iter(self.molecules)) if self.molecules else None

    def to_json(self):
        """Convert the scene to JSON."""
        return json.dumps({
            'molecules': {id: molecule.to_json() for id, molecule in self.molecules.items()},
            'active_molecule': self.active_molecule,
            'display_settings': self.display_settings
        })

    def create_molecule_from_id(self, identifier, import_method='PDB'):
        """Create a new molecule from an identifier and add it to the scene.
        
        Args:
            identifier (str): PDB ID or UniProt ID
            import_method (str): Either 'PDB' or 'ALPHAFOLD'
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print("Creating molecule", identifier, import_method)
            # Get protein file contents
            pdb_contents = get_protein_file(identifier, import_method)
            
            if not pdb_contents:
                print(f"Failed to retrieve molecule data for {identifier}")
                return False

            molecule = Molecule(identifier)
            molecule.parse_pdb_string(pdb_contents)
            molecule.create_visualization()
            
            # Add to scene and set as active using the unique ID
            unique_id = molecule.unique_id
            self.molecules[unique_id] = molecule
            self.active_molecule = unique_id
            
            # Force a redraw of all UI areas
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
            
            return True
            
        except Exception as e:
            print(f"Error creating molecule: {str(e)}")
            return False

    @classmethod
    def from_json(cls, json_str):
        """Create a ProteinBlenderScene instance from JSON."""
        data = json.loads(json_str)
        scene = cls()
        scene.molecules = {
            id: Molecule.from_json(molecule_json) 
            for id, molecule_json in data['molecules'].items()
        }
        scene.active_molecule = data['active_molecule']
        scene.display_settings = data['display_settings']
        return scene 