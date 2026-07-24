"""Regression: splitting a chain AFTER it is already in a puppet.

Reported (Blender 5.2): import a PDB, puppet two chains, then split one of the
chains. From then on only the chain that was NOT split follows the puppet - the
split pieces stay behind, so poses capture/restore only that one chain and the
split pieces never move. Splitting the chains BEFORE building the puppet is fine.

Two independent root causes, one per test:

  * The split deletes the chain's single controller-parented object and creates
    new piece objects parented to the MOLECULE, never re-parenting them to the
    puppet controller. => moving the puppet moves only the un-split chain.
  * pose_library.get_puppet_objects resolved a chain member's split pieces by
    matching the chain INDEX ("0") against split-domain keys that use the chain
    LETTER ("A"), so it matched nothing and dropped the split chain from the
    pose entirely.

Ground truth here is the raw Blender parent graph (objects whose ``.parent`` is
the controller Empty) - NOT the puppet-resolution helpers under test - so the
assertions can't move in lock-step with the code they exercise.
"""

import pytest
import bpy
import helpers as H


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _make_puppet_then_split(scene, mid):
    """Puppet the first two chains, then split the first chain at 1-50.

    Returns (puppet_id, controller_obj). The split turns the first chain into
    two pieces (1-50 and the remainder), so the puppet should end up controlling
    three objects: two pieces + the intact second chain.

    ``create_puppet``/``split_domain`` each rebuild ``scene.outliner_items``,
    invalidating any row wrapper held across the call (a stale row silently
    reads back ""). We therefore pull the puppet id out as a plain str, and
    return the controller as a Blender object (stable across rebuilds by name).
    """
    _build_outliner()
    chains = _chain_items(mid)
    assert len(chains) >= 2, "need >=2 chains"
    a, b = chains[0], chains[1]

    for it in scene.outliner_items:
        it.is_selected = it.item_id in {a.item_id, b.item_id}
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="PAB")

    puppet = next(p for p in scene.outliner_items
                  if p.item_type == "PUPPET" and p.name == "PAB")
    puppet_id = str(puppet.item_id)
    controller = bpy.data.objects.get(puppet.controller_object_name)
    assert controller is not None

    # Two objects before the split: one per chain.
    before = [o for o in bpy.data.objects
              if o.parent == controller and o.type == 'MESH']
    assert len(before) == 2, f"puppet should control 2 chain objects, got {len(before)}"

    # Split the FIRST chain (author letter A) through the public outliner path.
    res = H.split_domain_from_outliner(mid, "A", 1, 50)
    assert res == {'FINISHED'}

    return puppet_id, controller


@pytest.mark.integration
def test_split_pieces_follow_the_puppet(scene, sm, multi_chain):
    """After splitting a puppeted chain, moving the controller moves ALL three
    resulting objects (two split pieces + the intact chain), not just one."""
    mid = multi_chain
    _puppet_id, controller = _make_puppet_then_split(scene, mid)

    children = [o for o in bpy.data.objects
                if o.parent == controller and o.type == 'MESH']
    # 3 = two pieces of the split chain + the intact second chain.
    assert len(children) == 3, \
        f"controller should parent all 3 objects after split, got " \
        f"{[o.name for o in children]}"

    before = {o.name: tuple(o.matrix_world.translation) for o in children}
    ctrl_before = tuple(controller.location)
    controller.location = (ctrl_before[0] + 7.0,
                           ctrl_before[1] + 3.0,
                           ctrl_before[2] - 2.0)
    bpy.context.view_layer.update()

    for o in children:
        after = tuple(o.matrix_world.translation)
        delta = tuple(after[i] - before[o.name][i] for i in range(3))
        assert abs(delta[0] - 7.0) < 1e-3 and abs(delta[1] - 3.0) < 1e-3 \
            and abs(delta[2] + 2.0) < 1e-3, \
            f"{o.name} moved {delta}, expected (7, 3, -2)"


@pytest.mark.integration
def test_pose_captures_all_split_pieces(scene, sm, multi_chain):
    """proteinblender.capture_pose stores a transform for every object the
    puppet actually controls after the split - all three, not just one.

    Expected object set is read from the raw parent graph (controller's mesh
    children), independent of the get_puppet_objects resolver being exercised.
    """
    mid = multi_chain
    puppet_id, controller = _make_puppet_then_split(scene, mid)

    expected = {o.name for o in bpy.data.objects
                if o.parent == controller and o.type == 'MESH'}
    assert len(expected) == 3

    # Hand-seed a pose that references the puppet, then run the real capture
    # operator (create_pose is modal/UI-bound; capture_pose runs headless).
    pose = scene.pose_library.add()
    pose.name = "P"
    pose.puppet_ids = puppet_id
    res = bpy.ops.proteinblender.capture_pose('EXEC_DEFAULT', pose_index=0)
    assert res == {'FINISHED'}

    captured = {t.object_name for t in pose.transforms if not t.is_controller}
    assert expected <= captured, \
        f"pose dropped split pieces: controls {expected}, captured {captured}"
