bl_info = {
    "name": "ProteinBlender",
    "author": "Dillon Lee",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation",
    "category": "3D View"
}

import bpy
from . import panels
from . import properties
from . import operators
from . import handlers

def register():
    properties.register()
    operators.register()
    panels.register()
    handlers.register()

def unregister():
    handlers.unregister()
    panels.unregister()
    operators.unregister()
    properties.unregister()


if __name__ == "__main__":
    register()
