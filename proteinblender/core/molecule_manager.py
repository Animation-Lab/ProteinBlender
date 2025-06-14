# proteinblender/core/molecule_manager.py
"""
Manages the lifecycle and state of all molecule objects in the Blender scene.
"""

from typing import Optional, Dict
from pathlib import Path
import bpy

from ..utils.molecularnodes.entities import fetch, load_local
from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from .molecule_wrapper import MoleculeWrapper


class MoleculeManager:
    """Manages all molecules in the scene"""
    def __init__(self):
        self.molecules: Dict[str, MoleculeWrapper] = {}
        self._initialize_molecularnodes()
        
    def _initialize_molecularnodes(self):
        """Initialize MolecularNodes system"""
        # Register all MolecularNodes classes and systems
        
        # Register properties if needed
        '''
        if not hasattr(bpy.types.Scene, "mn"):
            from bpy.utils import register_class
            register_class(MolecularNodesSceneProperties)
            bpy.types.Scene.mn = bpy.props.PointerProperty(type=MolecularNodesSceneProperties)
        '''
        
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

    def delete_molecule(self, identifier: str) -> Optional[MoleculeWrapper]:
        """Delete a molecule and return the removed wrapper."""
        print(f"Attempting to delete molecule: {identifier}")
        molecule_wrapper = self.get_molecule(identifier)
        if not molecule_wrapper:
            print(f"Molecule {identifier} not found in manager.")
            return None

        # 1. Call cleanup on the MoleculeWrapper to remove domains and their objects/nodes
        print(f"Cleaning up domains for molecule {identifier}...")
        molecule_wrapper.cleanup()

        # 2. Delete the main Blender object for the molecule
        if molecule_wrapper.molecule and molecule_wrapper.molecule.object:
            main_mol_object = molecule_wrapper.molecule.object
            object_name = main_mol_object.name
            collection_name = main_mol_object.users_collection[0].name if main_mol_object.users_collection else None
            print(f"Deleting main molecule object: {object_name}")
            try:
                bpy.data.objects.remove(main_mol_object, do_unlink=True)
            except Exception as e:
                print(f"Error removing main molecule object {object_name}: {e}")

            # 3. Attempt to remove the collection if it was specific to this molecule and is now empty
            if collection_name:
                collection = bpy.data.collections.get(collection_name)
                if collection and not collection.all_objects: # If collection is empty
                    if identifier in collection_name or object_name.startswith(collection_name): # Basic check
                        print(f"Deleting empty collection: {collection_name}")
                        try:
                            bpy.data.collections.remove(collection)
                        except Exception as e:
                            print(f"Error removing collection {collection_name}: {e}")
                    else:
                        print(f"Collection {collection_name} is empty but not deemed specific to {identifier}, not deleting.")
                elif collection:
                    print(f"Collection {collection_name} is not empty, not deleting.")

        # 4. Remove the molecule from the manager's dictionary
        if identifier in self.molecules:
            del self.molecules[identifier]
            print(f"Molecule {identifier} removed from manager.")

        return molecule_wrapper
