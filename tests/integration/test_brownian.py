"""Integration tests for the Brownian-motion operators.

Brownian motion is a *puppet* feature: it bakes JITTER-typed keyframes onto a
puppet's controller Empty between a previous (user) keyframe and the current
frame, and records its configuration in a ``pb_brownian_metadata`` JSON custom
property on that controller.

Setup mirrors real usage: import a multi-chain protein, build the outliner,
create a puppet from two chains (which produces the controller Empty), give
the controller a starting keyframe, then drive the operators.

Covered operators:
  * proteinblender.brownian_settings   (bakes jitter + writes metadata)
  * proteinblender.brownian_disable    (clears jitter, flips enabled=False)
  * proteinblender.brownian_rebuild    (re-bakes from stored metadata)
  * proteinblender.brownian_clear_all  (removes metadata + baked keys)
"""

import pytest
import bpy
import helpers as H

from proteinblender.utils.animation import (
    ensure_quaternion_mode,
    get_fcurves_from_action,
)

END_FRAME = 10
START_FRAME = 1


def _jitter_key_count(obj):
    """Number of JITTER-typed keyframe points across the object's transform
    F-curves — the observable footprint of baked Brownian motion."""
    ad = getattr(obj, "animation_data", None)
    if not ad or not ad.action:
        return 0
    total = 0
    for fc in get_fcurves_from_action(ad.action, ad):
        if fc.data_path not in ("location", "rotation_quaternion"):
            continue
        total += sum(1 for kp in fc.keyframe_points if kp.type == "JITTER")
    return total


def _make_brownian_puppet(name="Brownian_Puppet"):
    """Import 4hhb, build a two-chain puppet, and return
    (controller_obj, puppet_id, puppet_name) with a starting keyframe placed
    at START_FRAME. Skips the test if the puppet/controller can't be built
    headlessly."""
    H.import_local("4hhb.pdb", "4hhb")
    scene = bpy.context.scene
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)

    chain_ids = [it.item_id for it in scene.outliner_items
                 if it.item_type == "CHAIN"]
    if len(chain_ids) < 2:
        pytest.skip("need at least two chains to form a puppet")

    for it in scene.outliner_items:
        it.is_selected = it.item_id in chain_ids[:2]

    try:
        bpy.ops.proteinblender.create_puppet("EXEC_DEFAULT", puppet_name=name)
    except RuntimeError as e:
        pytest.skip(f"create_puppet unavailable headless: {e}")

    puppet = next(
        (it for it in scene.outliner_items
         if it.item_type == "PUPPET"
         and it.item_id != "puppets_separator"
         and it.name == name),
        None,
    )
    if puppet is None or not puppet.controller_object_name:
        pytest.skip("puppet controller was not created")
    controller = bpy.data.objects.get(puppet.controller_object_name)
    if controller is None:
        pytest.skip("puppet controller object missing")

    # Give the segment a starting (user) keyframe so brownian_settings can
    # find a previous position to jitter around.
    ensure_quaternion_mode(controller)
    controller.keyframe_insert(data_path="location", frame=START_FRAME)
    controller.keyframe_insert(data_path="rotation_quaternion", frame=START_FRAME)

    return controller, puppet.item_id, name


def _run_settings(controller, puppet_id, puppet_name):
    """Bake Brownian motion onto the controller with a fixed, reproducible
    seed so keyframe placement is deterministic."""
    return bpy.ops.proteinblender.brownian_settings(
        "EXEC_DEFAULT",
        controller_object_name=controller.name,
        puppet_id=puppet_id,
        puppet_name=puppet_name,
        frame_number=END_FRAME,
        jitter_interval=3,
        jitter_max_distance=1.0,
        jitter_max_rotation=30.0,
        use_random_seed=False,
        seed=42,
    )


@pytest.mark.integration
def test_brownian_settings_bakes_metadata_and_keyframes():
    controller, puppet_id, puppet_name = _make_brownian_puppet("BR_Settings")
    res = _run_settings(controller, puppet_id, puppet_name)
    assert res == {"FINISHED"}

    assert "pb_brownian_metadata" in controller, "metadata not written"
    import json
    metadata = json.loads(controller["pb_brownian_metadata"])
    assert str(END_FRAME) in metadata
    assert metadata[str(END_FRAME)]["enabled"] is True

    assert _jitter_key_count(controller) > 0, "no JITTER keyframes were baked"


@pytest.mark.integration
def test_brownian_disable_turns_it_off():
    controller, puppet_id, puppet_name = _make_brownian_puppet("BR_Disable")
    _run_settings(controller, puppet_id, puppet_name)
    assert _jitter_key_count(controller) > 0  # precondition

    res = bpy.ops.proteinblender.brownian_disable(
        "EXEC_DEFAULT",
        controller_object_name=controller.name,
        puppet_id=puppet_id,
        frame_number=END_FRAME,
    )
    assert res == {"FINISHED"}

    import json
    metadata = json.loads(controller["pb_brownian_metadata"])
    assert metadata[str(END_FRAME)]["enabled"] is False
    assert _jitter_key_count(controller) == 0, "JITTER keyframes not cleared"


@pytest.mark.integration
def test_brownian_rebuild_regenerates_motion():
    controller, puppet_id, puppet_name = _make_brownian_puppet("BR_Rebuild")
    _run_settings(controller, puppet_id, puppet_name)
    assert _jitter_key_count(controller) > 0

    res = bpy.ops.proteinblender.brownian_rebuild(
        "EXEC_DEFAULT",
        controller_object_name=controller.name,
    )
    assert res == {"FINISHED"}
    # Metadata survives the rebuild and jitter is present again.
    assert "pb_brownian_metadata" in controller
    assert _jitter_key_count(controller) > 0


@pytest.mark.integration
def test_brownian_clear_all_removes_everything():
    controller, puppet_id, puppet_name = _make_brownian_puppet("BR_Clear")
    _run_settings(controller, puppet_id, puppet_name)
    assert "pb_brownian_metadata" in controller  # precondition

    res = bpy.ops.proteinblender.brownian_clear_all(
        "EXEC_DEFAULT",
        controller_object_name=controller.name,
    )
    assert res == {"FINISHED"}

    assert "pb_brownian_metadata" not in controller, "metadata not removed"
    assert _jitter_key_count(controller) == 0, "baked keyframes not removed"
