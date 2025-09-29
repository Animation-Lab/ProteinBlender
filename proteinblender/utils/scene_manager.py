import json
import bpy
from typing import Dict, Optional, List, Set
from ..core.molecule_manager import MoleculeManager, MoleculeWrapper

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
        self._create_domains_for_each_chain(molecule.identifier)
        # Add to UI list
        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = molecule.identifier
        item.object_ptr = molecule.object
        scene.molecule_list_index = len(scene.molecule_list_items) - 1
        # Set as active molecule
        self.active_molecule = molecule.identifier
        # Build outliner hierarchy
        build_outliner_hierarchy(bpy.context)
        
        # Deselect all outliner items after import for clean state
        for item in scene.outliner_items:
            item.is_selected = False
        
        # Also deselect all objects in the 3D viewport
        bpy.ops.object.select_all(action='DESELECT')
        
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
        except Exception:
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
            id: MoleculeWrapper.from_json(molecule_json) 
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
        except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
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


def build_outliner_hierarchy(context=None):
    """Build or rebuild the outliner hierarchy from current molecule data"""
    if context is None:
        context = bpy.context
    
    scene = context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    
    # Store existing groups and their memberships before clearing
    existing_groups = {}
    item_memberships = {}  # Store which groups each item belongs to
    item_selection_states = {}  # Store selection states for all items
    item_expansion_states = {}  # Store expansion states for all items
    
    # Temporarily disable selection sync during rebuild
    from ..handlers import selection_sync
    old_depth = selection_sync._selection_update_depth
    selection_sync._selection_update_depth = 999  # High value to prevent any updates during rebuild
    
    # Get all valid molecule and domain IDs currently in the scene
    valid_item_ids = set()
    for molecule_id in scene_manager.molecules.keys():
        valid_item_ids.add(molecule_id)
        molecule = scene_manager.molecules.get(molecule_id)
        if hasattr(molecule, 'domains'):
            valid_item_ids.update(molecule.domains.keys())

        # Also add chain IDs which are used in outliner items
        # Chain IDs have format: "{molecule_id}_chain_{chain_id}"
        mol_object = None
        if hasattr(molecule, 'object') and molecule.object:
            mol_object = molecule.object
        elif hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
            mol_object = molecule.molecule.object

        if mol_object and "chain_id" in mol_object.data.attributes:
            chain_attr = mol_object.data.attributes["chain_id"]
            chain_ids = set(value.value for value in chain_attr.data)
            for chain_id in chain_ids:
                valid_item_ids.add(f"{molecule_id}_chain_{chain_id}")

    for item in scene.outliner_items:
        # Store selection state for all items
        if item.item_id and item.item_id != "puppets_separator":
            item_selection_states[item.item_id] = item.is_selected
            item_expansion_states[item.item_id] = item.is_expanded

        if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
            # Check if puppet has any valid members
            member_ids = item.puppet_memberships.split(',') if item.puppet_memberships else []
            valid_members = [m for m in member_ids if m in valid_item_ids]

            if valid_members:
                # Filter out any proteins from the member list - puppets should only contain chains and domains
                filtered_members = []
                for member_id in valid_members:
                    # Check if this member is a protein by looking at existing items
                    is_protein = False
                    for check_item in scene.outliner_items:
                        if check_item.item_id == member_id and check_item.item_type == 'PROTEIN':
                            is_protein = True
                            break
                    if not is_protein:
                        filtered_members.append(member_id)

                # Only store puppets that have at least one valid non-protein member
                if filtered_members:
                    existing_groups[item.item_id] = {
                        'name': item.name,
                        'is_expanded': item.is_expanded,
                        'is_selected': item.is_selected,
                        'controller_object_name': item.controller_object_name,
                        'members': filtered_members  # Store only chains and domains
                    }
            else:
                # Puppet has no valid members - clean up its controller object
                if item.controller_object_name:
                    controller_obj = bpy.data.objects.get(item.controller_object_name)
                    if controller_obj:
                        # First unlink from all collections
                        for collection in controller_obj.users_collection:
                            collection.objects.unlink(controller_obj)
                        # Then remove the object
                        bpy.data.objects.remove(controller_obj, do_unlink=True)
        elif item.puppet_memberships:
            # Store item's group memberships
            item_memberships[item.item_id] = item.puppet_memberships
    
    # Clear existing outliner items
    scene.outliner_items.clear()
    
    # Import counter for unique IDs
    
    # Add molecules
    for molecule_id, molecule in scene_manager.molecules.items():
        # Add protein item
        protein_item = scene.outliner_items.add()
        protein_item.item_type = 'PROTEIN'
        protein_item.item_id = molecule_id
        protein_item.parent_id = ""
        protein_item.name = getattr(molecule, 'name', molecule.identifier)
        # Get the object - it might be molecule.object or molecule.molecule.object
        mol_object = None
        if hasattr(molecule, 'object') and molecule.object:
            mol_object = molecule.object
        elif hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
            mol_object = molecule.molecule.object
        
        protein_item.object_name = mol_object.name if mol_object else ""
        protein_item.indent_level = 0
        protein_item.icon = 'MESH_DATA'
        protein_item.is_visible = not mol_object.hide_get(view_layer=context.view_layer) if mol_object else True
        
        # Restore selection and expansion states
        if molecule_id in item_selection_states:
            protein_item.is_selected = item_selection_states[molecule_id]
        if molecule_id in item_expansion_states:
            protein_item.is_expanded = item_expansion_states[molecule_id]
        
        # Get chains from the molecule
        if mol_object and "chain_id" in mol_object.data.attributes:
            chain_attr = mol_object.data.attributes["chain_id"]
            chain_ids = sorted({value.value for value in chain_attr.data})
            
            # Debug output (commented out for production)
            # print(f"Molecule {getattr(molecule, 'name', molecule.identifier)} has chains: {chain_ids}")
            # print(f"Chain mapping: {getattr(molecule, 'chain_mapping', getattr(molecule, 'idx_to_label_asym_id_map', 'None'))}")
            
            # Add chain items
            for chain_id in chain_ids:
                chain_item = scene.outliner_items.add()
                chain_item.item_type = 'CHAIN'
                chain_item.item_id = f"{molecule_id}_chain_{chain_id}"
                chain_item.parent_id = molecule_id
                
                # Use chain mapping if available
                # First try auth_chain_id_map (has the actual author chain IDs like 'S', 'T')
                # Then fall back to chain_mapping or idx_to_label_asym_id_map
                chain_name = None
                
                if hasattr(molecule, 'auth_chain_id_map') and molecule.auth_chain_id_map:
                    chain_name = molecule.auth_chain_id_map.get(chain_id)
                
                if not chain_name and hasattr(molecule, 'chain_mapping') and molecule.chain_mapping:
                    chain_name = molecule.chain_mapping.get(chain_id)
                
                if not chain_name and hasattr(molecule, 'idx_to_label_asym_id_map') and molecule.idx_to_label_asym_id_map:
                    chain_name = molecule.idx_to_label_asym_id_map.get(chain_id)
                
                # Final fallback to sequential alphabet
                if not chain_name:
                    chain_name = chr(65 + chain_id) if chain_id < 26 else f"Chain{chain_id}"
                
                chain_item.name = f"Chain {chain_name}"
                chain_item.chain_id = str(chain_id)
                chain_item.indent_level = 1
                chain_item.icon = 'LINKED'
                
                # Restore selection and expansion states
                if chain_item.item_id in item_selection_states:
                    chain_item.is_selected = item_selection_states[chain_item.item_id]
                if chain_item.item_id in item_expansion_states:
                    chain_item.is_expanded = item_expansion_states[chain_item.item_id]
                
                # Get chain residue ranges
                if hasattr(molecule, 'chain_residue_ranges') and molecule.chain_residue_ranges:
                    # chain_residue_ranges is keyed by label_asym_id (like 'A', 'B', etc)
                    # Try multiple ways to find the correct chain range
                    
                    # First, try using idx_to_label_asym_id_map
                    if hasattr(molecule, 'idx_to_label_asym_id_map') and chain_id in molecule.idx_to_label_asym_id_map:
                        label_asym_id = molecule.idx_to_label_asym_id_map[chain_id]
                        if label_asym_id in molecule.chain_residue_ranges:
                            start, end = molecule.chain_residue_ranges[label_asym_id]
                            chain_item.chain_start = start
                            chain_item.chain_end = end
                    # Second, try auth_chain_id_map
                    elif chain_mapping and chain_id in chain_mapping:
                        label_asym_id = chain_mapping[chain_id]
                        if label_asym_id in molecule.chain_residue_ranges:
                            start, end = molecule.chain_residue_ranges[label_asym_id]
                            chain_item.chain_start = start
                            chain_item.chain_end = end
                    # Third, try using chain_name directly if it matches
                    elif chain_name in molecule.chain_residue_ranges:
                        start, end = molecule.chain_residue_ranges[chain_name]
                        chain_item.chain_start = start
                        chain_item.chain_end = end
                    # Fourth, try converting chain_id to string
                    elif str(chain_id) in molecule.chain_residue_ranges:
                        start, end = molecule.chain_residue_ranges[str(chain_id)]
                        chain_item.chain_start = start
                        chain_item.chain_end = end
                    
                    # Debug output if we couldn't find ranges
                    if chain_item.chain_start == 1 and chain_item.chain_end == 1:
                        print(f"Warning: Could not find residue range for chain {chain_name} (id={chain_id})")
                        print(f"  Available keys in chain_residue_ranges: {list(molecule.chain_residue_ranges.keys())}")
                        if hasattr(molecule, 'idx_to_label_asym_id_map'):
                            print(f"  idx_to_label_asym_id_map: {molecule.idx_to_label_asym_id_map}")
                
                # Debug output (commented out for production)
                # print(f"\nProcessing chain {chain_name} (id={chain_id}):")
                # print(f"Available domains in molecule: {list(molecule.domains.keys())}")
                
                # Collect domains for this chain
                chain_domains = []
                for domain_id, domain in molecule.domains.items():
                    # Skip chain-level copies - they should be shown as separate chains
                    if hasattr(domain, 'is_copy') and domain.is_copy:
                        # Check if this is a full chain copy (covers entire chain range)
                        if hasattr(molecule, 'chain_residue_ranges'):
                            # Get the correct chain key for looking up ranges
                            domain_chain = domain.chain_id
                            chain_key = None
                            
                            # Try to map to the correct key in chain_residue_ranges
                            if hasattr(molecule, 'idx_to_label_asym_id_map'):
                                # If domain.chain_id is numeric, map it
                                if str(domain_chain).isdigit():
                                    chain_key = molecule.idx_to_label_asym_id_map.get(int(domain_chain))
                                else:
                                    # It's already an author chain ID
                                    chain_key = domain_chain
                            
                            if not chain_key:
                                chain_key = str(domain_chain)
                            
                            if chain_key in molecule.chain_residue_ranges:
                                min_res, max_res = molecule.chain_residue_ranges[chain_key]
                                if domain.start == min_res and domain.end == max_res:
                                    # This is a full chain copy, skip it here (will be added as separate chain)
                                    continue
                    
                    # Check if domain belongs to this chain
                    domain_chain_id = getattr(domain, 'chain_id', None)
                    
                    # If no chain_id on domain, try to extract from name
                    if domain_chain_id is None and hasattr(domain, 'name'):
                        # Try to extract chain from domain name pattern like "3b75_001_0_1_197_Chain_A"
                        import re
                        match = re.search(r'Chain_([A-Z])', domain.name)
                        if match:
                            domain_chain_id = match.group(1)
                        
                        # Also try to extract chain index from pattern like "3b75_001_0_1_197"
                        if domain_chain_id is None:
                            match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                            if match2:
                                domain_chain_id = int(match2.group(1))
                    
                    if domain_chain_id is not None:
                        # Check if this domain belongs to the current chain
                        domain_chain_str = str(domain_chain_id)
                        chain_str = str(chain_id)
                        
                        match_found = (domain_chain_str == chain_str or 
                                     domain_chain_str == chain_name or 
                                     (isinstance(domain_chain_id, int) and domain_chain_id == chain_id))
                        
                        if match_found:
                            chain_domains.append((domain_id, domain))
                
                # Mark if this chain has domains (for UI purposes)
                if len(chain_domains) > 1:
                    chain_item.has_domains = True
                elif len(chain_domains) == 1:
                    # If there's exactly one domain for this chain, the chain item should reference that domain's object
                    domain_id, domain = chain_domains[0]
                    if domain.object:
                        chain_item.object_name = domain.object.name
                    
                # Only add domains if there's more than one for this chain
                # OR if the domain doesn't span the entire chain
                # AND only if the chain is expanded
                if len(chain_domains) > 1 and chain_item.is_expanded:
                    for domain_id, domain in chain_domains:
                        domain_item = scene.outliner_items.add()
                        domain_item.item_type = 'DOMAIN'
                        # Domain ID already includes molecule ID, so use it directly
                        domain_item.item_id = domain_id
                        domain_item.parent_id = chain_item.item_id
                        
                        # Extract meaningful domain name
                        # Use the domain's actual name property first
                        domain_display_name = domain.name
                        
                        # For copies, the name already includes the copy number (e.g., "Chain A 1")
                        # For non-copies, show the residue range if available
                        if not (hasattr(domain, 'is_copy') and domain.is_copy):
                            if hasattr(domain, 'start') and hasattr(domain, 'end'):
                                # Only override with residue range for non-copies
                                # Check if name ends with a number (copy format)
                                import re
                                if not re.search(r'\s+\d+$', domain.name):
                                    domain_display_name = f"Residues {domain.start}-{domain.end}"
                        
                        domain_item.name = domain_display_name
                        domain_item.object_name = domain.object.name if domain.object else ""
                        domain_item.domain_start = getattr(domain, 'start', 0)
                        domain_item.domain_end = getattr(domain, 'end', 0)
                        domain_item.indent_level = 2
                        domain_item.icon = 'GROUP_VERTEX'
                        domain_item.is_visible = not domain.object.hide_get(view_layer=context.view_layer) if domain.object else True
                        
                        # Restore selection state
                        if domain_id in item_selection_states:
                            domain_item.is_selected = item_selection_states[domain_id]
            
            # After processing all regular chains, add chain copies as separate chain items
            # These are full-chain domain copies that should appear at the chain level
            for domain_id, domain in molecule.domains.items():
                if hasattr(domain, 'is_copy') and domain.is_copy:
                    # Check if this is a full chain copy
                    if hasattr(molecule, 'chain_residue_ranges'):
                        # Get the correct chain key for looking up ranges
                        domain_chain = domain.chain_id
                        chain_key = None
                        
                        # Try to map to the correct key in chain_residue_ranges
                        if hasattr(molecule, 'idx_to_label_asym_id_map'):
                            # If domain.chain_id is numeric, map it
                            if str(domain_chain).isdigit():
                                chain_key = molecule.idx_to_label_asym_id_map.get(int(domain_chain))
                            else:
                                # It's already an author chain ID
                                chain_key = domain_chain
                        
                        if not chain_key:
                            chain_key = str(domain_chain)
                        
                        if chain_key in molecule.chain_residue_ranges:
                            min_res, max_res = molecule.chain_residue_ranges[chain_key]
                            if domain.start == min_res and domain.end == max_res:
                                # This is a full chain copy - add it as a chain-level item
                                chain_copy_item = scene.outliner_items.add()
                                chain_copy_item.item_type = 'CHAIN'
                                chain_copy_item.item_id = domain_id  # Use domain_id as the item_id
                                chain_copy_item.parent_id = molecule_id
                                chain_copy_item.name = domain.name  # e.g., "1 Chain A"
                                chain_copy_item.chain_id = str(domain.chain_id)
                                chain_copy_item.indent_level = 1
                                chain_copy_item.icon = 'LINKED'
                                chain_copy_item.object_name = domain.object.name if domain.object else ""
                                chain_copy_item.is_visible = not domain.object.hide_get(view_layer=context.view_layer) if domain.object else True
                                chain_copy_item.chain_start = domain.start
                                chain_copy_item.chain_end = domain.end
                                
                                # Restore selection and expansion states
                                if domain_id in item_selection_states:
                                    chain_copy_item.is_selected = item_selection_states[domain_id]
                                if domain_id in item_expansion_states:
                                    chain_copy_item.is_expanded = item_expansion_states[domain_id]
    
    # Restore group memberships to items
    # IMPORTANT: Only restore memberships for chains and molecules, not domains
    # Domains should only appear in groups as children of their parent chains
    for item in scene.outliner_items:
        if item.item_id in item_memberships:
            # Only restore group memberships for non-domain items
            if item.item_type != 'DOMAIN':
                item.puppet_memberships = item_memberships[item.item_id]
    
    # Add existing groups at the end
    # First, create a mapping of item_id to item for easy lookup
    item_map = {}
    existing_ref_ids = set()  # Track existing reference IDs to avoid duplicates
    for item in scene.outliner_items:
        item_map[item.item_id] = item
        # If this is a reference item, add it to our tracking set
        if "_ref_" in item.item_id:
            existing_ref_ids.add(item.item_id)
    
    # Add separator if there are groups
    if existing_groups:
        # Add a visual separator (could be a label or empty item)
        separator = scene.outliner_items.add()
        separator.item_type = 'PUPPET'  # Use PUPPET type but make it non-interactive
        separator.item_id = "puppets_separator"
        separator.name = "─── Puppets ───"
        separator.parent_id = ""
        separator.indent_level = 0
        separator.icon = 'NONE'
        separator.is_expanded = False
        separator.is_visible = True
    
    # Process each existing group
    for group_id, group_info in existing_groups.items():
        # Add group item
        group_item = scene.outliner_items.add()
        group_item.item_type = 'PUPPET'
        group_item.item_id = group_id
        group_item.parent_id = ""
        group_item.name = group_info['name']
        group_item.indent_level = 0
        group_item.icon = 'GROUP'
        group_item.is_expanded = group_info.get('is_expanded', True)
        group_item.is_selected = group_info.get('is_selected', False)
        group_item.controller_object_name = group_info.get('controller_object_name', '')  # RESTORE THE CONTROLLER!
        group_item.object_name = group_info.get('controller_object_name', '')  # Also set object_name for selection sync
        
        # Store all members (including domains) in the group
        # We'll handle display logic when adding references
        all_members = group_info.get('members', [])
        group_item.puppet_memberships = ','.join(all_members)
        
        # Add group members as references (not moving them from original location)
        # Always build complete hierarchy - UI filtering will handle visibility
        # Helper function to add a reference item with its children
        def add_reference_with_children(member_id, parent_ref_id, indent_offset=0):
            if member_id not in item_map:
                return

            original_item = item_map[member_id]

            # Create a reference item
            ref_item = scene.outliner_items.add()
            ref_item.item_type = original_item.item_type
            ref_item.item_id = f"{group_id}_ref_{member_id}"  # Unique ID for the reference
            ref_item.parent_id = parent_ref_id
            # Track this reference ID to avoid duplicates
            existing_ref_ids.add(ref_item.item_id)
            ref_item.name = f"→ {original_item.name}"  # Arrow to indicate reference
            ref_item.object_name = original_item.object_name
            ref_item.indent_level = 1 + indent_offset
            ref_item.icon = original_item.icon
            ref_item.is_visible = original_item.is_visible
            ref_item.is_selected = original_item.is_selected
            # Preserve the expansion state of reference items independently
            # Check if we have a stored state for this reference item
            if ref_item.item_id in item_expansion_states:
                ref_item.is_expanded = item_expansion_states[ref_item.item_id]
            else:
                # Default to collapsed for new reference items to match original behavior
                ref_item.is_expanded = False
            ref_item.chain_id = original_item.chain_id
            ref_item.chain_start = original_item.chain_start
            ref_item.chain_end = original_item.chain_end
            ref_item.domain_start = original_item.domain_start
            ref_item.domain_end = original_item.domain_end
            ref_item.has_domains = original_item.has_domains
            # Store the original item ID for reference
            ref_item.puppet_memberships = member_id  # Store original ID

            # If this is a chain, always add its domain children (UI will filter based on expansion)
            # ONLY add domains that are group members
            if original_item.item_type == 'CHAIN':
                # Find all domains that belong to this chain
                # We need to look for original domains (not references) that belong to the original chain
                for child_item in scene.outliner_items:
                    # Skip reference items - we only want original domains
                    if "_ref_" in child_item.item_id:
                        continue

                    if (child_item.item_type == 'DOMAIN' and
                        child_item.parent_id == member_id):
                        # IMPORTANT: Only add domains that are explicitly group members
                        # Check if this domain is in the group's member list
                        if child_item.item_id in group_info.get('members', []):
                            # Check if a reference for this domain already exists
                            ref_id = f"{group_id}_ref_{child_item.item_id}"

                            if ref_id not in existing_ref_ids:
                                # Add the domain as a child of the chain reference
                                add_reference_with_children(child_item.item_id, ref_item.item_id, 1)
                                # Track that we've added this reference
                                existing_ref_ids.add(ref_id)

        # Add each member with its hierarchy
        for member_id in group_info.get('members', []):
            if member_id in item_map:
                member_item = item_map[member_id]

                # Skip proteins - they should never be puppet members
                if member_item.item_type == 'PROTEIN':
                    continue

                # For domains, check if their parent chain is also in the group
                if member_item.item_type == 'DOMAIN':
                    # Check if the parent chain is in the group
                    parent_chain_in_group = False
                    if member_item.parent_id in group_info.get('members', []):
                        parent_chain_in_group = True

                    # Only add domain as direct member if its parent chain is NOT in the group
                    # (If the chain is in the group, the domain will be added as a child of the chain)
                    if not parent_chain_in_group:
                        add_reference_with_children(member_id, group_id)
                else:
                    # Add non-domain, non-protein items (chains) directly
                    add_reference_with_children(member_id, group_id)
    
    # Update outliner display
    # Re-enable selection sync
    selection_sync._selection_update_depth = old_depth

    if context.area:
        context.area.tag_redraw()


