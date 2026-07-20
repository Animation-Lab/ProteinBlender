"""Keyframes, playback and Brownian motion, observed in a live Blender.

The headless suite proves that keyframes exist: a row on the
``MoleculeListItem``, keyframe points on an F-curve, JITTER-typed keys on a
puppet controller. Every one of those is a fact about the data model, and all of
them can be true of an animation that does not animate.

That is the gap this module fills, and it is a gap `--background` cannot close
at all. Scrubbing the timeline is a viewport operation: the depsgraph
re-evaluates, geometry nodes re-run, and the screen changes. A headless process
has no screen to change. So the assertions here set ``frame_current`` across the
keyed range and require the rendered image to differ between frames - and, for
Brownian, to differ in a way a fixed seed reproduces exactly.

F-curve reading is done with a local walker rather than the add-on's own
``get_fcurves_from_action``. Partly for the ground-truth rule in CLAUDE.md - the
truth about "is there a key at frame 30" should not come from the module that
put it there - and partly because this lane runs against the *deployed* add-on,
whose importable module path is not guaranteed to be ``proteinblender.*``.
"""

from __future__ import annotations

import textwrap

import pytest


# ---------------------------------------------------------------------------
# Blender-side helpers, injected into each snippet.
#
# ``_action_fcurves`` is the Blender 4.x / 5.x compatibility shim: 4.x exposed
# ``Action.fcurves`` directly, 5.x moved them under
# ``layers[*].strips[*].channelbag(slot).fcurves``. It reads raw animation data
# and touches no add-on code.
# ---------------------------------------------------------------------------

_FCURVES = '''
def _action_fcurves(action):
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        for fc in fcurves:
            yield fc
        return
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for slot in getattr(action, "slots", ()):
                bag = strip.channelbag(slot)
                if bag is None:
                    continue
                for fc in getattr(bag, "fcurves", ()):
                    yield fc


def _keyed_frames(obj):
    frames = set()
    ad = getattr(obj, "animation_data", None)
    if ad and ad.action:
        for fc in _action_fcurves(ad.action):
            for kp in fc.keyframe_points:
                frames.add(int(round(kp.co[0])))
    return sorted(frames)


def _jitter_keys(obj):
    """(frame, value) of every JITTER-typed transform key, sorted.

    The full coordinates, not just a count: a fixed seed has to reproduce the
    same motion, and a count alone cannot tell two different bakes apart.
    """
    out = []
    ad = getattr(obj, "animation_data", None)
    if not ad or not ad.action:
        return out
    for fc in _action_fcurves(ad.action):
        if fc.data_path not in ("location", "rotation_quaternion"):
            continue
        for kp in fc.keyframe_points:
            if kp.type == "JITTER":
                out.append([fc.data_path, int(fc.array_index),
                            round(float(kp.co[0]), 4),
                            round(float(kp.co[1]), 6)])
    return sorted(out)
'''


def with_fcurves(body: str) -> str:
    """Prefix a snippet with the F-curve readers above.

    Each part is dedented before joining. ``mcp_client.call`` dedents the whole
    snippet once and then indents it into a function body, so concatenating a
    zero-indent block (``_FCURVES``) with an indented triple-quoted literal
    would leave nothing common to strip and hand Blender an IndentationError.
    """
    return _FCURVES + textwrap.dedent(body)


_MAKE_PUPPET = '''
mid = H.import_local("4hhb.pdb", "4hhb")
H.scene_manager_module().build_outliner_hierarchy(bpy.context)
scene = bpy.context.scene
chain_ids = [it.item_id for it in scene.outliner_items
             if it.item_type == "CHAIN" and it.parent_id == mid][:2]
if len(chain_ids) < 2:
    raise RuntimeError("need two chains to build a puppet")
wanted = set(chain_ids)
for it in scene.outliner_items:
    it.is_selected = it.item_id in wanted
with R.view3d_override():
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=puppet_name)
puppet = next(p for p in scene.outliner_items
              if p.item_type == "PUPPET"
              and p.item_id != "puppets_separator"
              and p.name == puppet_name)
return {"molecule_id": mid, "puppet_id": puppet.item_id,
        "puppet_name": puppet.name,
        "controller": puppet.controller_object_name}
'''


