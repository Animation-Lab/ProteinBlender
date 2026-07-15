"""Integration tests for KEYFRAME creation / navigation / edit / delete.

The primary, headless-reachable keyframe path for a plain protein is the
``molecule.keyframe_protein`` operator (per-molecule keyframes recorded on the
``MoleculeListItem`` AND real transform F-curves on the protein + domain
objects). Ported and expanded from tests/feature_audit/section_keyframes.py.

The newer ``proteinblender.create_keyframe`` operator is a modal
``invoke_props_dialog`` whose per-target selection collection is only populated
in ``invoke()`` and which needs at least one puppet / DNA / membrane target —
so it is not exercisable via ``EXEC_DEFAULT`` headless. That is documented with
a skip. The frame-based navigation operator ``proteinblender.jump_to_keyframe``
IS reachable and is tested here.

F-curve access uses the ``_action_fcurves`` compatibility shim (copied from
tests/stress_test/inner_runner.py) so the assertions work on both the Blender
4.x direct-``fcurves`` API and the 5.x slotted-action API.
"""

import pytest
import bpy
import helpers as H


# ---------------------------------------------------------------------------
# Blender 4.x / 5.x F-curve compatibility shim (copied verbatim from
# tests/stress_test/inner_runner.py so this module is self-contained).
# ---------------------------------------------------------------------------

def _action_fcurves(action):
    """Compatibility shim: Blender 4.x exposed `Action.fcurves` directly,
    Blender 5.x moves them under `Action.layers[*].strips[*].channelbag(slot).fcurves`.
    Yield every F-curve regardless of which API is in use."""
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        yield from fcurves
        return
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            # Slotted action API
            for slot in getattr(action, "slots", ()):
                cb = strip.channelbag(slot)
                if cb is None:
                    continue
                yield from getattr(cb, "fcurves", ())


def _keyframed_frames(obj):
    """Set of integer frames that have a keyframe_point on any F-curve of an
    object, or an empty set if the object has no animation."""
    frames = set()
    ad = getattr(obj, "animation_data", None)
    if ad and ad.action:
        for fc in _action_fcurves(ad.action):
            for kp in fc.keyframe_points:
                frames.add(int(round(kp.co[0])))
    return frames


# ---------------------------------------------------------------------------
# molecule.keyframe_protein — create / verify F-curves
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_keyframe_protein_records_list_entry_and_fcurve(scene, sm, single_chain):
    """Creating a keyframe grows list_item.keyframes AND inserts a real
    keyframe_point on the protein object's transform F-curves at that frame."""
    mid = single_chain
    scene.selected_molecule_id = mid
    scene.frame_current = 1

    item = H.list_item(mid)
    before = len(item.keyframes)
    res = bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1)
    assert res == {'FINISHED'}

    item = H.list_item(mid)
    assert len(item.keyframes) == before + 1
    assert item.keyframes[-1].name == "KF_Start"
    assert item.keyframes[-1].frame == 1

    # And the real F-curve keyframe exists on the protein object.
    mol = sm.molecules[mid]
    assert mol.object is not None
    assert 1 in _keyframed_frames(mol.object), \
        "no keyframe_point at frame 1 on the protein object"


@pytest.mark.integration
def test_keyframe_protein_second_frame(scene, sm, single_chain):
    """A second keyframe at a different frame after translating the protein is
    recorded with the right frame, and both frames show up on the F-curves."""
    mid = single_chain
    scene.selected_molecule_id = mid
    mol = sm.molecules[mid]

    scene.frame_current = 1
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1)

    scene.frame_current = 30
    mol.object.location = (5.0, 0.0, 0.0)
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Mid", frame_number=30)

    item = H.list_item(mid)
    assert len(item.keyframes) == 2
    assert [k.frame for k in item.keyframes] == [1, 30]

    frames = _keyframed_frames(mol.object)
    assert {1, 30} <= frames, f"expected frames 1 & 30 on F-curves, got {frames}"


