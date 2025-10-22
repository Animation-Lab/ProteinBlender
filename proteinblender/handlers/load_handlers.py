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

    print("ProteinBlender: load_post handler triggered")

    # Check if workspace already exists
    if "Protein Blender" not in bpy.data.workspaces:
        print("ProteinBlender: Workspace missing, recreating...")

        # Create workspace manager if it doesn't exist
        if manager is None:
            manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

        # Create the workspace
        try:
            manager.create_custom_workspace()
            manager.add_panels_to_workspace()
            manager.set_properties_context()
            print("ProteinBlender: Workspace created successfully")
        except Exception as e:
            print(f"ProteinBlender: Error creating workspace: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("ProteinBlender: Workspace already exists, no action needed")

def register_load_handlers():
    """Register the persistent load handler"""
    global manager

    # Create workspace manager
    manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")

    # Register the persistent handler
    if create_workspace_on_load not in bpy.app.handlers.load_post:
        print("ProteinBlender: Registering persistent load_post handler")
        bpy.app.handlers.load_post.append(create_workspace_on_load)

    # Try to create workspace immediately if possible
    # (only works if bpy.data is fully initialized, otherwise the timer will handle it)
    try:
        if bpy.data.workspaces and "Protein Blender" not in bpy.data.workspaces:
            manager.create_custom_workspace()
            manager.add_panels_to_workspace()
            manager.set_properties_context()
            print("ProteinBlender: Initial workspace created on addon registration")
    except (AttributeError, RuntimeError) as e:
        # bpy.data.workspaces not accessible yet - that's okay, the timer will handle it
        print(f"ProteinBlender: Workspace creation deferred to timer (data not ready yet)")

def unregister_load_handlers():
    """Unregister the load handler"""
    # Remove the persistent handler
    if create_workspace_on_load in bpy.app.handlers.load_post:
        print("ProteinBlender: Unregistering load_post handler")
        bpy.app.handlers.load_post.remove(create_workspace_on_load)

LASSES = []  # No classes to register, but keeping consistent with our pattern