def make_puppet(blender, puppet_name="Live_Anim_Puppet") -> dict:
    """Import 4hhb and puppet two of its chains. Returns ids, not RNA rows."""
    return blender.call(_MAKE_PUPPET, puppet_name=puppet_name)


_SEED_BROWNIAN_SEGMENT = '''
ctrl = bpy.data.objects[controller_name]
# A Brownian segment is baked BETWEEN a previous user keyframe and the target
# frame, so the controller needs a starting key to jitter around. Setting
# rotation_mode directly (rather than through the add-on's helper) keeps the
# setup independent of the code being measured.
ctrl.rotation_mode = 'QUATERNION'
ctrl.keyframe_insert(data_path="location", frame=start_frame)
ctrl.keyframe_insert(data_path="rotation_quaternion", frame=start_frame)
return None
'''


# ---------------------------------------------------------------------------
# Keyframes - structure
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_keyframe_protein_writes_a_row_and_a_real_fcurve(blender, single_chain):
    """A keyframe must be both a panel row and a genuine F-curve key.

    The two can diverge: the list entry is add-on bookkeeping while the F-curve
    is what Blender actually plays back, and a keyframe that exists only in the
    list animates nothing. Both frames are checked against the raw
    ``keyframe_points``.
    """
    result = blender.call(with_fcurves('''
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        mol = H.sm().molecules[mid]

        scene.frame_set(1)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_Start", frame_number=1)

        scene.frame_set(30)
        mol.object.location = (0.5, 0.0, 0.0)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_End", frame_number=30)

        item = H.list_item(mid)
        return {
            "rows": [[k.name, k.frame] for k in item.keyframes],
            "fcurve_frames": _keyed_frames(mol.object),
        }
    '''), mid=single_chain)

    assert result["rows"] == [["Live_Start", 1], ["Live_End", 30]]
    assert {1, 30} <= set(result["fcurve_frames"]), (
        "the keyframe rows exist but Blender has no keys to play back at "
        f"frames 1 and 30 (F-curve frames: {result['fcurve_frames']})")


@pytest.mark.live
def test_jump_and_edit_keyframe_move_the_playhead(blender, single_chain):
    """Navigation must actually move ``frame_current``.

    ``edit_keyframe`` normally ends by invoking the Create-Keyframe dialog,
    which this transport cannot survive - a modal dialog blocks Blender's main
    thread and the socket call times out. Its ``skip_dialog`` property is the
    documented escape hatch for scripted callers, and it still exercises the
    part that matters here: the playhead moves BEFORE the dialog would open,
    because the dialog seeds itself from ``scene.frame_current``.
    """
    result = blender.call('''
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        scene.frame_set(30)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_Mid", frame_number=30)
        scene.frame_set(42)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_Late", frame_number=42)

        scene.frame_set(5)
        bpy.ops.proteinblender.jump_to_keyframe('EXEC_DEFAULT', frame=30)
        jumped = scene.frame_current

        scene.frame_set(5)
        bpy.ops.proteinblender.edit_keyframe(
            'EXEC_DEFAULT', frame=42, skip_dialog=True)
        edited = scene.frame_current

        scene.frame_set(5)
        bpy.ops.molecule.select_keyframe('EXEC_DEFAULT', keyframe_index=1)
        selected = scene.frame_current
        return {"jumped": jumped, "edited": edited, "selected": selected,
                "active_index": H.list_item(mid).active_keyframe_index}
    ''', mid=single_chain)

    assert result["jumped"] == 30, "jump_to_keyframe did not move the playhead"
    assert result["edited"] == 42, (
        "edit_keyframe must move the playhead before opening its dialog, "
        "because the dialog seeds itself from scene.frame_current")
    assert result["selected"] == 42, "select_keyframe did not follow its index"
    assert result["active_index"] == 1


