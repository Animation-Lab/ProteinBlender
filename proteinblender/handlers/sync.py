# proteinblender/handlers/sync.py
import bpy
from ..utils.scene_manager import get_protein_blender_scene
from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..core.molecule_manager import MoleculeWrapper

def sync_manager_on_undo_redo(scene):
    """
    Simplified sync handler that rebuilds addon state from Blender objects after undo/redo.
    Uses custom properties to reconstruct protein-domain relationships.
    """
    print("PB: Running simplified undo/redo sync handler...")

    # Clear current UI state - it will be rebuilt from objects
    scene.molecule_list_items.clear()
    
    # Scan for molecule and domain objects 
    found_molecules = {}
    found_domains = {}
    
    for obj in bpy.data.objects:
        mol_id = obj.get("molecule_identifier")
        if not mol_id:
            continue
            
        if obj.get("is_protein_blender_main"):
            # This is a main protein object
            found_molecules[mol_id] = obj
            print(f"  Found main protein: {mol_id} ({obj.name})")
            
        elif obj.get("is_protein_blender_domain"):
            # This is a domain object
            domain_id = obj.get("pb_domain_id")
            if domain_id:
                if mol_id not in found_domains:
                    found_domains[mol_id] = {}
                found_domains[mol_id][domain_id] = obj
                print(f"  Found domain: {domain_id} for molecule {mol_id}")
    
    # Rebuild UI list from found proteins
    for mol_id, mol_obj in found_molecules.items():
        item = scene.molecule_list_items.add()
        item.identifier = mol_id
        item.name = mol_obj.get("molecule_identifier", mol_obj.name)
        
        # Count domains for this molecule
        domain_count = len(found_domains.get(mol_id, {}))
        print(f"  Restored molecule '{mol_id}' with {domain_count} domains")
    
    # Validate and update selected molecule
    if scene.selected_molecule_id:
        if scene.selected_molecule_id not in found_molecules:
            # Selected molecule no longer exists, clear selection
            scene.selected_molecule_id = ""
            print("  Cleared invalid selected molecule")
        else:
            print(f"  Maintained selection: {scene.selected_molecule_id}")
    
    # Force UI refresh
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
                
    molecules_count = len(found_molecules)
    total_domains = sum(len(domains) for domains in found_domains.values())
    print(f"PB: Sync complete. Found {molecules_count} molecules with {total_domains} total domains")


# The ReconstructedMolecule class is no longer needed as its logic
# has been moved into the MoleculeWrapper's __init__ method.
# class ReconstructedMolecule:
#     """
#     A minimal molecule wrapper that allows us to reconstruct MoleculeWrapper
#     from an existing Blender object after undo/redo operations.
#     """
#     def __init__(self, blender_object):
#         self.object = blender_object
#         # We don't have the original biotite array, but that's okay for basic functionality
#         self.array = None


# Wrap the handler in 'persistent' decorator to ensure it's not removed on file reload
persistent_handler = bpy.app.handlers.persistent(sync_manager_on_undo_redo)

def register():
    # Register for both undo and redo operations
    # Check if it's not already there to prevent duplicates during hot-reloads.
    if persistent_handler not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(persistent_handler)
        print("PB: Registered sync handler for undo operations.")
    
    # IMPROVED: More robust redo handler registration
    try:
        if hasattr(bpy.app.handlers, 'redo_post'):
            if persistent_handler not in bpy.app.handlers.redo_post:
                bpy.app.handlers.redo_post.append(persistent_handler)
                print("PB: Registered sync handler for redo operations.")
        else:
            print("PB: Warning - redo_post handler not available in this Blender version.")
    except AttributeError:
        print("PB: Warning - Failed to register redo handler. Feature not supported.")

def unregister():
    # Clean up both handlers on unregister
    if persistent_handler in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(persistent_handler)
        print("PB: Removed undo sync handler.")
            
    # IMPROVED: More robust redo handler cleanup
    try:
        if hasattr(bpy.app.handlers, 'redo_post'):
            if persistent_handler in bpy.app.handlers.redo_post:
                bpy.app.handlers.redo_post.remove(persistent_handler)
                print("PB: Removed redo sync handler.")
    except AttributeError:
        pass 