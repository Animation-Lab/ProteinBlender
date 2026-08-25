"""Contracts that keep the save/load lane exhaustive as the add-on grows.

The round-trip lane compares whole scenes, so it covers whatever it can see.
These tests police what it can see. They are the difference between "the save/
load tests passed" and "the save/load tests covered everything there was to
cover" - the second is only defensible if something fails when new persisted
state appears.

Each contract answers one question:

  * Does every ``bpy.types.Scene`` / ``bpy.types.Object`` property the add-on
    registers get snapshotted, or is it excluded on the record with a reason?
  * Does the RNA walk actually reach every field of every PropertyGroup that
    ends up in a .blend?
  * Is every deferred load pass pumped by the verifier, so no reconstruction
    work is invisible to a headless test?
  * Does every subsystem that persists state have a builder that creates some?
  * Is every tolerance and exclusion justified in writing?

They are cheap (no subprocess) and not marked slow, so they run on every
invocation of the suite - the drift they catch is introduced by ordinary
feature work, not by save/load work.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _builders                                            # noqa: E402
import _snapshot                                            # noqa: E402
import _verify                                              # noqa: E402
import test_saveload                                        # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE = REPO_ROOT / "proteinblender"
VERIFY_PATH = Path(__file__).resolve().parent / "_verify.py"
VERIFY_SOURCE = VERIFY_PATH.read_text(encoding="utf-8")

PROP_RE = re.compile(r"bpy\.types\.(Scene|Object)\.([A-Za-z_][A-Za-z0-9_]*)\s*=")
TIMER_RE = re.compile(r"bpy\.app\.timers\.register\(\s*([A-Za-z_][A-Za-z0-9_]*)")


def _product_files():
    """Every first-party module. The embedded MolecularNodes copy is upstream
    code with its own registration model and is not ours to police."""
    for path in PACKAGE.rglob("*.py"):
        if "molecularnodes" in path.parts:
            continue
        yield path


def _registered_properties():
    """{("Scene"|"Object", name): [source locations]} for every add-on property."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in _product_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = PROP_RE.search(line)
            if match:
                key = (match.group(1), match.group(2))
                found.setdefault(key, []).append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}")
    return found


# ---------------------------------------------------------------------------
# Coverage of registered properties
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_every_registered_property_is_snapshotted_or_excluded_with_a_reason():
    """Registering a new persisted property without covering it fails here.

    This is the mechanism that makes "full save/load coverage" a maintained
    property rather than a claim about a point in time. A developer adding
    ``bpy.types.Scene.my_new_thing`` has two options and both are deliberate:
    add it to SCENE_PROPS so it round-trips, or add it to EXCLUSIONS and say
    why it does not need to.
    """
    registered = _registered_properties()
    assert registered, "found no registered properties - the scan is broken"

    covered = {("Scene", name) for name in _snapshot.SCENE_PROPS}
    covered |= {("Object", name) for name in _snapshot.OBJECT_PROPS}
    excluded = set()
    for key in _snapshot.EXCLUSIONS:
        owner, _, name = key.partition(".")
        excluded.add((owner, name))

    uncovered = [f"{owner}.{name}  ({', '.join(locations)})"
                 for (owner, name), locations in sorted(registered.items())
                 if (owner, name) not in covered and (owner, name) not in excluded]

    assert not uncovered, (
        "these add-on properties are persisted but nothing in the save/load "
        "snapshot looks at them, so a reload could silently drop them:\n  "
        + "\n  ".join(uncovered)
        + "\n\nAdd each to _snapshot.SCENE_PROPS / OBJECT_PROPS, or to "
          "_snapshot.EXCLUSIONS with the reason it need not persist.")


