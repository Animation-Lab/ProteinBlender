"""Integration tests for the Animation panel.

Two things are covered:

  1. The keyframe-selection FILTER used by the Animate Scene panel. The panel
     itself computes the filtered list inside ``draw()`` (not reachable
     headless), but the underlying functions in
     ``proteinblender.operators.keyframe_operators`` ARE importable and pure
     enough to drive directly:

        * ``get_keyframe_targets(context)``          — every animatable target
        * ``get_filtered_keyframe_targets(context)`` — subset implied by the
          viewport selection (``(targets, n_selected)``)
        * ``get_keyframe_frames(context, targets)``  — frames on those targets

     We build two DNA/RNA strands (each becomes a ``DNA_RNA`` keyframe target),
     drop transform keys on them at different frames, and assert:
        - nothing selected  → all targets, all frames
        - unrelated object  → all targets (n_selected == 0)
        - one target picked → only that target's frames

  2. The Create-Keyframe dialog's Select-All / Select-None helper operators,
     which flip ``use_puppet`` on every row of the live dialog instance. The
     dialog is modal, so we install a stand-in ``_active_instance`` (exactly
     what ``invoke()`` publishes) and assert the operators mutate its rows.
"""

import pytest
import bpy
import helpers as H

from proteinblender.operators.keyframe_operators import (
    get_keyframe_targets,
    get_filtered_keyframe_targets,
    get_keyframe_frames,
    PROTEINBLENDER_OT_create_keyframe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_two_dna_targets():
    """Build two DNA strands and return (obj_a, obj_b). Skips the test if the
    DNA builder isn't available or didn't register two DNA_RNA keyframe
    targets."""
    try:
        obj_a = H.build_dna(seq="ATCGATCGATCG", name_prefix="DNA_A")
        obj_b = H.build_dna(seq="GGCCAATTGGCC", name_prefix="DNA_B")
    except Exception as e:  # builder missing deps / operator failure
        pytest.skip(f"DNA builder unavailable: {type(e).__name__}: {e}")

    targets = get_keyframe_targets(bpy.context)
    if len({t[1].name for t in targets}) < 2:
        pytest.skip(
            "fewer than 2 DNA_RNA keyframe targets registered after build "
            f"(got {[t[0] for t in targets]}) — cannot exercise the filter")
    return obj_a, obj_b


# ---------------------------------------------------------------------------
# Panel scene property
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_filter_toggle_property_exists_and_defaults_off(scene):
    """The panel's filter toggle is registered and defaults to OFF (show all)."""
    assert hasattr(scene, "pb_keyframe_filter_by_selection")
    assert scene.pb_keyframe_filter_by_selection is False
    # keyframe-list backing collection is registered too
    assert hasattr(scene, "pb_keyframe_list")


# ---------------------------------------------------------------------------
# Keyframe-selection filter
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_unfiltered_targets_and_frames_span_all(scene):
    """With keys on two targets and no filter, get_keyframe_frames returns
    every keyed frame across all targets."""
    obj_a, obj_b = _build_two_dna_targets()
    obj_a.keyframe_insert("location", frame=10)
    obj_b.keyframe_insert("location", frame=20)

    targets = get_keyframe_targets(bpy.context)
    frames = get_keyframe_frames(bpy.context, targets=targets)
    assert 10 in frames and 20 in frames


@pytest.mark.integration
def test_no_selection_returns_all_targets(scene):
    """Nothing selected → filter falls back to ALL targets, n_selected == 0."""
    obj_a, obj_b = _build_two_dna_targets()
    obj_a.keyframe_insert("location", frame=10)
    obj_b.keyframe_insert("location", frame=20)

    bpy.ops.object.select_all(action="DESELECT")
    all_targets = get_keyframe_targets(bpy.context)
    filtered, n_selected = get_filtered_keyframe_targets(bpy.context)
    assert n_selected == 0
    assert len(filtered) == len(all_targets)
    frames = get_keyframe_frames(bpy.context, targets=filtered)
    assert 10 in frames and 20 in frames


@pytest.mark.integration
def test_unrelated_selection_returns_all_targets(scene):
    """Selecting an object that belongs to no keyframe target must NOT blank
    the panel — the filter falls back to all targets (n_selected == 0)."""
    obj_a, obj_b = _build_two_dna_targets()
    obj_a.keyframe_insert("location", frame=10)
    obj_b.keyframe_insert("location", frame=20)

    unrelated = bpy.data.objects.new("Unrelated_Empty", None)
    scene.collection.objects.link(unrelated)
    H.select_only(unrelated)

    all_targets = get_keyframe_targets(bpy.context)
    filtered, n_selected = get_filtered_keyframe_targets(bpy.context)
    assert n_selected == 0
    assert len(filtered) == len(all_targets)


@pytest.mark.integration
def test_relevant_selection_scopes_to_that_target(scene):
    """Selecting one target's object scopes the filter to that target only, so
    get_keyframe_frames returns just its frame."""
    obj_a, obj_b = _build_two_dna_targets()
    obj_a.keyframe_insert("location", frame=10)
    obj_b.keyframe_insert("location", frame=20)

    H.select_only(obj_a)
    filtered, n_selected = get_filtered_keyframe_targets(bpy.context)

    assert n_selected >= 1
    filtered_names = {t[1].name for t in filtered}
    assert obj_a.name in filtered_names
    assert obj_b.name not in filtered_names

    frames = get_keyframe_frames(bpy.context, targets=filtered)
    assert 10 in frames
    assert 20 not in frames, "DNA_B's frame must be filtered out"


# ---------------------------------------------------------------------------
# Create-Keyframe dialog Select All / Select None
# ---------------------------------------------------------------------------

class _FakeRow:
    """Stand-in for a PuppetKeyframeSettings row — the select helpers only
    read/write ``use_puppet``."""
    def __init__(self):
        self.use_puppet = False


class _FakeDialog:
    """Mimics the fields the select helpers touch on the live operator
    instance."""
    def __init__(self, n):
        self.puppet_items = [_FakeRow() for _ in range(n)]


@pytest.mark.integration
def test_select_all_puppets_flips_flags_on_active_dialog(scene):
    """keyframe_select_all_puppets ticks use_puppet on every row of the live
    Create-Keyframe dialog instance; keyframe_select_none_puppets clears them."""
    fake = _FakeDialog(3)
    PROTEINBLENDER_OT_create_keyframe._active_instance = fake
    try:
        res = bpy.ops.proteinblender.keyframe_select_all_puppets('EXEC_DEFAULT')
        assert res == {'FINISHED'}
        assert all(r.use_puppet for r in fake.puppet_items)

        res = bpy.ops.proteinblender.keyframe_select_none_puppets('EXEC_DEFAULT')
        assert res == {'FINISHED'}
        assert all(not r.use_puppet for r in fake.puppet_items)
    finally:
        PROTEINBLENDER_OT_create_keyframe._active_instance = None


@pytest.mark.integration
def test_select_all_puppets_cancels_with_no_active_dialog(scene):
    """With no dialog open the select helpers report CANCELLED rather than
    raising."""
    PROTEINBLENDER_OT_create_keyframe._active_instance = None
    res = bpy.ops.proteinblender.keyframe_select_all_puppets('EXEC_DEFAULT')
    assert res == {'CANCELLED'}
    res = bpy.ops.proteinblender.keyframe_select_none_puppets('EXEC_DEFAULT')
    assert res == {'CANCELLED'}
