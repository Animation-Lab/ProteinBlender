bl_info = {
    "name": "ProteinBlender",
    "author": "Dillon Lee",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > ProteinBlender",
    "description": "A Blender addon for protein visualization and animation",
    "category": "3D View"
}

from .addon import register, unregister, _test_register