@pytest.mark.roundtrip
def test_snapshot_does_not_claim_to_cover_properties_that_do_not_exist():
    """The inverse drift: a covered name that was renamed or removed.

    Without this, deleting a property leaves a stale entry in SCENE_PROPS which
    the snapshot records as ``"<not registered>"`` on both sides - comparing
    equal forever, and quietly reducing coverage while looking unchanged.
    """
    import bpy

    scene = bpy.context.scene
    missing_scene = [name for name in _snapshot.SCENE_PROPS
                     if not hasattr(scene, name)]
    assert not missing_scene, (
        f"_snapshot.SCENE_PROPS names properties the add-on no longer "
        f"registers: {missing_scene}")

    missing_object = [name for name in _snapshot.OBJECT_PROPS
                      if not hasattr(bpy.types.Object, name)]
    assert not missing_object, (
        f"_snapshot.OBJECT_PROPS names properties the add-on no longer "
        f"registers: {missing_object}")


# ---------------------------------------------------------------------------
# Completeness of the RNA walk
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_the_rna_walk_reaches_every_field_of_every_persisted_property_group(scene):
    """Serialize live PropertyGroups and assert no RNA field went missing.

    The snapshot is generic by construction, but "by construction" is an
    argument, not evidence. This builds real rows in each persisted collection
    and compares the serialized key set against the PropertyGroup's own RNA -
    so a future ``continue`` added to the walk, or a field the walk cannot
    read, shows up here rather than as a silent hole.
    """
    import bpy
    import helpers as H

    mid = H.import_local("4hhb.pdb", "4hhb_contract")
    bpy.context.scene.selected_molecule_id = mid
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)

    # Give the nested collections at least one row each so they are reachable.
    item = H.list_item(mid)
    keyframe = item.keyframes.add()
    keyframe.name, keyframe.frame = "K", 5
    assert bpy.ops.molecule.create_pose(
        'EXEC_DEFAULT', pose_name="ContractPose") == {'FINISHED'}
    library_pose = bpy.context.scene.pose_library.add()
    library_pose.name = "ContractLibraryPose"
    library_pose.transforms.add()
    linker = bpy.context.scene.pb2_linkers.add()
    linker.uid = "contract-linker"

    snapshot = _snapshot.scene_snapshot()
    problems: list[str] = []

    def compare(struct, serialized, path):
        if not isinstance(serialized, dict):
            problems.append(f"{path}: serialized as {type(serialized).__name__}, "
                            "expected a dict of RNA fields")
            return
        type_name = type(struct).__name__
        for prop in struct.bl_rna.properties:
            pid = prop.identifier
            if pid == "rna_type":
                continue
            if (type_name, pid) in _snapshot.PG_EXCLUSIONS:
                continue
            if pid not in serialized:
                problems.append(f"{path}.{pid} ({type_name}) is not in the snapshot")
                continue
            value = serialized[pid]
            if isinstance(value, str) and value.startswith("<un"):
                problems.append(f"{path}.{pid} ({type_name}) serialized as {value}")
            # Recurse one level into nested collections so their row type is
            # checked too (poses -> domain_transforms, linkers, outliner rows).
            if prop.type == "COLLECTION" and isinstance(value, list) and value:
                rows = getattr(struct, pid)
                if len(rows):
                    compare(rows[0], value[0], f"{path}.{pid}[0]")

    scene_state = snapshot["scene"]
    checked = 0
    for name in _snapshot.SCENE_PROPS:
        prop = bpy.context.scene.bl_rna.properties.get(name)
        if prop is None:
            continue
        value = getattr(bpy.context.scene, name)
        serialized = scene_state.get(name)
        if prop.type == "COLLECTION" and len(value):
            compare(value[0], serialized[0], f"scene.{name}[0]")
            checked += 1
        elif prop.type == "POINTER" and value is not None:
            compare(value, serialized, f"scene.{name}")
            checked += 1

    assert checked >= 6, (
        f"only {checked} PropertyGroup stores were populated and therefore "
        "checked; this test cannot vouch for the walk on an empty scene")
    assert not problems, (
        "the RNA walk did not reach every persisted field:\n  "
        + "\n  ".join(problems))


