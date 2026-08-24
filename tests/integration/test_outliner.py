"""Integration tests for the PB Outliner's row operators.

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
  * proteinblender.edit_protein_visuals (the protein row's edit pencil, here
    only for the membrane force field it owns; the rest of that dialog lives
    in test_visual_edit_dialogs.py)
"""

import bpy
import pytest

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
# The protein row's edit dialog: membrane force field
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_protein_dialog_force_field_flag(scene, sm, single_chain):
    """The protein row's edit dialog owns the membrane force-field toggle."""
    obj = sm.molecules[single_chain].object
    assert obj is not None

    res = bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_force_field=True)
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is True

    res = bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_force_field=False)
    assert res == {'FINISHED'}
    assert obj.pb_force_field_enabled is False


@pytest.mark.integration
def test_edit_protein_visuals_unknown_row_cancels(scene, sm, single_chain):
    """An item_id that matches no outliner row must refuse, not silently no-op.

    The operator reports {'ERROR'} and cancels; Blender turns a reported
    ERROR into a RuntimeError on the way out through ``bpy.ops``, which is the
    same contract the Domain Splitter has for an unresolvable chain.
    """
    obj = sm.molecules[single_chain].object
    with pytest.raises(RuntimeError, match="Could not resolve the protein"):
        bpy.ops.proteinblender.edit_protein_visuals(
            item_id="no_such_protein", vs_force_field=True)
    assert getattr(obj, "pb_force_field_enabled", False) is False


@pytest.mark.integration
def test_outliner_chain_range_falls_back_to_auth_chain_id_map(scene, sm, single_chain):
    """The chain-range resolver's second fallback must actually run.

    build_outliner_hierarchy tries idx_to_label_asym_id_map first and
    auth_chain_id_map second. The second branch referenced a bare
    ``chain_mapping`` that was never bound in the function, so reaching it
    raised NameError - masked in production because every caller wraps the
    rebuild in a broad except, leaving the outliner silently unbuilt.

    Emptying idx_to_label_asym_id_map forces the first lookup to miss.
    """
    from proteinblender.utils.scene_manager import build_outliner_hierarchy

    molecule = sm.molecules[single_chain]
    assert molecule.auth_chain_id_map, "fixture must have an auth chain map to fall back to"
    assert molecule.chain_residue_ranges, "fixture must have residue ranges to resolve"

    molecule.idx_to_label_asym_id_map = {}

    build_outliner_hierarchy(bpy.context)

    chain_rows = [i for i in scene.outliner_items if i.item_type == 'CHAIN']
    assert chain_rows, "expected at least one chain row"
    assert any(r.chain_end >= r.chain_start > 0 for r in chain_rows), (
        "auth_chain_id_map fallback should still resolve a real residue range"
    )


# --------------------------------------------------------------------------
# Row order
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_chain_domain_rows_are_ordered_by_residue(scene, sm, multi_chain):
    """Domains read down the chain, whatever order they were created in.

    The rows used to come out in creation order (the wrapper's dict order), so
    a chain split back-to-front listed its last domain first. Ordering is a
    property of the chain, not of the order the user happened to carve it up
    in.

    The layout is submitted deliberately out of order and the expectation is
    the residue numbers written here, not anything the add-on derived.
    """
    import json

    from proteinblender.utils.scene_manager import build_outliner_hierarchy

    mid = multi_chain
    scene.selected_molecule_id = mid
    build_outliner_hierarchy(bpy.context)
    chain_row = next(it for it in scene.outliner_items
                     if it.item_type == "CHAIN" and it.name == "Chain A")

    payload = json.dumps([
        {"name": "Third", "start": 130, "end": 198, "domain_id": ""},
        {"name": "First", "start": 1, "end": 60, "domain_id": ""},
        {"name": "Second", "start": 61, "end": 129, "domain_id": ""},
    ])
    assert bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=chain_row.item_id, layout_json=payload,
        chain_name=chain_row.name) == {'FINISHED'}

    build_outliner_hierarchy(bpy.context)
    rows = [it for it in scene.outliner_items
            if it.item_type == "DOMAIN" and it.parent_id == chain_row.item_id]

    assert [it.name for it in rows] == ["First", "Second", "Third"]
    assert [it.domain_start for it in rows] == [1, 61, 130]
