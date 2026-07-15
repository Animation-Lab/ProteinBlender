"""Subprocess verifier for save/load round-trip tests.

Launched as::

    blender <file.blend> --background --factory-startup \
        --python tests/roundtrip/_verify.py -- <repo_root> <out_json>

CRITICAL ordering: the .blend is passed on the command line so Blender opens it
*before* this script runs. Registering the addon and THEN calling
open_mainfile in-process triggers EXCEPTION_STACK_OVERFLOW on Blender 5.0/5.1,
so we must register only after the file is already loaded.

Writes the post-reload scene snapshot (after driving the UI reconstruction) to
<out_json>.
"""

import json
import os
import sys
import traceback

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO_ROOT = argv[0]
OUT_JSON = argv[1]


def main():
    out = {"ok": False}
    try:
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "roundtrip"))

        import proteinblender
        proteinblender._test_register()

        # Drive the same reconstruction the panel does on first draw after load.
        try:
            from proteinblender.utils.scene_manager import sync_molecule_list_after_undo
            sync_molecule_list_after_undo()
        except Exception as e:
            out["sync_error"] = str(e)

        from _snapshot import scene_snapshot
        out["snapshot"] = scene_snapshot()
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
        out["traceback"] = traceback.format_exc()

    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2, default=str)


main()