# ---------------------------------------------------------------------------
# Fidelity of the simulated load
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_every_deferred_load_pass_is_pumped_by_the_verifier():
    """Work deferred to a timer must still be exercised headless.

    ``bpy.app.timers`` never ticks in ``--background``, so a load handler that
    defers its real work is invisible to every headless test unless the
    verifier calls the body directly. Three already do (registry rebuild,
    linker rebuild, force-field re-apply). A fourth added later must either be
    pumped or be listed here as irrelevant to persisted state.
    """
    not_load_related = {
        "_deferred_molecule_purge":
            "deletion detector, scheduled from depsgraph updates rather than "
            "from a load handler",
        "_deferred_selection_update":
            "viewport->outliner selection echo; selection is not persisted state",
        "_selection_poll":
            "permanent polling timer for viewport selection, not a load pass",
        "_deferred_cleanup":
            "DNA bend orphan sweep, scheduled from depsgraph updates",
        "_deferred_membrane_refresh":
            "membrane modifier refresh scheduled from depsgraph updates",
        "create_workspace_callback":
            "builds the Protein Blender workspace UI; no persisted model state",
        "_finalize_workspace_callback":
            "retries workspace activation until Blender's screen switch "
            "settles; UI layout only, and it never terminates in --background",
        "_apply_workspace_context_callback":
            "re-applies Scene context to the workspace's Properties editor "
            "after activation; UI layout only, covered by the foreground-ui lane",
        "click_away_watcher":
            "watches for a click away from the Edit Pivot helper; registered "
            "by begin_pivot_edit and only while a session is open, never from "
            "a load handler, and it reads nothing a reopened file restores. "
            "Its effect on the pivot IS persisted, but by the operator it "
            "runs - covered by test_visual_edit_dialogs.py, the foreground-ui "
            "lane's simulated click, and tests/live",
    }

    scheduled: dict[str, list[str]] = {}
    for path in _product_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = TIMER_RE.search(line)
            if match:
                scheduled.setdefault(match.group(1), []).append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert scheduled, "found no timer registrations - the scan is broken"

    unpumped = [f"{name}  ({', '.join(where)})"
                for name, where in sorted(scheduled.items())
                if name not in VERIFY_SOURCE and name not in not_load_related]

    assert not unpumped, (
        "these deferred passes are scheduled on bpy.app.timers but the "
        "round-trip verifier never runs them, so nothing headless can observe "
        "their effect on a reopened file:\n  "
        + "\n  ".join(unpumped)
        + "\n\nAdd each to _verify._deferred_bodies, or to the "
          "not_load_related map in this test with the reason.")


@pytest.mark.roundtrip
def test_the_verifier_does_not_drive_the_undo_path_instead_of_the_load_path():
    """Guard against the specific regression this lane was rebuilt to fix.

    ``sync_molecule_list_after_undo`` is registered on ``undo_post`` and
    ``redo_post`` only. Calling it in the verifier reconstructs *something*,
    which is why the substitution went unnoticed for so long - the tests passed
    while testing a different code path than the one they reported on.
    """
    # Match a call, not a mention: _verify.py's own docstring explains this
    # history and must be allowed to name the function.
    calls = re.findall(r"sync_molecule_list_after_undo\s*\(", VERIFY_SOURCE)
    assert not calls, (
        "_verify.py calls the undo/redo handler. It must run the real "
        "load_post chain (simulate_file_load) instead, or this lane reports on "
        "the load path while exercising the undo path.")
    assert "simulate_file_load" in VERIFY_SOURCE
    assert "bpy.app.handlers.load_post" in VERIFY_SOURCE


