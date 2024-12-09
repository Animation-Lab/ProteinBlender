# protein_workspace/__init__.py
import bpy

from . import handlers

bl_info = {
    "name": "Protein Blender",
    "author": "Dillon Lee",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "Automatic",
    "description": "Creates a specialized Protein Blender workspace on startup",
    "category": "Interface",
}
def register():
    handlers.register()

def unregister():
    handlers.unregister()

if __name__ == "__main__":
    register()
