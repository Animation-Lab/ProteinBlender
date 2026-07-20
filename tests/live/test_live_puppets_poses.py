"""Puppets and poses, observed in a live, windowed Blender.

The headless lane already proves the *bookkeeping* of both subsystems: that a
PUPPET row appears, that membership is exclusive, that a pose stores one
transform per domain. None of that requires a screen, and none of it can fail
in a way a user would notice as "nothing moved".

This lane adds the half `--background` cannot reach. A puppet exists so that
dragging one Empty drags a pile of protein geometry with it, and a pose exists
so that applying it puts that geometry back where it was. Both of those are
claims about pixels, and both are currently unfalsifiable by any other test:
the headless suite asserts on ``obj.matrix_world`` and on
``pose.domain_transforms``, which are the same numbers the operators just wrote.
A parenting bug that leaves the mesh behind, or a pose that restores the
transform of an object nothing is drawn from, keeps every existing assertion
green while the viewport shows the geometry stuck in place.

So the visual tests here are metamorphic and threshold-free. Move and move
back: the image must change, then return. Pose, disturb, re-apply: the image
must diverge, then re-converge. Neither assertion contains a number read off
today's build, and neither can pass if the geometry never followed.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Blender-side setup snippets
#
# These run inside the live Blender. They are inline here rather than in
# remote.py because they are test scaffolding, not harness infrastructure, and
# because every one of them drives the same public operator the panel does.
# ---------------------------------------------------------------------------

_MAKE_PUPPET = """
mid = H.import_local("4hhb.pdb", "4hhb")
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene = bpy.context.scene
chain_ids = [it.item_id for it in scene.outliner_items
             if it.item_type == "CHAIN" and it.parent_id == mid][:n_chains]
if len(chain_ids) < n_chains:
    raise RuntimeError(
        "4hhb produced %d chain rows, need %d" % (len(chain_ids), n_chains))
wanted = set(chain_ids)
for it in scene.outliner_items:
    it.is_selected = it.item_id in wanted
with R.view3d_override():
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=puppet_name)

# create_puppet rebuilds scene.outliner_items. Every row gathered above is now
# dangling and reads back defaults instead of raising, so re-resolve by id.
puppet = next(p for p in scene.outliner_items
              if p.item_type == "PUPPET"
              and p.item_id != "puppets_separator"
              and p.name == puppet_name)
by_id = {it.item_id: it for it in scene.outliner_items}
chains = []
for cid in chain_ids:
    row = by_id[cid]
    chains.append({
        "item_id": row.item_id,
        "name": row.name,
        "chain_id": row.chain_id,
        "chain_start": row.chain_start,
        "chain_end": row.chain_end,
        "object_name": row.object_name,
    })
return {
    "molecule_id": mid,
    "puppet_id": puppet.item_id,
    "puppet_name": puppet.name,
    "controller": puppet.controller_object_name,
    "chains": chains,
}
"""


def make_puppet(blender, puppet_name="Live_Puppet", n_chains=2) -> dict:
    """Import 4hhb and puppet its first *n_chains* chains, in live Blender.

    Returns plain data (ids and object names), never live RNA rows, because
    anything held across a later operator call would be rebuilt out from under
    the test.
    """
    return blender.call(_MAKE_PUPPET, puppet_name=puppet_name,
                        n_chains=n_chains)


_PUPPET_STATE = """
scene = bpy.context.scene
puppet = next((p for p in scene.outliner_items if p.item_id == puppet_id), None)
if puppet is None:
    return {"exists": False}
controller = bpy.data.objects.get(puppet.controller_object_name)
members = [m for m in (puppet.puppet_memberships or "").split(",") if m]
children = sorted(o.name for o in bpy.data.objects
                  if o.parent is not None and o.parent == controller)
