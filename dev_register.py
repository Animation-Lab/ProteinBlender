"""Development loader: enable ProteinBlender from this source tree.

Run with:  blender --python dev_register.py

Puts the repo root and Blender's user site-packages on sys.path, then enables the
addon for this session only.

The enable deliberately uses ``addon_utils.enable(default_set=False)`` rather than
``bpy.ops.preferences.addon_enable``. The operator sets the user preference, and with
Blender's default "Auto-Save Preferences" that writes ``proteinblender`` into
userpref.blend permanently. The module lives only in this repo and is only importable
while this script has run, so every *other* Blender launch would then fail at startup
with: Add-on not loaded: "proteinblender", cause: No module named 'proteinblender'.
Loading from source must not leave persistent state in the user's preferences.
"""

import os
import site
import sys
import traceback

import addon_utils

ADDON = "proteinblender"

# Path to the plugin source (this file lives at the repo root).
addon_root = os.path.abspath(os.path.dirname(__file__))

if addon_root not in sys.path:
    sys.path.append(addon_root)

# Blender's Python does not process the user site-packages dir, and install_deps.sh
# installs the addon's dependencies there (Program Files is read-only).
user_site_packages = site.getusersitepackages()
if os.path.exists(user_site_packages) and user_site_packages not in sys.path:
    sys.path.append(user_site_packages)
    print(f"Added user site-packages to sys.path: {user_site_packages}")

try:
    # default_set=False -> do not touch the saved preferences (see module docstring).
    # persistent=True   -> stay enabled after loading a new file (Ctrl+N).
    if addon_utils.enable(ADDON, default_set=False, persistent=True) is None:
        raise RuntimeError(f"addon_utils.enable({ADDON!r}) returned None")
    print(f"Successfully enabled '{ADDON}' addon.")
except Exception as e:
    print(f"Error enabling '{ADDON}' addon: {e}")
    traceback.print_exc()
