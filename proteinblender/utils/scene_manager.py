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
        self._saved_states = {}  # molecule_id -> MoleculeState

    @property
    def molecules(self) -> Dict[str, MoleculeWrapper]:
        return self.molecule_manager.molecules

    def _capture_molecule_state(self, molecule_id):
        """Store complete state before destructive operations"""
        if molecule_id in self.molecules:
            from ..core.molecule_state import MoleculeState
            self._saved_states[molecule_id] = MoleculeState(self.molecules[molecule_id])
            print(f"Captured state for molecule: {molecule_id}")

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
        item.object_ptr = molecule.object
        scene.molecule_list_index = len(scene.molecule_list_items) - 1
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



    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
        # Capture state before deletion
        self._capture_molecule_state(identifier)
        
        # Check if the molecule exists via the manager, which holds the actual MoleculeWrapper objects
        if self.molecule_manager.get_molecule(identifier):
            # Call the MoleculeManager's delete_molecule method
            # This method now handles the core cleanup of the molecule wrapper, 
            # its Blender object, and potentially its collection.
            self.molecule_manager.delete_molecule(identifier)
            
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
        mol = self.molecules.get(identifier)
        if mol and hasattr(mol, "object"):
            item.object_ptr = mol.object
        scene.molecule_list_index = len(scene.molecule_list_items) - 1
        
        # Set as active molecule
        self.active_molecule = identifier
        
        # Force UI refresh
        self._refresh_ui()


def _is_object_valid(obj):
    """Check if Blender object reference is still valid"""
    try:
        return obj and obj.name in bpy.data.objects
    except:
        return False


def _is_molecule_valid(molecule):
    """Check if molecule wrapper has a valid object reference"""
    try:
        if not molecule:
            return False
        obj = getattr(molecule, 'object', None)
        if not _is_object_valid(obj):
            name = getattr(molecule, 'object_name', '')
            if name and name in bpy.data.objects:
                if hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                    molecule.molecule.object = bpy.data.objects[name]
                molecule.object = bpy.data.objects[name]
                return True
            return False
        return True
    except Exception as e:
        # Handle MolecularNodes databpy LinkedObjectError and other exceptions
        return False


def _has_invalid_domains(molecule):
    """Check if any domains have invalid object references"""
    try:
        # First check if we can access the molecule at all
        if not _is_molecule_valid(molecule):
            return True

        for domain in molecule.domains.values():
            if not _is_object_valid(domain.object):
                name = getattr(domain, 'object_name', '')
                if name and name in bpy.data.objects:
                    domain.object = bpy.data.objects[name]
                else:
                    return True
        return False
    except:
        return True


def _refresh_molecule_ui(scene_manager, scene):
    """Refresh the UI to match current state"""
    # Clear and rebuild molecule list
    scene.molecule_list_items.clear()

    for identifier, molecule in scene_manager.molecules.items():
        if not _is_object_valid(molecule.object):
            name = getattr(molecule, 'object_name', '')
            if name and name in bpy.data.objects:
                molecule.object = bpy.data.objects[name]
                if hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                    molecule.molecule.object = molecule.object
        if _is_object_valid(molecule.object):
            # Restore domain pointers if needed
            for domain in molecule.domains.values():
                if not _is_object_valid(domain.object):
                    name = getattr(domain, 'object_name', '')
                    if name and name in bpy.data.objects:
                        domain.object = bpy.data.objects[name]
            item = scene.molecule_list_items.add()
            item.identifier = identifier
            item.object_ptr = molecule.object
    
    # Update active molecule
    if scene_manager.active_molecule not in scene_manager.molecules:
        scene_manager.active_molecule = next(iter(scene_manager.molecules), None)
    
    # Force UI refresh
    scene_manager._refresh_ui()


def sync_molecule_list_after_undo(*args):
    """Sync molecule state after undo/redo operations"""
    print("Syncing molecule list after undo/redo")
    
    scene_manager = ProteinBlenderScene.get_instance()
    scene = bpy.context.scene
    
    # Step 1: Clean up molecules that have invalid objects (e.g., after undoing an import)
    molecules_to_remove = []
    for molecule_id, molecule in list(scene_manager.molecules.items()):
        if not _is_molecule_valid(molecule):
            scene_manager._capture_molecule_state(molecule_id)
            molecules_to_remove.append(molecule_id)

    for molecule_id in molecules_to_remove:
        print(f"Removing invalid molecule from scene manager: {molecule_id}")
        del scene_manager.molecules[molecule_id]
        if molecule_id in scene_manager.molecule_manager.molecules:
            del scene_manager.molecule_manager.molecules[molecule_id]
        for i, item in enumerate(scene.molecule_list_items):
            if item.identifier == molecule_id:
                scene.molecule_list_items.remove(i)
                break
    # Step 2: Find molecules that should be restored (e.g., after undoing a delete)
    molecules_to_restore = []
    
    for molecule_id, saved_state in scene_manager._saved_states.items():
        current_molecule = scene_manager.molecules.get(molecule_id)
        
        # Check if molecule exists and is valid
        needs_restore = (
            current_molecule is None or 
            not _is_molecule_valid(current_molecule) or
            _has_invalid_domains(current_molecule)
        )
        
        # Only restore if the object actually exists in Blender (was restored by undo)
        if needs_restore and saved_state.molecule_data.get('object_name'):
            restored_obj = bpy.data.objects.get(saved_state.molecule_data['object_name'])
            if restored_obj:  # Object exists, so this should be restored
                molecules_to_restore.append((molecule_id, saved_state))
    
    # Step 3: Restore missing molecules
    for molecule_id, saved_state in molecules_to_restore:
        print(f"Restoring molecule: {molecule_id}")
        try:
            restored = saved_state.restore_to_scene(scene_manager)
            # Once restored, clear its saved state
            if restored and molecule_id in scene_manager._saved_states:
                del scene_manager._saved_states[molecule_id]
        except Exception as e:
            print(f"Failed to restore molecule {molecule_id}: {str(e)}")
            import traceback
            traceback.print_exc()
    # If we restored any molecules, mark the last one as selected
    if molecules_to_restore:
        last_id = molecules_to_restore[-1][0]
        scene.selected_molecule_id = last_id
    
    # Step 4: Update UI
    _refresh_molecule_ui(scene_manager, scene)
    # If some saved states still refer to real objects, retry once
    try:
        # Collect names of saved molecules yet to restore
        pending = [s.molecule_data.get('object_name') for s in scene_manager._saved_states.values() if s.molecule_data.get('object_name')]
        # Check if any of these objects exist in Blender data
        if not scene_manager.molecules and any(name in bpy.data.objects for name in pending):
            print("Sync: Pending molecule objects detected, scheduling retry...")
            bpy.app.timers.register(lambda: sync_molecule_list_after_undo(), first_interval=0.2)
    except Exception:
        pass 