from typing import Optional, Dict
import bpy
from pathlib import Path

from ..utils.molecularnodes.entities import fetch, load_local
from .molecule_wrapper import MoleculeWrapper

class MoleculeManager:
    """Manages all molecules in the scene"""
    def __init__(self):
        self.molecules: Dict[str, MoleculeWrapper] = {}
    
    def add_molecule(self, molecule: MoleculeWrapper):
        """Add a molecule to the manager"""
        if molecule and molecule.identifier:
            self.molecules[molecule.identifier] = molecule
            return True
        return False
        
    def remove_molecule(self, identifier: str):
        """Remove a molecule from the manager"""
        if identifier in self.molecules:
            # First clean up the molecule's resources
            molecule = self.molecules[identifier]
            
            # Clean up the Blender object
            if hasattr(molecule, 'object') and molecule.object:
                # Store object data
                obj_data = molecule.object.data
                
                # Remove the object
                bpy.data.objects.remove(molecule.object, do_unlink=True)
                
                # Clean up object data if no other users
                if obj_data and obj_data.users == 0:
                    if isinstance(obj_data, bpy.types.Mesh):
                        bpy.data.meshes.remove(obj_data, do_unlink=True)
            
            # Call molecule's cleanup method to handle domains
            molecule.cleanup()
            
            # Remove from the dictionary
            del self.molecules[identifier]
            return True
        return False
        
    def import_from_pdb(self, pdb_id: str, molecule_id: str, style: str = "surface", **kwargs) -> MoleculeWrapper:
        """Import a molecule from PDB"""
        try:
            # Use MolecularNodes fetch functionality
            mol = fetch(
                pdb_code=pdb_id,
                style=style,
                del_solvent=True,  # Default settings, could be made configurable
                build_assembly=False,
                **kwargs
            )
            
            # Create our wrapper object
            wrapper = MoleculeWrapper(mol, molecule_id)
            self.molecules[molecule_id] = wrapper
            
            return wrapper
            
        except Exception as e:
            print(f"Failed to import PDB {pdb_id}: {str(e)}")
            raise
            
    def import_from_file(self, filepath: str, name: Optional[str] = None) -> MoleculeWrapper:
        """Import a molecule from a local file"""
        try:
            mol = load_local(
                file_path=filepath,
                name=name or Path(filepath).stem,
                style="spheres",
                del_solvent=True
            )
            
            identifier = name or Path(filepath).stem
            wrapper = MoleculeWrapper(mol, identifier)
            self.molecules[identifier] = wrapper
            
            return wrapper
            
        except Exception as e:
            print(f"Failed to import file {filepath}: {str(e)}")
            raise
    
    def get_molecule(self, identifier: str) -> Optional[MoleculeWrapper]:
        """Get a molecule by its identifier (PDB ID or name)"""
        return self.molecules.get(identifier) 