# ---------------------------------------------------------------------------
# Navigation — jump to keyframe
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_jump_to_keyframe_sets_frame_current(scene, sm, single_chain):
    """proteinblender.jump_to_keyframe(frame=N) moves the playhead to N."""
    mid = single_chain
    scene.selected_molecule_id = mid
    scene.frame_current = 30
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Mid", frame_number=30)

    scene.frame_current = 5  # somewhere else
    res = bpy.ops.proteinblender.jump_to_keyframe('EXEC_DEFAULT', frame=30)
    assert res == {'FINISHED'}
    assert scene.frame_current == 30


@pytest.mark.integration
def test_select_keyframe_jumps_via_index(scene, sm, single_chain):
    """molecule.select_keyframe(keyframe_index=i) selects that keyframe and
    jumps scene.frame_current to its stored frame."""
    mid = single_chain
    scene.selected_molecule_id = mid

    scene.frame_current = 1
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1)
    scene.frame_current = 42
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_End", frame_number=42)

    scene.frame_current = 10
    res = bpy.ops.molecule.select_keyframe('EXEC_DEFAULT', keyframe_index=1)
    assert res == {'FINISHED'}
    assert scene.frame_current == 42
    assert H.list_item(mid).active_keyframe_index == 1


# ---------------------------------------------------------------------------
# Edit / delete
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_edit_keyframe_renames_and_moves_frame(scene, sm, single_chain):
    """molecule.edit_keyframe updates the list entry's name + frame, and moves
    the underlying F-curve keys from the old frame to the new one."""
    mid = single_chain
    scene.selected_molecule_id = mid
    mol = sm.molecules[mid]

    scene.frame_current = 1
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1)
    assert 1 in _keyframed_frames(mol.object)

    res = bpy.ops.molecule.edit_keyframe(
        'EXEC_DEFAULT', keyframe_index=0,
        keyframe_name="KF_Start_Renamed", frame_number=2)
    assert res == {'FINISHED'}

    kf = H.list_item(mid).keyframes[0]
    assert kf.name == "KF_Start_Renamed"
    assert kf.frame == 2

    # The F-curve keys moved: frame 2 now present, frame 1 gone.
    frames = _keyframed_frames(mol.object)
    assert 2 in frames
    assert 1 not in frames


@pytest.mark.integration
def test_delete_keyframe_removes_list_entry_and_fcurve(scene, sm, single_chain):
    """molecule.delete_keyframe removes the list entry and clears the transform
    F-curve keys at that frame."""
    mid = single_chain
    scene.selected_molecule_id = mid
    mol = sm.molecules[mid]

    scene.frame_current = 1
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1)
    scene.frame_current = 20
    bpy.ops.molecule.keyframe_protein(
        'EXEC_DEFAULT', keyframe_name="KF_Two", frame_number=20)

    item = H.list_item(mid)
    assert len(item.keyframes) == 2
    assert {1, 20} <= _keyframed_frames(mol.object)

    res = bpy.ops.molecule.delete_keyframe('EXEC_DEFAULT', keyframe_index=0)
    assert res == {'FINISHED'}

    item = H.list_item(mid)
    assert len(item.keyframes) == 1
    assert item.keyframes[0].frame == 20

    frames = _keyframed_frames(mol.object)
    assert 1 not in frames, "frame-1 keys should be gone after delete"
    assert 20 in frames, "the surviving keyframe's F-curve keys must remain"


# ---------------------------------------------------------------------------
# proteinblender.create_keyframe — modal / target-bound, documented as skipped
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_keyframe_is_modal_and_target_bound():
    """proteinblender.create_keyframe builds its per-target checkbox collection
    only inside invoke() (a modal invoke_props_dialog) and needs at least one
    puppet / DNA / membrane target. Neither is available via EXEC_DEFAULT in a
    headless run, so the interactive create path is not directly testable here.

    We still assert the operator is registered so a rename/removal is caught.
    """
    assert hasattr(bpy.types, "PROTEINBLENDER_OT_create_keyframe") or \
        hasattr(bpy.ops.proteinblender, "create_keyframe")
    pytest.skip(
        "proteinblender.create_keyframe requires a modal dialog + a puppet/"
        "DNA/membrane target; its selection collection is populated only in "
        "invoke(). Covered indirectly by molecule.keyframe_protein above.")
