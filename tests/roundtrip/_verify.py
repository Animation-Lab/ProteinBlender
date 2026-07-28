"""Subprocess verifier for save/load round-trip tests.

Launched as::

    blender <file.blend> --background --factory-startup \
        --python tests/roundtrip/_verify.py \
        -- <repo_root> <out_json> [--resave <path>] [--render]

CRITICAL ordering: the .blend is passed on the command line so Blender opens it
*before* this script runs. Registering the add-on and THEN calling
``wm.open_mainfile`` in-process is not viable - it raises
EXCEPTION_STACK_OVERFLOW on Blender 5.0/5.1 and hangs indefinitely on 5.2
(measured: killed after 9 minutes on an otherwise idle machine).

That ordering has a consequence this file exists to correct. Because the file
was already open before the add-on registered, ``load_post`` never fired, so
none of the ten handlers a real File > Open runs had executed. The previous
version of this verifier papered over that by calling
``sync_molecule_list_after_undo`` - which is registered on ``undo_post`` /
``redo_post`` and *only* there. It is not a load handler. The lane was
therefore testing the undo path and reporting on the load path.

``simulate_file_load`` below runs the real thing:

  1. every registered ``load_post`` handler, in registration order, which is
     the order Blender itself uses; then
  2. the deferred bodies those handlers schedule on ``bpy.app.timers``.

Step 2 matters because ``bpy.app.timers`` never ticks in ``--background``.
Three of the load handlers do their actual work in a deferred pass - the
molecule registry rebuild, the linker rebuild and the force-field re-apply -
so without pumping them a headless test can never observe the state a user
gets. They are pumped in the order their timers were registered (linkers,
force fields, then the registry rebuild), which reproduces the real firing
order including its quirk that linkers rebuild before the registry exists.

Everything the run learns is reported in the JSON payload - which handlers
ran, which raised, which deferred bodies were pumped - so a failure can be
attributed to a specific stage rather than to "reload broke something".
"""

import json
import os
import sys
import traceback

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

# This module is both Blender's ``--python`` target and an ordinary import (the
# contract test reads SKIPPED_HANDLERS from it). The discriminator MUST be
# ``__name__``, not the shape of argv: the test suite itself runs as
# ``blender --background --python run_blender.py -- <pytest args>``, so argv
# after ``--`` is populated during a normal test run too. Treating that as
# script mode made an import of this module run main() and write its JSON
# payload over ``argv[1]`` - a path that, in that context, is one of the test
# files.
RUNNING_AS_SCRIPT = __name__ == "__main__" and len(argv) >= 2
REPO_ROOT = argv[0] if RUNNING_AS_SCRIPT else ""
OUT_JSON = argv[1] if RUNNING_AS_SCRIPT else ""
FLAGS = argv[2:] if RUNNING_AS_SCRIPT else []

RESAVE_PATH = None
if "--resave" in FLAGS:
    RESAVE_PATH = FLAGS[FLAGS.index("--resave") + 1]
WANT_RENDER = "--render" in FLAGS


# ---------------------------------------------------------------------------
# The real file-load lifecycle
# ---------------------------------------------------------------------------

# Load handlers deliberately not run here, each with the reason. Everything not
# listed IS run - a new handler is exercised by default rather than by
# opt-in. test_persistence_contract.py asserts each entry carries a reason.
SKIPPED_HANDLERS = {
    "create_workspace_on_load": (
        "Builds the Protein Blender workspace: duplicates a screen, closes "
        "editors and rebinds areas. It does not terminate in --background "
        "(measured: still running after 180s with --factory-startup), because "
        "the window/screen it manipulates does not exist there. It creates no "
        "persisted model state - only UI layout - and the workspace itself is "
        "covered by the foreground-ui lane, which runs under a real X display "
        "with an event loop."),
}


def _deferred_bodies():
    """The timer callbacks the load handlers schedule, in the order their
    timers are registered during a real load.

    Resolved by import rather than by inspecting ``bpy.app.timers`` because
    Blender exposes no way to enumerate registered timer functions.
    """
    bodies = []
    try:
        from proteinblender.linkers import linker_handlers
        bodies.append(("linker_rebuild", linker_handlers._deferred_linker_rebuild))
    except Exception:
        pass
    try:
        from proteinblender.membrane_builder import force_fields
        bodies.append(("force_field_reapply", force_fields._deferred_ff_reapply))
    except Exception:
        pass
    try:
        from proteinblender.utils import scene_manager
        bodies.append(("registry_reconstruct",
                       scene_manager._deferred_reconstruct_on_load))
    except Exception:
        pass
    try:
        from proteinblender.handlers import selection_sync
        bodies.append(("selection_sync_init", selection_sync._delayed_init))
    except Exception:
        pass
    return bodies


