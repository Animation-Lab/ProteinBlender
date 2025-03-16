from .file_io import get_protein_file
import json
import bpy
from typing import Dict, Optional
from .molecularnodes.entities import fetch, load_local
from ..core.molecule_manager import MoleculeManager, MoleculeWrapper
from bpy.app.handlers import undo_post, undo_pre

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
            
            # Create unique identifier if this ID already exists
            counter = 1
            base_identifier = f"{identifier}_{counter:03d}"
            while base_identifier in self.molecules:
                counter += 1
                base_identifier = f"{identifier}_{counter:03d}"
            if import_method == 'PDB':
                molecule = self.molecule_manager.import_from_pdb(identifier, base_identifier)  # Use original ID for fetch
            else:  # AlphaFold
                molecule = self.molecule_manager.import_from_pdb(
                    identifier,  # Use original ID for fetch
                    base_identifier,
                    database="alphafold",
                    color="plddt"
                )
            
            # Store with unique identifier
            self.molecules[base_identifier] = molecule
            molecule.identifier = base_identifier  # Update the molecule's identifier
            
            # Add to UI list
            scene = bpy.context.scene
            item = scene.molecule_list_items.add()
            item.identifier = base_identifier
            
            # Set as active molecule
            self.active_molecule = base_identifier
            
            # Force UI refresh
            self._refresh_ui()
            
            return True
            
        except Exception as e:
            print(f"Error creating molecule: {str(e)}")
            return False

    def sync_molecule_list_after_undo(*args):
        """Synchronize the molecule list UI after undo/redo operations"""
        print("Syncing molecule list after undo/redo")
        # THIS FUNCTION WILL BE CALLED WHENEVER AN UNDO OR REDO IS DONE
        '''
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        # Clear existing list
        scene.molecule_list_items.clear()
        
        # Rebuild list from current molecules
        for identifier, molecule in scene_manager.molecules.items():
            if molecule.object and molecule.object.name in bpy.data.objects:
                item = scene.molecule_list_items.add()
                item.identifier = identifier
        
        # Ensure active molecule is valid
        if scene_manager.active_molecule not in scene_manager.molecules:
            scene_manager.active_molecule = next(iter(scene_manager.molecules)) if scene_manager.molecules else None
        
        # Force UI refresh
        scene_manager._refresh_ui()
        '''

    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
        if identifier in self.molecules:
            # Remove from scene
            molecule = self.molecules[identifier]
            
            # Clean up all associated domains first
            print(f"Cleaning up all domains for molecule {identifier}")
            molecule.cleanup()
            
            if molecule.object:
                # Push to undo stack before making changes
                print("Pushing to undo stack")
                bpy.ops.ed.undo_push(message=f"Delete Molecule {identifier}")

                print("Appending undo post handler")
                bpy.app.handlers.undo_post.append(self.sync_molecule_list_after_undo)

                print("Removing object")
                # Store object data
                obj_data = molecule.object.data
                
                # Remove the object
                bpy.data.objects.remove(molecule.object, do_unlink=True)
                
                # Clean up object data if no other users
                if obj_data and obj_data.users == 0:
                    if isinstance(obj_data, bpy.types.Mesh):
                        bpy.data.meshes.remove(obj_data, do_unlink=True)
            
            # Remove from our internal tracking
            del self.molecules[identifier]
            
            # Update UI list - this will be restored by the undo handler if needed
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