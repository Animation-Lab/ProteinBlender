"""Selection synchronization handler for two-way binding between Blender and ProteinBlender outliner"""

import bpy
from ..utils.scene_manager import ProteinBlenderScene


# Global variables for selection tracking
_selection_update_depth = 0  # Use depth counter to prevent recursion
_msgbus_owner = None  # Owner object for msgbus subscriptions
_subscribed_objects = set()  # Track which objects we've subscribed to


def on_selection_changed(*args):
    """Callback for msgbus when selection changes"""
    global _selection_update_depth

    # Prevent recursive updates
    if _selection_update_depth > 0:
        return

    _selection_update_depth += 1
    try:
        # Defer the actual update to avoid issues during msgbus callback
        bpy.app.timers.register(lambda: deferred_selection_update(), first_interval=0.01, persistent=False)
    finally:
        _selection_update_depth -= 1


def deferred_selection_update():
    """Deferred update to handle selection changes outside of msgbus callback context"""
    global _selection_update_depth

    if _selection_update_depth > 0:
        return None  # Return None to stop the timer

    _selection_update_depth += 1
    try:
        update_outliner_from_blender_selection()
    finally:
        _selection_update_depth -= 1

    return None  # Return None to stop the timer


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
    selected_objects = bpy.context.selected_objects
    
    # Build set of selected object names for quick lookup
    selected_names = {obj.name for obj in selected_objects}
    
    # First check if any puppet Empty controllers are selected
    # Store current puppet selection states to preserve them if needed
    puppet_states = {}
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET':
            puppet_states[item.item_id] = item.is_selected

            if item.controller_object_name:
                # Check if the Empty controller is selected
                if item.controller_object_name in selected_names:
                    item.is_selected = True
                else:
                    # Only deselect if we're sure the Empty is not selected
                    # Check if the Empty object actually exists
                    empty_obj = bpy.data.objects.get(item.controller_object_name)
                    if empty_obj and not empty_obj.select_get():
                        item.is_selected = False
                    elif not empty_obj:
                        # Empty doesn't exist, clear selection
                        item.is_selected = False
    
    # Update outliner selection state for other items
    for item in scene.outliner_items:
        # Skip puppets - already handled above
        if item.item_type == 'PUPPET':
            continue
        # For items with direct objects, check if selected
        elif item.object_name and item.object_name in selected_names:
            item.is_selected = True
        elif item.item_type == 'CHAIN':
            # Extract chain info
            chain_id_str = item.item_id.split('_chain_')[-1]
            try:
                chain_id = int(chain_id_str)
            except:
                chain_id = chain_id_str
            
            # Get parent molecule
            parent_molecule = scene_manager.molecules.get(item.parent_id)
            if parent_molecule:
                # Check if any domain of this chain is selected
                chain_has_selection = False
                for domain in parent_molecule.domains.values():
                    if domain.object:
                        try:
                            # Check if object is still valid before accessing it
                            obj_name = domain.object.name
                            if obj_name in selected_names:
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
                                        chain_has_selection = True
                                        break
                        except ReferenceError:
                            # Object has been removed, skip this domain
                            pass
                
                item.is_selected = chain_has_selection
            else:
                item.is_selected = False
        else:
            # For other items without objects, deselect
            item.is_selected = False
    
    # Update all reference items to match their originals
    # This is a one-way sync from original to reference only
    for item in scene.outliner_items:
        if "_ref_" in item.item_id and item.puppet_memberships:
            # Find the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == item.puppet_memberships:
                    if item.is_selected != orig_item.is_selected:
                        item.is_selected = orig_item.is_selected
                    break
    
    # When a puppet Empty is selected/deselected, also update all its member items
    for puppet_item in scene.outliner_items:
        if puppet_item.item_type == 'PUPPET':
            # Get member IDs from the puppet
            member_ids = puppet_item.puppet_memberships.split(',') if puppet_item.puppet_memberships else []
            
            # Update all reference items under this puppet to match puppet's selection state
            for ref_item in scene.outliner_items:
                if ref_item.parent_id == puppet_item.item_id and "_ref_" in ref_item.item_id:
                    ref_item.is_selected = puppet_item.is_selected
            
            # Also update the original items to match puppet's selection state
            for member_id in member_ids:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        item.is_selected = puppet_item.is_selected
                        break
    
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
    """Sync outliner selection to Blender objects"""
    global _selection_update_depth
    
    # Prevent recursive updates
    if _selection_update_depth > 2:  # Allow some depth for legitimate nested calls
        return
    
    _selection_update_depth += 1
    try:
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Check if this is a reference item and get the actual item ID
        actual_item_id = item_id
        if "_ref_" in item_id:
            # Find the reference item to get the actual ID
            for ref_item in scene.outliner_items:
                if ref_item.item_id == item_id and ref_item.puppet_memberships:
                    actual_item_id = ref_item.puppet_memberships
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
                    # Regular chain - select all non-copy domains belonging to this chain
                    # Extract chain identifier from item_id (format: "molecule_id_chain_X")
                    chain_id_str = item.item_id.split('_chain_')[-1]
                    try:
                        chain_id = int(chain_id_str)
                    except:
                        chain_id = chain_id_str
                    
                    # Select/deselect all non-copy domains of this chain
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
            
            # Don't cascade to members - the Empty's parent-child relationship handles that
            return
    
    finally:
        _selection_update_depth -= 1


def update_outliner_selection_display(context):
    """Update outliner to show current selection state"""
    # Force redraw of properties panel
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def on_depsgraph_update_post(scene, depsgraph):
    """Handler for depsgraph updates to catch new objects"""
    # Check if any new objects were added
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object):
            obj = update.id
            if obj.name not in _subscribed_objects:
                subscribe_to_object_selection(obj)


def on_load_post(dummy):
    """Handler for file load to refresh subscriptions"""
    refresh_object_subscriptions()


def delayed_init():
    """Delayed initialization to run after Blender is fully loaded"""
    refresh_object_subscriptions()
    return None  # Stop the timer


def register():
    """Register all selection sync handlers"""
    # Clear any existing handlers
    clear_selection_handlers()

    # Try to initialize msgbus subscriptions
    refresh_object_subscriptions()

    # Schedule a delayed initialization in case Blender isn't fully ready yet
    bpy.app.timers.register(delayed_init, first_interval=0.1, persistent=False)

    # Register depsgraph handler to catch new objects
    if on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update_post)

    # Register load handler to refresh subscriptions after file load
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    """Unregister all selection sync handlers"""
    # Clear msgbus subscriptions
    clear_selection_handlers()

    # Remove depsgraph handler
    if on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update_post)

    # Remove load handler
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)