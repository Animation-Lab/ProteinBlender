import json
from .protein import Protein

class ProteinBlenderScene:
    def __init__(self):
        self.proteins = {}  # Dictionary of protein_id: Protein instances
        self.active_protein = None
        self.display_settings = {
            'representation': 'ball_stick',  # or 'ribbon', 'surface', etc.
            'show_hydrogens': False,
            'show_sidechains': True
        }

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