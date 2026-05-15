"""Selection synchronization handler for two-way binding between Blender and ProteinBlender outliner.

This module handles synchronization between Blender's viewport selection and the
ProteinBlender outliner checkboxes. It uses msgbus subscriptions for efficient
notification of selection changes.

Key improvements in this refactored version:
- Fixed race condition by keeping depth counter incremented until timer fires
- Simplified handler structure
- Removed redundant depsgraph handler (now only uses msgbus)
"""

import bpy
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.blender_utils import is_object_valid


# Global variables for selection tracking
_update_pending = False  # Track if an update is already scheduled
_update_in_progress = False  # Track if update is currently running
_msgbus_owner = None  # Owner object for msgbus subscriptions
_subscribed_objects = set()  # Track which objects we've subscribed to


def on_selection_changed(*args):
    """Callback for msgbus when selection changes.

    Schedules a deferred update to avoid issues during msgbus callback context.
    Uses a pending flag instead of depth counter to properly handle the race condition.
    """
    global _update_pending, _update_in_progress

    # Prevent recursive updates
    if _update_in_progress or _update_pending:
        return

    # Mark update as pending and schedule it
    _update_pending = True
    bpy.app.timers.register(_deferred_selection_update, first_interval=0.01, persistent=False)


def _deferred_selection_update():
    """Deferred update to handle selection changes outside of msgbus callback context.

    This runs after a short delay to ensure Blender's selection state is fully updated.
    """
    global _update_pending, _update_in_progress

    # Clear pending flag now that we're running
    _update_pending = False

    # Prevent recursive updates
    if _update_in_progress:
        return None

    _update_in_progress = True
    try:
        update_outliner_from_blender_selection()
    except Exception as e:
        print(f"Error in selection sync: {e}")
    finally:
        _update_in_progress = False

    return None  # Stop the timer


def subscribe_to_object_selection(obj):
    """Subscribe to selection changes for a specific object"""
    global _msgbus_owner, _subscribed_objects

    if not _msgbus_owner or obj.name in _subscribed_objects:
        return

    try:
        # Subscribe to this object's select property
        key = obj.path_resolve("select", False)
        bpy.msgbus.subscribe_rna(
            key=key,
            owner=_msgbus_owner,
            args=(),
            notify=on_selection_changed,
        )
        _subscribed_objects.add(obj.name)
    except Exception:
        # Object may not support selection subscription
        pass


def clear_selection_handlers():
    """Clear all msgbus subscriptions"""
    global _msgbus_owner, _subscribed_objects

    if _msgbus_owner is not None:
        try:
            bpy.msgbus.clear_by_owner(_msgbus_owner)
        except Exception:
            pass
        _msgbus_owner = None

    _subscribed_objects.clear()


def refresh_object_subscriptions():
    """Refresh msgbus subscriptions for all objects in the scene"""
    global _msgbus_owner, _subscribed_objects

    # Clear existing subscriptions
    clear_selection_handlers()

    # Create new owner
    _msgbus_owner = object()
    _subscribed_objects = set()

    # Check if we have access to bpy.data (not available during registration)
    try:
        # Subscribe to all selectable objects
        if hasattr(bpy.data, 'objects'):
            for obj in bpy.data.objects:
                if obj.type not in {'CAMERA', 'LIGHT'}:  # Skip non-selectable types
                    subscribe_to_object_selection(obj)
    except Exception:
        pass  # Will be set up on first file load

    # Always subscribe to the generic Object selection property for new objects
    try:
        key = (bpy.types.Object, "select")
        bpy.msgbus.subscribe_rna(
            key=key,
            owner=_msgbus_owner,
            args=(),
            notify=on_selection_changed,
        )
    except Exception:
        pass


