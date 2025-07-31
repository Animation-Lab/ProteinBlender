"""Depsgraph update handler for selection changes"""

import bpy
from ..core.selection_manager import SelectionManager

# Track if we're updating to prevent recursion
_updating_from_depsgraph = False
# Track last known selection to detect changes
_last_selection = set()


def on_depsgraph_update(scene, depsgraph):
    """Handle depsgraph updates for selection changes"""
    global _updating_from_depsgraph, _last_selection
    
    # Skip if we're already updating or if outliner doesn't exist
    if _updating_from_depsgraph or not hasattr(scene, 'outliner_items'):
        return
    
    # Check current selection
    try:
        current_selection = set(obj.name for obj in bpy.context.selected_objects)
    except:
        # Context might not be available
        return
    
    # Only proceed if selection actually changed
    if current_selection == _last_selection:
        return
    
    _last_selection = current_selection
    _updating_from_depsgraph = True
    try:
        SelectionManager.sync_from_viewport(scene)
        # Redraw UI
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
    finally:
        _updating_from_depsgraph = False


def register():
    """Register depsgraph handler"""
    if on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)


def unregister():
    """Unregister depsgraph handler"""
    if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)