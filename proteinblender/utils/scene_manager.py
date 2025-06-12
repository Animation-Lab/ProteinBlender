from .file_io import get_protein_file
import json
import bpy
from typing import Dict, Optional, List, Set
from .molecularnodes.entities import fetch, load_local
from ..core.molecule_manager import MoleculeManager, MoleculeWrapper
from bpy.app.handlers import undo_post, undo_pre
from databpy.object import LinkedObjectError

class ProteinBlenderScene:
    """A manager for the ProteinBlender scene, providing access to molecules and domains."""
    
    def __init__(self, context):
        self._scene = context.scene
        self._molecule_manager = MoleculeManager(self._scene)

    @property
    def molecules(self) -> Dict[str, 'MoleculeWrapper']:
        """Get the dictionary of all molecules in the scene using cached wrappers."""
        # Use cached wrappers to preserve domain state
        if not hasattr(self, '_cached_wrappers'):
            self._cached_wrappers = {}
            
        # Update cache with any new molecules found in scene
        current_molecules = {}
        for obj in bpy.data.objects:
            mol_id = obj.get("molecule_identifier")
            if mol_id and obj.get("is_protein_blender_main"):
                if mol_id in self._cached_wrappers:
                    # Use cached wrapper to preserve domain state
                    current_molecules[mol_id] = self._cached_wrappers[mol_id]
                else:
                    # Create new wrapper and cache it
                    from ..core.molecule_manager import MoleculeWrapper
                    wrapper = MoleculeWrapper(identifier=mol_id, blender_object=obj)
                    self._cached_wrappers[mol_id] = wrapper
                    current_molecules[mol_id] = wrapper
        
        # Update cache to reflect current state
        self._cached_wrappers = current_molecules
        return current_molecules

    @property
    def active_molecule(self) -> Optional['MoleculeWrapper']:
        """Get the currently active molecule."""
        active_id = self._scene.selected_molecule_id
        return self.get_molecule(active_id) if active_id else None

    def get_molecule(self, identifier: str) -> Optional['MoleculeWrapper']:
        """Get a molecule by its identifier using cached wrapper approach."""
        # Use the cached molecules property to ensure we get the same wrapper instance
        molecules = self.molecules
        return molecules.get(identifier)
    
    def import_molecule(self, *args, **kwargs) -> Optional['MoleculeWrapper']:
        """Import a molecule using the molecule manager."""
        # This now becomes a simple pass-through, keeping the scene manager as the main interface.
        # Determine import type from kwargs
        molecule = None
        if 'pdb_id' in kwargs:
            molecule = self._molecule_manager.import_from_pdb(*args, **kwargs)
        elif 'filepath' in kwargs:
            molecule = self._molecule_manager.import_from_file(*args, **kwargs)
        else:
            print("Error: No valid import source provided (pdb_id or filepath).")
            return None
            
        # If import was successful, finalize the molecule (create domains, update UI)
        if molecule:
            self._finalize_imported_molecule(molecule)
            
        return molecule

    def remove_molecule(self, identifier: str):
        """Remove a molecule from the scene."""
        self._molecule_manager.delete_molecule(identifier)
        
        # After deleting, update the active molecule if it was the one deleted
        if self._scene.selected_molecule_id == identifier:
            # Select the first available molecule or clear the selection
            all_ids = list(self.molecules.keys())
            self._scene.selected_molecule_id = all_ids[0] if all_ids else ""



    def get_selected_molecule(self, context) -> Optional['MoleculeWrapper']:
        """Get the currently selected molecule based on the scene property."""
        sel_id = context.scene.selected_molecule_id
        if not sel_id:
            return None
        return self.get_molecule(sel_id)

    def to_json(self):
        """Convert the scene to JSON."""
        return json.dumps({
            'molecules': {id: molecule.to_json() for id, molecule in self.molecules.items()},
            'active_molecule': self.active_molecule.identifier if self.active_molecule else None,
            'display_settings': {}
        })

    def _create_domains_for_each_chain(self, molecule_id: str):
        """Create domain objects for each chain using the new DomainDefinition approach"""
        print(f"SCENE_MANAGER DEBUG: Starting domain creation for molecule {molecule_id}")
        
        # Use our new property-based molecule lookup
        molecule = self.get_molecule(molecule_id)
        if not molecule:
            print(f"ERROR SceneManager: Molecule {molecule_id} not found for domain creation")
            return

        if not molecule.object:
            print(f"ERROR SceneManager: Molecule {molecule_id} has no object for domain creation")
            return
            
        print(f"SCENE_MANAGER DEBUG: Found molecule object: {molecule.object.name}")
        
        # Get chain ranges from the wrapper
        chain_ranges = molecule._get_chain_residue_ranges()
        print(f"SCENE_MANAGER DEBUG: Chain ranges from wrapper: {chain_ranges}")
        
        if not chain_ranges:
            print(f"WARNING SceneManager: No chain ranges found for {molecule_id}")
            return
        
        # Verify the parent object has the required modifier
        parent_modifier = molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier:
            print(f"ERROR SceneManager: Parent molecule {molecule_id} has no MolecularNodes modifier")
            return
        
        print(f"SCENE_MANAGER DEBUG: Parent has modifier: {parent_modifier.name}")
        
        # Import the DomainDefinition class
        from ..core.domain import DomainDefinition
        
        domains_created = 0
        
        # Create one domain per chain using our new simplified approach
        for idx, (label_asym_id, (start_res, end_res)) in enumerate(chain_ranges.items()):
            print(f"SCENE_MANAGER DEBUG: Creating domain {idx+1}/{len(chain_ranges)} for chain {label_asym_id}")
            
            # Create domain using the simplified DomainDefinition system
            domain_name = f"{molecule_id}_{label_asym_id}_{start_res}_{end_res}_Chain_{label_asym_id}"
            
            try:
                domain_def = DomainDefinition(
                    chain_id=label_asym_id,
                    start=start_res,
                    end=end_res,
                    name=domain_name
                )
                
                # Set parent molecule reference
                domain_def.parent_molecule_id = molecule_id
                
                print(f"SCENE_MANAGER DEBUG: Attempting to create object for domain {domain_name}")
                
                # Try to create the domain object
                success = domain_def.create_object_from_parent(molecule.object)
                
                if success and domain_def.object:
                    # Generate domain ID for this domain
                    domain_id = f"{molecule_id}_{label_asym_id}_{start_res}_{end_res}"
                    domain_def.domain_id = domain_id
                    
                    # Update the custom property with the final domain ID
                    domain_def.object["pb_domain_id"] = domain_id
                    
                    # Add domain to the molecule wrapper
                    molecule.add_domain(label_asym_id, domain_def)
                    
                    domains_created += 1
                    print(f"SUCCESS: Created domain for chain {label_asym_id} (ID: {domain_id})")
                else:
                    print(f"FAILED: Could not create domain object for {domain_name}")
                    
            except Exception as e:
                print(f"EXCEPTION during domain creation for {label_asym_id}: {e}")
                import traceback
                traceback.print_exc()
        
        if domains_created == 0:
            print(f"SceneManager: No domains were created for {molecule_id} during default domain creation.")
        else:
            print(f"SceneManager: Successfully created {domains_created} domains for {molecule_id}")

    def _finalize_imported_molecule(self, molecule):
        """Finalize the import of a molecule: create domains, update UI, set active, refresh."""
        print(f"SCENE_MANAGER DEBUG: Finalizing import for molecule {molecule.identifier}")
        
        # Add custom properties to main protein object for undo/redo tracking
        self._add_main_protein_properties(molecule)
        
        # Cache the molecule wrapper so domains persist
        if not hasattr(self, '_cached_wrappers'):
            self._cached_wrappers = {}
        self._cached_wrappers[molecule.identifier] = molecule
        print(f"SCENE_MANAGER DEBUG: Cached molecule wrapper for {molecule.identifier}")
        
        # Create domains for each chain
        print(f"SCENE_MANAGER DEBUG: Creating domains for {molecule.identifier}")
        self._create_domains_for_each_chain(molecule.identifier)
        
        # Add to UI list
        scene = bpy.context.scene
        item = scene.molecule_list_items.add()
        item.identifier = molecule.identifier
        item.name = molecule.identifier  # Also set name
        
        # Set as active molecule
        scene.selected_molecule_id = molecule.identifier
        print(f"SCENE_MANAGER DEBUG: Set active molecule to {molecule.identifier}")
        
        # Force UI refresh
        self._refresh_ui()
    
    def _add_main_protein_properties(self, wrapper):
        """Add custom properties to main protein object for undo/redo tracking"""
        if not wrapper.object:
            return
            
        # Mark this as a ProteinBlender main protein object
        wrapper.object["is_protein_blender_main"] = True
        wrapper.object["molecule_identifier"] = wrapper.identifier
        
        # Store import metadata
        wrapper.object["import_source"] = "local"  # Will be overridden for remote imports
        wrapper.object["protein_style"] = wrapper.style
        
        print(f"Added main protein properties to {wrapper.identifier}")

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
            # Override import source for remote imports
            if molecule.object:
                molecule.object["import_source"] = "remote"
            # Finalize import (domains, UI, etc.)
            self._finalize_imported_molecule(molecule)
            return True
        except Exception as e:
            print(f"Error creating molecule: {str(e)}")
            return False

    def delete_molecule(self, identifier: str) -> bool:
        """Delete a molecule and update the UI list"""
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
        
        # Set as active molecule
        self.active_molecule = identifier
        
        # Force UI refresh
        self._refresh_ui() 

# Helper function to get the scene manager instance for the current context.
# This replaces the singleton `get_instance()` method.
_scene_managers = {}

def get_protein_blender_scene(context=None):
    """
    Returns a ProteinBlenderScene instance for the given context.
    Caches the instance per Blender scene to maintain a single manager per scene.
    """
    if context is None:
        context = bpy.context
    
    scene = context.scene
    # Use the scene's memory address as a unique key
    scene_key = hash(scene)
    
    if scene_key not in _scene_managers:
        _scene_managers[scene_key] = ProteinBlenderScene(context)
        
    return _scene_managers[scene_key]

def clear_scene_manager_cache(scene):
    """Function to be called when a scene is removed."""
    scene_key = hash(scene)
    if scene_key in _scene_managers:
        del _scene_managers[scene_key]
        print(f"Cleared scene manager for scene: {scene.name}") 