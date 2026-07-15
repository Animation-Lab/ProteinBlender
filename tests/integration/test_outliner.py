"""Integration tests for the PB Outliner + Visual Set-up operators.

Drives the real operators against a headless Blender scene and asserts
observable state (the ``scene.outliner_items`` selection/expansion flags and the
backing Blender object's hide flags).

Headless caveat: several outliner operators tag UI areas for redraw at the tail
of ``execute`` via ``context.screen.areas`` / ``context.area``, and under
``--background --factory-startup`` there is no screen/area, so those calls
raise. Where that redraw tail is *unguarded* (``outliner_select``), the test
tolerates the RuntimeError — the operator mutates the observable flag BEFORE the
redraw tail, so the post-condition still holds. ``toggle_visibility`` guards the
missing-area case internally and needs no tolerance; ``toggle_expand`` is
exercised through its headless-safe CHAIN path (which rebuilds the hierarchy
instead of tagging a redraw).

Covered operators:
  * proteinblender.outliner_select
  * proteinblender.toggle_expand
  * proteinblender.toggle_visibility
  * proteinblender.outliner_item_info
  * proteinblender.apply_representation
  * proteinblender.toggle_force_fields
"""

import bpy
import pytest

import helpers as H

from proteinblender.utils.molecularnodes.style import STYLE_ITEMS

STYLE_VALUES = [item[0] for item in STYLE_ITEMS]


def _item_by_id(scene, item_id):
    for it in scene.outliner_items:
        if it.item_id == item_id:
            return it
    return None


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_outliner_select_sets_is_selected(scene, sm, single_chain):
    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    assert pit.is_selected is False
    pid = pit.item_id

    # The operator toggles is_selected first, then tags UI areas for redraw.
    # Headless has no area, so tolerate the redraw-tail RuntimeError; the
    # selection flag is mutated before that point.
    try:
        bpy.ops.proteinblender.outliner_select(item_id=pid)
    except RuntimeError:
        pass

    pit = _item_by_id(scene, pid)
    assert pit is not None
    assert pit.is_selected is True, \
        "outliner_select did not set is_selected (unexpected headless rollback)"


# --------------------------------------------------------------------------
# Expand / collapse
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_toggle_expand_flips_is_expanded(scene, sm, multi_chain):
    # Use a CHAIN row: its toggle_expand path rebuilds the hierarchy (headless
    # safe) rather than tagging a redraw through context.screen.
    chain = next(it for it in scene.outliner_items
                 if it.item_type == "CHAIN" and it.parent_id == multi_chain)
    cid = chain.item_id
    before = chain.is_expanded

    res = bpy.ops.proteinblender.toggle_expand(item_id=cid)
    assert res == {'FINISHED'}

    # Rebuild invalidates the old PropertyGroup ref — re-fetch by id.
    chain = _item_by_id(scene, cid)
    assert chain is not None
    assert chain.is_expanded is (not before), "toggle_expand did not flip state"


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_toggle_visibility_flips_object_hide(scene, sm, single_chain):
    obj = sm.molecules[single_chain].object
    assert obj is not None
    before = obj.hide_render

    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)

    res = bpy.ops.proteinblender.toggle_visibility(item_id=pit.item_id)
    assert res == {'FINISHED'}
    assert obj.hide_render is (not before), "visibility toggle did not flip hide_render"

    # Toggling again restores the original state.
    res = bpy.ops.proteinblender.toggle_visibility(item_id=pit.item_id)
    assert res == {'FINISHED'}
    assert obj.hide_render is before


# --------------------------------------------------------------------------
# Item info (tooltip operator — must run without raising)
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_outliner_item_info_runs(scene, sm, single_chain):
    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    res = bpy.ops.proteinblender.outliner_item_info(item_id=pit.item_id)
    assert res == {'FINISHED'}


# --------------------------------------------------------------------------
# Visual Set-up: apply_representation
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_apply_representation_requires_selection(scene, sm, single_chain):
    # Nothing selected → the operator warns and cancels.
    for it in scene.outliner_items:
        it.is_selected = False
    res = bpy.ops.proteinblender.apply_representation(style="surface")
    assert res == {'CANCELLED'}


@pytest.mark.integration
def test_apply_representation_finishes_with_selection(scene, sm, single_chain):
    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    pit.is_selected = True
    res = bpy.ops.proteinblender.apply_representation(style="surface")
    assert res == {'FINISHED'}


@pytest.mark.integration
def test_apply_representation_style_enum_accepts_all_values(scene, sm, single_chain):
    # Every advertised style value must be a legal operator argument.
    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    pit.is_selected = True
    for style in STYLE_VALUES:
        res = bpy.ops.proteinblender.apply_representation(style=style)
        assert res == {'FINISHED'}, f"apply_representation rejected style {style!r}"


# --------------------------------------------------------------------------
# Visual Set-up: toggle_force_fields flag
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_toggle_force_fields_flag(scene, sm, single_chain):
    obj = sm.molecules[single_chain].object
    assert obj is not None

    pit = next(it for it in scene.outliner_items
               if it.item_type == "PROTEIN" and it.item_id == single_chain)
    pit.is_selected = True

    res = bpy.ops.proteinblender.toggle_force_fields(target_state="on")
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is True

    res = bpy.ops.proteinblender.toggle_force_fields(target_state="off")
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is False


@pytest.mark.integration
def test_toggle_force_fields_no_selection_cancels(scene, sm, single_chain):
    for it in scene.outliner_items:
        it.is_selected = False
    res = bpy.ops.proteinblender.toggle_force_fields(target_state="on")
    assert res == {'CANCELLED'}
