"""Save/load round-trip regression - the data-loss guard.

Each test builds real add-on state through the public operators, saves a
.blend, then reopens it in a FRESH Blender subprocess (never in-process - that
crashes on 5.0/5.1 and hangs on 5.2), runs the *real* file-load lifecycle, and
asserts the reconstructed scene is indistinguishable from what was saved.

What "indistinguishable" means here is deliberately strong. The comparison is a
whole-scene structural diff produced by walking RNA, not a hand-picked list of
fields: every property of every PropertyGroup, every object transform, custom
property, modifier input, geometry-node link, F-curve keyframe value, material
node value and the runtime molecule registry. A field added to the add-on
tomorrow is covered tomorrow, with no edit to this lane.

Marked `slow`: each case spawns a second Blender.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from _builders import BUILDERS                       # noqa: E402
from _diff import diff, format_report                # noqa: E402
from _snapshot import scene_snapshot                 # noqa: E402


def settle():
    """Bring the scene to the state a freshly-loaded file is always in.

    Two normalisations, both about comparing like with like rather than about
    relaxing the assertion:

    * ``frame_set`` re-evaluates animation. Inserting a keyframe leaves the
      object at the value the user typed; opening a file evaluates its
      F-curves at the current frame instead. Without this the expected
      snapshot holds a pending edit that the reload legitimately overwrites.
    * ``view_layer.update()`` flushes the depsgraph, so ``matrix_world`` on a
      parented object reflects a parent that was just moved. Blender computes
      it lazily, and a reload always computes it.

    Anything that still differs after this is the file's fault, not the
    measurement's.
    """
    import bpy
    scene = bpy.context.scene
    scene.frame_set(scene.frame_current)
    bpy.context.view_layer.update()

VERIFY = os.path.join(os.path.dirname(__file__), "_verify.py")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Reviewed tolerances
#
# Every entry is a glob over diff paths that is NOT a round-trip defect, each
# with the reason it is not. The list is deliberately short and deliberately
# explicit: an unexplained difference must fail, because "we ignore that one"
# is how a lane stops being evidence. test_persistence_contract.py asserts
# every entry carries a reason.
# ---------------------------------------------------------------------------

IGNORED = {
    "scene.protein_props.file_path":
        "Absolute path of the imported fixture. The verifier runs in a second "
        "process with a different working directory; the path is a UI "
        "convenience, not model state.",
    "scene.protein_props.filepath":
        "Same as file_path - import-dialog convenience, not model state.",
    "*.action_slot":
        "Blender 4.4+ action slots are re-bound by name on load and the "
        "display name is regenerated; the F-curves the slot carries are "
        "compared in full, which is the state that matters.",
}


def _ignored(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in IGNORED)


def filtered_diff(expected, actual):
    """Structural diff with reviewed tolerances removed."""
    return [d for d in diff(expected, actual, "")
            if not _ignored(d.split(":", 1)[0])]


# ---------------------------------------------------------------------------
# Subprocess driver
# ---------------------------------------------------------------------------

def run_verifier(blend_path, resave_to=None, render=False, timeout=900):
    """Reopen *blend_path* in a fresh Blender and return the verifier payload."""
    import bpy

    out_json = str(blend_path) + ".verify.json"
    cmd = [
        bpy.app.binary_path,
        str(blend_path),                 # open the file FIRST
        "--background", "--factory-startup",
        "--python", VERIFY,
        "--", REPO_ROOT, out_json,
    ]
    if resave_to:
        cmd += ["--resave", str(resave_to)]
    if render:
        cmd += ["--render"]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if not os.path.exists(out_json):
        raise AssertionError(
            f"verifier produced no output (rc={proc.returncode}).\n"
            f"stderr tail:\n{proc.stderr[-3000:]}")
    with open(out_json) as handle:
        payload = json.load(handle)
    payload["_returncode"] = proc.returncode
    return payload


def assert_load_lifecycle_clean(payload, name):
    """The reopened file must have run the real load lifecycle without error.

    A handler that raises leaves the add-on half-reconstructed. Blender's own
    handler dispatch swallows nothing, but the product wraps most of its
    handler bodies in broad excepts, so a silent failure there would otherwise
    surface only as a puzzling state difference much later.
    """
    assert payload.get("ok"), (
        f"[{name}] verifier failed: {payload.get('error')}\n"
        f"{payload.get('traceback', '')}")
    assert not payload.get("load_post_handler_errors"), (
        f"[{name}] load_post handlers raised on reopen: "
        f"{payload['load_post_handler_errors']}")
    assert not payload.get("deferred_body_errors"), (
        f"[{name}] deferred load passes raised on reopen: "
        f"{payload['deferred_body_errors']}")
    assert payload.get("load_post_handlers_run"), (
        f"[{name}] no load_post handlers ran - the lifecycle was not simulated, "
        "so this run proves nothing about file loading")


# ---------------------------------------------------------------------------
# The lane
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
@pytest.mark.slow
@pytest.mark.parametrize("name", list(BUILDERS))
def test_saveload_roundtrip(name, tmp_path):
    """Build → save → reopen in a fresh Blender → nothing changed."""
    BUILDERS[name]()
    settle()
    expected = scene_snapshot()

    # Non-vacuity: only the deliberately-empty case may snapshot an empty
    # scene. Without this a builder that silently failed would round-trip
    # nothing, perfectly, and report a pass.
    if name != "empty":
        assert expected["objects"], (
            f"builder {name!r} created no objects - the round trip would be "
            "vacuous")

    blend = tmp_path / f"rt_{name}.blend"
    import bpy
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    payload = run_verifier(blend)
    assert_load_lifecycle_clean(payload, name)

    differences = filtered_diff(expected, payload["snapshot"])
    assert not differences, format_report(
        differences,
        f"[{name}] state did not survive save → reopen "
        f"(Blender {payload.get('blender')}):")


@pytest.mark.roundtrip
@pytest.mark.slow
@pytest.mark.parametrize("name", ["domains", "chain_rename", "kitchen_sink"])
def test_saveload_survives_a_second_generation(name, tmp_path):
    """Save → reopen → save again → reopen: still identical.

    One cycle cannot catch the failure mode the original data-loss bug had.
    There, opening a file degraded the molecule list and the *next save*
    persisted the degraded values - so generation 1 looked fine (the damage
    happened after the snapshot) and the user lost their work on generation 2.
    Comparing generation 2 against the ORIGINAL expectation is what closes it.
    """
    BUILDERS[name]()
    settle()
    expected = scene_snapshot()

    import bpy
    gen1 = tmp_path / f"gen1_{name}.blend"
    gen2 = tmp_path / f"gen2_{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(gen1))

    first = run_verifier(gen1, resave_to=gen2)
    assert_load_lifecycle_clean(first, f"{name}/gen1")
    assert first.get("resaved"), "verifier did not write the second generation"

    second = run_verifier(gen2)
    assert_load_lifecycle_clean(second, f"{name}/gen2")

    differences = filtered_diff(expected, second["snapshot"])
    assert not differences, format_report(
        differences,
        f"[{name}] state survived one save/reopen but not two - the reload "
        f"degraded state that the next save then persisted:")


@pytest.mark.roundtrip
@pytest.mark.slow
@pytest.mark.visual
@pytest.mark.parametrize("name", ["multi_chain", "kitchen_sink"])
def test_reopened_file_still_renders(name, tmp_path):
    """A reopened file must still put pixels on screen.

    Every other assertion in this lane reads state. State cannot see the class
    of bug where a node tree reloads subtly rewired - the defect that made every
    imported molecule render nothing while 234 tests stayed green. This one
    observes the renderer.
    """
    BUILDERS[name]()
    settle()

    import bpy
    import helpers as H
    before = int(H.render_coverage(tmp_path).sum())
    assert before > 0, (
        f"[{name}] nothing rendered BEFORE saving, so a zero after reload "
        "would prove nothing - fix the builder, not the assertion")

    blend = tmp_path / f"render_{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    payload = run_verifier(blend, render=True)
    assert_load_lifecycle_clean(payload, name)
    assert "render_error" not in payload, (
        f"[{name}] render failed after reload: {payload['render_error']}")

    after = payload.get("render_covered_pixels", 0)
    assert after > 0, (
        f"[{name}] the reopened file rendered NOTHING ({before} px before "
        "save). State survived but the geometry path did not.")
    # Coverage is compared as a band, not exactly: the second process renders
    # through a freshly-built camera and its own depsgraph evaluation.
    assert 0.5 * before <= after <= 2.0 * before, (
        f"[{name}] rendered coverage changed materially across the round trip: "
        f"{before} px → {after} px")


# ---------------------------------------------------------------------------
# The lane's own falsifiability check
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_the_comparison_detects_a_planted_change():
    """Prove the diff can fail.

    A whole-scene comparison that silently swallowed differences would produce
    a green lane forever, which is indistinguishable from perfect persistence
    right up until it isn't. This plants one change of each kind the round trip
    must catch and asserts each is reported, with the path in the message.
    """
    import helpers as H
    H.import_local("4hhb.pdb", "4hhb_diffcheck")
    baseline = scene_snapshot()

    def mutated(fn):
        clone = json.loads(json.dumps(baseline))
        fn(clone)
        return filtered_diff(baseline, clone)

    # 1. A scalar PropertyGroup field silently reset (the chain_custom_names
    #    failure mode). The baseline value is "" on a freshly imported
    #    molecule, so the mutation has to be *away* from the default - planting
    #    the default over the default would be a no-op and would make this
    #    check pass for the wrong reason.
    assert baseline["scene"]["molecule_list_items"][0]["chain_custom_names"] == ""
    def set_field(snap):
        snap["scene"]["molecule_list_items"][0]["chain_custom_names"] = \
            '{"0": "Renamed"}'
    found = mutated(set_field)
    assert any("chain_custom_names" in d for d in found), found

    # 2. A whole collection dropped.
    def drop_domains(snap):
        snap["scene"]["molecule_list_items"][0]["domains"] = []
    assert mutated(drop_domains)

    # 3. An object transform moved.
    def move_object(snap):
        first = sorted(snap["objects"])[0]
        snap["objects"][first]["location"] = [99.0, 99.0, 99.0]
    found = mutated(move_object)
    assert any("location" in d for d in found), found

    # 4. The runtime registry emptied - the "Molecule not found" failure.
    def empty_registry(snap):
        snap["registry"]["molecules"] = {}
        snap["registry"]["molecule_ids"] = []
    found = mutated(empty_registry)
    assert any("registry" in d for d in found), found

    # 5. A geometry-node link rewired (renders nothing, state looks perfect).
    def rewire(snap):
        for obj in snap["objects"].values():
            for mod in obj["modifiers"]:
                tree = mod.get("tree")
                if isinstance(tree, dict) and isinstance(tree.get("links"), list) \
                        and tree["links"]:
                    tree["links"][0][0] = "Rewired"
                    return
        pytest.fail("no geometry-node links captured - the snapshot is not "
                    "covering node topology, so the render-nothing bug class "
                    "would be invisible")
    found = mutated(rewire)
    assert any("links" in d for d in found), found

    # 6. An identical-length collection whose members changed identity, which a
    #    naive count comparison cannot see.
    def rename_domain(snap):
        snap["scene"]["molecule_list_items"][0]["domains"][0]["name"] = "Changed"
    assert mutated(rename_domain)
