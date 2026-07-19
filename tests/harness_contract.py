"""Assertions about Blender process hygiene used by the test harness.

These checks intentionally live outside product code.  A cleanup or registration
failure must make the harness red; otherwise later tests can pass against leaked
state and give a false sense of safety.
"""

from __future__ import annotations

import os
from collections import Counter


STRICT_CONTEXT = os.environ.get("PB_STRICT_CONTEXT", "").lower() in {
    "1", "true", "yes", "on",
}


def context_unavailable(pytest, reason: str) -> None:
    """Skip locally, but fail in the canonical CI/UI environment."""
    if STRICT_CONTEXT:
        pytest.fail(f"required Blender context unavailable: {reason}")
    pytest.skip(reason)


def addon_objects():
    import bpy
    return [obj for obj in bpy.data.objects if (
        obj.get("pb_molecule_id")
        or obj.get("pb_is_nucleic_acid")
        or obj.get("pb_membrane_root")
        or obj.get("pb2_linker_uid")
        or obj.name.startswith(("PB_", "ProteinBlender"))
    )]


def assert_clean_scene() -> None:
    import bpy
    from helpers import sm

    scene = bpy.context.scene
    problems = []
    if sm().molecules:
        problems.append(f"molecule registry: {sorted(sm().molecules)}")
    for name in ("molecule_list_items", "outliner_items", "pb2_linkers",
                 "pose_library", "chain_selections"):
        value = getattr(scene, name, None)
        if value is not None and len(value):
            problems.append(f"scene.{name}: {len(value)} row(s)")
    leaked = addon_objects()
    if leaked:
        problems.append("addon objects: " + ", ".join(o.name for o in leaked))
    assert not problems, "scene cleanup left state behind:\n  " + "\n  ".join(problems)


def callable_key(fn):
    return (getattr(fn, "__module__", ""), getattr(fn, "__name__", repr(fn)))


def proteinblender_handler_duplicates():
    import bpy

    problems = []
    for list_name in (
        "load_pre", "load_post", "undo_post", "redo_post",
        "depsgraph_update_post", "frame_change_post",
    ):
        handlers = getattr(bpy.app.handlers, list_name)
        keys = [callable_key(fn) for fn in handlers
                if callable_key(fn)[0].startswith("proteinblender")]
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        if duplicates:
            problems.append(f"{list_name}: {duplicates}")
    return problems

