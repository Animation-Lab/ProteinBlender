"""Section: save/load checkpoints for protein + DNA + puppet + linker + animation.

Each test does setup → save → fresh-process load → verify diff.
Saved blends and verify-state JSONs land in tests/feature_audit/results/.
"""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
import subprocess
load_existing_results()

BLENDS_DIR = RESULTS / "blends"
BLENDS_DIR.mkdir(parents=True, exist_ok=True)
VERIFY_SCRIPT = RESULTS / "_verify_subprocess.py"

# Write a dump script the subprocess will run after loading the blend
VERIFY_SCRIPT.write_text(r"""
import sys, json, bpy
out_path = sys.argv[sys.argv.index('--') + 1]
import bl_ext.vscode_development.proteinblender.utils.scene_manager as sm_mod
sm_mod.sync_molecule_list_after_undo()
mgr = sm_mod.ProteinBlenderScene.get_instance()
scene = bpy.context.scene
snap = {
    "blend": bpy.data.filepath,
    "manager_ids": sorted(mgr.molecules.keys()),
    "list_items": [
        {
            "id": it.identifier,
            "object_name": it.object_name,
            "style": getattr(it, "style", None),
            "n_domains": len(it.domains),
            "n_poses": len(it.poses),
            "n_keyframes": len(it.keyframes),
        }
        for it in scene.molecule_list_items
    ],
    "outliner_count": len(scene.outliner_items),
    "outliner_types": {},
    "linker_count": len(scene.pb2_linkers) if hasattr(scene, 'pb2_linkers') else 0,
    "linker_uids": [l.uid for l in scene.pb2_linkers] if hasattr(scene, 'pb2_linkers') else [],
    "nucleic_objs": sorted(o.name for o in bpy.data.objects if o.get("pb_is_nucleic_acid")),
    "puppet_count": sum(1 for it in scene.outliner_items if it.item_type == "PUPPET"),
}
for it in scene.outliner_items:
    snap["outliner_types"][it.item_type] = snap["outliner_types"].get(it.item_type, 0) + 1
open(out_path, "w").write(json.dumps(snap, indent=2, default=str))
""")


BLENDER = r"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"


