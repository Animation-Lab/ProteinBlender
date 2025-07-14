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

    def _refresh_domain_object_references(self, molecule):
        """Refresh domain object references after undo/redo operations"""
        for domain_id, domain in molecule.domains.items():
            # Refresh object reference by name
            if hasattr(domain, 'object_name') and domain.object_name:
                fresh_obj = bpy.data.objects.get(domain.object_name)
                if fresh_obj:
                    domain.object = fresh_obj
            
            # Refresh node group reference by name
            if hasattr(domain, 'node_group_name') and domain.node_group_name:
                fresh_ng = bpy.data.node_groups.get(domain.node_group_name)
                if fresh_ng:
                    domain.node_group = fresh_ng

    def _capture_molecule_state(self, molecule_id):
        """Store complete state before destructive operations"""
        if molecule_id in self.molecules:
            try:
                # Refresh domain object references to avoid stale references after undo/redo
                self._refresh_domain_object_references(self.molecules[molecule_id])
                from ..core.molecule_state import MoleculeState
                self._saved_states[molecule_id] = MoleculeState(self.molecules[molecule_id])
            except Exception as e:
                print(f"Warning: Failed to capture state for molecule {molecule_id}: {e}")
                # Don't let state capture failures block other operations

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
            return

        # Use the chain_residue_ranges from MoleculeWrapper, which should now be keyed by label_asym_id.
        chain_ranges_from_wrapper = molecule.chain_residue_ranges

        if not chain_ranges_from_wrapper:
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
                continue

            current_min_res = min_res
            if current_min_res == 0: # Adjusting 0-indexed min_res, though chain_residue_ranges should ideally be 1-indexed from wrapper
                current_min_res = 1
            
            # Get the corresponding integer chain index string for Blender attribute lookups
            int_chain_idx = label_asym_id_to_idx_map.get(label_asym_id_key)
            if int_chain_idx is None:
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

    def _finalize_imported_molecule(self, molecule):
        """Finalize the import of a molecule: create domains, update UI, set active, refresh."""
        # Create domains for each chain
        # self._create_domains_for_each_chain(molecule.identifier)
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
                return False
            # Finalize import (domains, UI, etc.)
            self._finalize_imported_molecule(molecule)
            return True
        except Exception as e:
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
            if not domain.node_group:
                ng_name = getattr(domain, 'node_group_name', '')
                if ng_name and ng_name in bpy.data.node_groups:
                    domain.node_group = bpy.data.node_groups[ng_name]
                elif ng_name:
                    return True
        return False
    except:
        return True


def _refresh_molecule_ui(scene_manager, scene):
    """Refresh the UI to match current state"""
    # Preserve existing keyframes and poses before clearing the list
    existing_keyframes = {}
    existing_poses = {}
    
    for item in scene.molecule_list_items:
        if item.identifier:
            # Preserve keyframes
            if len(item.keyframes) > 0:
                existing_keyframes[item.identifier] = []
                for kf in item.keyframes:
                    # Store keyframe data
                    kf_data = {
                        'name': kf.name,
                        'frame': kf.frame,
                        'use_brownian_motion': kf.use_brownian_motion,
                        'intensity': kf.intensity,
                        'frequency': kf.frequency,
                        'seed': kf.seed,
                        'resolution': kf.resolution
                    }
                    existing_keyframes[item.identifier].append(kf_data)
            
            # Preserve poses
            if len(item.poses) > 0:
                existing_poses[item.identifier] = []
                for pose in item.poses:
                    # Store pose data
                    pose_data = {
                        'name': pose.name,
                        'has_protein_transform': pose.has_protein_transform,
                        'protein_location': list(pose.protein_location),
                        'protein_rotation': list(pose.protein_rotation),
                        'protein_scale': list(pose.protein_scale),
                        'domain_transforms': []
                    }
                    # Store domain transforms
                    for domain_transform in pose.domain_transforms:
                        domain_data = {
                            'domain_id': domain_transform.domain_id,
                            'location': list(domain_transform.location),
                            'rotation': list(domain_transform.rotation),
                            'scale': list(domain_transform.scale)
                        }
                        pose_data['domain_transforms'].append(domain_data)
                    existing_poses[item.identifier].append(pose_data)
    
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
                if not domain.node_group:
                    ng_name = getattr(domain, 'node_group_name', '')
                    if ng_name and ng_name in bpy.data.node_groups:
                        domain.node_group = bpy.data.node_groups[ng_name]
            item = scene.molecule_list_items.add()
            item.identifier = identifier
            item.object_ptr = molecule.object
            
            # Restore keyframes for this molecule if they existed
            if identifier in existing_keyframes:
                for kf_data in existing_keyframes[identifier]:
                    new_kf = item.keyframes.add()
                    new_kf.name = kf_data['name']
                    new_kf.frame = kf_data['frame']
                    new_kf.use_brownian_motion = kf_data['use_brownian_motion']
                    new_kf.intensity = kf_data['intensity']
                    new_kf.frequency = kf_data['frequency']
                    new_kf.seed = kf_data['seed']
                    new_kf.resolution = kf_data['resolution']
            
            # Restore poses for this molecule if they existed
            if identifier in existing_poses:
                for pose_data in existing_poses[identifier]:
                    new_pose = item.poses.add()
                    new_pose.name = pose_data['name']
                    new_pose.has_protein_transform = pose_data['has_protein_transform']
                    new_pose.protein_location = pose_data['protein_location']
                    new_pose.protein_rotation = pose_data['protein_rotation']
                    new_pose.protein_scale = pose_data['protein_scale']
                    
                    # Restore domain transforms
                    for domain_data in pose_data['domain_transforms']:
                        new_domain_transform = new_pose.domain_transforms.add()
                        new_domain_transform.domain_id = domain_data['domain_id']
                        new_domain_transform.location = domain_data['location']
                        new_domain_transform.rotation = domain_data['rotation']
                        new_domain_transform.scale = domain_data['scale']
    
    # Update active molecule
    if scene_manager.active_molecule not in scene_manager.molecules:
        scene_manager.active_molecule = next(iter(scene_manager.molecules), None)
    
    # Force UI refresh
    scene_manager._refresh_ui()


