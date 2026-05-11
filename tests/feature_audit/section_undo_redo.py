"""Section: undo/redo across creation and deletion operations.

The merged save/load fix relies on sync_molecule_list_after_undo to
reconstruct wrappers from PropertyGroups after Blender's undo restores
deleted objects. We verify the round-trip for several operations."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_undo_redo():
    print("\n" + "=" * 60)
    print("SECTION: UNDO / REDO")
    print("=" * 60)

    # ----- UR1: Undo a protein import -----
    reset_scene()
    try:
        # Push an undo step so we have something to come back to
        bpy.ops.ed.undo_push(message="baseline")
        mid = import_pdb("1aki")
        before_undo = mid in sm().molecules
        bpy.ops.ed.undo()
        sm_module().sync_molecule_list_after_undo()
        after_undo = "1aki_001" in sm().molecules
        ok = before_undo and not after_undo
        record("UR1", "Undo a protein import removes the molecule",
               "PASS" if ok else "FAIL",
               error=None if ok else f"before_undo present={before_undo} after_undo present={after_undo}",
               repro={"steps": ["ed.undo_push baseline", "molecule.import_protein 1aki",
                                "ed.undo", "sync_molecule_list_after_undo"]})
    except Exception as e:
        record("UR1", "Undo protein import", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- UR2: Redo brings it back -----
    try:
        bpy.ops.ed.redo()
        sm_module().sync_molecule_list_after_undo()
        ok = "1aki_001" in sm().molecules
        record("UR2", "Redo after undo restores the molecule",
               "PASS" if ok else "FAIL",
               error=None if ok else f"molecules={list(sm().molecules.keys())}",
               repro={"steps": ["follows UR1 then ed.redo + sync"]})
    except Exception as e:
        record("UR2", "Redo protein import", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- UR3: Undo a protein DELETE -----
    reset_scene()
    try:
        mid = import_pdb("1aki")
        bpy.ops.ed.undo_push(message="post_import")
        bpy.ops.molecule.delete(molecule_id=mid)
        gone = mid not in sm().molecules
        bpy.ops.ed.undo()
        sm_module().sync_molecule_list_after_undo()
        restored = mid in sm().molecules
        obj_back = bpy.data.objects.get("1aki") is not None
        ok = gone and restored and obj_back
        record("UR3", "Undo a molecule.delete restores the protein + wrapper",
               "PASS" if ok else "FAIL",
               error=None if ok else f"gone_after_delete={gone} restored={restored} obj_back={obj_back}",
               repro={"steps": ["import 1aki", "undo_push", "molecule.delete",
                                "ed.undo", "sync_molecule_list_after_undo"]})
    except Exception as e:
        record("UR3", "Undo molecule delete", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- UR4: Undo a DNA build -----
    reset_scene()
    try:
        bpy.ops.ed.undo_push(message="pre_dna")
        dna = build_dna(seq="ATCG", name_prefix="UndoDNA")
        before = dna is not None and dna.get("pb_is_nucleic_acid")
        bpy.ops.ed.undo()
        sm_module().sync_molecule_list_after_undo()
        # Object should be gone OR wrapper gone
        after_objs = [o.name for o in bpy.data.objects if o.get("pb_is_nucleic_acid")]
        after_mols = [k for k, v in sm().molecules.items() if k.startswith("UndoDNA")]
        ok = before and not after_objs and not after_mols
        shot = screenshot("UR4_after_undo_dna_build")
        record("UR4", "Undo a DNA build removes object + wrapper",
               "PASS" if ok else "FAIL",
               error=None if ok else f"after_undo_objs={after_objs} after_undo_mols={after_mols}",
               repro={"steps": ["undo_push", "proteinblender.build_dna", "ed.undo", "sync"]},
               screenshot=shot)
    except Exception as e:
        record("UR4", "Undo DNA build", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- UR5: Undo a domain split -----
    reset_scene()
    try:
        mid = import_pdb("4hhb")
        mol = sm().molecules[mid]
        before_count = len(mol.domains)
        bpy.ops.ed.undo_push(message="pre_split")
        # Need to call the split operator via outliner OR direct properties
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        bpy.ops.proteinblender.split_domain(chain_id="A", molecule_id=mid, split_start=1, split_end=50)
        after_split = len(mol.domains)
        bpy.ops.ed.undo()
        sm_module().sync_molecule_list_after_undo()
        # Re-resolve molecule (wrapper may have been re-built)
        mol = sm().molecules.get(mid)
        after_undo = len(mol.domains) if mol else -1
        ok = after_split == before_count + 1 and after_undo == before_count
        record("UR5", "Undo a domain split restores original count",
               "PASS" if ok else "FAIL",
               error=None if ok else f"before={before_count} after_split={after_split} after_undo={after_undo}",
               repro={"steps": ["import 4hhb", "undo_push", "split_domain chain A 1-50",
                                "ed.undo", "sync"]})
    except Exception as e:
        record("UR5", "Undo domain split", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_undo_redo()
print("\n--- Section complete ---\n")
