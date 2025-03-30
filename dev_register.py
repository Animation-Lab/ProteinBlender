import bpy
import os

# Automatically enable your add-on
bpy.ops.preferences.addon_enable(module="proteinblender")

# Or if you’re developing in-place without packaging:
addon_path = os.path.abspath(os.path.dirname(__file__))
if addon_path not in bpy.utils.script_paths("addons"):
    print(f"Add-on path not found in Blender's add-on directories: {addon_path}")

bpy.ops.wm.read_homefile(app_template="")  # optional
