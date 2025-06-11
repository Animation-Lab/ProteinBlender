# proteinblender/handlers/sync.py
import bpy
from ..utils.scene_manager import get_protein_blender_scene
from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..core.molecule_manager import MoleculeWrapper

def sync_manager_on_undo_redo(scene):
    """
    Synchronizes the MoleculeManager with Blender's data after an undo/redo.
    This bidirectional sync both removes stale molecules and restores recreated ones.
    """
    print("PB: Running undo/redo sync handler...")

    scene_manager = get_protein_blender_scene(bpy.context)
    if not scene_manager:
        return

    # Part 1: Find molecules to remove (objects that no longer exist)
    molecules_to_remove = []
    for molecule_id, molecule_wrapper in scene_manager.molecules.items():
        object_exists = False
        try:
            # Search for an object with this molecule_id as custom property
            for obj_name, obj in bpy.data.objects.items():
                # CRITICAL FIX: Skip domain objects and only check main molecule objects
                if (obj.get("molecule_identifier") == molecule_id and 
                    not obj.get("is_protein_blender_domain") and  # Skip domains
                    not obj.get("pb_domain_id")):  # Double-check for domains
                    object_exists = True
                    break
        except:
            object_exists = False
        
        if not object_exists:
            print(f"  - Stale molecule found: '{molecule_id}'. Marking for removal.")
            molecules_to_remove.append(molecule_id)

    # Part 2: Find molecules to add (objects that exist but aren't in manager)
    molecules_to_add = []
    # IMPROVED: Remove silent error swallowing and add logging
    try:
        print("  - Scanning scene for orphaned molecules...")
        for obj in bpy.data.objects:
            # More detailed logging to see what the handler is evaluating
            print(f"    - Scanning obj: {obj.name}, is_domain: {obj.get('is_protein_blender_domain')}, molecule_id: {obj.get('molecule_identifier')}")
            
            molecule_identifier = obj.get("molecule_identifier")
            is_domain = obj.get("is_protein_blender_domain") or obj.get("pb_domain_id")

            # CRITICAL FIX: Only process main molecule objects, not domains
            if molecule_identifier and not is_domain:
                if molecule_identifier not in scene_manager.molecules:
                    print(f"  - Orphaned molecule found: '{molecule_identifier}' ({obj.name}). Marking for reconstruction.")
                    # Ensure we don't add duplicates if multiple objects have the same ID
                    if not any(m[0] == molecule_identifier for m in molecules_to_add):
                        molecules_to_add.append((molecule_identifier, obj))
    except Exception as e:
        print(f"  - ERROR while scanning for orphaned molecules: {e}")

    # Remove stale molecules
    for molecule_id in molecules_to_remove:
        if molecule_id in scene_manager.molecules:
            # The blender object is already deleted by the undo operation.
            # We must NOT call cleanup(), as it will try to access the deleted
            # object and crash. We only need to remove our Python-side wrapper.
            del scene_manager.molecules[molecule_id]
            print(f"  - Removed stale wrapper '{molecule_id}' from the scene manager.")
        
        # Also remove from UI list
        # We search and remove from the list safely.
        for i, item in enumerate(scene.molecule_list_items):
            if item.identifier == molecule_id:
                scene.molecule_list_items.remove(i)
                print(f"  - Removed '{molecule_id}' from UI list.")
                break

    # Reconstruct orphaned molecules
    for molecule_id, blender_obj in molecules_to_add:
        try:
            # Create a minimal Molecule wrapper that wraps the existing Blender object
            reconstructed_molecule = ReconstructedMolecule(blender_obj)
            wrapper = MoleculeWrapper(reconstructed_molecule, molecule_id)
            scene_manager.molecules[molecule_id] = wrapper
            print(f"  - Reconstructed '{molecule_id}' and added to scene manager.")
            
            # Add to UI list
            item = scene.molecule_list_items.add()
            item.identifier = molecule_id
            print(f"  - Added '{molecule_id}' to UI list.")
            
        except Exception as e:
            print(f"  - Failed to reconstruct '{molecule_id}': {e}")

    # Update UI state
    changes_made = molecules_to_remove or molecules_to_add
    
    if molecules_to_remove and scene.selected_molecule_id in molecules_to_remove:
        scene.selected_molecule_id = ""
        print("  - Cleared active molecule selection as it was removed.")

    if not changes_made:
        print("  - No sync changes needed. Scene is in sync.")
        return

    # Force UI redraw
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


class ReconstructedMolecule:
    """
    A minimal molecule wrapper that allows us to reconstruct MoleculeWrapper
    from an existing Blender object after undo/redo operations.
    """
    def __init__(self, blender_object):
        self.object = blender_object
        # We don't have the original biotite array, but that's okay for basic functionality
        self.array = None


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