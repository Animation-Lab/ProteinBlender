"""Section: pose create / apply (switch) / update / rename / delete."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_poses():
    print("\n" + "=" * 60)
    print("SECTION: POSES")
    print("=" * 60)

    reset_scene()
    mid = import_pdb("4hhb")
    mol = sm().molecules[mid]
    scene = bpy.context.scene
    scene.selected_molecule_id = mid

    # ----- PO1: Create pose with default-positioned domains -----
    try:
        before = len(next(it for it in scene.molecule_list_items if it.identifier == mid).poses)
        res = bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Pose_Default")
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        after = len(item.poses)
        ok = after == before + 1 and item.poses[after - 1].name == "Pose_Default"
        n_tx = len(item.poses[after - 1].domain_transforms) if after > 0 else 0
        shot = screenshot("PO1_create_pose_default")
        record("PO1", "Create pose 'Pose_Default' capturing 4 domain transforms",
               "PASS" if ok and n_tx == 4 else "FAIL",
               error=None if ok and n_tx == 4 else f"poses {before}->{after}, transforms={n_tx}, last_name={item.poses[-1].name if after else None}",
               repro={"op": "molecule.create_pose", "props": {"pose_name": "Pose_Default"},
                      "precondition": "selected_molecule_id=4hhb_001"},
               screenshot=shot)
    except Exception as e:
        record("PO1", "Create pose default", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PO2: Move domains, create second pose -----
    try:
        dids = sorted(mol.domains.keys())
        # Move first two chains far apart
        for i, did in enumerate(dids[:2]):
            d = mol.domains[did]
            if d.object:
                d.object.location = (3.0 * (i + 1), 2.0, 1.0)
                d.object.rotation_euler = (0.2, 0.1, 0.3 * (i + 1))

        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="Pose_Moved")
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        ok = len(item.poses) == 2 and item.poses[1].name == "Pose_Moved"
        # Verify the stored transforms reflect moved positions
        stored = {t.domain_id: tuple(t.location) for t in item.poses[1].domain_transforms}
        first_did = dids[0]
        expected_first = (3.0, 2.0, 1.0)
        delta = sum((stored.get(first_did, (0,0,0))[i] - expected_first[i]) ** 2 for i in range(3)) ** 0.5
        ok2 = delta < 0.1
        shot = screenshot("PO2_create_pose_moved")
        record("PO2", "Create pose 'Pose_Moved' captures translated domain positions",
               "PASS" if ok and ok2 else "FAIL",
               error=None if ok and ok2 else f"poses={len(item.poses)}, stored_first={stored.get(first_did)}, delta={delta}",
               repro={"op": "molecule.create_pose",
                      "props": {"pose_name": "Pose_Moved"},
                      "preconditions": ["chain A moved to (3, 2, 1)", "chain B moved to (6, 2, 1)"]},
               screenshot=shot)
    except Exception as e:
        record("PO2", "Create pose moved", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PO3: Apply pose to switch between them -----
    try:
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        first_did = sorted(mol.domains.keys())[0]
        # Switch to Pose_Default (idx 0) — first chain should snap back to origin
        bpy.ops.molecule.apply_pose('EXEC_DEFAULT', pose_index="0")
        loc_after_default = tuple(mol.domains[first_did].object.location)
        # Apply Pose_Moved — should put it back at (3, 2, 1)
        bpy.ops.molecule.apply_pose('EXEC_DEFAULT', pose_index="1")
        loc_after_moved = tuple(mol.domains[first_did].object.location)
        ok = (max(abs(x) for x in loc_after_default) < 0.5
              and abs(loc_after_moved[0] - 3.0) < 0.1)
        shot = screenshot("PO3_after_apply_moved")
        record("PO3", "Apply pose toggles domain positions between 2 stored states",
               "PASS" if ok else "FAIL",
               error=None if ok else f"after Pose_Default loc={loc_after_default}, after Pose_Moved loc={loc_after_moved}",
               repro={"ops": ["molecule.apply_pose(pose_index='0')",
                              "molecule.apply_pose(pose_index='1')"]},
               screenshot=shot)
    except Exception as e:
        record("PO3", "Apply pose", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PO4: Update existing pose -----
    try:
        # Move chain A somewhere new, then update Pose_Default to capture it
        first_did = sorted(mol.domains.keys())[0]
        mol.domains[first_did].object.location = (9.0, 9.0, 9.0)
        bpy.ops.molecule.update_pose('EXEC_DEFAULT', pose_index="0")
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        stored_first = next((t for t in item.poses[0].domain_transforms if t.domain_id == first_did), None)
        ok = stored_first is not None and abs(stored_first.location[0] - 9.0) < 0.1
        record("PO4", "Update pose overwrites stored transforms",
               "PASS" if ok else "FAIL",
               error=None if ok else f"stored.location={tuple(stored_first.location) if stored_first else None}",
               repro={"op": "molecule.update_pose",
                      "props": {"pose_index": "0"},
                      "precondition": "first chain moved to (9, 9, 9)"})
    except Exception as e:
        record("PO4", "Update pose", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PO5: Rename pose -----
    try:
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        item.active_pose_index = 0  # rename_pose uses active_pose_index
        bpy.ops.molecule.rename_pose('EXEC_DEFAULT', new_name="Renamed_Pose")
        ok = item.poses[0].name == "Renamed_Pose"
        record("PO5", "Rename pose",
               "PASS" if ok else "FAIL",
               error=None if ok else f"name={item.poses[0].name!r}",
               repro={"op": "molecule.rename_pose",
                      "props": {"new_name": "Renamed_Pose"},
                      "precondition": "item.active_pose_index = 0"})
    except Exception as e:
        record("PO5", "Rename pose", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PO6: Delete pose -----
    try:
        item = next(it for it in scene.molecule_list_items if it.identifier == mid)
        before = len(item.poses)
        item.active_pose_index = 0
        bpy.ops.molecule.delete_pose('EXEC_DEFAULT')
        after = len(item.poses)
        ok = after == before - 1
        record("PO6", "Delete pose",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count {before} -> {after}",
               repro={"op": "molecule.delete_pose",
                      "precondition": "item.active_pose_index = 0"})
    except Exception as e:
        record("PO6", "Delete pose", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_poses()
print("\n--- Section complete ---\n")
