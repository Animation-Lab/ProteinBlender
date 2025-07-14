import bpy
import sys  # Add sys import
# Development loader: build & install all dependencies via Blender's extension build
import os
import site # Import site module to find user site-packages

# Path to your plugin source
addon_root = os.path.abspath(os.path.dirname(__file__))
# plugin_dir = os.path.join(addon_root, "proteinblender") # No longer needed for build op

# Add the addon root directory to Python's path
if addon_root not in sys.path:
    sys.path.append(addon_root)

# Add user site-packages directory to Python's path
user_site_packages = site.getusersitepackages()
if os.path.exists(user_site_packages) and user_site_packages not in sys.path:
    sys.path.append(user_site_packages)
    print(f"Added user site-packages to sys.path: {user_site_packages}")


# Build + install the addon and its wheel dependencies into Blender
# try: # Remove the failing build call
#     bpy.ops.extension.build(
#         source_dir=plugin_dir,
#         output_dir=".",
#         split_platforms=False,
#         install=True,
#         install_deps=True,
#     )
# except Exception as e:
#     print(f"Extension build/install failed: {e}")


# Enable the addon
try: # Add try/except around enable for better error reporting
    bpy.ops.preferences.addon_enable(module="proteinblender")
    print("Successfully enabled 'proteinblender' addon.")
except Exception as e:
    print(f"Error enabling 'proteinblender' addon: {e}")
    # Attempt to provide more context if it's a module not found error again
    import traceback
    traceback.print_exc()


# Optionally reset to Blender's default scene
# bpy.ops.wm.read_homefile(app_template="")  # optional
