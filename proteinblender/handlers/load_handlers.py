import bpy
from bpy.app.handlers import persistent
from ..layout import workspace_setup

manager = None

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

def register_load_handlers():
    """Register the persistent load handler that recreates workspace after Ctrl+N"""
    global manager

    # Create workspace manager
    manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

    # Register the persistent handler (survives across new sessions)
    if create_workspace_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(create_workspace_on_load)

def unregister_load_handlers():
    """Unregister the load handler"""
    if create_workspace_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(create_workspace_on_load)

LASSES = []  # No classes to register, but keeping consistent with our pattern
