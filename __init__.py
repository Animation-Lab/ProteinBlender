import bpy
import importlib
import sys
from pathlib import Path
import os

bl_info = {
    "name": "ProteinBlender",
    "author": "Dillon Lee",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation",
    "category": "3D View"
}

# Get the folder containing this file
ADDON_DIR = Path(__file__).parent.resolve()

# Add the wheels directory to Python path
WHEELS_DIR = ADDON_DIR / "wheels"
if str(WHEELS_DIR) not in sys.path:
    sys.path.append(str(WHEELS_DIR))

# Import local modules
import proteinblender

# First unregister if necessary
try:
    proteinblender.unregister()
except Exception as e:
    print(f"Note: No need to unregister: {str(e)}")

# Reload all proteinblender modules
proteinblender_modules = [mod for mod in sys.modules if mod.startswith('proteinblender')]
for mod in proteinblender_modules:
    del sys.modules[mod]

# Re-import main module
import proteinblender

def register():
    proteinblender.register()

def unregister():
    proteinblender.unregister()

if __name__ == "__main__":
    register()