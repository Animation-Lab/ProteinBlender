"""Guard: fixing an invalid linker by editing re-attaches it to the proteins.

Reported (Blender 5.2, Janet): a linker created with an out-of-range residue
was "invisible" but still listed; after editing it to a valid residue it became
visible again but no longer followed the proteins when they were moved.

The movement handlers (``depsgraph_update_post`` / ``frame_change_post``) skip
any linker whose ``is_valid`` flag is False, and that flag is only set by
``update_linker_curve``. This test walks the exact repro - drive a linker
invalid, then edit it back to a valid residue keeping every appearance param
identical - and asserts the fixed linker is live again AND actually re-snaps to
a moved endpoint (observed through the real frame-change handler that gates on
``is_valid``, with the raw curve control points as ground truth).

On the current code the edit path restores ``is_valid`` (the coil-width property
callback re-runs ``update_linker_curve`` once the endpoints are valid again), so
this passes - it exists to keep that behaviour from regressing.
"""

import pytest
import bpy
import helpers as H

from proteinblender.linkers.linker_geometry import (
    update_linker_curve, get_residue_position_from_item,
)
from proteinblender.linkers.linker_handlers import linker_frame_change_handler


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _puppets():
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]


def _mid_residue(row):
    start = row.chain_start or 1
    end = row.chain_end or start
    return max(start, (start + end) // 2)


def _curve_signature(linker):
    obj = bpy.data.objects.get(linker.curve_object_name)
    if not obj or not obj.data or not obj.data.splines:
        return None
    pts = obj.data.splines[0].bezier_points
    return tuple(round(c, 4) for bp in pts for c in bp.co)


def _setup_puppet_two_chains(name="LinkerPuppet"):
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    chain_ids = [it.item_id for it in _chain_items(mid)[:2]]
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in set(chain_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=name)
    puppet = next(p for p in _puppets() if p.name == name)
    by_id = {it.item_id: it for it in bpy.context.scene.outliner_items}
    return mid, puppet.item_id, [by_id[c] for c in chain_ids]


@pytest.mark.integration
def test_editing_invalid_linker_reattaches_and_follows_movement(scene):
    mid, puppet_id, chains = _setup_puppet_two_chains()
    a, b = chains[0], chains[1]
    a_id, b_id = a.item_id, b.item_id
    a_res, b_res = _mid_residue(a), _mid_residue(b)

    # Create a valid linker first.
    bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT', puppet_selector=puppet_id,
        endpoint_a_item=f"A_{a_id}", endpoint_a_residue=a_res,
        endpoint_b_item=f"B_{b_id}", endpoint_b_residue=b_res,
        linker_name="L", length_residues=30, style="TUBE", rendering_mode="QUICK")
    linker = scene.pb2_linkers[-1]
    uid = linker.uid
    assert linker.is_valid is True

    # Snapshot the appearance params so the edit below changes ONLY the
    # residue - just like a user fixing a bad residue number. Blender skips a
    # property update callback when the assigned value is unchanged, so the
    # coil-width callback (the incidental path that re-runs update_linker_curve)
    # must NOT fire here; is_valid then depends solely on edit_linker itself.
    cw = linker.coil_width

    # Drive it invalid exactly as a puppet-move with an out-of-range endpoint
    # does: point endpoint B past the chain and run the live update path.
    linker.endpoint_b_residue = 99999
    assert update_linker_curve(linker) is False
    assert linker.is_valid is False, "linker should have gone invalid"

    # "Edit it to fix" - re-route endpoint B back to a real residue, keeping
    # every appearance parameter identical to what the linker already has.
    res = bpy.ops.pb2.edit_linker(
        'EXEC_DEFAULT', linker_uid=uid, puppet_selector=puppet_id,
        endpoint_a_item=f"A_{a_id}", endpoint_a_residue=a_res,
        endpoint_b_item=f"B_{b_id}", endpoint_b_residue=b_res,
        linker_name=linker.name, length_residues=linker.length_residues,
        style=linker.style, rendering_mode=linker.rendering_mode,
        behavior=linker.behavior, coil_width=cw, color=linker.color,
        tube_radius=linker.tube_radius, bead_radius=linker.bead_radius,
        bead_radius_variance=linker.bead_radius_variance,
        bead_overlap=linker.bead_overlap, bead_jitter=linker.bead_jitter,
        binding_zone_residues=linker.binding_zone_residues)
    assert res == {'FINISHED'}
    linker = next(l for l in scene.pb2_linkers if l.uid == uid)

    # Independent truth: both endpoints resolve to real positions again.
    assert get_residue_position_from_item(
        linker.endpoint_a_item_id, linker.endpoint_a_chain,
        linker.endpoint_a_residue) is not None
    assert get_residue_position_from_item(
        linker.endpoint_b_item_id, linker.endpoint_b_chain,
        linker.endpoint_b_residue) is not None

    # The fix: a fixed linker is live again, so movement handlers no longer
    # skip it. Observe it end-to-end: move an endpoint chain object and let the
    # real frame-change handler (which gates on is_valid) re-snap the curve.
    row_a = next(it for it in scene.outliner_items if it.item_id == a_id)
    obj_a = bpy.data.objects.get(row_a.object_name)
    assert obj_a is not None

    sig_before = _curve_signature(linker)
    assert sig_before is not None
    obj_a.location = (obj_a.location.x + 12.0, obj_a.location.y, obj_a.location.z)
    bpy.context.view_layer.update()
    linker_frame_change_handler(scene)
    sig_after = _curve_signature(linker)

    assert sig_after != sig_before, \
        "fixed linker did not follow the moved endpoint - still detached"