return {
    "exists": True,
    "name": puppet.name,
    "controller": puppet.controller_object_name,
    "controller_exists": controller is not None,
    "controller_type": controller.type if controller else None,
    "members": members,
    "children": children,
}
"""


def puppet_state(blender, puppet_id: str) -> dict:
    """Re-resolve a puppet row by id and describe it. Never cache the row."""
    return blender.call(_PUPPET_STATE, puppet_id=puppet_id)


# ---------------------------------------------------------------------------
# Puppets - structure
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_create_puppet_makes_a_controller_that_parents_its_members(blender):
    """A puppet is only useful if its controller actually owns the geometry.

    Asserted here as scene structure: an EMPTY exists, the recorded membership
    is non-empty, and every member's object is a child of that Empty. The
    matching pixel claim is
    ``test_moving_the_controller_moves_the_rendered_geometry`` below.
    """
    setup = make_puppet(blender, "Live_Puppet_AB", 2)
    state = puppet_state(blender, setup["puppet_id"])

    assert state["exists"], "no PUPPET row survived create_puppet"
    assert state["controller_exists"], "puppet has no controller object"
    assert state["controller_type"] == "EMPTY"

    member_ids = {c["item_id"] for c in setup["chains"]}
    assert member_ids <= set(state["members"]), (
        f"chains {member_ids} should be members, got {state['members']}")
    assert len(state["children"]) >= 2, (
        "the controller should parent at least the two member objects, "
        f"it parents {state['children']}")


@pytest.mark.live
def test_a_chain_cannot_belong_to_two_puppets(blender):
    """Membership is exclusive. A second puppet seeded from an already-puppeted
    chain must be refused, and must not leave a half-built puppet behind.

    The count assertion matters as much as the rejection: an operator that
    reports an error *after* adding the row would still look correct if we only
    checked for a raised exception.
    """
    setup = make_puppet(blender, "Live_Puppet_AB", 2)
    first_chain = setup["chains"][0]["item_id"]

    result = blender.call("""
        scene = bpy.context.scene
        before = len([p for p in scene.outliner_items
                      if p.item_type == "PUPPET"
                      and p.item_id != "puppets_separator"])
        for it in scene.outliner_items:
            it.is_selected = it.item_id == chain_id
        rejected = False
        try:
            with R.view3d_override():
                res = bpy.ops.proteinblender.create_puppet(
                    'EXEC_DEFAULT', puppet_name="Conflicting")
            rejected = (res == {'CANCELLED'})
        except RuntimeError:
            rejected = True
        after = len([p for p in scene.outliner_items
                     if p.item_type == "PUPPET"
                     and p.item_id != "puppets_separator"])
        return {"rejected": rejected, "before": before, "after": after}
    """, chain_id=first_chain)

    assert result["rejected"], "a chain already in a puppet seeded a second one"
    assert result["after"] == result["before"], (
        "the rejected create still added a puppet row")


@pytest.mark.live
def test_edit_puppet_membership_and_rename(blender):
    """EDIT recomputes membership from ``member_ids`` when there is no dialog.

    The dialog fills an ``item_selections`` collection that only exists on a
    live modal instance, which this transport cannot reach - a modal dialog
    blocks Blender's main thread and the socket call times out. ``member_ids``
    is the scriptable equivalent the operator supports for exactly that reason.
    """
    setup = make_puppet(blender, "Live_EP", 2)
    keep, drop = setup["chains"][0]["item_id"], setup["chains"][1]["item_id"]
    puppet_id = setup["puppet_id"]

    result = blender.call("""
        scene = bpy.context.scene
        with R.view3d_override():
            bpy.ops.proteinblender.edit_puppet(
                'EXEC_DEFAULT', action='EDIT', puppet_id=puppet_id,
                new_name="Live_EP", member_ids=keep)
            bpy.ops.proteinblender.edit_puppet(
                'EXEC_DEFAULT', action='RENAME', puppet_id=puppet_id,
                new_name="Live_Renamed")
        puppet = next(p for p in scene.outliner_items if p.item_id == puppet_id)
        drop_row = next((it for it in scene.outliner_items
                         if it.item_id == drop), None)
        return {
            "name": puppet.name,
            "members": [m for m in (puppet.puppet_memberships or "").split(",")
                        if m],
            "drop_backref": [m for m in
                             (drop_row.puppet_memberships or "").split(",")
                             if m] if drop_row else None,
        }
    """, puppet_id=puppet_id, keep=keep, drop=drop)

    assert keep in result["members"], "the kept chain was dropped"
    assert drop not in result["members"], "the unticked chain is still a member"
    assert puppet_id not in (result["drop_backref"] or []), (
        "the dropped chain still points back at the puppet, so a later "
        "exclusivity check would wrongly refuse to re-puppet it")
    assert result["name"] == "Live_Renamed"


@pytest.mark.live
def test_delete_puppet_unparents_members_and_leaves_them_in_place(blender):
    """Deleting a puppet must free its members without teleporting them.

    Un-parenting is where world position quietly gets lost: clearing
    ``obj.parent`` without keeping the transform snaps every member back to its
    local origin. The members' world positions are read before and after, so a
    regression that moves them fails here rather than being noticed as a
    scrambled protein much later.
    """
    setup = make_puppet(blender, "Live_Del", 2)
    puppet_id = setup["puppet_id"]
    controller = setup["controller"]

    result = blender.call("""
        scene = bpy.context.scene
        puppet = next(p for p in scene.outliner_items if p.item_id == puppet_id)
        ctrl = bpy.data.objects.get(puppet.controller_object_name)
        members = sorted(o.name for o in bpy.data.objects
                         if o.parent is not None and o.parent == ctrl)
        before = {n: [round(float(v), 5) for v in
                      bpy.data.objects[n].matrix_world.translation]
                  for n in members}

        with R.view3d_override():
            bpy.ops.proteinblender.delete_puppet(
                'EXEC_DEFAULT', puppet_id=puppet_id)

        after = {}
        parents = {}
        for n in members:
            obj = bpy.data.objects.get(n)
            after[n] = ([round(float(v), 5) for v in
                         obj.matrix_world.translation] if obj else None)
            parents[n] = (obj.parent.name if obj and obj.parent else None)
        return {
            "row_gone": not any(p.item_id == puppet_id
                                for p in scene.outliner_items),
            "controller_gone": bpy.data.objects.get(controller_name) is None,
            "before": before,
            "after": after,
            "parents": parents,
        }
    """, puppet_id=puppet_id, controller_name=controller)

    assert result["row_gone"], "the PUPPET row outlived delete_puppet"
    assert result["controller_gone"], "the controller Empty was left behind"
    assert result["before"], "setup produced no parented members to check"
    for name, before in result["before"].items():
        assert result["after"][name] is not None, f"member {name} was deleted"
        assert result["parents"][name] is None, f"member {name} is still parented"
        for axis in range(3):
            assert abs(result["after"][name][axis] - before[axis]) < 0.01, (
                f"{name} moved when the puppet was deleted: "
                f"{before} -> {result['after'][name]}")


# ---------------------------------------------------------------------------
# Puppets - what the user actually sees
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_moving_the_controller_moves_the_rendered_geometry(blender, shot):
    """Dragging a puppet controller must drag its protein across the screen.

    This is the claim a puppet exists to make, and it is the one the headless
    lane cannot check: it asserts on ``matrix_world``, which the parenting code
    computes, so a molecule whose *drawn* geometry does not follow its object
    transform - the exact failure mode of the pivot/domain-space rule in
    CLAUDE.md - leaves it green.

    The assertion is metamorphic, with no threshold taken from this build:
    moving the controller must change the image, and moving it back must
    restore the image. A render that ignores the move fails the first half; a
    render that drifts, caches, or double-applies the offset fails the second.

    The view is framed once and never re-framed, because ``frame_all`` re-centres
    on the geometry and would cancel out exactly the displacement being measured.
    """
    setup = make_puppet(blender, "Live_Move", 2)
    blender.call("return R.frame_all()")

    origin = blender.call('return R.capture("origin")')
    assert origin["covered"] > 0, "the puppeted protein rendered nothing"

    # The move is sized from the puppet's own bounding box rather than being a
    # fixed number of Blender units. MolecularNodes scales Angstroms by 0.01, so
    # 4hhb is well under one unit across and a hard-coded 5.0 would throw it out
    # of frame, turning "it moved" into "it vanished".
    moved_by = blender.call("""
        import numpy as np
        ctrl = bpy.data.objects[controller_name]
        children = [o for o in bpy.data.objects
                    if o.parent is not None and o.parent == ctrl]
        pts = np.concatenate([H.eval_positions(o) for o in children])
        span = float((pts.max(axis=0) - pts.min(axis=0)).max())
        delta = span * 0.25
        home = [float(v) for v in ctrl.location]
        ctrl.location = (home[0] + delta, home[1], home[2] + delta)
        bpy.context.view_layer.update()
        return {"delta": delta, "home": home}
    """, controller_name=setup["controller"])
    assert moved_by["delta"] > 0, "the puppet has no measurable size to move by"

    moved = blender.call('return R.capture("moved")')
    shot("moved", frame=False)

    blender.call("""
        ctrl = bpy.data.objects[controller_name]
        ctrl.location = home
        bpy.context.view_layer.update()
        return None
    """, controller_name=setup["controller"], home=moved_by["home"])
    blender.call('return R.capture("restored")')

    shifted = blender.call('return R.compare("origin", "moved")')
    assert not shifted["identical"], (
        "moving the puppet controller left the rendered image byte-identical; "
        "the geometry did not follow its controller")
    assert moved["covered"] > 0, "the protein left the frame instead of moving"

    dx = moved["centroid"][0] - origin["centroid"][0]
    dy = moved["centroid"][1] - origin["centroid"][1]
    assert (dx * dx + dy * dy) ** 0.5 > 0.001, (
        f"the drawn geometry's centroid barely moved ({origin['centroid']} -> "
        f"{moved['centroid']}) for a controller offset of {moved_by['delta']:.4f} "
        "units; the image changed but the protein is not tracking the controller")

    # The renders are deterministic, so returning the controller to its exact
    # starting location must reproduce the starting image exactly. Anything less
    # means the move left residue behind.
    back = blender.call('return R.compare("origin", "restored")')
    assert back["identical"], (
        "returning the controller to its original location did not reproduce "
        f"the original image (xor={back['xor']}, rgb_delta={back['rgb_delta']})")


# ---------------------------------------------------------------------------
# Poses - molecule.* (the per-molecule system, fully scriptable)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_molecule_pose_captures_applies_and_deletes(blender, multi_chain):
    """The per-molecule pose life cycle, end to end through its operators.

    Structural cover for the same flow the visual test below renders. Ground
    truth for "the pose was restored" is the domain object's location recorded
    *before* any pose existed, not a value read back out of the pose itself.
    """
    result = blender.call("""
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        mol = H.sm().molecules[mid]
        did = sorted(mol.domains.keys())[0]
        obj_name = mol.domains[did].object.name
        original = [float(v) for v in bpy.data.objects[obj_name].location]

        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Live_Pose_A")
        bpy.data.objects[obj_name].location = (
            original[0] + 1.0, original[1] + 2.0, original[2] + 3.0)
        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Live_Pose_B")

        bpy.ops.molecule.apply_pose('EXEC_DEFAULT', pose_index="0")
        restored = [float(v) for v in bpy.data.objects[obj_name].location]

        bpy.ops.molecule.apply_pose('EXEC_DEFAULT', pose_index="1")
        reapplied = [float(v) for v in bpy.data.objects[obj_name].location]

        item = H.list_item(mid)
        names = [p.name for p in item.poses]
        item.active_pose_index = 0
        bpy.ops.molecule.delete_pose('EXEC_DEFAULT')
        item = H.list_item(mid)
        return {
            "original": original,
            "restored": restored,
            "reapplied": reapplied,
            "names": names,
            "n_domains": len(mol.domains),
            "n_transforms": len(H.list_item(mid).poses[0].domain_transforms),
            "after_delete": [p.name for p in item.poses],
        }
    """, mid=multi_chain)

    assert result["names"] == ["Live_Pose_A", "Live_Pose_B"]
    assert result["n_transforms"] == result["n_domains"], (
        "a pose must store one transform per domain")

    for axis in range(3):
        assert abs(result["restored"][axis] - result["original"][axis]) < 1e-3, (
            f"applying pose A did not restore the original arrangement: "
            f"{result['original']} -> {result['restored']}")
    expected = [result["original"][i] + (1.0, 2.0, 3.0)[i] for i in range(3)]
    for axis in range(3):
        assert abs(result["reapplied"][axis] - expected[axis]) < 1e-3, (
            f"applying pose B did not reach the arrangement it captured: "
            f"expected {expected}, got {result['reapplied']}")

    assert result["after_delete"] == ["Live_Pose_B"], (
        "delete_pose removed the wrong pose")


@pytest.mark.live
@pytest.mark.visual
def test_applying_a_pose_restores_the_rendered_arrangement(blender, shot):
    """A pose must put the *picture* back, not just the transform numbers.

    Capture the arrangement, disturb it, apply the pose, capture again. The
    image has to diverge and then re-converge. Stated as a ratio of the two
    divergences rather than an absolute pixel count, so it holds across GPUs and
    drivers: whatever the disturbance costs in pixels, restoring must recover
    nearly all of it.

    This is the assertion the headless suite structurally cannot make. It reads
    ``pose.domain_transforms`` and ``obj.location``, which are the values
    ``create_pose`` and ``apply_pose`` write and read - both sides move together,
    so a pose applied to an object that nothing is drawn from stays green.
    """
    mid = blender.call('return H.import_local("4hhb.pdb", "4hhb")')
    blender.call("return R.frame_all()")

    moved_by = blender.call("""
        import numpy as np
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        mol = H.sm().molecules[mid]
        did = sorted(mol.domains.keys())[0]
        obj = mol.domains[did].object
        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Live_Visual")
        # Displace by a fraction of the molecule's own size: big enough to be
        # unmistakable on screen, small enough to stay inside the framed view.
        pts = H.eval_positions(obj)
        span = float((pts.max(axis=0) - pts.min(axis=0)).max())
        return {"object": obj.name, "span": span,
                "home": [float(v) for v in obj.location]}
    """, mid=mid)

    posed = blender.call('return R.capture("posed")')
    assert posed["covered"] > 0, "the molecule rendered nothing to pose"

    blender.call("""
        obj = bpy.data.objects[object_name]
        obj.location = (home[0] + span * 0.6, home[1], home[2] + span * 0.6)
        bpy.context.view_layer.update()
        return None
    """, object_name=moved_by["object"], home=moved_by["home"],
        span=moved_by["span"])
    blender.call('return R.capture("disturbed")')
    shot("disturbed", frame=False)

    blender.call("""
        bpy.ops.molecule.apply_pose('EXEC_DEFAULT', pose_index="0")
        bpy.context.view_layer.update()
        return None
    """)
    blender.call('return R.capture("reposed")')
    shot("reposed", frame=False)

    disturbed = blender.call('return R.compare("posed", "disturbed")')
    reposed = blender.call('return R.compare("posed", "reposed")')

    assert disturbed["xor"] > 0, (
        "moving a domain changed nothing on screen, so this test cannot "
        "measure whether the pose restored anything")
    assert reposed["xor"] < disturbed["xor"] * 0.05, (
        "applying the pose did not bring the render back to the arrangement it "
        f"captured: disturbing cost {disturbed['xor']} pixels, restoring left "
        f"{reposed['xor']} of them still wrong")
    assert reposed["iou"] > disturbed["iou"], (
        "the restored image overlaps the captured pose no better than the "
        "disturbed one did")


@pytest.mark.live
def test_apply_pose_and_keyframe_records_a_keyframe_at_the_current_frame(
        blender, multi_chain):
    """The combined action must do both halves, at the playhead's frame.

    The frame is the interesting part: reading it from ``scene.frame_current``
    at execute time is what makes the button match what the user sees in the
    timeline, and hard-coding frame 1 would pass any test that only counted
    keyframes.
    """
    result = blender.call("""
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        scene.frame_set(7)
        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Live_KF_Pose")
        before = len(H.list_item(mid).keyframes)
        res = bpy.ops.molecule.apply_pose_and_keyframe(
            'EXEC_DEFAULT', pose_index="0", keyframe_name="Live_KF")
        item = H.list_item(mid)
        return {
            "result": sorted(res),
            "before": before,
            "after": len(item.keyframes),
            "name": item.keyframes[-1].name,
            "frame": item.keyframes[-1].frame,
        }
    """, mid=multi_chain)

    assert result["result"] == ["FINISHED"]
    assert result["after"] == result["before"] + 1
    assert result["name"] == "Live_KF"
    assert result["frame"] == 7, (
        f"the keyframe landed on frame {result['frame']}, not the playhead's 7")


# ---------------------------------------------------------------------------
# Poses - proteinblender.* (the pose-library system)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_pose_library_delete_and_reject_invalid_index(blender):
    """The library's index-driven operators, including the out-of-range guard.

    ``scene.pose_library`` is hand-populated because its ``create_pose`` is
    dialog-bound (see the next test). ``delete_pose`` and ``apply_pose`` take an
    explicit ``pose_index`` and run straight through ``execute()``, so they are
    reachable regardless.
    """
    result = blender.call("""
        scene = bpy.context.scene
        p0 = scene.pose_library.add()
        p0.name = "Lib_0"
        p1 = scene.pose_library.add()
        p1.name = "Lib_1"

        empty_ok = sorted(bpy.ops.proteinblender.apply_pose(
            'EXEC_DEFAULT', pose_index=0))

        with R.view3d_override():
            bpy.ops.proteinblender.delete_pose('EXEC_DEFAULT', pose_index=0)
        remaining = [p.name for p in scene.pose_library]

        rejected = False
        try:
            bpy.ops.proteinblender.apply_pose('EXEC_DEFAULT', pose_index=99)
        except RuntimeError:
            rejected = True
        return {"empty_ok": empty_ok, "remaining": remaining,
                "rejected": rejected,
                "count": len(scene.pose_library)}
    """)

    assert result["empty_ok"] == ["FINISHED"], (
        "applying a pose with no stored transforms should be a clean no-op")
    assert result["remaining"] == ["Lib_1"], (
        f"delete_pose(0) removed the wrong entry: {result['remaining']}")
    assert result["rejected"], (
        "an out-of-range pose_index was accepted instead of being refused")
    assert result["count"] == 1, "the rejected apply mutated the library"


@pytest.mark.live
@pytest.mark.visual
def test_pose_library_capture_and_apply_restores_the_rendered_puppet(
        blender, shot):
    """The pose-library round trip, driven without its dialog, checked on screen.

    ``capture_pose`` reads the puppets to capture from the pose's own
    ``puppet_ids`` string rather than from any dialog state, so seeding that
    field is enough to reach the real capture path - the one that stores each
    member's transform relative to the puppet controller.

    The controller is deliberately left where it is. Because the stored
    transforms are controller-relative, applying the pose after moving the
    controller would correctly reproduce the arrangement at the *new* controller
    position, which is a different picture and not something a fixed view can
    compare against. Disturbing a member instead isolates the claim under test:
    the library put the members back where it found them, on screen.
    """
    setup = make_puppet(blender, "Live_Lib_RT", 2)
    blender.call("return R.frame_all()")

    home = blender.call("""
        scene = bpy.context.scene
        pose = scene.pose_library.add()
        pose.name = "Live_Lib_RT_Pose"
        pose.puppet_ids = puppet_id
        with R.view3d_override():
            bpy.ops.proteinblender.capture_pose('EXEC_DEFAULT', pose_index=0)
        if len(pose.transforms) == 0:
            raise RuntimeError(
                "capture_pose stored no transforms for puppet %r; the pose "
                "library round trip cannot be measured" % puppet_id)

        import numpy as np
        ctrl = bpy.data.objects[controller_name]
        children = [o for o in bpy.data.objects
                    if o.parent is not None and o.parent == ctrl]
        pts = np.concatenate([H.eval_positions(o) for o in children])
        span = float((pts.max(axis=0) - pts.min(axis=0)).max())
        return {"n_transforms": len(pose.transforms), "span": span,
                "member": children[0].name,
                "home": [float(v) for v in children[0].location]}
    """, puppet_id=setup["puppet_id"], controller_name=setup["controller"])

    assert home["n_transforms"] > 0
    captured = blender.call('return R.capture("captured")')
    assert captured["covered"] > 0, "the puppeted protein rendered nothing"

    # Disturb one member of the puppet, leaving the controller alone.
    blender.call("""
        member = bpy.data.objects[member_name]
        member.location = (home[0] + span * 0.5, home[1], home[2] + span * 0.5)
        bpy.context.view_layer.update()
        return None
    """, member_name=home["member"], home=home["home"], span=home["span"])
    blender.call('return R.capture("disturbed")')
    shot("disturbed", frame=False)

    blender.call("""
        with R.view3d_override():
            bpy.ops.proteinblender.apply_pose('EXEC_DEFAULT', pose_index=0)
        bpy.context.view_layer.update()
        return None
    """)
    blender.call('return R.capture("applied")')
    shot("applied", frame=False)

    disturbed = blender.call('return R.compare("captured", "disturbed")')
    applied = blender.call('return R.compare("captured", "applied")')

    assert disturbed["xor"] > 0, (
        "moving a puppet member changed nothing on screen, so this test cannot "
        "tell whether apply_pose restored anything")
    assert applied["xor"] < disturbed["xor"] * 0.05, (
        "the pose library did not restore the arrangement it captured: "
        f"disturbing cost {disturbed['xor']} pixels, applying the pose left "
        f"{applied['xor']} of them still wrong")


@pytest.mark.live
def test_pose_library_create_pose_over_this_transport(blender):
    """``proteinblender.create_pose`` is dialog-bound; try it anyway.

    It is an ``invoke_props_dialog`` whose selection state
    (``self.available_puppets`` / ``self.selected_puppets``) is plain Python
    built only in ``invoke()``, so ``EXEC_DEFAULT`` finds those attributes
    missing - the headless suite carries this as a strict=False xfail.

    This lane cannot do better. It has a real window, but driving the operator
    with ``INVOKE_DEFAULT`` would open a modal dialog on Blender's main thread,
    which is precisely what stops the socket answering (``mcp_client`` reports a
    timeout with "It may be blocked on a modal dialog"). Attaching a live
    Blender does not make a modal dialog scriptable.

    So this skips rather than asserting something vacuous - but it *attempts*
    the call first, so if the operator is ever refactored to build its selection
    in ``execute()``, this turns into a real passing test instead of silently
    staying skipped.
    """
    setup = make_puppet(blender, "Live_Lib_Puppet", 2)

    outcome = blender.call("""
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        try:
            res = sorted(bpy.ops.proteinblender.create_pose(
                'EXEC_DEFAULT', pose_name="Live_Lib_Pose"))
        except Exception as exc:
            return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        return {"ok": True, "result": res, "count": len(scene.pose_library)}
    """, mid=setup["molecule_id"])

    if not outcome["ok"]:
        pytest.skip(
            "proteinblender.create_pose still requires its modal dialog "
            f"({outcome['error']}). A modal dialog blocks Blender's main "
            "thread, so this transport cannot drive it either; the pose "
            "CREATION logic it wraps is covered by molecule.create_pose.")

    assert outcome["result"] == ["FINISHED"]
    assert outcome["count"] == 1, (
        "create_pose reported success without adding a library entry")
