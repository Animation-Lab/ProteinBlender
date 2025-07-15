# proteinblender/handlers/outliner_handler.py
import bpy
from ..utils.scene_manager import ProteinBlenderScene

# Global state for selection monitoring
_last_selected_objects = set()
_selection_timer = None

def populate_outliner_from_molecules(scene):
    """
    Populate the outliner with all molecules and their hierarchies.
    This completely rebuilds the outliner from the current molecule data.
    """
    scene_manager = ProteinBlenderScene.get_instance()
    outliner_state = scene.protein_outliner_state
    
    # Clear existing items
    outliner_state.items.clear()
    
    # Add all molecules and their hierarchies
    for identifier, molecule in scene_manager.molecules.items():
        if not molecule.object:
            continue
            
        # Add top-level protein entry
        protein_item = outliner_state.items.add()
        protein_item.name = molecule.object.name
        protein_item.identifier = identifier
        protein_item.type = 'PROTEIN'
        protein_item.depth = 0
        protein_item.is_selected = molecule.object.select_get()
        protein_item.is_visible = not molecule.object.hide_get()
        
        # Organize domains by chain
        chains_with_domains = {}
        if hasattr(molecule, 'domains') and molecule.domains:
            for domain_id, domain in molecule.domains.items():
                if domain.object and hasattr(domain, 'chain_id'):
                    chain_id = domain.chain_id
                    if chain_id not in chains_with_domains:
                        chains_with_domains[chain_id] = []
                    chains_with_domains[chain_id].append((domain_id, domain))
        
        # Add chain entries and their domains
        for chain_id, domains in chains_with_domains.items():
            # Add chain entry
            chain_item = outliner_state.items.add()
            chain_item.name = f"Chain {chain_id}"
            chain_item.identifier = f"{identifier}_chain_{chain_id}"
            chain_item.type = 'CHAIN'
            chain_item.depth = 1  # Indented under protein
            chain_item.is_selected = False  # Chains don't have direct objects
            chain_item.is_visible = True
            
            # Add domains under this chain
            for domain_id, domain in domains:
                domain_item = outliner_state.items.add()
                domain_item.name = domain.object.name
                domain_item.identifier = domain_id
                domain_item.type = 'DOMAIN'
                domain_item.depth = 2  # Indented under chain
                domain_item.is_selected = domain.object.select_get()
                domain_item.is_visible = not domain.object.hide_get()

def sync_selection_from_viewport():
    """
    Sync selection state from viewport to outliner.
    Called when selection changes in viewport.
    """
    # Check if sync is already in progress to avoid infinite loops
    from ..properties.outliner_properties import _sync_in_progress
    if _sync_in_progress:
        return
        
    scene = bpy.context.scene
    if not hasattr(scene, 'protein_outliner_state'):
        return
        
    scene_manager = ProteinBlenderScene.get_instance()
    outliner_state = scene.protein_outliner_state
    
    # Track if any changes were made to avoid infinite recursion
    changes_made = False
    
    # Sync all outliner items
    for item in outliner_state.items:
        if item.type == 'PROTEIN':
            molecule = scene_manager.molecules.get(item.identifier)
            if molecule and molecule.object:
                new_selection = molecule.object.select_get()
                if item.is_selected != new_selection:
                    item.is_selected = new_selection
                    changes_made = True
                    
                new_visibility = not molecule.object.hide_get()
                if item.is_visible != new_visibility:
                    item.is_visible = new_visibility
                    changes_made = True
                    
        elif item.type == 'DOMAIN':
            # Find the domain by searching through all molecules
            for mol in scene_manager.molecules.values():
                if hasattr(mol, 'domains') and item.identifier in mol.domains:
                    domain = mol.domains[item.identifier]
                    if domain and domain.object:
                        new_selection = domain.object.select_get()
                        if item.is_selected != new_selection:
                            item.is_selected = new_selection
                            changes_made = True
                            
                        new_visibility = not domain.object.hide_get()
                        if item.is_visible != new_visibility:
                            item.is_visible = new_visibility
                            changes_made = True
                    break
    
    # Force UI redraw if changes were made
    if changes_made:
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()

def check_selection_changes():
    """
    Timer-based function to detect selection changes that aren't caught by other handlers.
    This acts as a fallback for direct viewport interactions.
    """
    global _last_selected_objects
    
    try:
        # Get current selection
        current_selected = set(obj.name for obj in bpy.context.selected_objects)
        
        # Check if selection changed
        if current_selected != _last_selected_objects:
            _last_selected_objects = current_selected
            sync_selection_from_viewport()
            
    except Exception as e:
        print(f"Error in selection check: {e}")
    
    # Return the timer interval (in seconds) to keep the timer running
    return 0.1  # Check every 100ms

def start_selection_timer():
    """Start the selection monitoring timer."""
    global _selection_timer
    if _selection_timer is None:
        _selection_timer = bpy.app.timers.register(check_selection_changes)

def stop_selection_timer():
    """Stop the selection monitoring timer."""
    global _selection_timer
    if _selection_timer is not None:
        try:
            bpy.app.timers.unregister(check_selection_changes)
        except Exception:
            pass  # Timer might already be unregistered
        _selection_timer = None

def msgbus_selection_callback(*args):
    """Callback for message bus selection changes."""
    sync_selection_from_viewport()

@bpy.app.handlers.persistent
def outliner_sync_handler(scene):
    """
    Main handler for syncing outliner state.
    Called by multiple Blender handlers.
    """
    try:
        sync_selection_from_viewport()
    except Exception as e:
        print(f"Error in outliner sync: {e}")

def sync_outliner_state(scene):
    """
    Legacy function for compatibility.
    """
    outliner_sync_handler(scene)

def register():
    """Register all necessary handlers for outliner synchronization."""
    # Register traditional handlers for various events that might change selection/visibility
    handlers_to_register = [
        (bpy.app.handlers.depsgraph_update_post, outliner_sync_handler),
        (bpy.app.handlers.undo_post, outliner_sync_handler),
        (bpy.app.handlers.redo_post, outliner_sync_handler),
    ]
    
    for handler_list, handler_func in handlers_to_register:
        if handler_func not in handler_list:
            handler_list.append(handler_func)
    
    # Register message bus subscriptions for better selection detection
    try:
        # Subscribe to object selection changes for all objects
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Object, "select"),
            owner=outliner_sync_handler,  # Use the handler function as owner
            notify=msgbus_selection_callback,
        )
        
        # Subscribe to active object changes
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=outliner_sync_handler,
            notify=msgbus_selection_callback,
        )
        
        # Subscribe to view layer changes 
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.ViewLayer, "objects"),
            owner=outliner_sync_handler,
            notify=msgbus_selection_callback,
        )
        
    except Exception as e:
        print(f"Failed to register message bus subscriptions: {e}")
    
    # Start the selection monitoring timer as a fallback
    start_selection_timer()

def unregister():
    """Unregister all outliner handlers."""
    # Stop the selection timer
    stop_selection_timer()
    
    # Clear message bus subscriptions
    try:
        bpy.msgbus.clear_by_owner(outliner_sync_handler)
    except Exception as e:
        print(f"Failed to clear message bus subscriptions: {e}")
    
    # Unregister traditional handlers
    handlers_to_unregister = [
        (bpy.app.handlers.depsgraph_update_post, outliner_sync_handler),
        (bpy.app.handlers.undo_post, outliner_sync_handler),
        (bpy.app.handlers.redo_post, outliner_sync_handler),
    ]
    
    for handler_list, handler_func in handlers_to_unregister:
        if handler_func in handler_list:
            handler_list.remove(handler_func)

CLASSES = [] 