@pytest.mark.live
def test_delete_keyframe_removes_the_row_and_its_fcurve_keys(blender,
                                                             single_chain):
    """Deleting a keyframe must clear the underlying keys, not just the row.

    A row-only delete leaves the object still animated at that frame: the panel
    stops listing it while playback keeps honouring it. The surviving keyframe
    is asserted too, so a delete that wipes the whole action cannot pass.
    """
    result = blender.call(with_fcurves('''
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        mol = H.sm().molecules[mid]

        scene.frame_set(1)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_One", frame_number=1)
        scene.frame_set(20)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_Two", frame_number=20)
        before = _keyed_frames(mol.object)

        bpy.ops.molecule.delete_keyframe('EXEC_DEFAULT', keyframe_index=0)
        item = H.list_item(mid)
        return {
            "before": before,
            "rows": [[k.name, k.frame] for k in item.keyframes],
            "after": _keyed_frames(mol.object),
        }
    '''), mid=single_chain)

    assert {1, 20} <= set(result["before"]), "setup did not key both frames"
    assert result["rows"] == [["Live_Two", 20]]
    assert 1 not in result["after"], (
        "the frame-1 row was removed but its F-curve keys survive, so playback "
        "still honours a keyframe the panel no longer shows")
    assert 20 in result["after"], "delete removed the surviving keyframe's keys"


@pytest.mark.live
def test_create_keyframe_keys_a_ticked_puppet_controller(blender):
    """``proteinblender.create_keyframe``, driven through its execute() path.

    The operator is an ``invoke_props_dialog``, but the only thing ``invoke()``
    does that ``execute()`` depends on is fill the ``puppet_items`` checkbox
    collection from the outliner. That is a real ``CollectionProperty``, so it
    can be supplied directly over ``bpy.ops`` and the multi-target aggregation
    runs without the dialog ever opening - which matters here, because an open
    dialog would block the socket.
    """
    setup = make_puppet(blender, "Live_KF_Puppet")

    result = blender.call(with_fcurves('''
        controller = bpy.data.objects[controller_name]
        res = bpy.ops.proteinblender.create_keyframe(
            'EXEC_DEFAULT',
            frame_number=frame,
            puppet_items=[{
                "name": puppet_name,
                "puppet_id": puppet_id,
                "puppet_name": puppet_name,
                "controller_object_name": controller_name,
                "item_kind": "PUPPET",
                "use_puppet": True,
                "keyframe_location": True,
                "keyframe_rotation": True,
                "keyframe_scale": True,
                "keyframe_pose": False,
                "keyframe_color": False,
                "brownian_enabled": False,
            }],
        )
        return {"result": sorted(res),
                "frames": _keyed_frames(controller)}
    '''), controller_name=setup["controller"], puppet_id=setup["puppet_id"],
        puppet_name=setup["puppet_name"], frame=12)

    assert result["result"] == ["FINISHED"]
    assert 12 in result["frames"], (
        "the ticked puppet's controller has no key at frame 12 "
        f"(keys at {result['frames']})")


