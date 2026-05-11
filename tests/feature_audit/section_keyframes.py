"""Section: keyframe create / edit / delete / jump on a protein."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_keyframes():
    print("\n" + "=" * 60)
    print("SECTION: KEYFRAMES")
    print("=" * 60)

    reset_scene()
    mid = import_pdb("1aki")
    scene = bpy.context.scene
    scene.selected_molecule_id = mid

    # ----- KF1: Create a keyframe on a protein at the current frame -----
    try:
        scene.frame_current = 1
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        before = len(item.keyframes)
        res = bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="KF_Start", frame_number=1
        )
        after = len(item.keyframes)
        ok = after == before + 1 and item.keyframes[-1].name == "KF_Start"
        record("KF1", "Create keyframe 'KF_Start' at frame 1",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count {before}->{after}, last name={item.keyframes[-1].name if after else None}",
               repro={"op": "molecule.keyframe_protein",
                      "props": {"keyframe_name": "KF_Start", "frame_number": 1},
                      "precondition": "selected_molecule_id=1aki_001, frame_current=1"})
    except Exception as e:
        record("KF1", "Create keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- KF2: Move protein, create second keyframe at frame 30 -----
    try:
        scene.frame_current = 30
        obj = bpy.data.objects.get("1aki")
        if obj:
            obj.location = (5.0, 0.0, 0.0)
        bpy.ops.molecule.keyframe_protein(
            'EXEC_DEFAULT', keyframe_name="KF_Mid", frame_number=30
        )
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        ok = len(item.keyframes) == 2 and item.keyframes[1].name == "KF_Mid" and item.keyframes[1].frame == 30
        record("KF2", "Create second keyframe at frame 30 with translated protein",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count={len(item.keyframes)}, frames={[k.frame for k in item.keyframes]}",
               repro={"op": "molecule.keyframe_protein",
                      "props": {"keyframe_name": "KF_Mid", "frame_number": 30},
                      "precondition": "frame_current=30, 1aki.location=(5,0,0)"})
    except Exception as e:
        record("KF2", "Create second keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- KF3: Jump to keyframe (reads item.active_keyframe_index) -----
    try:
        scene.frame_current = 5  # somewhere else
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        # proteinblender.jump_to_keyframe takes no kwargs — it reads
        # item.active_keyframe_index. Set that to the second keyframe.
        item.active_keyframe_index = 1
        res = bpy.ops.proteinblender.jump_to_keyframe('EXEC_DEFAULT')
        ok = scene.frame_current == 30
        record("KF3", "Jump to keyframe via active_keyframe_index -> scene.frame_current == 30",
               "PASS" if ok else "FAIL",
               error=None if ok else f"frame_current={scene.frame_current}, ops={res}",
               repro={"op": "proteinblender.jump_to_keyframe",
                      "preconditions": ["frame_current=5", "item.active_keyframe_index = 1"]})
    except Exception as e:
        record("KF3", "Jump to keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- KF4: Edit keyframe (rename + move frame) -----
    try:
        bpy.ops.molecule.edit_keyframe(
            'EXEC_DEFAULT', keyframe_index=0, keyframe_name="KF_Start_Renamed", frame_number=2
        )
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        kf = item.keyframes[0]
        ok = kf.name == "KF_Start_Renamed" and kf.frame == 2
        record("KF4", "Edit keyframe: rename + change frame",
               "PASS" if ok else "FAIL",
               error=None if ok else f"name={kf.name!r} frame={kf.frame}",
               repro={"op": "molecule.edit_keyframe",
                      "props": {"keyframe_index": 0, "keyframe_name": "KF_Start_Renamed", "frame_number": 2}})
    except Exception as e:
        record("KF4", "Edit keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- KF5: Delete keyframe -----
    try:
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        before = len(item.keyframes)
        bpy.ops.molecule.delete_keyframe('EXEC_DEFAULT', keyframe_index=0)
        after = len(item.keyframes)
        ok = after == before - 1
        record("KF5", "Delete keyframe (index 0)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count {before} -> {after}",
               repro={"op": "molecule.delete_keyframe", "props": {"keyframe_index": 0}})
    except Exception as e:
        record("KF5", "Delete keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- KF6: Verify F-curves actually exist on protein object -----
    try:
        obj = bpy.data.objects.get("1aki")
        action = obj.animation_data.action if (obj and obj.animation_data) else None
        # Count F-curves spanning locations
        fcurve_count = 0
        if action:
            # Blender 5 layered actions
            try:
                for layer in action.layers:
                    for strip in layer.strips:
                        for sb in strip.channelbag(action.slots[0]).fcurves:
                            fcurve_count += 1
            except Exception:
                try:
                    fcurve_count = len(action.fcurves)
                except Exception:
                    fcurve_count = -1
        ok = fcurve_count >= 3  # location x/y/z at minimum
        record("KF6", "F-curves exist after keyframe ops (>=3 channels)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"fcurve_count={fcurve_count}, action={action}",
               repro={"note": "Inspect 1aki object's animation_data.action F-curves"})
    except Exception as e:
        record("KF6", "F-curve check", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    shot = screenshot("KF_final_state")


run_keyframes()
print("\n--- Section complete ---\n")
