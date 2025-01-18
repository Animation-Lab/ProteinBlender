import os
import sys

# Add libs directory to Python path
libs_path = os.path.join(os.path.dirname(__file__), "libs")
if libs_path not in sys.path:
    sys.path.append(libs_path)

import bpy

from . import operators
from . import handlers
from . import panels
from . import properties

bl_info = {
    "name": "Protein Blender",
    "author": "Dillon Lee",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "Automatic",
    "description": "Creates a specialized Protein Blender workspace on startup",
    "category": "Interface",
}

def register():
    properties.register()
    operators.register()
    panels.register()
    handlers.register()

def unregister():
    properties.unregister()
    operators.unregister()
    panels.unregister()
    handlers.unregister()


if __name__ == "__main__":
    register()