# ---------------------------------------------------------------------------
# Playback - the assertion this lane exists for
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.visual
def test_scrubbing_between_keyframes_changes_the_viewport(blender, shot):
    """Animation must animate: the screen has to change as the playhead moves.

    Nothing else in the suite can assert this. `--background` has no viewport to
    re-draw, so the headless tests stop at "a keyframe point exists at frame
    30". Between that fact and a protein that visibly moves lie the depsgraph,
    the geometry-nodes evaluation and the object's drawn transform - and a
    molecule whose mesh does not follow its animated object transform satisfies
    every existing assertion while sitting perfectly still on screen.

    Three claims, all metamorphic:
      * the endpoints differ, so the animation has an effect at all;
      * the midpoint differs from BOTH endpoints, so the frames in between are
        genuinely interpolated rather than snapping between two poses;
      * returning to frame 1 reproduces frame 1 exactly, so what was measured is
        the animation and not accumulated drift in the capture path.

    The view is framed once and never re-framed - ``frame_all`` re-centres on
    the geometry and would cancel out the motion being measured. It is framed at
    the MIDPOINT of the motion, so both endpoints stay inside a view that
    ``frame_all`` deliberately zooms in on.
    """
    mid = blender.call('return H.import_local("1ubq.pdb", "1ubq")')

    span = blender.call('''
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        mol = H.sm().molecules[mid]
        pts = H.eval_positions(mol.object)
        span = float((pts.max(axis=0) - pts.min(axis=0)).max())
        home = [float(v) for v in mol.object.location]

        scene.frame_set(1)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_A", frame_number=1)

        # Displaced by a fraction of the molecule's own size. MolecularNodes
        # scales Angstroms by 0.01, so a hard-coded offset of a few units would
        # fly the protein out of frame and turn "it moved" into "it vanished".
        scene.frame_set(30)
        mol.object.location = (home[0] + span * 0.5, home[1],
                               home[2] + span * 0.5)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="Live_B", frame_number=30)
        return span
    ''', mid=mid)
    assert span > 0, "the imported molecule has no measurable size"

    # Frame on the midpoint of the motion so neither endpoint falls outside the
    # view, then leave the view alone for the rest of the test.
    blender.call('bpy.context.scene.frame_set(15)\nreturn R.frame_all()')

    first = blender.call('scene = bpy.context.scene\n'
                         'scene.frame_set(1)\n'
                         'return R.capture("f1")')
    shot("frame-01", frame=False)
    mid_frame = blender.call('scene = bpy.context.scene\n'
                             'scene.frame_set(15)\n'
                             'return R.capture("f15")')
    shot("frame-15", frame=False)
    last = blender.call('scene = bpy.context.scene\n'
                        'scene.frame_set(30)\n'
                        'return R.capture("f30")')
    shot("frame-30", frame=False)
    blender.call('scene = bpy.context.scene\n'
                 'scene.frame_set(1)\n'
                 'return R.capture("f1-again")')

    assert first["covered"] > 0, "nothing was on screen at frame 1"
    assert last["covered"] > 0, (
        "the protein left the frame entirely by frame 30, so this measures "
        "disappearance rather than motion")
    assert mid_frame["covered"] > 0, "nothing was on screen at frame 15"

    ends = blender.call('return R.compare("f1", "f30")')
    assert not ends["identical"], (
        "frames 1 and 30 render identically. The keyframes exist but the "
        "animation is not reaching the screen")

    to_mid = blender.call('return R.compare("f1", "f15")')
    from_mid = blender.call('return R.compare("f15", "f30")')
    assert to_mid["xor"] > 0 and from_mid["xor"] > 0, (
        "frame 15 is identical to one of the endpoints; the motion is snapping "
        "between keyframes instead of interpolating through them")

    replay = blender.call('return R.compare("f1", "f1-again")')
    assert replay["identical"], (
        "returning to frame 1 did not reproduce frame 1 "
        f"(xor={replay['xor']}, rgb_delta={replay['rgb_delta']}); the capture "
        "path or the depsgraph is carrying state between frames, which would "
        "make every frame-to-frame comparison above unreliable")


# ---------------------------------------------------------------------------
# Brownian motion
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_brownian_settings_bakes_jitter_and_metadata(blender):
    """Baking must leave both halves of its footprint: keys and metadata.

    The metadata is what ``brownian_rebuild`` later reads, so a bake that keys
    the controller without recording its configuration produces motion that
    cannot be reproduced or edited.
    """
    setup = make_puppet(blender, "Live_BR_Bake")
    blender.call(_SEED_BROWNIAN_SEGMENT,
                 controller_name=setup["controller"], start_frame=1)

    result = blender.call(with_fcurves('''
        import json
        controller = bpy.data.objects[controller_name]
        res = bpy.ops.proteinblender.brownian_settings(
            'EXEC_DEFAULT',
            controller_object_name=controller_name,
            puppet_id=puppet_id,
            puppet_name=puppet_name,
            frame_number=10,
            jitter_interval=3,
            jitter_max_distance=1.0,
            jitter_max_rotation=30.0,
            use_random_seed=False,
            seed=42,
        )
        metadata = json.loads(controller["pb_brownian_metadata"]) \\
            if "pb_brownian_metadata" in controller else None
        return {"result": sorted(res), "metadata": metadata,
                "n_jitter": len(_jitter_keys(controller))}
    '''), controller_name=setup["controller"], puppet_id=setup["puppet_id"],
        puppet_name=setup["puppet_name"])

    assert result["result"] == ["FINISHED"]
    assert result["metadata"] is not None, "no pb_brownian_metadata was written"
    assert "10" in result["metadata"], (
        f"no segment recorded at the target frame: {sorted(result['metadata'])}")
    assert result["metadata"]["10"]["enabled"] is True
    assert result["n_jitter"] > 0, "no JITTER keyframes were baked"


