"""Verify an installed-extension .blend in a second fresh Blender process."""

import json
import sys
from pathlib import Path

import bpy


report_path = Path(sys.argv[sys.argv.index("--") + 1])
expected = json.loads(report_path.read_text(encoding="utf-8"))
enabled = [name for name in bpy.context.preferences.addons.keys()
           if name.endswith(".proteinblender") or name == "proteinblender"]
assert enabled, "ProteinBlender extension is not enabled after reopen"
module_name = expected["module"]
assert module_name in sys.modules, (
    f"installed extension module not loaded after reopen: {module_name}")
scene_manager = __import__(f"{module_name}.utils.scene_manager", fromlist=["*"])
scene_manager.sync_molecule_list_after_undo()
manager = scene_manager.ProteinBlenderScene.get_instance()
assert expected["molecule_id"] in manager.molecules
molecule = manager.molecules[expected["molecule_id"]]
assert molecule.object and molecule.object.name == expected["object_name"]
assert len(molecule.domains) == expected["domain_count"]
assert len(bpy.context.scene.molecule_list_items) == 1