@pytest.mark.roundtrip
def test_the_verifier_is_import_safe():
    """Importing the verifier must not run it.

    It is both a module (this file reads SKIPPED_HANDLERS from it) and
    Blender's ``--python`` target. The suite itself runs as
    ``blender --python run_blender.py -- <pytest args>``, so ``sys.argv``
    contains a ``--`` during an ordinary test run; a script/module
    discriminator based on argv shape therefore fires on import and writes the
    verifier's JSON payload over ``argv[1]``, which in that context is one of
    the test files. It must key off ``__name__``.
    """
    assert '__name__ == "__main__"' in VERIFY_SOURCE, (
        "_verify.py must decide script-vs-import mode from __name__")
    assert _verify.RUNNING_AS_SCRIPT is False, (
        "_verify believes it is running as a script while imported by pytest - "
        "it would overwrite a file on import")
    assert _verify.OUT_JSON == "", (
        f"_verify bound an output path on import: {_verify.OUT_JSON!r}")


# ---------------------------------------------------------------------------
# Coverage of subsystems
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_every_subsystem_that_persists_state_has_a_builder():
    """A package that registers persisted properties must have a round-trip
    builder that actually creates some of that state."""
    owners = set()
    for path in _product_files():
        text = path.read_text(encoding="utf-8")
        if not PROP_RE.search(text) and "PropertyGroup" not in text:
            continue
        relative = path.relative_to(PACKAGE)
        owners.add(relative.parts[0] if len(relative.parts) > 1 else "addon")

    exercised = {name for names in _builders.BUILDER_SUBSYSTEMS.values()
                 for name in names}
    missing = sorted(owners - exercised)
    assert not missing, (
        f"these packages define persisted state but no round-trip builder "
        f"exercises them: {missing}. Add a builder to _builders.BUILDERS and "
        f"list the package in BUILDER_SUBSYSTEMS.")


@pytest.mark.roundtrip
def test_every_builder_is_registered_and_declared():
    """Each builder must be in BUILDERS and declare the subsystems it covers,
    so the map above cannot be satisfied by a builder nobody runs."""
    undeclared = sorted(set(_builders.BUILDERS) - set(_builders.BUILDER_SUBSYSTEMS))
    assert not undeclared, f"builders with no subsystem declaration: {undeclared}"
    unregistered = sorted(set(_builders.BUILDER_SUBSYSTEMS) - set(_builders.BUILDERS))
    assert not unregistered, f"declared but never run: {unregistered}"


# ---------------------------------------------------------------------------
# Everything waived is waived on the record
# ---------------------------------------------------------------------------

@pytest.mark.roundtrip
def test_every_exclusion_and_tolerance_carries_a_reason():
    """No silent waivers.

    A tolerance without a stated reason is indistinguishable from a bug someone
    muted to get to green, and it is the mechanism by which a comprehensive
    lane decays into a decorative one.
    """
    for label, mapping in (("_snapshot.EXCLUSIONS", _snapshot.EXCLUSIONS),
                           ("test_saveload.IGNORED", test_saveload.IGNORED),
                           ("_verify.SKIPPED_HANDLERS", _verify.SKIPPED_HANDLERS)):
        for key, reason in mapping.items():
            assert isinstance(reason, str) and len(reason.strip()) >= 40, (
                f"{label}[{key!r}] needs a real explanation, got {reason!r}")

    for key, reason in _snapshot.PG_EXCLUSIONS.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"_snapshot.PG_EXCLUSIONS[{key!r}] has no reason")

    assert len(test_saveload.IGNORED) <= 8, (
        f"{len(test_saveload.IGNORED)} reviewed tolerances. Past a handful "
        "this stops being a short list of understood exceptions and starts "
        "being a filter that hides regressions - re-examine them.")
    assert len(_verify.SKIPPED_HANDLERS) <= 2, (
        f"{len(_verify.SKIPPED_HANDLERS)} load handlers are skipped by the "
        "verifier. Each one is a piece of the real load path this lane no "
        "longer exercises; keep the list to genuinely UI-only handlers.")