def verify_in_subprocess(blend_path, verify_json_path):
    cmd = [BLENDER, "--background", str(blend_path),
           "--python", str(VERIFY_SCRIPT), "--", str(verify_json_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        print(f"verify subprocess rc={proc.returncode}, stderr tail: {proc.stderr[-500:]}")
        return None
    return json.loads(verify_json_path.read_text())


def run_saveload():
    print("\n" + "=" * 60)
    print("SECTION: SAVE / LOAD")
    print("=" * 60)

    # ----- SL1: Save+load a single protein -----
    reset_scene()
    try:
        mid = import_pdb("1aki")
        blend_path = BLENDS_DIR / "sl1_single_protein.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl1_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        ok = snap is not None and mid in snap.get("manager_ids", [])
        record("SL1", "Save+load a single protein roundtrips manager state",
               "PASS" if ok else "FAIL",
               error=None if ok else f"snap manager_ids={snap.get('manager_ids') if snap else None}",
               repro={"steps": ["reset", "import_pdb 1aki", "save_as_mainfile",
                                "fresh blender --background <blend> verify_dump"]},
               notes=f"verify snap: {snap}" if snap else "")
    except Exception as e:
        record("SL1", "Save+load protein", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- SL2: Save+load multi-chain protein with domains intact -----
    reset_scene()
    try:
        mid = import_pdb("4hhb")
        blend_path = BLENDS_DIR / "sl2_multi_chain.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl2_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        item_4hhb = next((it for it in snap.get("list_items", []) if it["id"] == mid), None) if snap else None
        ok = item_4hhb is not None and item_4hhb["n_domains"] == 4
        record("SL2", "Save+load 4hhb preserves 4 auto-chain-domains (Bug B regression guard)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"item={item_4hhb}",
               repro={"steps": ["reset", "import_pdb 4hhb", "save_as_mainfile",
                                "fresh blender verify"]},
               notes=str(snap)[:300] if snap else "")
    except Exception as e:
        record("SL2", "Save+load multi-chain", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- SL3: Save+load mixed scene: protein + DNA + bend -----
    reset_scene()
    try:
        mid = import_pdb("1aki")
        dna = build_dna(seq="ATCGATCGATCG", name_prefix="MixDNA")
        select_only(dna)
        bpy.ops.proteinblender.dna_add_bend()
        blend_path = BLENDS_DIR / "sl3_mixed.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl3_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        if snap is None:
            record("SL3", "Save+load protein+DNA+bend", "FAIL", error="verify subprocess failed")
        else:
            mids = snap.get("manager_ids", [])
            nucleic_objs = snap.get("nucleic_objs", [])
            ok = mid in mids and any("MixDNA" in n for n in nucleic_objs)
            record("SL3", "Save+load mixed protein + DNA + bend",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"mids={mids} nucleic={nucleic_objs}",
                   repro={"steps": ["import 1aki", "build DNA MixDNA", "add bend", "save"]},
                   notes=str(snap)[:400])
    except Exception as e:
        record("SL3", "Save+load mixed", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- SL4: Save+load with poses on a multi-chain protein -----
    reset_scene()
    try:
        from mathutils import Vector
        mid = import_pdb("4hhb")
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        # Move a domain, make a pose
        mol = sm().molecules[mid]
        dids = sorted(mol.domains.keys())
        if mol.domains[dids[0]].object:
            mol.domains[dids[0]].object.location = (3.0, 0, 0)
        bpy.ops.molecule.create_pose('EXEC_DEFAULT', pose_name="SL_Pose")
        blend_path = BLENDS_DIR / "sl4_with_pose.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl4_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        if snap is None:
            record("SL4", "Save+load pose", "FAIL", error="verify subprocess failed")
        else:
            item_4hhb = next((it for it in snap["list_items"] if it["id"] == mid), None)
            ok = item_4hhb is not None and item_4hhb["n_poses"] >= 1
            record("SL4", "Save+load preserves pose data",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"item={item_4hhb}",
                   repro={"steps": ["import 4hhb", "move chain A", "create_pose SL_Pose", "save"]})
    except Exception as e:
        record("SL4", "Save+load pose", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- SL5: Save+load with keyframes -----
    reset_scene()
    try:
        mid = import_pdb("1aki")
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        bpy.ops.molecule.keyframe_protein('EXEC_DEFAULT', keyframe_name="SL_KF", frame_number=1)
        blend_path = BLENDS_DIR / "sl5_with_kf.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl5_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        if snap is None:
            record("SL5", "Save+load keyframe", "FAIL", error="verify subprocess failed")
        else:
            item = next((it for it in snap["list_items"] if it["id"] == mid), None)
            ok = item is not None and item["n_keyframes"] >= 1
            record("SL5", "Save+load preserves keyframe metadata",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"item={item}",
                   repro={"steps": ["import 1aki", "keyframe_protein", "save"]})
    except Exception as e:
        record("SL5", "Save+load keyframe", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- SL6: Save+load with puppet + linker -----
    reset_scene()
    try:
        # build puppet+linker scene
        mid = import_pdb("4hhb")
        sm_module().build_outliner_hierarchy(bpy.context)
        scene = bpy.context.scene
        chain_ids = [it.item_id for it in scene.outliner_items
                     if it.item_type == "CHAIN" and ("Chain A" in it.name or "Chain B" in it.name)]
        for it in scene.outliner_items:
            it.is_selected = (it.item_id in chain_ids)
        bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="SL_Puppet")
        puppet_id = next((it.item_id for it in scene.outliner_items
                          if it.item_type == "PUPPET" and it.name == "SL_Puppet"), None)
        bpy.ops.pb2.add_linker(
            'EXEC_DEFAULT',
            puppet_selector=puppet_id,
            endpoint_a_item=f"A_{chain_ids[0]}",
            endpoint_a_residue=5,
            endpoint_b_item=f"B_{chain_ids[1]}",
            endpoint_b_residue=5,
            linker_name="SL_Linker",
        )
        blend_path = BLENDS_DIR / "sl6_puppet_linker.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        verify_path = BLENDS_DIR / "sl6_verify.json"
        snap = verify_in_subprocess(blend_path, verify_path)
        if snap is None:
            record("SL6", "Save+load puppet+linker", "FAIL", error="verify subprocess failed")
        else:
            ok = snap["puppet_count"] >= 1 and snap["linker_count"] >= 1
            record("SL6", "Save+load preserves puppet + linker",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"puppets={snap['puppet_count']} linkers={snap['linker_count']}",
                   repro={"steps": ["import 4hhb", "create_puppet", "add_linker", "save"]},
                   notes=f"linker uids in snap: {snap.get('linker_uids')}")
    except Exception as e:
        record("SL6", "Save+load puppet+linker", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_saveload()
print("\n--- Section complete ---\n")