def simulate_file_load(report):
    """Run the lifecycle a real File > Open triggers, and record what happened."""
    import bpy

    handlers_run, handler_errors, skipped = [], {}, []
    for handler in list(bpy.app.handlers.load_post):
        name = getattr(handler, "__name__", repr(handler))
        if name in SKIPPED_HANDLERS:
            skipped.append(name)
            continue
        print(f"[verify] load_post -> {name}", file=sys.stderr, flush=True)
        try:
            # Blender calls load_post handlers with one argument, but hands
            # some of them a second; the embedded MolecularNodes handler
            # declares two. Match whatever the handler accepts rather than
            # recording an arity mismatch as a load failure.
            try:
                handler(None)
            except TypeError as arity:
                if "positional argument" not in str(arity):
                    raise
                handler(None, None)
            handlers_run.append(name)
        except Exception as exc:
            handler_errors[name] = f"{type(exc).__name__}: {exc}"
    report["load_post_handlers_run"] = handlers_run
    report["load_post_handler_errors"] = handler_errors
    report["load_post_handlers_skipped"] = skipped

    deferred_run, deferred_errors = [], {}
    for label, body in _deferred_bodies():
        print(f"[verify] deferred -> {label}", file=sys.stderr, flush=True)
        try:
            body()
            deferred_run.append(label)
        except Exception as exc:
            deferred_errors[label] = f"{type(exc).__name__}: {exc}"
    report["deferred_bodies_run"] = deferred_run
    report["deferred_body_errors"] = deferred_errors

    # Let the depsgraph settle so evaluated geometry and parenting are current
    # before anything is measured.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _render_coverage():
    """Covered pixel count of a Cycles render of the reopened file.

    The only assertion in this lane that observes what the *user* sees rather
    than what the data claims. A file whose node trees reloaded subtly wrong
    reports full state and renders nothing.
    """
    import bpy
    import numpy as np

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    out = os.path.join(os.path.dirname(OUT_JSON), "verify_render.png")
    scene.render.filepath = out

    cam_data = bpy.data.cameras.new("verify_cam")
    cam = bpy.data.objects.new("verify_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0, -12, 0)
    cam.rotation_euler = (1.5707963, 0, 0)
    scene.camera = cam
    try:
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(out)
        try:
            pixels = np.array(image.pixels[:], dtype=np.float32).reshape(-1, 4)
            return int((pixels[:, 3] > 0.01).sum())
        finally:
            bpy.data.images.remove(image)
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)


def main():
    out = {"ok": False, "stage": "start"}

    def checkpoint(stage):
        """Write the payload after every stage.

        A verifier that hangs or is killed still leaves a file naming the last
        stage it completed, so a stall is diagnosable instead of being an empty
        directory and a timeout.
        """
        out["stage"] = stage
        with open(OUT_JSON, "w") as handle:
            json.dump(out, handle, indent=2, default=str)
        print(f"[verify] {stage}", file=sys.stderr, flush=True)

    try:
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        for extra in (os.path.join(REPO_ROOT, "tests"),
                      os.path.join(REPO_ROOT, "tests", "roundtrip")):
            if extra not in sys.path:
                sys.path.insert(0, extra)

        import bpy

        import proteinblender
        proteinblender._test_register()
        out["blender"] = bpy.app.version_string
        checkpoint("registered")

        simulate_file_load(out)
        checkpoint("load_lifecycle_simulated")

        from _snapshot import scene_snapshot
        out["snapshot"] = scene_snapshot()
        checkpoint("snapshotted")

        if WANT_RENDER:
            try:
                out["render_covered_pixels"] = _render_coverage()
            except Exception as exc:
                out["render_error"] = f"{type(exc).__name__}: {exc}"

        if RESAVE_PATH:
            # Generation 2: save the reopened file straight back out. The
            # original data-loss bug degraded state *on load* and then
            # persisted the degradation on the next save, which one
            # save/load cycle structurally cannot detect.
            bpy.ops.wm.save_as_mainfile(filepath=RESAVE_PATH)
            out["resaved"] = RESAVE_PATH
            checkpoint("resaved")

        out["ok"] = True
    except Exception as exc:
        out["error"] = str(exc)
        out["traceback"] = traceback.format_exc()

    out["stage"] = "done" if out["ok"] else out.get("stage", "failed")
    with open(OUT_JSON, "w") as handle:
        json.dump(out, handle, indent=2, default=str)


if RUNNING_AS_SCRIPT:
    main()