def _refresh_object_references_only(scene_manager, scene):
    """Refresh object references without rebuilding the entire UI list"""
    for identifier, molecule in scene_manager.molecules.items():
        # Refresh molecule object reference
        if not _is_object_valid(molecule.object):
            name = getattr(molecule, 'object_name', '')
            if name and name in bpy.data.objects:
                molecule.object = bpy.data.objects[name]
                if hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                    molecule.molecule.object = molecule.object
        
        # Refresh domain object references
        for domain in molecule.domains.values():
            if not _is_object_valid(domain.object):
                name = getattr(domain, 'object_name', '')
                if name and name in bpy.data.objects:
                    domain.object = bpy.data.objects[name]
            if not domain.node_group:
                ng_name = getattr(domain, 'node_group_name', '')
                if ng_name and ng_name in bpy.data.node_groups:
                    domain.node_group = bpy.data.node_groups[ng_name]
    
    # Force UI refresh without rebuilding
    scene_manager._refresh_ui()


def sync_molecule_list_after_undo(*args):
    """Sync molecule state after undo/redo operations"""
    try:
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        # Step 1: Clean up molecules that have invalid objects (e.g., after undoing an import)
        molecules_to_remove = []
        for molecule_id, molecule in list(scene_manager.molecules.items()):
            if not _is_molecule_valid(molecule):
                print(f"----------- Molecule {molecule_id} is invalid, removing ------------")
                # Don't try to capture state of invalid molecules - this causes errors
                molecules_to_remove.append(molecule_id)
            else:
                # Refresh domain object references for valid molecules after undo/redo
                try:
                    scene_manager._refresh_domain_object_references(molecule)
                except Exception as e:
                    print(f"Warning: Failed to refresh domain references for {molecule_id}: {e}")

        for molecule_id in molecules_to_remove:
            # Safely remove invalid molecules
            if molecule_id in scene_manager.molecules:
                del scene_manager.molecules[molecule_id]
            if molecule_id in scene_manager.molecule_manager.molecules:
                del scene_manager.molecule_manager.molecules[molecule_id]
            # Remove from UI list
            for i, item in enumerate(scene.molecule_list_items):
                if item.identifier == molecule_id:
                    scene.molecule_list_items.remove(i)
                    break
        
        # Step 2: Find molecules that should be restored (e.g., after undoing a delete)
        molecules_to_restore = []
        
        for molecule_id, saved_state in list(scene_manager._saved_states.items()):
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
            try:
                restored = saved_state.restore_to_scene(scene_manager)
                # Once restored, clear its saved state
                if restored and molecule_id in scene_manager._saved_states:
                    del scene_manager._saved_states[molecule_id]
            except Exception as e:
                print(f"Warning: Failed to restore molecule {molecule_id}: {e}")
        
        # If we restored any molecules, mark the last one as selected
        if molecules_to_restore:
            last_id = molecules_to_restore[-1][0]
            scene.selected_molecule_id = last_id
        
        # Step 4: Update UI - but be more careful about when to rebuild
        # Only rebuild UI if we actually removed or restored molecules
        if molecules_to_remove or molecules_to_restore:
            _refresh_molecule_ui(scene_manager, scene)
        else:
            # Just refresh object references without rebuilding the entire UI
            _refresh_object_references_only(scene_manager, scene)
        
    except Exception as e:
        print(f"Error in undo handler: {e}")
        import traceback
        traceback.print_exc() 