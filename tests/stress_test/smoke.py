"""Smoke test: launched inside Blender 5.1 to confirm we can register the
worktree's proteinblender package and import a tiny PDB.

Run via the harness; not user-runnable on its own.
"""

import sys
import os
import json
import traceback

# CLI args passed after `--` go to argv after blender's own args.
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
worktree = argv[0]
output = argv[1]


def main():
    result = {"step": "start", "ok": False}
    try:
        # Disable any installed extension version so we don't double-register.
        import bpy
        for mod in list(sys.modules):
            if mod.startswith("bl_ext.") and mod.endswith(".proteinblender"):
                try:
                    bpy.ops.preferences.addon_disable(module=mod)
                except Exception:
                    pass

        # Drop any cached import of proteinblender so the worktree wins.
        for mod in list(sys.modules):
            if mod == "proteinblender" or mod.startswith("proteinblender."):
                del sys.modules[mod]

        # Inject worktree onto sys.path.
        if worktree not in sys.path:
            sys.path.insert(0, worktree)

        result["step"] = "import"
        import proteinblender  # noqa: F401
        result["package_path"] = proteinblender.__file__

        result["step"] = "register"
        proteinblender.register()

        result["step"] = "scene_props"
        scene = bpy.context.scene
        result["has_protein_props"] = hasattr(scene, "protein_props")
        result["has_molecule_list_items"] = hasattr(scene, "molecule_list_items")
        result["has_outliner_items"] = hasattr(scene, "outliner_items")
        result["has_pb2_linkers"] = hasattr(scene, "pb2_linkers")

        result["step"] = "ok"
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    with open(output, "w") as f:
        json.dump(result, f, indent=2)


main()
