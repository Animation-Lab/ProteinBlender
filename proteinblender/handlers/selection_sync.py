"""Two-way selection sync between Blender's viewport and the ProteinBlender outliner.

Outliner -> viewport: handled directly by the outliner_select operator
(sync_outliner_to_blender_selection).

Viewport -> outliner: handled by a lightweight polling timer (_selection_poll).
Blender has no reliable event for selection changes — the msgbus "select" key is
not a real Object RNA property in Blender 4.x+/5.x (so the subscription never
fires), and selection changes do not emit depsgraph_update_post. Polling the
selection set on a short timer is the robust, version-proof approach. The msgbus
subscriptions are kept as a best-effort fast path where they happen to work.
"""

import bpy
from ..utils.scene_manager import ProteinBlenderScene
from ..utils.chain_utils import get_chain_objects


# Global variables for selection tracking
_update_pending = False  # Track if an update is already scheduled
_update_in_progress = False  # Track if update is currently running
_msgbus_owner = None  # Owner object for msgbus subscriptions
_subscribed_objects = set()  # Track which objects we've subscribed to

# Viewport -> outliner polling (the reliable path)
_POLL_INTERVAL = 0.2  # seconds
_last_selection_key = None  # cache: (sorted selected names, active name)


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


def _puppet_members_all_selected(scene, scene_manager, puppet_item, selected_names):
    """True if every chain/domain member of a puppet has all of its objects
    selected in the viewport. Lets the puppet row tick when its whole
    membership is selected (not only when its controller Empty is)."""
    members = [m for m in (puppet_item.puppet_memberships or "").split(",") if m]
    if not members:
        return False
    by_id = {it.item_id: it for it in scene.outliner_items}
    objects = []
    for member_id in members:
        member = by_id.get(member_id)
        if member is None:
            return False
        if member.item_type == 'CHAIN':
            resolved = get_chain_objects(scene_manager.molecules.get(member.parent_id), member)
        elif member.object_name:
            obj = bpy.data.objects.get(member.object_name)
            resolved = [obj] if obj else []
        else:
            resolved = []
        if not resolved:
            return False
        objects.extend(resolved)
    return all(o.name in selected_names for o in objects)


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
    
    # A puppet ticks when its controller Empty is selected OR when its whole
    # membership (all member chains) is selected.
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET':
            controller_selected = False
            if item.controller_object_name:
                empty_obj = bpy.data.objects.get(item.controller_object_name)
                controller_selected = bool(empty_obj and empty_obj.select_get())
            item.is_selected = controller_selected or _puppet_members_all_selected(
                scene, scene_manager, item, selected_names)
    
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
            # Resolve the chain to its backing object(s) — a single object for
            # a whole chain or copy, several for a chain split into domains —
            # then treat the chain as selected only when all of them are.
            parent_molecule = scene_manager.molecules.get(item.parent_id)
            chain_objs = get_chain_objects(parent_molecule, item)
            item.is_selected = bool(chain_objs) and all(
                o.name in selected_names for o in chain_objs
            )
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
            # Runs only when the user explicitly clicks a chain checkbox.
            # Resolve the chain to its backing object(s): a single object for a
            # whole chain or a copy, or every domain object once the chain has
            # been split. (The chain-index vs. chain-letter mismatch this used
            # to get wrong is now handled inside get_chain_objects.)
            parent_molecule = scene_manager.molecules.get(item.parent_id)
            chain_objs = get_chain_objects(parent_molecule, item)

            active_set = False
            for obj in chain_objs:
                obj.select_set(item.is_selected)
                if item.is_selected and not active_set:
                    context.view_layer.objects.active = obj
                    active_set = True

            # Keep the chain's domain checkboxes in sync (split chains).
            selected_obj_names = {o.name for o in chain_objs}
            for domain_item in scene.outliner_items:
                if (domain_item.item_type == 'DOMAIN'
                        and domain_item.parent_id == item.item_id
                        and domain_item.object_name in selected_obj_names):
                    domain_item.is_selected = item.is_selected
        
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


def _selection_poll():
    """Mirror the viewport selection into the outliner checkboxes.

    Runs on a short repeating timer because Blender has no reliable selection
    event (see module docstring). Cheap when nothing changed: build a key from
    the selected-object names + active object and compare to the last one; only
    do real work on an actual change.
    """
    global _last_selection_key, _update_pending
    try:
        if _update_in_progress or _update_pending:
            return _POLL_INTERVAL
        view_layer = getattr(bpy.context, "view_layer", None)
        if view_layer is None:
            return _POLL_INTERVAL
        selected = tuple(sorted(o.name for o in view_layer.objects if o.select_get()))
        active = view_layer.objects.active
        key = (selected, active.name if active else None)
        if key != _last_selection_key:
            _last_selection_key = key
            update_outliner_from_blender_selection()
    except Exception:
        pass
    return _POLL_INTERVAL  # reschedule


def on_load_post(dummy):
    """Handler for file load to refresh subscriptions."""
    global _last_selection_key
    _last_selection_key = None  # force a resync against the freshly loaded file
    refresh_object_subscriptions()


def _delayed_init():
    """Delayed initialization to run after Blender is fully loaded."""
    refresh_object_subscriptions()
    return None  # Stop the timer


def register():
    """Register selection sync: msgbus (best-effort) + the reliable poll timer."""
    # Clear any existing handlers
    clear_selection_handlers()

    # Best-effort msgbus subscriptions (fast path where supported)
    refresh_object_subscriptions()
    bpy.app.timers.register(_delayed_init, first_interval=0.1, persistent=False)

    # Reliable viewport -> outliner sync: poll the selection on a timer
    if not bpy.app.timers.is_registered(_selection_poll):
        bpy.app.timers.register(_selection_poll, first_interval=_POLL_INTERVAL,
                                persistent=True)

    # Register load handler to refresh subscriptions after file load
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    """Unregister all selection sync handlers."""
    # Clear msgbus subscriptions
    clear_selection_handlers()

    # Stop the poll timer
    if bpy.app.timers.is_registered(_selection_poll):
        bpy.app.timers.unregister(_selection_poll)

    # Remove load handler
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)