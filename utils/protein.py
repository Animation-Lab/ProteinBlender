import json
import os
from datetime import datetime

class Protein:
    def __init__(self, identifier, method='PDB'):
        self.identifier = identifier
        self.method = method
        self.file_path = None
        self.import_date = datetime.now().isoformat()
        self.atoms = []  # List of atom positions and types
        self.chains = []  # List of chain IDs
        self.residues = []  # List of residue information
        
    def parse_pdb_file(self, file_path):
        """Parse a PDB file and store relevant information."""
        self.file_path = file_path
        with open(file_path, 'r') as f:
            for line in f:
                if line.startswith('ATOM') or line.startswith('HETATM'):
                    # Parse atom information
                    atom_info = {
                        'type': line[12:16].strip(),
                        'residue': line[17:20].strip(),
                        'chain': line[21],
                        'residue_num': int(line[22:26]),
                        'position': [
                            float(line[30:38]),
                            float(line[38:46]),
                            float(line[46:54])
                        ]
                    }
                    self.atoms.append(atom_info)
                    
                    if atom_info['chain'] not in self.chains:
                        self.chains.append(atom_info['chain'])
                        
                    residue_key = (atom_info['chain'], atom_info['residue'], atom_info['residue_num'])
                    if residue_key not in self.residues:
                        self.residues.append(residue_key)

    def to_json(self):
        """Convert the protein instance to JSON."""
        return json.dumps({
            'identifier': self.identifier,
            'method': self.method,
            'file_path': self.file_path,
            'import_date': self.import_date,
            'atoms': self.atoms,
            'chains': self.chains,
            'residues': self.residues
        })

    @classmethod
    def from_json(cls, json_str):
        """Create a Protein instance from JSON."""
        data = json.loads(json_str)
        protein = cls(data['identifier'], data['method'])
        protein.file_path = data['file_path']
        protein.import_date = data['import_date']
        protein.atoms = data['atoms']
        protein.chains = data['chains']
        protein.residues = data['residues']
        return protein 