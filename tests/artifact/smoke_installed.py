"""Smoke test executed by Blender after the built ZIP has been installed.

Every phase announces itself before it runs, and a watchdog dumps stack traces
and exits if the script overruns. Both exist because this wedged in CI: it
printed nothing after add-on registration, sat silent for 41 minutes, and was
killed by the job timeout with no indication of which line was stuck. A test
that can hang has to be able to say where.
"""

import faulthandler
import json
import os
import sys
import time
from pathlib import Path

import bpy


fixture, blend_path, report_path = sys.argv[sys.argv.index("--") + 1:]

# Well under the workflow's timeout-minutes, so a wedge produces a traceback we
# can read instead of an opaque "The operation was canceled". Overridable for
# slower machines.
WATCHDOG_SECONDS = float(os.environ.get("PB_SMOKE_WATCHDOG_SECONDS", "600"))

_START = time.monotonic()


def step(message):
    print(f"[smoke +{time.monotonic() - _START:6.1f}s] {message}", flush=True)


faulthandler.enable()
if WATCHDOG_SECONDS > 0:
    # exit=True: print every thread's stack to stderr, then abort. Without it the
    # process just sits there and CI reports a cancellation, not a location.
    faulthandler.dump_traceback_later(WATCHDOG_SECONDS, exit=True)
    step(f"watchdog armed at {WATCHDOG_SECONDS:.0f}s")


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


step("resolving installed module")
module_name, package = find_module()
step(f"module resolved: {module_name}")

# Imported one at a time, each announced: these resolve out of the extension's
# freshly extracted wheel tree, and on a cold runner they are the slowest and
# most deadlock-prone part of the run.
for dependency in ("numpy", "scipy", "biotite", "MDAnalysis", "databpy", "mrcfile", "starfile"):
    step(f"importing {dependency}")
    __import__(dependency)
step("bundled dependencies imported")

scene = bpy.context.scene
for prop in ("protein_props", "molecule_list_items", "outliner_items"):
    assert hasattr(scene, prop), f"installed extension did not register scene.{prop}"
step("scene properties registered")

scene_manager = __import__(f"{module_name}.utils.scene_manager", fromlist=["*"])
manager = scene_manager.ProteinBlenderScene.get_instance()

step(f"importing fixture {Path(fixture).name}")
assert bpy.ops.molecule.import_local("EXEC_DEFAULT", filepath=fixture) == {"FINISHED"}
assert manager.molecules, "installed extension imported no molecule"
mol_id, molecule = next(iter(manager.molecules.items()))
assert molecule.object is not None and molecule.object.name in bpy.data.objects
assert molecule.domains, "installed extension created no chain domains"
step(f"imported {mol_id} with {len(molecule.domains)} domains")

before_handlers = {
    name: len([fn for fn in getattr(bpy.app.handlers, name)
               if getattr(fn, "__module__", "").startswith(module_name)])
    for name in ("load_post", "undo_post", "redo_post", "depsgraph_update_post", "frame_change_post")
}

step("saving .blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
Path(report_path).write_text(json.dumps({
    "module": module_name,
    "molecule_id": mol_id,
    "object_name": molecule.object.name,
    "domain_count": len(molecule.domains),
    "handlers": before_handlers,
    "blender": bpy.app.version_string,
}, indent=2), encoding="utf-8")
step("report written")

faulthandler.cancel_dump_traceback_later()
