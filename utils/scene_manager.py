from .file_io import get_protein_file
from .protein import Protein
import json
import bpy

class ProteinBlenderScene:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize the singleton instance
            cls._instance.proteins = {}  # Dictionary of protein_id: Protein instances
            cls._instance.active_protein = None
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

    def set_active_protein(self, protein_id):
        """Set the active protein."""
        self.active_protein = protein_id

    def add_protein(self, protein):
        """Add a protein to the scene."""
        self.proteins[protein.identifier] = protein
        self.active_protein = protein.identifier

    def remove_protein(self, identifier):
        """Remove a protein from the scene."""
        if identifier in self.proteins:
            del self.proteins[identifier]
            if self.active_protein == identifier:
                self.active_protein = next(iter(self.proteins)) if self.proteins else None

    def to_json(self):
        """Convert the scene to JSON."""
        return json.dumps({
            'proteins': {id: protein.to_json() for id, protein in self.proteins.items()},
            'active_protein': self.active_protein,
            'display_settings': self.display_settings
        })

    def create_protein_from_id(self, identifier, import_method='PDB'):
        """Create a new protein from an identifier and add it to the scene.
        
        Args:
            identifier (str): PDB ID or UniProt ID
            import_method (str): Either 'PDB' or 'ALPHAFOLD'
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print("Creating protein", identifier, import_method)
            # Get protein file contents
            pdb_contents = get_protein_file(identifier, import_method)
            
            if not pdb_contents:
                print(f"Failed to retrieve protein data for {identifier}")
                return False

            # Create new protein instance
            protein = Protein(identifier, method=import_method)
            protein.parse_pdb_string(pdb_contents)
            protein.create_model()
            
            # Add to scene and set as active using the unique ID
            unique_id = protein.get_id()
            self.proteins[unique_id] = protein
            self.active_protein = unique_id
            
            # Force a redraw of all UI areas
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
            
            return True
            
        except Exception as e:
            print(f"Error creating protein: {str(e)}")
            return False

    @classmethod
    def from_json(cls, json_str):
        """Create a ProteinBlenderScene instance from JSON."""
        data = json.loads(json_str)
        scene = cls()
        scene.proteins = {
            id: Protein.from_json(protein_json) 
            for id, protein_json in data['proteins'].items()
        }
        scene.active_protein = data['active_protein']
        scene.display_settings = data['display_settings']
        return scene 