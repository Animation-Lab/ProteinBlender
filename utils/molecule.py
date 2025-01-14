import uuid
import json
import numpy as np
from typing import Optional, Union, List, Dict, Any
from pathlib import Path
import biotite.structure as struc

from ..visualizer.molecule_visualization import MoleculeVisualization

class Molecule:
    """
    Base class for molecular structures with efficient data storage and visualization support.
    """
    def __init__(self, identifier: str, method: str = "PDB"):
        # Metadata
        self.identifier = identifier
        self.method = method
        self.unique_id = f"{identifier}-{str(uuid.uuid4())[:8]}"
        
        # Core data storage (from MolecularNodes)
        self.array: Optional[Union[struc.AtomArray, struc.AtomArrayStack]] = None
        self.object: Optional['bpy.types.Object'] = None
        self._visualization = None
        
        # Additional metadata storage
        self.chains: set = set()
        self.residues: List[tuple] = []
        self._import_date = None

    @property
    def visualization(self):
        """Get the visualization handler."""
        return self._visualization
    
    @property
    def n_atoms(self) -> int:
        """Get the number of atoms in the molecule."""
        if self.array is not None:
            return self.array.array_length()
        return 0
        
    @property
    def chain_ids(self) -> List[str]:
        """Get unique chain IDs."""
        if self.array is not None and hasattr(self.array, "chain_id"):
            return np.unique(self.array.chain_id).tolist()
        return []

    def parse_pdb_string(self, pdb_content: str) -> None:
        """
        Parse PDB content into biotite structure array.
        """
        try:
            # Convert string to file-like object
            from io import StringIO
            from biotite.structure.io import pdb
            
            pdb_file = pdb.PDBFile.read(StringIO(pdb_content))
            self.array = pdb.get_structure(
                pdb_file,
                extra_fields=["b_factor", "occupancy", "atom_id"],
                include_bonds=True
            )
            
            # Update metadata
            if hasattr(self.array, "chain_id"):
                self.chains = set(np.unique(self.array.chain_id))
            
            # Update residues list
            if hasattr(self.array, "res_id") and hasattr(self.array, "res_name"):
                unique_residues = set()
                for chain_id, res_name, res_id in zip(
                    self.array.chain_id, 
                    self.array.res_name, 
                    self.array.res_id
                ):
                    unique_residues.add((chain_id, res_name, int(res_id)))
                self.residues = sorted(list(unique_residues))
                
        except Exception as e:
            print(f"Error parsing PDB content: {str(e)}")
            raise

    def to_json(self) -> str:
        """Convert molecule metadata to JSON."""
        data = {
            'identifier': self.identifier,
            'unique_id': self.unique_id,
            'method': self.method,
            'chains': list(self.chains),
            'residues': self.residues,
            'import_date': self._import_date,
            # Add any visualization settings that need to persist
            'visualization': {
                'style': self.visualization.style if self._visualization else None,
                'groups': self.visualization.get_groups() if self._visualization else {}
            }
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> 'Molecule':
        """Create a Molecule instance from JSON."""
        data = json.loads(json_str)
        molecule = cls(data['identifier'], data['method'])
        molecule.unique_id = data['unique_id']
        molecule.chains = set(data['chains'])
        molecule.residues = data['residues']
        molecule._import_date = data['import_date']
        
        # Note: The actual molecular data (array) and visualization 
        # need to be reconstructed separately
        return molecule

    def create_visualization(self, style: str = "surface") -> None:
        """
        Create or update the visualization of the molecule.
        
        This is a placeholder - we'll implement this when we create
        the visualization handler.
        """
        from . import visualization
        if self._visualization is None:
            self._visualization = visualization.MoleculeVisualization(self)
        self._visualization.create_visualization(style)

    def remove_visualization(self) -> None:
        """Remove the visualization."""
        if self._visualization:
            self._visualization.remove()
            self._visualization = None