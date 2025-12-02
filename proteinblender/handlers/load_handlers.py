import bpy
from bpy.app.handlers import persistent
from ..layout import workspace_setup
from ..utils.scene_manager import ProteinBlenderScene

_workspace_manager = None


@persistent
def reset_scene_manager_on_load(dummy):
    """Reset scene manager when a new file is loaded/created.
    
    This ensures clean state and prevents stale references to deleted objects.
    Called before workspace creation to ensure fresh start.
    
    Following Blender addon best practices:
    - Use @persistent decorator for file lifecycle handlers
    - Reset state before any operations
    - Handle errors gracefully
    """
    try:
        ProteinBlenderScene.reset()
    except Exception as e:
        # Log error but don't fail - reset is best-effort
        print(f"ProteinBlender: Warning during scene manager reset: {e}")
        # Force reset even if cleanup failed
        ProteinBlenderScene._instance = None


@persistent
def create_workspace_on_load(dummy):
    """Recreate the Protein Blender workspace after loading/creating a file."""
    global _workspace_manager

    if "Protein Blender" in bpy.data.workspaces:
        return

    if _workspace_manager is None:
        _workspace_manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

    try:
        _workspace_manager.create_custom_workspace()
        _workspace_manager.add_panels_to_workspace()
        _workspace_manager.set_properties_context()
    except Exception as e:
        print(f"ProteinBlender: Error creating workspace: {e}")
        import traceback
        traceback.print_exc()


def _register_handler(handler_list, handler):
    """Helper to register a handler if not already registered."""
    if handler not in handler_list:
        handler_list.append(handler)


def _unregister_handler(handler_list, handler):
    """Helper to unregister a handler if registered."""
    if handler in handler_list:
        handler_list.remove(handler)


def register_load_handlers():
    """Register all persistent handlers.
    
    Order matters: reset_scene_manager_on_load must run before create_workspace_on_load
    to ensure clean state before workspace operations.
    """
    global _workspace_manager
    _workspace_manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")
    # Register reset handler first (runs before workspace creation)
    _register_handler(bpy.app.handlers.load_post, reset_scene_manager_on_load)
    # Register workspace creation handler
    _register_handler(bpy.app.handlers.load_post, create_workspace_on_load)


def unregister_load_handlers():
    """Unregister all load handlers."""
    _unregister_handler(bpy.app.handlers.load_post, reset_scene_manager_on_load)
    _unregister_handler(bpy.app.handlers.load_post, create_workspace_on_load)


CLASSES = []
