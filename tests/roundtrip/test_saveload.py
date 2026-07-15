"""Save/load round-trip regression — the data-loss guard.

Each test builds addon state, saves a .blend, then reopens it in a FRESH
Blender subprocess (never in-process — that segfaults) and asserts the
reconstructed scene matches what was saved. This is where "save my scene, come
back tomorrow, everything's still there" is protected.

Marked `slow` because each test spawns a second Blender.
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

import helpers as H

sys.path.insert(0, os.path.dirname(__file__))
from _snapshot import scene_snapshot  # noqa: E402

VERIFY = os.path.join(os.path.dirname(__file__), "_verify.py")


# --------------------------------------------------------------------------
# Builders: each populates the scene and returns nothing; the snapshot is
# captured generically afterwards.
# --------------------------------------------------------------------------

def build_empty():
    pass


def build_single():
    H.import_local("1ubq.pdb", "1ubq")


def build_multi():
    H.import_local("4hhb.pdb", "4hhb")


def build_domains():
    # 4hhb auto-creates one domain per chain (4). Tint them so colour is part
    # of the round trip too.
    mid = H.import_local("4hhb.pdb", "4hhb")
    mol = H.sm().molecules[mid]
    for i, (_did, d) in enumerate(sorted(mol.domains.items())):
        if getattr(d, "object", None) is not None:
            d.object.domain_color = (0.2 * (i + 1), 0.4, 0.8, 1.0)


def build_keyframes():
    import bpy
    from mathutils import Vector
    mid = H.import_local("1aki.pdb", "1aki")
    mol = H.sm().molecules[mid]
    item = H.list_item(mid)
    # Raw transform keyframes on the first auto-domain object + metadata entries.
    if mol.domains:
        _did, d = sorted(mol.domains.items())[0]
        if getattr(d, "object", None) is not None:
            for frame, loc in [(1, (0, 0, 0)), (24, (3, 0, 0)), (48, (3, 3, 0))]:
                d.object.location = Vector(loc)
                d.object.keyframe_insert(data_path="location", frame=frame)
    for frame, name in [(1, "Start"), (24, "Middle"), (48, "End")]:
        kf = item.keyframes.add()
        kf.frame = frame
        kf.name = name


BUILDERS = {
    "empty": build_empty,
    "single": build_single,
    "multi": build_multi,
    "domains": build_domains,
    "keyframes": build_keyframes,
}


def _run_verifier(blend_path):
    import bpy
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out_json = blend_path + ".verify.json"
    cmd = [
        bpy.app.binary_path,
        blend_path,                      # open the file FIRST
        "--background", "--factory-startup",
        "--python", VERIFY,
        "--", repo_root, out_json,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not os.path.exists(out_json):
        raise AssertionError(
            f"verifier produced no output (rc={proc.returncode}).\n"
            f"stderr tail:\n{proc.stderr[-2000:]}")
    with open(out_json) as f:
        payload = json.load(f)
    return payload


def _assert_snapshots_match(expected, actual):
    assert actual["molecule_ids"] == expected["molecule_ids"], \
        f"molecule ids changed: {expected['molecule_ids']} -> {actual['molecule_ids']}"
    assert actual["outliner_count"] == expected["outliner_count"]
    assert actual["linker_count"] == expected["linker_count"]
    for mid, em in expected["molecules"].items():
        am = actual["molecules"].get(mid)
        assert am is not None, f"molecule {mid} missing after reload"
        for key in ("style", "domain_count", "pose_count", "keyframe_count",
                    "object_exists"):
            assert am[key] == em[key], \
                f"{mid}.{key}: expected {em[key]!r}, got {am[key]!r}"
        assert am["domains"] == em["domains"], f"{mid} domains changed"
        assert am["poses"] == em["poses"], f"{mid} poses changed"
        assert am["keyframes"] == em["keyframes"], f"{mid} keyframes changed"


@pytest.mark.roundtrip
@pytest.mark.slow
@pytest.mark.parametrize("name", list(BUILDERS))
def test_saveload_roundtrip(name):
    BUILDERS[name]()
    expected = scene_snapshot()

    with tempfile.TemporaryDirectory() as tmp:
        blend = os.path.join(tmp, f"rt_{name}.blend")
        import bpy
        bpy.ops.wm.save_as_mainfile(filepath=blend)

        payload = _run_verifier(blend)
        assert payload.get("ok"), \
            f"verifier failed: {payload.get('error')}\n{payload.get('traceback', '')}"
        _assert_snapshots_match(expected, payload["snapshot"])
