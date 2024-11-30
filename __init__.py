bl_info = {
    "name": "Protein Blender",
    "author": "Dillon Lee",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "Automatic",
    "description": "Creates a specialized Protein Blender workspace on startup",
    "category": "Interface",
}

import bpy
from . import workspace_setup

max_retries = 10
current_retries = 0

def load_handler():
    global current_retries

    # Check if workspaces have been initialized
    if bpy.data.workspaces:
        print("Workspaces have been initialized!")
        # Perform your operations here
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
    current_retries = 0  # Reset retry counter
    bpy.app.timers.register(load_handler, first_interval=1.0)  # Start with a 1-second delay


def unregister():
    pass

if __name__ == "__main__":
    register()