@pytest.mark.live
def test_brownian_is_reproducible_for_a_fixed_seed(blender):
    """The same seed must produce the same motion; a different seed must not.

    Both halves are needed. Reproducibility alone would also hold for a bake
    that ignored the seed and always emitted the same keys, so the second half -
    a different seed producing different keys - is what proves the seed is
    actually feeding the random source.

    Compared on the raw keyframe coordinates rather than a key count, because
    two entirely different bakes have the same count.
    """
    setup = make_puppet(blender, "Live_BR_Seed")

    result = blender.call(with_fcurves('''
        controller = bpy.data.objects[controller_name]

        def bake(seed):
            # Wipe the previous segment and re-seed the anchoring user keyframe
            # so each bake starts from an identical controller state; otherwise
            # a difference in the keys could just be a difference in where the
            # segment began.
            bpy.ops.proteinblender.brownian_clear_all(
                'EXEC_DEFAULT', controller_object_name=controller_name)
            controller.animation_data_clear()
            controller.location = (0.0, 0.0, 0.0)
            controller.rotation_mode = 'QUATERNION'
            controller.keyframe_insert(data_path="location", frame=1)
            controller.keyframe_insert(data_path="rotation_quaternion", frame=1)
            bpy.ops.proteinblender.brownian_settings(
                'EXEC_DEFAULT',
                controller_object_name=controller_name,
                puppet_id=puppet_id,
                puppet_name=puppet_name,
                frame_number=12,
                jitter_interval=3,
                jitter_max_distance=1.0,
                jitter_max_rotation=30.0,
                use_random_seed=False,
                seed=seed,
            )
            return _jitter_keys(controller)

        first = bake(42)
        second = bake(42)
        other = bake(7)
        return {"first": first, "second": second, "other": other}
    '''), controller_name=setup["controller"], puppet_id=setup["puppet_id"],
        puppet_name=setup["puppet_name"])

    assert result["first"], "the first bake produced no JITTER keys to compare"
    assert result["second"] == result["first"], (
        "two bakes with seed 42 produced different motion, so a saved scene "
        "cannot be reproduced from its stored Brownian settings")
    assert result["other"] != result["first"], (
        "seed 7 produced exactly the motion seed 42 did; the seed is not "
        "reaching the random source, so 'reproducible' above is vacuous")


@pytest.mark.live
def test_brownian_disable_and_clear_all_remove_the_bake(blender):
    """Disable keeps the configuration; clear-all removes it.

    The distinction is the point: ``brownian_disable`` must strip the baked keys
    while leaving metadata behind with ``enabled=False``, so the segment can be
    switched back on, whereas ``brownian_clear_all`` must leave no trace.
    """
    setup = make_puppet(blender, "Live_BR_Off")
    blender.call(_SEED_BROWNIAN_SEGMENT,
                 controller_name=setup["controller"], start_frame=1)

    result = blender.call(with_fcurves('''
        import json
        controller = bpy.data.objects[controller_name]

        def bake():
            bpy.ops.proteinblender.brownian_settings(
                'EXEC_DEFAULT',
                controller_object_name=controller_name,
                puppet_id=puppet_id, puppet_name=puppet_name,
                frame_number=10, jitter_interval=3,
                jitter_max_distance=1.0, jitter_max_rotation=30.0,
                use_random_seed=False, seed=42)

        bake()
        baked = len(_jitter_keys(controller))

        bpy.ops.proteinblender.brownian_disable(
            'EXEC_DEFAULT', controller_object_name=controller_name,
            puppet_id=puppet_id, frame_number=10)
        disabled_meta = json.loads(controller["pb_brownian_metadata"])
        disabled_keys = len(_jitter_keys(controller))

        # Re-enable, then wipe it entirely.
        bake()
        rebuilt = len(_jitter_keys(controller))
        bpy.ops.proteinblender.brownian_rebuild(
            'EXEC_DEFAULT', controller_object_name=controller_name)
        after_rebuild = len(_jitter_keys(controller))

        bpy.ops.proteinblender.brownian_clear_all(
            'EXEC_DEFAULT', controller_object_name=controller_name)
        return {
            "baked": baked,
            "disabled_enabled": disabled_meta["10"]["enabled"],
            "disabled_keys": disabled_keys,
            "rebuilt": rebuilt,
            "after_rebuild": after_rebuild,
            "cleared_keys": len(_jitter_keys(controller)),
            "metadata_gone": "pb_brownian_metadata" not in controller,
        }
    '''), controller_name=setup["controller"], puppet_id=setup["puppet_id"],
        puppet_name=setup["puppet_name"])

    assert result["baked"] > 0, "nothing was baked, so nothing can be removed"
    assert result["disabled_keys"] == 0, "disable left JITTER keys behind"
    assert result["disabled_enabled"] is False, (
        "disable cleared the keys but left the segment marked enabled, so a "
        "rebuild would silently bring the motion back")
    assert result["rebuilt"] > 0
    assert result["after_rebuild"] > 0, (
        "rebuild produced no motion from the stored metadata")
    assert result["cleared_keys"] == 0, "clear-all left baked keys behind"
    assert result["metadata_gone"], "clear-all left its metadata behind"


