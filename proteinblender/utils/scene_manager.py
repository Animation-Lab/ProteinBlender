"""ProteinBlender scene management.

This module provides the ProteinBlenderScene singleton class which manages
all molecule state in a Blender session. It handles:
- Molecule import and deletion
- Undo/redo state synchronization
- UI list management
- Lazy wrapper reconstruction

The scene manager uses MoleculeListItem PropertyGroups as the primary
persistent storage, with runtime MoleculeWrapper objects reconstructed
on-demand.
"""

import json
import logging
import re
import bpy
from bpy.app.handlers import persistent
from typing import Dict, Optional, List, Set
from ..core.molecule_manager import MoleculeManager, MoleculeWrapper
from .blender_utils import is_object_valid
from .chain_utils import chain_match_tokens

logger = logging.getLogger(__name__)


class ProteinBlenderScene:
    _instance = None

    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton instance for a fresh start.
        
        This should be called when a new file is loaded/created to ensure
        clean state and prevent stale references to deleted objects.
        
        Following Blender addon best practices:
        - Clean up all resources before resetting
        - Handle errors gracefully (objects may already be deleted by Blender)
        - Ensure no memory leaks from stale references
        - Always reset even if cleanup fails (fail-safe)
        """
        if cls._instance is not None:
            # Clean up any resources before resetting
            try:
                # Clear all molecules (this will trigger cleanup in MoleculeManager)
                # Use list() to create a copy since we're modifying during iteration
                molecule_ids = list(cls._instance.molecules.keys())
                for molecule_id in molecule_ids:
                    try:
                        # Only try to remove if molecule still exists
                        # (objects may already be deleted by Blender on File->New)
                        if molecule_id in cls._instance.molecules:
                            cls._instance.molecule_manager.remove_molecule(molecule_id)
                    except (ReferenceError, KeyError, AttributeError):
                        # Expected errors when objects are already deleted
                        # Log at debug level, not warning
                        pass
                    except Exception as e:
                        # Unexpected errors - log but don't fail
                        print(f"ProteinBlender: Warning cleaning up molecule {molecule_id}: {e}")
                
                # Clear saved states
                
                # Reset instance variables
                cls._instance.active_molecule = None
                cls._instance.display_settings = {}
            except Exception as e:
                # Even if cleanup fails, reset the instance to prevent corruption
                print(f"ProteinBlender: Warning during scene manager cleanup: {e}")
            finally:
                # Always reset the instance (fail-safe)
                cls._instance = None

    def __init__(self):
        # Initialize the singleton instance
        self.molecule_manager = MoleculeManager()
        self.active_molecule: Optional[str] = None
        self.display_settings = {}

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

    def refresh_domain_refs_before_destructive_op(self, molecule_id):
        """Re-bind a molecule's domain object/node-group references to live data.

        Called ahead of destructive operations so they never act through a stale
        reference left behind by an undo/redo.

        This used to also build a MoleculeState snapshot into self._saved_states.
        Nothing ever read that dict and nothing ever called MoleculeState.
        restore_to_scene, so every delete/split/merge walked the molecule's
        domains copying matrices and materials, then threw the result away -
        undo/redo is handled by sync_molecule_list_after_undo instead. The
        snapshot is gone; the reference refresh it was wrapped around is real and
        is why this method still exists.
        """
        if molecule_id in self.molecules:
            try:
                self._refresh_domain_object_references(self.molecules[molecule_id])
            except Exception as e:
                logger.warning(
                    f"Failed to refresh domain references for {molecule_id}: {e}")

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

            from .chain_utils import normalize_domain_residue_range
            current_min_res, max_res = normalize_domain_residue_range(
                (min_res, max_res))
            
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
        # Set protein pivot to center of mass and move to world origin
        print("Setting protein pivot to center of mass...")
        molecule.set_protein_pivot_to_center_of_mass(bpy.context)

        # Create domains for each chain
        self._create_domains_for_each_chain(molecule.identifier)
        # Add to UI list
        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = molecule.identifier
        item.object_ptr = molecule.object
        # Store object name and chain data for reference healing after undo/redo
        if molecule.object:
            item.object_name = molecule.object.name
        item.sync_from_wrapper(molecule)
        scene.molecule_list_index = len(scene.molecule_list_items) - 1
        # Auto-domain creation ran BEFORE the list item existed, so each
        # _create_domain_with_params call mirrored into a None list item
        # (no-op). Now that the item exists, mirror once explicitly so the
        # auto-created chain domains land in the persistent PG (Bug B).
        if hasattr(molecule, '_mirror_domains_to_property_group'):
            molecule._mirror_domains_to_property_group()
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

    def _finalize_dna_molecule(self, molecule):
        """Finalize a DNA/RNA molecule: add to UI list, build outliner. No domain creation."""
        molecule.set_protein_pivot_to_center_of_mass(bpy.context)

        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = molecule.identifier
        item.object_ptr = molecule.object
        if molecule.object:
            item.object_name = molecule.object.name
        item.sync_from_wrapper(molecule)
        scene.molecule_list_index = len(scene.molecule_list_items) - 1
        self.active_molecule = molecule.identifier

        build_outliner_hierarchy(bpy.context)

        for oitem in scene.outliner_items:
            oitem.is_selected = False
        bpy.ops.object.select_all(action='DESELECT')
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
            print(f"Error in create_molecule_from_id: {e}")
            import traceback
            traceback.print_exc()
            return False



    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
        # Capture state before deletion
        self.refresh_domain_refs_before_destructive_op(identifier)

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
                scene.edit_molecule_identifier = ""

            # Deleting a molecule can leave puppets whose members all belonged
            # to it, plus pose-library entries that still point at those
            # puppets. The outliner rebuild below drops the orphaned puppet
            # ROWS but not their poses, so the Protein Pose Library kept listing
            # poses for puppets/proteins that no longer exist. Clean them up
            # here, while the puppet rows still exist to be resolved.
            try:
                self._cleanup_orphaned_puppets(scene)
            except Exception as e:
                print(f"delete_molecule: orphaned-puppet cleanup failed: {e}")

            # Rebuild the outliner so chain/domain rows for the deleted
            # molecule are dropped immediately. Without this the outliner
            # carries orphan rows until the next sync (e.g. a reload), which
            # showed up in scenario 07 of the save/load stress test.
            try:
                build_outliner_hierarchy(bpy.context)
            except Exception as e:
                print(f"delete_molecule: outliner rebuild failed: {e}")

            # Refresh UI
            self._refresh_ui()

            return True
        return False

    def _cleanup_orphaned_puppets(self, scene):
        """Delete puppets left with no surviving members, and clear the pose-
        library entries that only referenced them.

        A puppet is orphaned when none of its members resolve to a live object
        (their molecule was deleted). We route each through the normal
        ``delete_puppet`` operator so the controller Empty, member linkers and
        pose transforms are all torn down the same way a manual delete would,
        then prune any pose that is now empty. Puppets that still span a
        surviving molecule are left untouched.
        """
        from ..utils.chain_utils import get_puppet_member_objects

        orphaned = []
        for item in scene.outliner_items:
            if item.item_type == 'PUPPET' and item.item_id != 'puppets_separator':
                if not get_puppet_member_objects(scene, self, item):
                    orphaned.append(item.item_id)

        if not orphaned:
            return

        for pid in orphaned:
            try:
                bpy.ops.proteinblender.delete_puppet('EXEC_DEFAULT', puppet_id=pid)
            except Exception as e:
                print(f"_cleanup_orphaned_puppets: delete_puppet({pid}) failed: {e}")
                try:
                    from ..panels.group_maker_panel import _strip_puppet_from_pose_library
                    _strip_puppet_from_pose_library(scene, pid)
                except Exception:
                    pass

        # Prune poses that only referenced the orphaned puppets and are now
        # empty, so the library reflects reality after the model is gone.
        if hasattr(scene, 'pose_library'):
            for i in range(len(scene.pose_library) - 1, -1, -1):
                pose = scene.pose_library[i]
                if len(pose.transforms) == 0 and not pose.puppet_ids:
                    scene.pose_library.remove(i)
            if hasattr(scene, 'active_pose_index') and \
                    scene.active_pose_index >= len(scene.pose_library):
                scene.active_pose_index = max(0, len(scene.pose_library) - 1)

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


def _is_molecule_valid(molecule):
    """Check if molecule wrapper has a valid object reference.

    Uses the centralized is_object_valid from blender_utils.
    Also attempts to heal the reference if possible.

    Catches LinkedObjectError / ReferenceError / etc. — after `ed.undo`
    of an import the wrapper's stored UUID may no longer resolve, and
    those exceptions need to be treated as "invalid" rather than fatal.
    """
    if not molecule:
        return False
    try:
        # Use wrapper's is_valid method if available (new approach)
        if hasattr(molecule, 'is_valid'):
            return molecule.is_valid()
        # Fallback for compatibility
        return is_object_valid(molecule.object)
    except Exception:
        return False


def _has_invalid_domains(molecule):
    """Check if any domains have invalid object references"""
    try:
        # First check if we can access the molecule at all
        if not _is_molecule_valid(molecule):
            return True

        for domain in molecule.domains.values():
            if not is_object_valid(domain.object):
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


def _snapshot_list_item(item):
    """Capture every persistent field of a MoleculeListItem so the list can
    be cleared and rebuilt without losing state.

    Historically this function only preserved keyframes and poses, which
    meant every panel-draw-after-load silently wiped object_name, style,
    chain mappings, residue ranges, and the persisted domains collection.
    See tests/COVERAGE.md ("Save/load wiped every persisted field") for the
    regression history; guarded by roundtrip/test_saveload.py.
    """
    snap = {
        # Top-level scalar persistence — without these, loading a saved file
        # leaves the molecule list visibly broken (no chain ranges, default
        # style, no object reference healing).
        'object_name': item.object_name,
        'style': item.style,
        'chain_mapping_json': item.chain_mapping_json,
        'chain_residue_ranges_json': item.chain_residue_ranges_json,
        # Per-protein membrane force field — without snapshotting, undo /
        # rebuild paths silently reset to FloatProperty defaults and the
        # protein's FF setup gets wiped.
        'force_field_enabled': bool(getattr(item, 'force_field_enabled', False)),
        'force_field_spacing': float(getattr(item, 'force_field_spacing', 1.0)),
        # Persisted domain definitions (the runtime wrapper has more state,
        # but this collection is what survives a .blend round-trip).
        'domains': [
            {
                'is_expanded': getattr(d, 'is_expanded', False),
                'domain_id': getattr(d, 'domain_id', ''),
                'chain_id': d.chain_id,
                'start': d.start,
                'end': d.end,
                'name': d.name,
                # Object PointerProperty is restored by name lookup below.
                'object_name': (
                    d.object.name if d.object
                    else getattr(d, 'object_name', '')
                ),
            }
            for d in item.domains
        ],
        'keyframes': [
            {'name': kf.name, 'frame': kf.frame} for kf in item.keyframes
        ],
        'active_keyframe_index': item.active_keyframe_index,
        'active_pose_index': item.active_pose_index,
        'poses': [
            {
                'name': p.name,
                'has_protein_transform': p.has_protein_transform,
                'protein_location': list(p.protein_location),
                'protein_rotation': list(p.protein_rotation),
                'protein_scale': list(p.protein_scale),
                'domain_transforms': [
                    {
                        'domain_id': dt.domain_id,
                        'location': list(dt.location),
                        'rotation': list(dt.rotation),
                        'scale': list(dt.scale),
                    }
                    for dt in p.domain_transforms
                ],
                'group_transforms': [
                    {
                        'group_id': gt.group_id,
                        'relative_location': list(gt.relative_location),
                        'relative_rotation': list(gt.relative_rotation),
                        'relative_scale': list(gt.relative_scale),
                    }
                    for gt in getattr(p, 'group_transforms', [])
                ],
            }
            for p in item.poses
        ],
    }
    return snap


def _restore_list_item(item, snap):
    """Inverse of _snapshot_list_item — write captured state back onto a
    freshly-added MoleculeListItem."""
    if not snap:
        return

    # Top-level scalars
    item.object_name = snap.get('object_name', '')
    style = snap.get('style')
    if style:
        try:
            item.style = style
        except (TypeError, ValueError):
            # Style enum may have changed across versions — fall back to default.
            pass
    item.chain_mapping_json = snap.get('chain_mapping_json', '{}')
    item.chain_residue_ranges_json = snap.get('chain_residue_ranges_json', '{}')

    # Force-field state — write the spacing first so the update callback
    # that fires on force_field_enabled = True applies the right value
    # against every membrane in one shot.
    if 'force_field_spacing' in snap:
        try:
            item.force_field_spacing = float(snap['force_field_spacing'])
        except (TypeError, ValueError):
            pass
    if 'force_field_enabled' in snap:
        try:
            item.force_field_enabled = bool(snap['force_field_enabled'])
        except (TypeError, ValueError):
            pass

    # Domains collection (Domain PropertyGroup)
    for d_data in snap.get('domains', []):
        new_d = item.domains.add()
        if hasattr(new_d, 'domain_id'):
            new_d.domain_id = d_data.get('domain_id', '')
        new_d.chain_id = d_data.get('chain_id', '')
        new_d.start = d_data.get('start', 1)
        new_d.end = d_data.get('end', 1)
        new_d.name = d_data.get('name', '')
        if hasattr(new_d, 'is_expanded'):
            new_d.is_expanded = d_data.get('is_expanded', False)
        obj_name = d_data.get('object_name')
        if hasattr(new_d, 'object_name'):
            new_d.object_name = obj_name or ''
        if obj_name and obj_name in bpy.data.objects:
            new_d.object = bpy.data.objects[obj_name]

    # Keyframes
    for kf_data in snap.get('keyframes', []):
        new_kf = item.keyframes.add()
        new_kf.name = kf_data.get('name', '')
        new_kf.frame = kf_data.get('frame', 0)
    item.active_keyframe_index = snap.get('active_keyframe_index', 0)

    # Poses
    for pose_data in snap.get('poses', []):
        new_pose = item.poses.add()
        new_pose.name = pose_data.get('name', '')
        new_pose.has_protein_transform = pose_data.get('has_protein_transform', False)
        new_pose.protein_location = pose_data.get('protein_location', (0, 0, 0))
        new_pose.protein_rotation = pose_data.get('protein_rotation', (0, 0, 0))
        new_pose.protein_scale = pose_data.get('protein_scale', (1, 1, 1))
        for dt_data in pose_data.get('domain_transforms', []):
            new_dt = new_pose.domain_transforms.add()
            new_dt.domain_id = dt_data.get('domain_id', '')
            new_dt.location = dt_data.get('location', (0, 0, 0))
            new_dt.rotation = dt_data.get('rotation', (0, 0, 0))
            new_dt.scale = dt_data.get('scale', (1, 1, 1))
        for gt_data in pose_data.get('group_transforms', []):
            new_gt = new_pose.group_transforms.add()
            new_gt.group_id = gt_data.get('group_id', '')
            new_gt.relative_location = gt_data.get('relative_location', (0, 0, 0))
            new_gt.relative_rotation = gt_data.get('relative_rotation', (0, 0, 0))
            new_gt.relative_scale = gt_data.get('relative_scale', (1, 1, 1))
    item.active_pose_index = snap.get('active_pose_index', 0)


def _refresh_molecule_ui(scene_manager, scene):
    """Refresh the UI list to match the runtime wrapper dict.

    All persistent MoleculeListItem fields are snapshotted up-front, the
    list is then cleared and rebuilt one item per wrapper, and finally each
    snapshot is restored. New molecules (no prior snapshot) get just the
    bare identifier + object_ptr — `sync_from_wrapper` then fills in the
    rest from the wrapper itself.
    """
    # 1. Snapshot every existing list item by identifier.
    snapshots = {
        item.identifier: _snapshot_list_item(item)
        for item in scene.molecule_list_items
        if item.identifier
    }

    # 2. Clear and rebuild the list from the wrapper dict.
    scene.molecule_list_items.clear()

    for identifier, molecule in scene_manager.molecules.items():
        # Heal the wrapper's object pointer if it became stale.
        if not is_object_valid(molecule.object):
            name = getattr(molecule, 'object_name', '')
            if name and name in bpy.data.objects:
                molecule.object = bpy.data.objects[name]
                if hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                    molecule.molecule.object = molecule.object

        if not is_object_valid(molecule.object):
            # Wrapper has no recoverable object — skip rather than create a
            # broken list entry.
            continue

        # Heal each domain's references too.
        for domain in molecule.domains.values():
            if not is_object_valid(domain.object):
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

        snap = snapshots.get(identifier)
        if snap is not None:
            # 3a. Restore every persistent field from the snapshot.
            _restore_list_item(item, snap)
        else:
            # 3b. New molecule (e.g. orphan adoption) — pull what we can
            # from the runtime wrapper. sync_from_wrapper writes object_name,
            # chain_mapping_json, chain_residue_ranges_json.
            try:
                item.object_name = molecule.object.name
            except (ReferenceError, AttributeError):
                pass
            if hasattr(item, 'sync_from_wrapper'):
                try:
                    item.sync_from_wrapper(molecule)
                except Exception as e:
                    print(f"sync_from_wrapper failed for {identifier}: {e}")

    # Update active molecule
    if scene_manager.active_molecule not in scene_manager.molecules:
        scene_manager.active_molecule = next(iter(scene_manager.molecules), None)

    # Force UI refresh
    scene_manager._refresh_ui()


def _refresh_object_references_only(scene_manager, scene):
    """Refresh object references without rebuilding the entire UI list"""
    for identifier, molecule in scene_manager.molecules.items():
        # Refresh molecule object reference
        if not is_object_valid(molecule.object):
            name = getattr(molecule, 'object_name', '')
            if name and name in bpy.data.objects:
                molecule.object = bpy.data.objects[name]
                if hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                    molecule.molecule.object = molecule.object
        
        # Refresh domain object references
        for domain in molecule.domains.values():
            if not is_object_valid(domain.object):
                name = getattr(domain, 'object_name', '')
                if name and name in bpy.data.objects:
                    domain.object = bpy.data.objects[name]
            if not domain.node_group:
                ng_name = getattr(domain, 'node_group_name', '')
                if ng_name and ng_name in bpy.data.node_groups:
                    domain.node_group = bpy.data.node_groups[ng_name]
    
    # Force UI refresh without rebuilding
    scene_manager._refresh_ui()


def _is_molecular_nodes_protein(obj):
    """Check if object is a MolecularNodes protein"""
    try:
        # Check for MolecularNodes modifier
        if not obj.modifiers.get("MolecularNodes"):
            return False

        # Check for protein-specific attributes
        if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
            return False

        # Proteins have chain_id and res_id attributes
        attrs = obj.data.attributes
        return ("chain_id" in attrs and "res_id" in attrs)
    except (AttributeError, ReferenceError):
        return False


def _extract_molecule_id_from_object(obj):
    """Extract molecule identifier from MolecularNodes object name"""
    try:
        # MolecularNodes objects are named like "3b75", "3b75_001", "4hhb", etc.
        # Remove Blender's duplicate suffixes (.001, .002, etc.)
        base_name = obj.name.split('.')[0]
        return base_name
    except (AttributeError, ReferenceError):
        return None


def _recreate_molecule_wrapper_from_object(molecule_id, obj):
    """Recreate MoleculeWrapper from existing Blender object"""
    try:
        from ..core.molecule_wrapper import MoleculeWrapper
        import biotite.structure as struc
        import numpy as np

        # Create a minimal mock Molecule object that wraps the existing Blender object
        # We can't use the real Molecule class because it requires a file path
        class MockMolecule:
            """Minimal mock of MolecularNodes Molecule for wrapping existing objects"""
            def __init__(self, blender_obj):
                self.object = blender_obj
                # Extract array data from object attributes if available
                self.array = self._extract_array_from_object(blender_obj)

            def _extract_array_from_object(self, obj):
                """Extract biotite array from Blender object attributes"""
                try:
                    # Get mesh data
                    if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                        return None

                    attrs = obj.data.attributes
                    num_atoms = len(obj.data.vertices)

                    # Create a simple AtomArray from the chain_id and res_id
                    # This is a minimal array just for initialization
                    array = struc.AtomArray(num_atoms)

                    # Extract chain mapping from object custom property
                    chain_mapping = {}
                    if hasattr(obj, 'data') and hasattr(obj.data, 'get'):
                        mapping_str = obj.data.get("chain_mapping_str", "")
                        if mapping_str:
                            # Parse the mapping string: "0:A,1:B,2:C"
                            for pair in mapping_str.split(","):
                                if ":" in pair:
                                    k, v = pair.split(":")
                                    chain_mapping[int(k)] = v

                    # Try to extract chain IDs (these are numeric in Blender)
                    if "chain_id" in attrs:
                        chain_data = np.zeros(num_atoms, dtype=np.int32)
                        attrs["chain_id"].data.foreach_get("value", chain_data)

                        # Map numeric chain IDs to string labels using chain_mapping
                        if chain_mapping:
                            # Convert each numeric ID to its string label
                            chain_labels = np.array([chain_mapping.get(cid, str(cid)) for cid in chain_data])
                            array.chain_id = chain_labels
                        else:
                            # Fallback: just convert numbers to strings
                            array.chain_id = chain_data.astype(str)

                    # Try to extract residue IDs
                    if "res_id" in attrs:
                        res_data = np.zeros(num_atoms, dtype=np.int32)
                        attrs["res_id"].data.foreach_get("value", res_data)
                        array.res_id = res_data

                    return array
                except Exception as e:
                    print(f"    Warning: Could not extract array data: {e}")
                    # Return a minimal empty array as fallback
                    return struc.AtomArray(0)

        # Create mock molecule
        mock_molecule = MockMolecule(obj)

        # Wrap it with MoleculeWrapper
        wrapper = MoleculeWrapper(mock_molecule, molecule_id)
        wrapper.object_name = obj.name

        return wrapper
    except Exception as e:
        print(f"Failed to recreate wrapper for {molecule_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def _find_orphaned_protein_objects():
    """Find MolecularNodes protein objects that aren't tracked in scene_manager.
    
    Only returns truly orphaned TOP-LEVEL protein objects, not domain objects
    that are children of tracked molecules.
    """
    scene_manager = ProteinBlenderScene.get_instance()
    orphaned = []
    
    # Build a set of all tracked object names (molecules AND their domains)
    tracked_object_names = set()
    for molecule in scene_manager.molecules.values():
        if is_object_valid(molecule.object):
            tracked_object_names.add(molecule.object.name)
        for domain in molecule.domains.values():
            if is_object_valid(domain.object):
                tracked_object_names.add(domain.object.name)

    for obj in bpy.data.objects:
        # Skip if already tracked
        if obj.name in tracked_object_names:
            continue
            
        # Check if it's a MolecularNodes protein
        if not _is_molecular_nodes_protein(obj):
            continue
        
        # Skip objects that are children of other objects (likely domains)
        if obj.parent is not None:
            continue

        # Extract potential molecule ID from object name
        potential_id = _extract_molecule_id_from_object(obj)
        
        if potential_id:
            orphaned.append((potential_id, obj))

    return orphaned


# =============================================================================
# Undo/Redo Helper Functions (Simplified Approach)
# =============================================================================

def _heal_all_wrapper_references(scene_manager):
    """Heal all object references in existing wrappers.

    This is called first in the undo handler to recover references
    that may have become valid again after undo.
    """
    for molecule_id, molecule in list(scene_manager.molecules.items()):
        try:
            if hasattr(molecule, 'heal_references'):
                molecule.heal_references()
            else:
                # Fallback: manually refresh domain references
                scene_manager._refresh_domain_object_references(molecule)
        except Exception as e:
            print(f"Warning: Failed to heal references for {molecule_id}: {e}")


def _remove_invalid_wrappers(scene_manager, scene) -> List[str]:
    """Remove wrappers for molecules whose objects no longer exist.

    Returns:
        List of removed molecule IDs
    """
    removed_ids = []

    for molecule_id, molecule in list(scene_manager.molecules.items()):
        # Wrap the validity check itself so a failure on one wrapper
        # (e.g. databpy raising LinkedObjectError) doesn't kill the rest
        # of the cleanup loop and leave other stale wrappers behind.
        try:
            is_valid = _is_molecule_valid(molecule)
        except Exception:
            is_valid = False
        if not is_valid:
            removed_ids.append(molecule_id)

            # Remove from scene_manager
            if molecule_id in scene_manager.molecules:
                del scene_manager.molecules[molecule_id]
            if molecule_id in scene_manager.molecule_manager.molecules:
                del scene_manager.molecule_manager.molecules[molecule_id]

            # Do not remove the persisted PropertyGroup here. Blender may have
            # just replaced the object's RNA wrapper during undo/redo; that row
            # is the source of truth _reconstruct_wrappers_from_properties()
            # needs in the very next step. _refresh_molecule_ui() reconciles
            # genuinely deleted molecules after reconstruction has had a chance
            # to recover them.

    return removed_ids


def _restore_domains_into_wrapper(wrapper, item):
    """Rebuild a MoleculeWrapper's runtime domain dict from the persisted
    MoleculeListItem.domains collection.

    Pairs with `MoleculeWrapper._mirror_domains_to_property_group` — the
    write path mirrors runtime domains to PG, this reads them back. Without
    this, auto-domains (and any user-created domains) vanish on file load
    even though their Blender objects still exist (Bug B).
    """
    try:
        from ..core.domain import DomainDefinition
    except Exception:
        return
    if not hasattr(item, "domains") or len(item.domains) == 0:
        return
    for d_pg in item.domains:
        try:
            domain = DomainDefinition(
                d_pg.chain_id,
                int(d_pg.start),
                int(d_pg.end),
                d_pg.name or None,
            )
            domain.parent_molecule_id = wrapper.identifier
            domain_id = d_pg.domain_id or domain.domain_id
            domain.domain_id = domain_id
            # Heal the object reference: PointerProperty first, then by
            # stored name as a fallback (handles undo/redo or rename
            # scenarios).
            obj = None
            try:
                obj = d_pg.object
            except (AttributeError, ReferenceError):
                obj = None
            if obj is None and d_pg.object_name:
                obj = bpy.data.objects.get(d_pg.object_name)
            if obj is not None:
                domain.object = obj
            # Restore visual properties from the Blender object's custom
            # properties (these survive .blend save automatically).
            if obj is not None:
                if hasattr(obj, "domain_color"):
                    try:
                        domain.color = tuple(obj.domain_color)
                    except Exception:
                        pass
                if hasattr(obj, "domain_style"):
                    try:
                        domain.style = obj.domain_style
                    except Exception:
                        pass
            wrapper.domains[domain_id] = domain
        except Exception as e:
            print(f"_restore_domains_into_wrapper: failed for "
                  f"{wrapper.identifier} / {getattr(d_pg, 'domain_id', '?')}: {e}")


def _sync_existing_wrapper_domains_from_properties(scene_manager, scene):
    """Replace live domain dictionaries with Blender's undo-restored rows.

    Undo can keep the molecule object valid while replacing its domain objects
    and CollectionProperty contents. In that case wrapper reconstruction never
    runs, so merely healing object pointers leaves newly-created domains in the
    Python singleton after Ctrl+Z. The persisted rows are Blender's undo-aware
    source of truth and must refresh existing wrappers too.
    """
    items = {item.identifier: item for item in scene.molecule_list_items
             if item.identifier}
    for molecule_id, wrapper in list(scene_manager.molecules.items()):
        item = items.get(molecule_id)
        if item is None:
            continue
        wrapper.domains.clear()
        _restore_domains_into_wrapper(wrapper, item)


def _reconstruct_wrappers_from_properties(scene_manager, scene) -> List[str]:
    """Reconstruct wrappers from PropertyGroups for restored objects.

    When undo restores a deleted object, the PropertyGroup still exists
    but the wrapper was removed. This function recreates the wrapper.

    Returns:
        List of reconstructed molecule IDs
    """
    restored_ids = []

    for item in scene.molecule_list_items:
        if not item.identifier:
            continue

        # Check if wrapper exists
        if item.identifier in scene_manager.molecules:
            continue

        # Check if object exists (was restored by undo)
        obj = item.get_valid_object() if hasattr(item, 'get_valid_object') else None
        if not obj:
            # Try by stored name
            obj_name = item.object_name if hasattr(item, 'object_name') else ""
            if obj_name and obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]

        if not obj:
            continue

        # Object exists but wrapper doesn't - reconstruct
        try:
            # Get stored chain data
            chain_mapping = None
            chain_ranges = None

            if hasattr(item, 'get_chain_mapping'):
                chain_mapping = item.get_chain_mapping()
            if hasattr(item, 'get_chain_residue_ranges'):
                chain_ranges = item.get_chain_residue_ranges()

            # Create wrapper from existing object
            wrapper = MoleculeWrapper.from_existing_object(
                obj=obj,
                identifier=item.identifier,
                chain_mapping=chain_mapping,
                chain_residue_ranges=chain_ranges
            )

            if wrapper:
                # Bug B fix: rebuild the wrapper's runtime domain dict from
                # the persisted MoleculeListItem.domains collection so
                # auto-domains and any user customizations survive
                # save → load.
                _restore_domains_into_wrapper(wrapper, item)
                scene_manager.molecules[item.identifier] = wrapper
                scene_manager.molecule_manager.molecules[item.identifier] = wrapper
                restored_ids.append(item.identifier)

        except Exception as e:
            print(f"Warning: Failed to reconstruct wrapper for {item.identifier}: {e}")

    return restored_ids


def _handle_orphaned_proteins(scene_manager, scene) -> List[str]:
    """Handle protein objects that exist but have no PropertyGroup entry.

    This can happen after redo past an import operation.

    Returns:
        List of handled molecule IDs
    """
    handled_ids = []

    orphaned = _find_orphaned_protein_objects()
    for molecule_id, obj in orphaned:
        try:
            wrapper = _recreate_molecule_wrapper_from_object(molecule_id, obj)
            if wrapper:
                scene_manager.molecules[molecule_id] = wrapper
                scene_manager._finalize_imported_molecule(wrapper)
                handled_ids.append(molecule_id)
        except Exception as e:
            print(f"Warning: Failed to handle orphaned protein {molecule_id}: {e}")

    return handled_ids


# ---------------------------------------------------------------------------
# Self-healing: purge molecule entries whose backing objects are gone
# ---------------------------------------------------------------------------
# A molecule is left "orphaned" when its objects are deleted outside
# ProteinBlender's own delete path — e.g. with Blender's X key, or by a
# script. The runtime registry, the molecule list and the protein outliner
# then keep dead entries: a protein you can't see, an eye toggle that does
# nothing, unselectable chains. These hooks heal that automatically — on
# file load, and immediately when objects are deleted. (Undo/redo is already
# healed by sync_molecule_list_after_undo below.)

def purge_orphaned_molecules(verbose: bool = True) -> int:
    """Remove molecule registry / list / outliner entries whose objects no
    longer exist. Safe to call any time; a no-op when nothing is orphaned.

    Returns the number of molecules purged.
    """
    try:
        scene_manager = ProteinBlenderScene.get_instance()
        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            return 0
        removed = _remove_invalid_wrappers(scene_manager, scene)
        if removed:
            if getattr(scene_manager, "active_molecule", None) in removed:
                scene_manager.active_molecule = None
            # Rebuild the outliner so the dead protein/chain rows disappear.
            build_outliner_hierarchy(bpy.context)
            if verbose:
                print(f"[ProteinBlender] healed outliner — purged orphaned "
                      f"molecule(s): {removed}")
        return len(removed)
    except Exception as e:
        print(f"[ProteinBlender] purge_orphaned_molecules failed: {e}")
        return 0


# Object-count baseline for the depsgraph-based deletion detector.
_object_count_cache = [-1]


def _deferred_molecule_purge():
    """One-shot timer body — runs the purge in a context where modifying
    Blender data is safe (a depsgraph handler is not such a context)."""
    purge_orphaned_molecules()
    return None  # returning None unregisters the timer


@persistent
def detect_deleted_molecules(scene, depsgraph):
    """depsgraph_update_post hook — heals the outliner after a deletion.

    A depsgraph handler must not modify data, so this only watches for the
    object count dropping (something was deleted) and defers the actual
    purge to a one-shot timer. The common case — no deletion — costs a
    single len() and an int compare.
    """
    try:
        count = len(bpy.data.objects)
        prev = _object_count_cache[0]
        _object_count_cache[0] = count
        if 0 <= prev and count < prev:
            if not bpy.app.timers.is_registered(_deferred_molecule_purge):
                bpy.app.timers.register(_deferred_molecule_purge,
                                        first_interval=0.0)
    except Exception:
        pass


def _deferred_reconstruct_on_load():
    """One-shot timer body — rebuild the runtime molecule registry from the
    saved PropertyGroups after a file load, then heal any orphans.

    reset_scene_manager_on_load clears the registry on load, but reconstruction
    was only ever wired to undo/redo — so without this a freshly opened file
    shows proteins in the outliner yet has an EMPTY registry, and colour /
    split / centre / duplicate / pose all fail ("Molecule not found") until an
    undo happens to trigger a rebuild. Deferring to a timer guarantees this
    runs after every load_post handler (notably the reset) has finished,
    independent of the order handlers were registered in.
    """
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is not None:
            scene_manager = ProteinBlenderScene.get_instance()
            restored = _reconstruct_wrappers_from_properties(scene_manager, scene)
            if restored:
                build_outliner_hierarchy(bpy.context)
    except Exception as e:
        print(f"[ProteinBlender] reconstruct on load failed: {e}")
    # Re-baseline the deletion detector now the registry matches the file.
    _object_count_cache[0] = len(bpy.data.objects)
    return None  # returning None unregisters the timer


@persistent
def purge_orphaned_molecules_on_load(_dummy):
    """load_post hook — rebuild the runtime registry from the saved
    PropertyGroups, then heal a freshly opened file.

    The rebuild is deferred to a one-shot timer so it runs after every
    load_post handler (notably reset_scene_manager_on_load, which clears the
    registry) has completed, regardless of handler registration order.
    """
    _object_count_cache[0] = -1  # reset the baseline for the new file
    if not bpy.app.timers.is_registered(_deferred_reconstruct_on_load):
        bpy.app.timers.register(_deferred_reconstruct_on_load, first_interval=0.0)
    purge_orphaned_molecules()


def sync_molecule_list_after_undo(*args):
    """Sync molecule state after undo/redo operations.

    This handler runs after Blender's undo/redo to synchronize the runtime
    MoleculeWrapper state with Blender's restored object state.

    The strategy is:
    1. Heal all existing wrapper references (objects may have been restored)
    2. Remove wrappers for objects that no longer exist
    3. Reconstruct wrappers for objects that exist in PropertyGroups but not in wrappers
    4. Rebuild the UI

    This approach uses PropertyGroups as the source of truth, which Blender
    handles correctly across undo/redo operations.
    """
    try:
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene

        # Step 1: Heal all existing wrapper references
        _heal_all_wrapper_references(scene_manager)

        # Blender may have restored domain PropertyGroups/objects without
        # invalidating the parent molecule wrapper. Refresh its runtime domain
        # dictionary before validity pruning or UI reconstruction.
        _sync_existing_wrapper_domains_from_properties(scene_manager, scene)

        # Step 2: Remove wrappers for deleted objects
        removed_ids = _remove_invalid_wrappers(scene_manager, scene)

        # Step 3: Reconstruct wrappers from PropertyGroups for restored objects
        restored_ids = _reconstruct_wrappers_from_properties(scene_manager, scene)

        # Step 4: Handle orphaned protein objects (objects without PropertyGroup entries)
        orphan_ids = _handle_orphaned_proteins(scene_manager, scene)

        # Step 5: Rebuild UI if anything changed
        if removed_ids or restored_ids or orphan_ids:
            _refresh_molecule_ui(scene_manager, scene)
        else:
            _refresh_object_references_only(scene_manager, scene)

        # Step 5: Always rebuild outliner hierarchy after undo/redo
        # This ensures that chain deletions/restorations are reflected in the UI
        # (domains may have been added/removed without molecule-level changes)
        print("\nRebuilding outliner hierarchy...")
        build_outliner_hierarchy(bpy.context)
        print("========== UNDO/REDO HANDLER COMPLETE ==========\n")

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
    # Note: visibility is read directly from Blender objects, no need to store/restore
    
    # Temporarily disable selection sync during rebuild
    from ..handlers import selection_sync
    old_in_progress = selection_sync._update_in_progress
    selection_sync._update_in_progress = True  # Prevent any updates during rebuild
    
    # Get all valid molecule and domain IDs currently in the scene
    # Drop any wrappers whose underlying object is gone — typically a
    # consequence of `ed.undo` reverting an import, which leaves the
    # runtime singleton with stale entries that would otherwise crash
    # build_outliner_hierarchy when resolving via databpy.
    for stale_id in [
        mid for mid, mol in list(scene_manager.molecules.items())
        if not _is_molecule_valid(mol)
    ]:
        try:
            del scene_manager.molecules[stale_id]
        except KeyError:
            pass
        try:
            del scene_manager.molecule_manager.molecules[stale_id]
        except (KeyError, AttributeError):
            pass

    valid_item_ids = set()
    for molecule_id in scene_manager.molecules.keys():
        valid_item_ids.add(molecule_id)
        molecule = scene_manager.molecules.get(molecule_id)
        if hasattr(molecule, 'domains'):
            valid_item_ids.update(molecule.domains.keys())

        # Also add chain IDs which are used in outliner items
        # Chain IDs have format: "{molecule_id}_chain_{chain_id}"
        mol_object = None
        try:
            if hasattr(molecule, 'object') and molecule.object:
                mol_object = molecule.object
            elif hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
                mol_object = molecule.molecule.object
        except Exception:
            mol_object = None

        if mol_object and "chain_id" in mol_object.data.attributes:
            chain_attr = mol_object.data.attributes["chain_id"]
            chain_ids = set(value.value for value in chain_attr.data)
            for chain_id in chain_ids:
                valid_item_ids.add(f"{molecule_id}_chain_{chain_id}")

    for item in scene.outliner_items:
        # Store selection and expansion states for all items
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
        # Get the object - it might be molecule.object or molecule.molecule.object
        mol_object = None
        if hasattr(molecule, 'object') and molecule.object:
            mol_object = molecule.object
        elif hasattr(molecule, 'molecule') and hasattr(molecule.molecule, 'object'):
            mol_object = molecule.molecule.object

        # Detect DNA/RNA molecules via custom property
        is_nucleic = False
        try:
            is_nucleic = bool(mol_object and mol_object.get("pb_is_nucleic_acid", False))
        except (ReferenceError, AttributeError):
            pass

        # Add top-level item
        protein_item = scene.outliner_items.add()
        protein_item.item_type = 'DNA_RNA' if is_nucleic else 'PROTEIN'
        protein_item.item_id = molecule_id
        protein_item.parent_id = ""
        protein_item.name = getattr(molecule, 'name', molecule.identifier)

        # Safely get object name and visibility
        try:
            protein_item.object_name = mol_object.name if mol_object else ""
        except (ReferenceError, AttributeError):
            protein_item.object_name = ""

        protein_item.indent_level = 0
        protein_item.icon = 'RNA' if is_nucleic else 'MESH_DATA'

        try:
            protein_item.is_visible = not mol_object.hide_get(view_layer=context.view_layer) if mol_object else True
        except (ReferenceError, AttributeError):
            protein_item.is_visible = True

        # Restore selection and expansion states
        if molecule_id in item_selection_states:
            protein_item.is_selected = item_selection_states[molecule_id]
        if molecule_id in item_expansion_states:
            protein_item.is_expanded = item_expansion_states[molecule_id]

        # Generate and store tooltip
        if is_nucleic:
            nt = mol_object.get("pb_nucleic_type", "DNA") if mol_object else "DNA"
            seq = mol_object.get("pb_sequence", "") if mol_object else ""
            seq_display = seq[:30] + "..." if len(seq) > 30 else seq
            tooltip_parts = [f"{nt}: {protein_item.name}", f"Sequence: {seq_display}", f"Length: {len(seq)} nt"]
        else:
            tooltip_parts = [f"Protein: {protein_item.name}"]
            if hasattr(molecule, 'identifier'):
                tooltip_parts.append(f"ID: {molecule.identifier}")
        protein_item.tooltip = "\n".join(tooltip_parts)

        # Get chains from the molecule
        if mol_object and "chain_id" in mol_object.data.attributes:
            chain_attr = mol_object.data.attributes["chain_id"]
            chain_ids = sorted({value.value for value in chain_attr.data})
            
            # Debug output (commented out for production)
            # print(f"Molecule {getattr(molecule, 'name', molecule.identifier)} has chains: {chain_ids}")
            # print(f"Chain mapping: {getattr(molecule, 'chain_mapping', getattr(molecule, 'idx_to_label_asym_id_map', 'None'))}")
            
            # Custom chain names the user assigned via the Rename button live on
            # the persistent list item as a JSON {chain_index: name} map; apply
            # them over the default "Chain <letter>" names below.
            import json as _json
            _custom_chain_names = {}
            _mol_list_item = next((it for it in scene.molecule_list_items
                                   if it.identifier == molecule.identifier), None)
            if _mol_list_item and _mol_list_item.chain_custom_names:
                try:
                    _custom_chain_names = _json.loads(_mol_list_item.chain_custom_names)
                except Exception:
                    _custom_chain_names = {}

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

                # DNA/RNA: use strand names instead of chain names
                if is_nucleic:
                    strand_labels = {0: "Sense strand (5'\u21923')", 1: "Antisense strand (3'\u21925')"}
                    chain_item.name = strand_labels.get(chain_id, f"Strand {chain_name}")
                else:
                    chain_item.name = f"Chain {chain_name}"
                # User-assigned name wins over the auto-generated default.
                _override = _custom_chain_names.get(str(chain_id))
                if _override:
                    chain_item.name = _override
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
                    elif chain_id in getattr(molecule, 'auth_chain_id_map', {}):
                        label_asym_id = molecule.auth_chain_id_map[chain_id]
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

                # Generate and store tooltip for chain (after residue ranges are set)
                tooltip_parts = []
                protein_name = getattr(molecule, 'name', molecule.identifier)
                tooltip_parts.append(f"Protein: {protein_name}")
                tooltip_parts.append(f"Chain: {chain_item.name}")
                if chain_item.chain_start > 0 and chain_item.chain_end > 0:
                    tooltip_parts.append(f"Chain Residues: {chain_item.chain_start}-{chain_item.chain_end}")
                chain_item.tooltip = "\n".join(tooltip_parts)

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
                        match = re.search(r'Chain_([A-Z])', domain.name)
                        if match:
                            domain_chain_id = match.group(1)
                        
                        # Also try to extract chain index from pattern like "3b75_001_0_1_197"
                        if domain_chain_id is None:
                            match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                            if match2:
                                domain_chain_id = int(match2.group(1))
                    
                    if domain_chain_id is not None:
                        # Single matching rule for the whole codebase: does this
                        # domain belong to the current chain? chain_match_tokens
                        # bridges the chain-index ("0") vs. chain-letter ("A")
                        # gap via the molecule's real maps.
                        if str(domain_chain_id) in chain_match_tokens(molecule, chain_id):
                            chain_domains.append((domain_id, domain))

                # If this chain has no domains, remove the chain item and skip to next chain
                if len(chain_domains) == 0:
                    # Remove the chain item we just added
                    scene.outliner_items.remove(len(scene.outliner_items) - 1)
                    continue

                # Determine if we should show domains in the outliner
                # Show domains if:
                # 1. There's more than one domain (chain has been split), OR
                # 2. There's exactly one domain that doesn't span the entire chain
                should_show_domains = False

                if len(chain_domains) > 1:
                    # Multiple domains - always show them
                    should_show_domains = True
                    chain_item.has_domains = True
                elif len(chain_domains) == 1:
                    # Single domain - check if it spans the entire chain
                    domain_id, domain = chain_domains[0]

                    # Get the chain's residue range
                    chain_min = chain_item.chain_start if hasattr(chain_item, 'chain_start') and chain_item.chain_start > 0 else None
                    chain_max = chain_item.chain_end if hasattr(chain_item, 'chain_end') and chain_item.chain_end > 0 else None

                    # If domain doesn't span the entire chain, show it
                    if chain_min and chain_max:
                        domain_spans_full_chain = (domain.start == chain_min and domain.end == chain_max)
                        should_show_domains = not domain_spans_full_chain
                        chain_item.has_domains = should_show_domains

                        # If domain spans full chain, make chain item reference the domain's object
                        if domain_spans_full_chain and is_object_valid(domain.object):
                            chain_item.object_name = domain.object.name
                        else:
                            chain_item.object_name = ""
                    else:
                        # Can't determine chain range, assume it's a full chain domain
                        chain_item.has_domains = False
                        if is_object_valid(domain.object):
                            chain_item.object_name = domain.object.name
                        else:
                            chain_item.object_name = ""

                # Add domain items if they should be shown and chain is expanded
                if should_show_domains and chain_item.is_expanded:
                    for domain_id, domain in chain_domains:
                        domain_item = scene.outliner_items.add()
                        domain_item.item_type = 'DOMAIN'
                        # Domain ID already includes molecule ID, so use it directly
                        domain_item.item_id = domain_id
                        domain_item.parent_id = chain_item.item_id
                        
                        # Extract meaningful domain name
                        # Use the domain's actual name property first
                        domain_display_name = domain.name

                        # For copies, the name already includes the copy number
                        # (e.g., "Chain A 1"). For non-copies, normalise an
                        # auto-generated name to the canonical
                        # "Chain <id>: Residues N-M" form - naming both the chain
                        # and the residue range - but keep a name the user set
                        # via Rename. A name counts as auto-generated when it's
                        # blank or matches any default form the create/split
                        # paths have produced ("Residues N-M", "Chain X",
                        # "Chain X: N-M", or the canonical form itself); anything
                        # else is a deliberate rename and must survive the rebuild.
                        if not (hasattr(domain, 'is_copy') and domain.is_copy):
                            if hasattr(domain, 'start') and hasattr(domain, 'end'):
                                name = (domain.name or "").strip()
                                is_auto_name = (
                                    not name
                                    or re.match(r'^Residues\s+\d+-\d+$', name)
                                    or re.match(r'^Chain\s+\S+$', name)
                                    or re.match(r'^Chain\s+\S+:\s*\d+-\d+$', name)
                                    or re.match(r'^Chain\s+\S+:\s*Residues\s+\d+-\d+$', name)
                                )
                                if is_auto_name:
                                    domain_display_name = (
                                        f"Chain {domain.chain_id}: "
                                        f"Residues {domain.start}-{domain.end}")

                        domain_item.name = domain_display_name

                        # Safely get object name - handle case where object is freed/invalid
                        if is_object_valid(domain.object):
                            domain_item.object_name = domain.object.name
                        else:
                            domain_item.object_name = ""

                        domain_item.domain_start = getattr(domain, 'start', 0)
                        domain_item.domain_end = getattr(domain, 'end', 0)
                        domain_item.indent_level = 2
                        domain_item.icon = 'GROUP_VERTEX'

                        # Safely get visibility - handle case where object is freed/invalid
                        if is_object_valid(domain.object):
                            try:
                                domain_item.is_visible = not domain.object.hide_get(view_layer=context.view_layer)
                            except Exception:
                                domain_item.is_visible = True
                        else:
                            domain_item.is_visible = True
                        
                        # Restore selection state
                        if domain_id in item_selection_states:
                            domain_item.is_selected = item_selection_states[domain_id]

                        # Generate and store tooltip for domain
                        tooltip_parts = []
                        protein_name = getattr(molecule, 'name', molecule.identifier)
                        tooltip_parts.append(f"Protein: {protein_name}")

                        # Add chain information - use parent chain's display name
                        tooltip_parts.append(f"Chain: {chain_item.name.replace('Chain ', '')}")

                        # Only show domain residues if available
                        if domain_item.domain_start > 0 and domain_item.domain_end > 0:
                            tooltip_parts.append(f"Domain Residues: {domain_item.domain_start}-{domain_item.domain_end}")

                        domain_item.tooltip = "\n".join(tooltip_parts)
            
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

                                # Safely get object name and visibility
                                if is_object_valid(domain.object):
                                    chain_copy_item.object_name = domain.object.name
                                    try:
                                        chain_copy_item.is_visible = not domain.object.hide_get(view_layer=context.view_layer)
                                    except Exception:
                                        chain_copy_item.is_visible = True
                                else:
                                    chain_copy_item.object_name = ""
                                    chain_copy_item.is_visible = True

                                chain_copy_item.chain_start = domain.start
                                chain_copy_item.chain_end = domain.end
                                
                                # Restore selection and expansion states
                                if domain_id in item_selection_states:
                                    chain_copy_item.is_selected = item_selection_states[domain_id]
                                if domain_id in item_expansion_states:
                                    chain_copy_item.is_expanded = item_expansion_states[domain_id]
    
    # Add membrane items — top-level rows for each ``pb_is_membrane`` root,
    # placed after the molecules so the user gets a single combined list.
    # Children of the root (lattice, hole controllers, force-field proxies)
    # are NOT shown in the outliner; the membrane row controls them as a
    # group via visibility / delete cascading.
    for obj in bpy.data.objects:
        try:
            if not obj.get("pb_is_membrane", False):
                continue
        except (ReferenceError, AttributeError):
            continue

        mem_item = scene.outliner_items.add()
        mem_item.item_type = 'MEMBRANE'
        mem_item.item_id = f"membrane_{obj.name}"
        mem_item.parent_id = ""
        mem_item.name = obj.name
        mem_item.object_name = obj.name
        mem_item.indent_level = 0
        mem_item.icon = 'MOD_FLUIDSIM'
        try:
            mem_item.is_visible = not obj.hide_get(view_layer=context.view_layer)
        except (ReferenceError, RuntimeError):
            mem_item.is_visible = True
        # Restore selection / expansion states
        if mem_item.item_id in item_selection_states:
            mem_item.is_selected = item_selection_states[mem_item.item_id]
        if mem_item.item_id in item_expansion_states:
            mem_item.is_expanded = item_expansion_states[mem_item.item_id]
        mem_item.tooltip = f"Membrane: {obj.name}"

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
            # Store the original item ID for reference (use dedicated field, not puppet_memberships)
            ref_item.reference_target_id = member_id

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
    selection_sync._update_in_progress = old_in_progress

    if context.area:
        context.area.tag_redraw()
