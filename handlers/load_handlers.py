import bpy
from ..layout import workspace_setup

max_retries = 10
current_retries = 0

def load_handler():
    global current_retries

    # Check if workspaces have been initialized
    if bpy.data.workspaces:
        print('blender version: ', bpy.app.version)
        print("Workspaces have been initialized!")
        workspace_setup.create_custom_workspace()
        return None  # Stop the timer

    # Retry if workspaces are not ready
    if current_retries < max_retries:
        current_retries += 1
        print(f"Workspaces not ready, retrying... ({current_retries}/{max_retries})")
        return 1.0  # Retry after 1 second
    else:
        print("Failed to initialize workspaces after maximum retries.")
        return None  # Stop the timer after max retries

def register():
    global current_retries
    current_retries = 0
    # Start the load handler timer
    bpy.app.timers.register(load_handler, first_interval=1.0)

def unregister():
    # Remove the handlers
    bpy.app.timers.unregister(load_handler)