@pytest.mark.live
@pytest.mark.visual
def test_brownian_jitter_visibly_moves_the_protein(blender, shot):
    """Baked jitter must be visible as motion, not just as keyframe points.

    Brownian motion is a purely visual feature - it exists so a protein looks
    alive - and the headless suite can only count JITTER keys on an Empty. Keys
    on a controller that the member geometry does not follow, or a jitter
    amplitude that rounds to nothing on screen, both leave that count intact.

    The amplitude is scaled from the puppet's own bounding box so the motion is
    a fixed fraction of the protein's size rather than an absolute distance,
    which is what keeps it both visible and inside the framed view.
    """
    setup = make_puppet(blender, "Live_BR_Visual")
    blender.call(_SEED_BROWNIAN_SEGMENT,
                 controller_name=setup["controller"], start_frame=1)

    baked = blender.call(with_fcurves('''
        import numpy as np
        controller = bpy.data.objects[controller_name]
        children = [o for o in bpy.data.objects
                    if o.parent is not None and o.parent == controller]
        pts = np.concatenate([H.eval_positions(o) for o in children])
        span = float((pts.max(axis=0) - pts.min(axis=0)).max())
        bpy.ops.proteinblender.brownian_settings(
            'EXEC_DEFAULT',
            controller_object_name=controller_name,
            puppet_id=puppet_id, puppet_name=puppet_name,
            frame_number=12, jitter_interval=2,
            jitter_max_distance=span * 0.25,
            jitter_max_rotation=30.0,
            use_random_seed=False, seed=42)
        bpy.context.scene.frame_set(1)
        return {"span": span, "n_jitter": len(_jitter_keys(controller))}
    '''), controller_name=setup["controller"], puppet_id=setup["puppet_id"],
        puppet_name=setup["puppet_name"])

    assert baked["n_jitter"] > 0, "no jitter was baked, so nothing can move"

    blender.call("return R.frame_all()")
    start = blender.call('scene = bpy.context.scene\n'
                         'scene.frame_set(1)\n'
                         'return R.capture("br-1")')
    shot("brownian-frame-01", frame=False)
    middle = blender.call('scene = bpy.context.scene\n'
                          'scene.frame_set(6)\n'
                          'return R.capture("br-6")')
    shot("brownian-frame-06", frame=False)
    end = blender.call('scene = bpy.context.scene\n'
                       'scene.frame_set(12)\n'
                       'return R.capture("br-12")')
    shot("brownian-frame-12", frame=False)

    assert start["covered"] > 0 and middle["covered"] > 0 and end["covered"] > 0, (
        "the jittering protein left the frame; the amplitude is drowning the "
        "measurement rather than demonstrating it")

    early = blender.call('return R.compare("br-1", "br-6")')
    late = blender.call('return R.compare("br-6", "br-12")')

    assert early["xor"] > 0, (
        "frames 1 and 6 render identically despite baked JITTER keys between "
        "them; the jitter is not reaching the member geometry")
    assert late["xor"] > 0, (
        "frames 6 and 12 render identically; the jitter stops partway through "
        "the baked segment")
