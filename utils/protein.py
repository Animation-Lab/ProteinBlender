import json
import os
from datetime import datetime
import uuid
from mathutils import Vector
from ..visualizer.protein_mesh import ProteinMesh
from ..visualizer.protein_point_cloud import ProteinPointCloud
from ..visualizer.base import RenderStyle

class Protein:
    def __init__(self, identifier, method="PDB"):
        self.identifier = identifier
        self.method = method
        self.atoms = []
        self.residues = []  # List of tuples (chain_id, residue_name, residue_num)
        self.chains = set()  # Set of chain IDs
        self.model = None
        self.unique_id = f"{identifier}-{str(uuid.uuid4())[:8]}"  # Using first 8 chars of UUID for brevity

    def get_id(self):
        """Get the unique identifier for this protein instance."""
        return self.unique_id
        
    def parse_pdb_string(self, pdb_content):
        """Parse PDB content and store relevant information."""
        for line in pdb_content.splitlines():
            if line.startswith(('ATOM', 'HETATM')):
                atom_info = {
                    'type': line[12:16].strip(),
                    'residue': line[17:20].strip(),
                    'chain': line[21],
                    'residue_num': int(line[22:26]),
                    'position': [
                        float(line[30:38]),
                        float(line[38:46]),
                        float(line[46:54]),
                    ],
                    'symbol': line[76:78].strip().upper()
                }
                
                # If symbol is empty, try to determine it from atom type
                if not atom_info['symbol']:
                    atom_type = atom_info['type'].upper()
                    if atom_type.startswith('C'):
                        atom_info['symbol'] = 'C'
                    elif atom_type.startswith('N'):
                        atom_info['symbol'] = 'N'
                    elif atom_type.startswith('O'):
                        atom_info['symbol'] = 'O'
                    elif atom_type.startswith('H'):
                        atom_info['symbol'] = 'H'
                    elif atom_type.startswith('S'):
                        atom_info['symbol'] = 'S'
                    elif atom_type.startswith('P'):
                        atom_info['symbol'] = 'P'
                    else:
                        atom_info['symbol'] = 'C'  # Default to carbon if unknown
                
                self.add_atom(atom_info)

    @staticmethod
    def determine_bond_type(atom1, atom2, distance):
        """Determine the type of bond between two atoms based on their properties."""
        # Default to single bond
        bond_type = 'single'
        
        # Get atom symbols
        symbol1 = atom1['symbol'].strip().upper()
        symbol2 = atom2['symbol'].strip().upper()
        
        # Check for hydrogen bonds
        if symbol1 == 'H' or symbol2 == 'H':
            return 'hydrogen'
            
        # Check for polar bonds (involving O or N)
        if symbol1 in ['O', 'N'] or symbol2 in ['O', 'N']:
            return 'polar'
            
        # Check for nonpolar bonds (primarily C-C)
        if symbol1 == 'C' and symbol2 == 'C':
            # Rough distance-based determination
            if distance < 1.2:  # Typical C-C triple bond length
                return 'triple'
            elif distance < 1.4:  # Typical C-C double bond length
                return 'double'
            elif distance < 1.6:  # Typical C-C aromatic bond length
                return 'aromatic'
            else:  # Typical C-C single bond length
                return 'nonpolar'
                
        return bond_type

    def create_model(self, style=RenderStyle.BALL_AND_STICK, position=None, scale=None, rotation=None):
        """Create a 3D model of the protein."""
        try:
            # Initialize model if not already done
            if self.model is None:
                # self.model = ProteinMesh()
                self.model = ProteinPointCloud()
            # Create the model with specified parameters
            self.model.create_model(
                protein=self,
                style=style,
                position=position,
                scale=scale,
                rotation=rotation
            )
            
        except Exception as e:
            print(f"Error creating protein: {str(e)}")
            raise
    
    def remove_model(self):
        """Remove the 3D model of the protein."""
        if self.model:
            self.model.remove_model()
            self.model = None
    
    def select_chain(self, chain_id):
        """Select a specific chain in the protein model."""
        if self.model:
            self.model.select_chain(chain_id)
    
    def select_residue(self, chain_id, residue_name, residue_num):
        """Select a specific residue in the protein model."""
        if self.model:
            self.model.select_residue(chain_id, residue_name, residue_num)
    
    def add_atom(self, atom_data):
        """Add an atom to the protein."""
        self.atoms.append(atom_data)
        
        # Update chains and residues sets
        chain_id = atom_data['chain']
        residue_name = atom_data['residue']
        residue_num = atom_data['residue_num']
        
        self.chains.add(chain_id)
        residue_key = (chain_id, residue_name, residue_num)
        if residue_key not in self.residues:
            self.residues.append(residue_key) 

    def to_json(self):
        """Convert the protein instance to JSON."""
        return json.dumps({
            'identifier': self.identifier,
            'unique_id': self.unique_id,  # Added unique_id to JSON serialization
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
        protein.unique_id = data['unique_id']  # Restore unique_id from JSON
        protein.file_path = data['file_path']
        protein.import_date = data['import_date']
        protein.atoms = data['atoms']
        protein.chains = data['chains']
        protein.residues = data['residues']
        return protein 