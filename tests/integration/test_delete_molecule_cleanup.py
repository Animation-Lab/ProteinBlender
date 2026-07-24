"""Regression: deleting a molecule must clear its puppets and their poses.

Reported (Blender 5.2): after deleting the entire PDB/model, the Protein Pose
Library still listed poses whose puppets/proteins no longer exist. Deleting the
molecule dropped the chain/domain rows but left orphaned PUPPET rows and their
pose-library entries behind.
"""

import pytest
import bpy
import helpers as H


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _real_puppets():
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]


@pytest.mark.integration
def test_delete_molecule_clears_puppets_and_poses(scene, sm, multi_chain):
    """Deleting the only molecule removes its (now orphaned) puppet and the
    pose that referenced it, so the pose library ends up empty."""
    mid = multi_chain
    _build_outliner()
    chains = _chain_items(mid)
    a, b = chains[0], chains[1]

    for it in scene.outliner_items:
        it.is_selected = it.item_id in {a.item_id, b.item_id}
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="PAB")
    puppet_id = next(p.item_id for p in _real_puppets() if p.name == "PAB")

    # Capture a real pose that references the puppet.
    pose = scene.pose_library.add()
    pose.name = "P"
    pose.puppet_ids = puppet_id
    bpy.ops.proteinblender.capture_pose('EXEC_DEFAULT', pose_index=0)
    assert len(scene.pose_library) == 1
    assert len(scene.pose_library[0].transforms) > 0, "pose should have captured members"

    # Delete the whole model.
    assert sm.delete_molecule(mid) is True

    # The orphaned puppet row is gone...
    assert not _real_puppets(), "orphaned puppet should be removed with its molecule"
    # ...and the pose that only referenced it no longer lingers in the library.
    assert len(scene.pose_library) == 0, \
        f"pose library should be empty, still has {[p.name for p in scene.pose_library]}"
