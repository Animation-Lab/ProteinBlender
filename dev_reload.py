import bpy
import sys
import importlib

# Unregister if already registered
if "proteinblender" in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_disable(module="proteinblender")

# Get all modules starting with 'proteinblender'
proteinblender_modules = [mod for mod in sys.modules if mod.startswith('proteinblender')]

# Remove them from sys.modules to force Python to reload them
for mod in proteinblender_modules:
    del sys.modules[mod]

# Re-enable the addon
bpy.ops.preferences.addon_enable(module="proteinblender") 