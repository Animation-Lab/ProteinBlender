import bpy
import time
from bpy.app.handlers import persistent
from ..layout import workspace_setup

manager = None

# Visibility sync throttling to avoid performance impact
_last_visibility_sync = 0
_sync_interval = 0.5  # Only sync every 500ms

@persistent
def create_workspace_on_load(dummy):
    """
    Persistent handler that recreates the Protein Blender workspace after:
    - Loading a .blend file
    - Creating a new file (Ctrl+N)
    - Any other file operation

    The @persistent decorator ensures this handler survives across new sessions.
    """
    global manager

    # Check if workspace already exists
    if "Protein Blender" not in bpy.data.workspaces:
        # Create workspace manager if it doesn't exist
        if manager is None:
            manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

        # Create the workspace
        try:
            manager.create_custom_workspace()
            manager.add_panels_to_workspace()
            manager.set_properties_context()
        except Exception as e:
            print(f"ProteinBlender: Error creating workspace: {e}")
            import traceback
            traceback.print_exc()

@persistent
def sync_outliner_visibility(scene, depsgraph):
    """
    Sync Blender's native object visibility back to outliner custom properties.
    This ensures the eye icons accurately reflect viewport visibility.

    Runs on depsgraph updates to catch visibility changes from:
    - Native Blender outliner
    - H key (hide/unhide)
    - Right-click menus
    - Scripts/operators

    Uses throttling to avoid performance impact from frequent depsgraph updates.
    """
    global _last_visibility_sync

    # Throttle: only run every 500ms to avoid performance impact
    current_time = time.time()
    if current_time - _last_visibility_sync < _sync_interval:
        return

    _last_visibility_sync = current_time

    # Only process if we have outliner items
    if not hasattr(scene, 'protein_outliner_items') or len(scene.protein_outliner_items) == 0:
        return

    # Get current view layer
    try:
        view_layer = bpy.context.view_layer
    except:
        return  # No context available

    if not view_layer:
        return

    # Track if any changes were made
    changes_made = False

    # Iterate through all outliner items and sync visibility
    for item in scene.protein_outliner_items:
        # Skip items without object references
        if not item.object_name:
            continue

        # Get the Blender object
        obj = bpy.data.objects.get(item.object_name)
        if not obj:
            continue

        # Get Blender's actual visibility state
        try:
            blender_visible = not obj.hide_get(view_layer=view_layer)
        except:
            continue  # Object may not be in this view layer

        # If outliner property doesn't match Blender's state, sync it
        if item.is_visible != blender_visible:
            item.is_visible = blender_visible
            changes_made = True

    # Force UI redraw if changes were made
    if changes_made:
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def register_load_handlers():
    """Register all persistent handlers (workspace and visibility sync)"""
    global manager

    # Create workspace manager
    manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

    # Register the persistent workspace handler (survives across new sessions)
    if create_workspace_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(create_workspace_on_load)

    # Register visibility sync handler for 2-way binding
    register_visibility_sync_handler()

def register_visibility_sync_handler():
    """Register the depsgraph handler for visibility sync"""
    if sync_outliner_visibility not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_outliner_visibility)

def unregister_visibility_sync_handler():
    """Unregister the visibility sync handler"""
    if sync_outliner_visibility in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_outliner_visibility)

def unregister_load_handlers():
    """Unregister all load handlers"""
    if create_workspace_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(create_workspace_on_load)

    # Unregister visibility sync handler
    unregister_visibility_sync_handler()

CLASSES = []  # No classes to register, but keeping consistent with our pattern
