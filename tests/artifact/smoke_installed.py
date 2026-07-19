"""Smoke test executed by Blender after the built ZIP has been installed."""

import json
import sys
from pathlib import Path

import bpy


fixture, blend_path, report_path = sys.argv[sys.argv.index("--") + 1:]


def find_module():
    enabled = [name for name in bpy.context.preferences.addons.keys()
               if name.endswith(".proteinblender") or name == "proteinblender"]
    assert enabled, "installed ProteinBlender extension is not enabled"
    # Blender 5.2 stores an extension's manifest id ("proteinblender") as the
    # preference key, while importing it through bl_ext.<repo>.<id>. Inspect
    # loaded modules to prove where the product actually came from.
    candidates = [name for name in sys.modules
                  if name == "bl_ext.pb_test.proteinblender"]
    assert candidates, (
        f"installed extension was enabled as {enabled}, but its isolated "
        "bl_ext.pb_test.proteinblender module is not loaded")
    module_name = candidates[0]
    return module_name, sys.modules[module_name]


module_name, package = find_module()
for dependency in ("numpy", "scipy", "biotite", "MDAnalysis", "databpy", "mrcfile", "starfile"):
    __import__(dependency)

scene = bpy.context.scene
for prop in ("protein_props", "molecule_list_items", "outliner_items"):
    assert hasattr(scene, prop), f"installed extension did not register scene.{prop}"

scene_manager = __import__(f"{module_name}.utils.scene_manager", fromlist=["*"])
manager = scene_manager.ProteinBlenderScene.get_instance()
assert bpy.ops.molecule.import_local("EXEC_DEFAULT", filepath=fixture) == {"FINISHED"}
assert manager.molecules, "installed extension imported no molecule"
mol_id, molecule = next(iter(manager.molecules.items()))
assert molecule.object is not None and molecule.object.name in bpy.data.objects
assert molecule.domains, "installed extension created no chain domains"

before_handlers = {
    name: len([fn for fn in getattr(bpy.app.handlers, name)
               if getattr(fn, "__module__", "").startswith(module_name)])
    for name in ("load_post", "undo_post", "redo_post", "depsgraph_update_post", "frame_change_post")
}

bpy.ops.wm.save_as_mainfile(filepath=blend_path)
Path(report_path).write_text(json.dumps({
    "module": module_name,
    "molecule_id": mol_id,
    "object_name": molecule.object.name,
    "domain_count": len(molecule.domains),
    "handlers": before_handlers,
    "blender": bpy.app.version_string,
}, indent=2), encoding="utf-8")