def update_outliner_from_blender_selection():
    """Update protein outliner selection based on Blender's selection"""
    scene = bpy.context.scene
    scene_manager = ProteinBlenderScene.get_instance()

    # Get selected objects in a context-safe way
    try:
        # Try the normal way first
        selected_objects = bpy.context.selected_objects
    except AttributeError:
        # Fallback: get selected objects from the view layer
        try:
            view_layer = bpy.context.view_layer
            if view_layer:
                selected_objects = [obj for obj in view_layer.objects if obj.select_get()]
            else:
                # If no view layer available, check the scene directly
                selected_objects = [obj for obj in scene.objects if obj.select_get()]
        except:
            # If all else fails, return early
            selected_objects = []

    # Build set of selected object names for quick lookup
    selected_names = {obj.name for obj in selected_objects}
    
    # Update puppet selection based ONLY on their controller Empty objects
    # Puppets without controllers should always be deselected
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET':
            if item.controller_object_name:
                # Check if the Empty controller is selected
                empty_obj = bpy.data.objects.get(item.controller_object_name)
                if empty_obj:
                    item.is_selected = empty_obj.select_get()
                else:
                    # Controller doesn't exist, deselect puppet
                    item.is_selected = False
            else:
                # No controller assigned, puppet should be deselected
                item.is_selected = False
    
    # Update outliner selection state for other items
    for item in scene.outliner_items:
        # Skip puppets - already handled above
        if item.item_type == 'PUPPET':
            continue
        # For domains and proteins with direct objects
        elif item.item_type in ['DOMAIN', 'PROTEIN'] and item.object_name:
            # Check if the object is selected in the viewport
            if item.object_name in selected_names:
                item.is_selected = True
            else:
                item.is_selected = False
        elif item.item_type == 'CHAIN':
            # For chains, check if the chain object itself is selected in the viewport
            # First, try to find the chain's object by checking if item has object_name
            chain_object_selected = False

            if item.object_name:
                # Direct chain object (for full chain domains)
                chain_object_selected = item.object_name in selected_names
            else:
                # Check if this is a chain item that references a domain
                # Extract chain info and find the corresponding domain object
                chain_id_str = item.item_id.split('_chain_')[-1] if '_chain_' in item.item_id else ""
                if chain_id_str:
                    try:
                        chain_id = int(chain_id_str)
                    except:
                        chain_id = chain_id_str

                    # Get parent molecule
                    parent_molecule = scene_manager.molecules.get(item.parent_id)
                    if parent_molecule:
                        # Find the domain that represents this chain
                        for domain in parent_molecule.domains.values():
                            if domain.object and hasattr(domain, 'chain_id'):
                                # Check if this domain belongs to the chain
                                if str(domain.chain_id) == str(chain_id):
                                    # Check if this domain's object is selected
                                    if domain.object.name in selected_names:
                                        chain_object_selected = True
                                        break

            # Update chain selection based on whether its object is selected
            item.is_selected = chain_object_selected
        else:
            # For other items without objects, deselect
            item.is_selected = False
    
    # Update all reference items to match their originals
    # This is a one-way sync from original to reference only
    for item in scene.outliner_items:
        if "_ref_" in item.item_id and item.reference_target_id:
            # Find the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == item.reference_target_id:
                    item.is_selected = orig_item.is_selected
                    break
    
    # Puppets no longer cascade their selection to members
    # The puppet checkbox only controls the Empty controller
    
    # Sync color picker to match selected item's color
    from ..panels.visual_setup_panel import sync_color_to_selection
    sync_color_to_selection(bpy.context)
    
    # Update UI - force redraw to show checkbox changes
    for area in bpy.context.screen.areas:
        if area.type in ['PROPERTIES', 'VIEW_3D']:
            area.tag_redraw()
    
    # Also force region redraw
    if bpy.context.region:
        bpy.context.region.tag_redraw()


