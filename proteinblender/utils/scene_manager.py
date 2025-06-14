from .file_io import get_protein_file
import json
import bpy
from typing import Dict, Optional, List, Set
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
        # Store wrappers of molecules that have been deleted so they can be
        # restored if the user performs an undo operation. Each wrapper keeps
        # the Blender object name that was removed for easy lookup on undo.
        self.deleted_molecules: Dict[str, MoleculeWrapper] = {}


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

    def _create_domains_for_each_chain(self, molecule_id: str):
        molecule = self.molecule_manager.get_molecule(molecule_id)
        if not molecule:
            print(f"Molecule {molecule_id} not found for domain creation.")
            return

        # Use the chain_residue_ranges from MoleculeWrapper, which should now be keyed by label_asym_id.
        chain_ranges_from_wrapper = molecule.chain_residue_ranges

        if not chain_ranges_from_wrapper:
            print(f"Warning SceneManager: No chain residue ranges found in molecule wrapper for {molecule_id}. Cannot create default domains.")
            return

        # Map each chain label to an integer index:
        label_asym_id_to_idx_map: Dict[str, int] = {}
        # 1) Use MoleculeWrapper.idx_to_label_asym_id_map if present
        if hasattr(molecule, 'idx_to_label_asym_id_map') and molecule.idx_to_label_asym_id_map:
            label_asym_id_to_idx_map = {v: k for k, v in molecule.idx_to_label_asym_id_map.items()}
        # 2) Fallback: sequential indices over chain_ranges_from_wrapper keys
        if not label_asym_id_to_idx_map:
            for idx, label in enumerate(chain_ranges_from_wrapper.keys()):
                label_asym_id_to_idx_map[label] = idx

        created_domain_ids_for_molecule: List[List[str]] = []
        # Keep track of processed label_asym_ids to avoid duplicates if chain_ranges_from_wrapper somehow has redundant entries
        processed_label_asym_ids: Set[str] = set()

        for label_asym_id_key, (min_res, max_res) in chain_ranges_from_wrapper.items():
            if label_asym_id_key in processed_label_asym_ids:
                print(f"DEBUG SceneManager: Label_asym_id '{label_asym_id_key}' already processed. Skipping.")
                continue

            current_min_res = min_res
            if current_min_res == 0: # Adjusting 0-indexed min_res, though chain_residue_ranges should ideally be 1-indexed from wrapper
                print(f"Warning SceneManager: Adjusting 0-indexed min_res to 1 for label_asym_id '{label_asym_id_key}'. Original range: ({min_res}-{max_res})")
                current_min_res = 1
            
            # Get the corresponding integer chain index string for Blender attribute lookups
            int_chain_idx = label_asym_id_to_idx_map.get(label_asym_id_key)
            if int_chain_idx is None:
                print(f"ERROR SceneManager: Could not find integer index for label_asym_id '{label_asym_id_key}' in label_asym_id_to_idx_map. Skipping domain creation for this chain.")
                continue
            chain_id_int_str_for_domain = str(int_chain_idx)

            domain_name = f"Chain {label_asym_id_key}" # Default name

            # Call using positional arguments: chain_id_int_str, start, end, name, auto_fill_chain, parent_domain_id
            created_domain_ids = molecule._create_domain_with_params(
                chain_id_int_str_for_domain,
                current_min_res,
                max_res,
                domain_name,
                False,  # auto_fill_chain
                None    # parent_domain_id
            )
            
            if created_domain_ids:
                created_domain_ids_for_molecule.append(created_domain_ids)
                processed_label_asym_ids.add(label_asym_id_key)
            else:
                 print(f"DEBUG SceneManager: Failed to create a valid domain for LabelAsymID '{label_asym_id_key}' (IntChainIdxStr: {chain_id_int_str_for_domain}). It may have been skipped or failed in MoleculeWrapper.")
        
        if created_domain_ids_for_molecule:
            # self.update_molecule_domain_list_in_ui(molecule_id) # Assuming a method to refresh UI if needed
            print(f"SceneManager: Finished creating default domains for {molecule_id}. Created IDs: {created_domain_ids_for_molecule}")
        else:
            print(f"SceneManager: No domains were created for {molecule_id} during default domain creation.")

    def _finalize_imported_molecule(self, molecule):
        """Finalize the import of a molecule: create domains, update UI, set active, refresh."""
        # Create domains for each chain
        self._create_domains_for_each_chain(molecule.identifier)
        # Add to UI list
        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = molecule.identifier
        # Set as active molecule
        self.active_molecule = molecule.identifier
        # Force UI refresh
        self._refresh_ui()

    def create_molecule_from_id(self, identifier: str, import_method: str = 'PDB', remote_format: str = 'pdb') -> bool:
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
                molecule = self.molecule_manager.import_from_pdb(
                    identifier,
                    base_identifier,
                    format=remote_format
                )
            else:  # AlphaFold
                molecule = self.molecule_manager.import_from_pdb(
                    identifier,
                    base_identifier,
                    database="alphafold",
                    color="plddt",
                    format=remote_format
                )
            # Store with unique identifier
            self.molecules[base_identifier] = molecule
            molecule.identifier = base_identifier  # Update the molecule's identifier
            # Finalize import (domains, UI, etc.)
            self._finalize_imported_molecule(molecule)
            return True
        except Exception as e:
            print(f"Error creating molecule: {str(e)}")
            return False

    def sync_molecule_list_after_undo(*args):
        """Synchronize the molecule list UI after undo/redo operations"""
        scene_manager = ProteinBlenderScene.get_instance()

        # Reload domain information for existing molecules
        for molecule in scene_manager.molecules.values():
            try:
                molecule._load_domains_from_rna()
            except Exception as e:
                print(f"Failed to reload domains for {molecule.identifier}: {e}")

        # Check if any previously deleted molecules reappeared after undo
        for identifier, wrapper in list(scene_manager.deleted_molecules.items()):
            obj_name = getattr(wrapper, "deleted_object_name", identifier)
            obj = bpy.data.objects.get(obj_name)
            if obj:
                # Restore pointer to Blender object and rebuild state
                wrapper.molecule.object = obj
                wrapper._load_domains_from_rna()
                scene_manager.molecule_manager.molecules[identifier] = wrapper
                scene_manager._add_molecule_to_list(identifier)
                del scene_manager.deleted_molecules[identifier]

    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
        # Check if the molecule exists via the manager, which holds the actual MoleculeWrapper objects
        if self.molecule_manager.get_molecule(identifier):
            # Call the MoleculeManager's delete_molecule method and keep the
            # wrapper around so it can be restored on undo.
            wrapper = self.molecule_manager.delete_molecule(identifier)
            if wrapper:
                self.deleted_molecules[identifier] = wrapper
            
            # Update UI list - this part is for the ProteinBlenderScene's own UI management
            scene = bpy.context.scene
            for i, item in enumerate(scene.molecule_list_items):
                if item.identifier == identifier:
                    scene.molecule_list_items.remove(i)
                    break
            
            # Reset UI state if the deleted molecule was the selected one
            if scene.selected_molecule_id == identifier:
                scene.selected_molecule_id = ""
                # scene.molecule_list_index = 0 # Resetting index might not be desired
                
                # Reset other UI properties related to molecule/domain editing
                try:
                    enum_items = scene.bl_rna.properties["new_domain_chain"].enum_items
                    if enum_items:
                        scene.new_domain_chain = enum_items[0].identifier
                except (KeyError, AttributeError, RuntimeError): # RuntimeError for enum not found
                    pass 
                
                scene.new_domain_start = 1
                scene.new_domain_end = 9999
                # scene.temp_domain_start = 1 # These are for active split, might not need reset here
                # scene.temp_domain_end = 9999
                # scene.temp_domain_id = "" 
                # scene.active_splitting_domain_id = "" # Also related to active split context

                # scene.show_domain_preview = False # This relates to a different feature
                scene.show_molecule_edit_panel = False
                scene.edit_molecule_identifier = ""

            # Refresh UI
            self._refresh_ui()
            
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

    def import_molecule_from_file(self, filepath: str, identifier: str) -> bool:
        """Import a molecule from a local file"""
        try:
            # Import the molecule using MoleculeManager
            molecule = self.molecule_manager.import_from_file(filepath, identifier)
            if not molecule:
                print(f"Failed to create molecule from file: {filepath}")
                return False
            # Finalize import (domains, UI, etc.)
            self._finalize_imported_molecule(molecule)
            return True
        except Exception as e:
            print(f"Error creating molecule from file {filepath}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False 

    def _add_molecule_to_list(self, identifier):
        """Add a molecule to the UI list and set it as active"""
        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = identifier
        
        # Set as active molecule
        self.active_molecule = identifier
        
        # Force UI refresh
        self._refresh_ui() 
