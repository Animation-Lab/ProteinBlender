import bpy
from ..layout import workspace_setup

max_retries = 10
current_retries = 0
manager = None

def load_handler():
    global current_retries
    # Check if workspaces have been initialized
    if bpy.data.workspaces:
        manager.create_custom_workspace()
        manager.add_panels_to_workspace()
        manager.set_properties_context()
        return None  # Stop the timer

    # Retry if workspaces are not ready
    if current_retries < max_retries:
        current_retries += 1
        return 1.0  # Retry after 1 second
    else:
        return None  # Stop the timer after max retries

def register_load_handlers():
    global manager
    manager = workspace_setup.ProteinWorkspaceManager("Protein Blender")
    
    global current_retries
    current_retries = 0
    # Start the load handler timer
    bpy.app.timers.register(load_handler, first_interval=1.0)

def unregister_load_handlers():
    # Remove the handlers
    if bpy.app.timers.is_registered(load_handler):
        bpy.app.timers.unregister(load_handler)

LASSES = []  # No classes to register, but keeping consistent with our pattern