def update_outliner_visibility(item_id, visible):
    """Update visibility for an outliner item and its corresponding objects"""
    scene = bpy.context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    view_layer = bpy.context.view_layer
    
    # Find the item
    item = None
    for outliner_item in scene.outliner_items:
        if outliner_item.item_id == item_id:
            item = outliner_item
            break
    
    if not item:
        return
    
    # Update item visibility state
    item.is_visible = visible
    
    # Update object visibility based on item type
    if item.item_type == 'PROTEIN':
        # Update protein and all its domains
        molecule = scene_manager.molecules.get(item_id)
        if molecule and molecule.object:
            molecule.object.hide_set(not visible, view_layer=view_layer)
            molecule.object.hide_render = not visible
            # Update all domains
            for domain in molecule.domains.values():
                if domain.object:
                    domain.object.hide_set(not visible, view_layer=view_layer)
                    domain.object.hide_render = not visible
                    
    elif item.item_type == 'CHAIN':
        # Update all domains belonging to this chain
        # Extract molecule_id from chain's parent
        molecule = scene_manager.molecules.get(item.parent_id)
        if molecule:
            # Extract chain identifier from item_id (format: "molecule_id_chain_X")
            chain_id_str = item.item_id.split('_chain_')[-1]
            try:
                chain_id = int(chain_id_str)
            except:
                chain_id = chain_id_str
            
            # Update visibility for all domains of this chain
            for domain_id, domain in molecule.domains.items():
                # Check if domain belongs to this chain (similar logic as in build_outliner_hierarchy)
                domain_chain_id = getattr(domain, 'chain_id', None)
                
                # Extract chain from domain name if needed
                if domain_chain_id is None and hasattr(domain, 'name'):
                    import re
                    match = re.search(r'Chain_([A-Z])', domain.name)
                    if match:
                        domain_chain_id = match.group(1)
                    elif '_' in domain.name:
                        match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                        if match2:
                            domain_chain_id = int(match2.group(1))
                
                # Check if this domain belongs to the chain
                if domain_chain_id is not None:
                    domain_chain_str = str(domain_chain_id)
                    chain_str = str(chain_id)
                    
                    if domain_chain_str == chain_str or domain_chain_id == chain_id:
                        if domain.object:
                            domain.object.hide_set(not visible, view_layer=view_layer)
                            domain.object.hide_render = not visible
                    
    elif item.item_type == 'DOMAIN':
        # Update just the domain
        if item.object_name:
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                obj.hide_set(not visible, view_layer=view_layer)
                # Also hide from render when hidden in viewport
                obj.hide_render = not visible
                
    elif item.item_type == 'PUPPET':
        # Update the puppet's controller object visibility
        if item.controller_object_name:
            controller_obj = bpy.data.objects.get(item.controller_object_name)
            if controller_obj:
                controller_obj.hide_set(not visible, view_layer=view_layer)
                controller_obj.hide_render = not visible

        # Update all items that are members of this group
        member_ids = item.puppet_memberships.split(',') if item.puppet_memberships else []
        for member_id in member_ids:
            # Find the actual member item
            for member_item in scene.outliner_items:
                if member_item.item_id == member_id:
                    update_outliner_visibility(member_id, visible)
                    break