def sync_outliner_to_blender_selection(context, item_id):
    """Sync outliner selection to Blender objects.

    Called when user clicks on an outliner checkbox to propagate the selection
    change to Blender's viewport.
    """
    global _update_in_progress

    # Prevent recursive updates
    if _update_in_progress:
        return

    _update_in_progress = True
    try:
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Check if this is a reference item and get the actual item ID
        actual_item_id = item_id
        if "_ref_" in item_id:
            # Find the reference item to get the actual ID
            for ref_item in scene.outliner_items:
                if ref_item.item_id == item_id and ref_item.reference_target_id:
                    actual_item_id = ref_item.reference_target_id
                    break
        
        # Find the item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == actual_item_id:
                item = outliner_item
                break
        
        if not item:
            return
        
        # Handle selection based on item type
        if item.item_type == 'PROTEIN':
            # Select/deselect protein and all its domains
            molecule = scene_manager.molecules.get(item_id)
            if molecule and molecule.object:
                molecule.object.select_set(item.is_selected)
                
                # Update all domains
                for domain in molecule.domains.values():
                    if domain.object:
                        try:
                            # Check if object is still valid before accessing it
                            domain.object.name  # This will raise ReferenceError if invalid
                            domain.object.select_set(item.is_selected)
                        except ReferenceError:
                            # Object has been removed, try to refresh from name
                            if hasattr(domain, 'object_name') and domain.object_name:
                                fresh_obj = bpy.data.objects.get(domain.object_name)
                                if fresh_obj:
                                    domain.object = fresh_obj
                                    fresh_obj.select_set(item.is_selected)
                
                # Make protein the active object if selected
                if item.is_selected:
                    context.view_layer.objects.active = molecule.object
                    
        elif item.item_type == 'DOMAIN':
            # Select/deselect just the domain
            if item.object_name:
                obj = bpy.data.objects.get(item.object_name)
                if obj:
                    obj.select_set(item.is_selected)
                    
                    # Make domain the active object if selected
                    if item.is_selected:
                        context.view_layer.objects.active = obj
                        
        elif item.item_type == 'CHAIN':
            # IMPORTANT: Only select/deselect domains when the chain checkbox is EXPLICITLY clicked
            # This function is called when the user clicks on the chain checkbox in the UI
            # We still want chains to be able to select all their domains, but only when
            # explicitly triggered by the user, not through automatic propagation

            # Check if this is a chain copy (item_id is directly a domain_id)
            # or a regular chain (item_id is "molecule_id_chain_X")
            parent_molecule = scene_manager.molecules.get(item.parent_id)

            if parent_molecule:
                # First check if item_id is directly a domain_id (for chain copies)
                if item.item_id in parent_molecule.domains:
                    # This is a chain copy - select only this specific domain
                    target_domain = parent_molecule.domains[item.item_id]

                    if target_domain and target_domain.object:
                        try:
                            # Check if object is still valid before accessing it
                            target_domain.object.name  # This will raise ReferenceError if invalid
                            target_domain.object.select_set(item.is_selected)
                            # Set as active if selected
                            if item.is_selected:
                                context.view_layer.objects.active = target_domain.object
                        except ReferenceError:
                            # Object has been removed, try to refresh from name
                            if hasattr(target_domain, 'object_name') and target_domain.object_name:
                                fresh_obj = bpy.data.objects.get(target_domain.object_name)
                                if fresh_obj:
                                    target_domain.object = fresh_obj
                                    fresh_obj.select_set(item.is_selected)
                                    if item.is_selected:
                                        context.view_layer.objects.active = fresh_obj

                else:
                    # Regular chain - when user explicitly clicks chain checkbox,
                    # select/deselect all non-copy domains belonging to this chain
                    # Extract chain identifier from item_id (format: "molecule_id_chain_X")
                    chain_id_str = item.item_id.split('_chain_')[-1]
                    try:
                        chain_id = int(chain_id_str)
                    except:
                        chain_id = chain_id_str

                    # Select/deselect all non-copy domains of this chain
                    # Also update the domain checkboxes in the outliner to match
                    active_set = False
                    for domain_id, domain in parent_molecule.domains.items():
                        # Skip domain copies - they have their own chain items
                        if hasattr(domain, 'is_copy') and domain.is_copy:
                            continue

                        # Check if domain belongs to this chain
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
                                # Update the domain's outliner checkbox to match chain selection
                                # This ensures UI consistency when chain is selected
                                for domain_item in scene.outliner_items:
                                    if (domain_item.item_type == 'DOMAIN' and
                                        domain_item.object_name == domain.object.name):
                                        domain_item.is_selected = item.is_selected
                                        break

                                if domain.object:
                                    try:
                                        # Check if object is still valid before accessing it
                                        domain.object.name  # This will raise ReferenceError if invalid
                                        domain.object.select_set(item.is_selected)
                                        # Set the first selected domain as active
                                        if item.is_selected and not active_set:
                                            context.view_layer.objects.active = domain.object
                                            active_set = True
                                    except ReferenceError:
                                        # Object has been removed, try to refresh from name
                                        if hasattr(domain, 'object_name') and domain.object_name:
                                            fresh_obj = bpy.data.objects.get(domain.object_name)
                                            if fresh_obj:
                                                domain.object = fresh_obj
                                                fresh_obj.select_set(item.is_selected)
                                                if item.is_selected and not active_set:
                                                    context.view_layer.objects.active = fresh_obj
                                                    active_set = True
        
        elif item.item_type == 'PUPPET':
            # Select/deselect the puppet's Empty controller if it exists
            puppet_item = item
            if puppet_item.controller_object_name:
                empty_obj = bpy.data.objects.get(puppet_item.controller_object_name)
                if empty_obj:
                    empty_obj.select_set(item.is_selected)

                    # Make Empty the active object if selected
                    if item.is_selected:
                        context.view_layer.objects.active = empty_obj

            # Don't cascade to members - puppet checkbox only controls the controller
            return

    finally:
        _update_in_progress = False


def update_outliner_selection_display(context):
    """Update outliner to show current selection state"""
    # Force redraw of properties panel
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def on_load_post(dummy):
    """Handler for file load to refresh subscriptions."""
    refresh_object_subscriptions()


def _delayed_init():
    """Delayed initialization to run after Blender is fully loaded."""
    refresh_object_subscriptions()
    return None  # Stop the timer


def register():
    """Register all selection sync handlers.

    Note: We no longer use depsgraph_update_post as it causes performance issues
    and conflicts with the msgbus-based selection sync. The msgbus approach is
    sufficient for tracking selection changes.
    """
    # Clear any existing handlers
    clear_selection_handlers()

    # Try to initialize msgbus subscriptions
    refresh_object_subscriptions()

    # Schedule a delayed initialization in case Blender isn't fully ready yet
    bpy.app.timers.register(_delayed_init, first_interval=0.1, persistent=False)

    # Register load handler to refresh subscriptions after file load
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    """Unregister all selection sync handlers."""
    # Clear msgbus subscriptions
    clear_selection_handlers()

    # Remove load handler
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)