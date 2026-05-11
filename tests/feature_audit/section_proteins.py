"""Section: protein import, style change, color, delete, duplicate, visibility."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_proteins():
    print("\n" + "=" * 60)
    print("SECTION: PROTEINS")
    print("=" * 60)

    # ----- P1: Import single-chain protein -----
    reset_scene()
    try:
        mid = import_pdb("1aki")
        obj = bpy.data.objects.get("1aki")
        ok = (mid in sm().molecules) and (obj is not None)
        shot = screenshot("P1_import_1aki")
        record("P1", "Import single-chain protein (1aki)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"molecule registered={mid in sm().molecules} obj={obj}",
               repro={"op": "molecule.import_protein", "props": {"pdb_id": "1aki", "import_method": "PDB"}},
               screenshot=shot)
    except Exception as e:
        record("P1", "Import single-chain protein (1aki)", "ERROR",
               error=f"{type(e).__name__}: {e}",
               repro={"op": "molecule.import_protein", "props": {"pdb_id": "1aki"}},
               notes=traceback.format_exc()[:500])

    # ----- P2: Import multi-chain protein -----
    try:
        mid = import_pdb("4hhb")
        mol = sm().molecules.get(mid)
        domain_count = len(mol.domains) if mol else 0
        ok = mol is not None and domain_count == 4  # 4hhb has 4 chains
        shot = screenshot("P2_import_4hhb")
        record("P2", "Import multi-chain protein (4hhb) — auto-domain count == 4",
               "PASS" if ok else "FAIL",
               error=None if ok else f"got {domain_count} auto-domains",
               repro={"op": "molecule.import_protein", "props": {"pdb_id": "4hhb"}},
               screenshot=shot)
    except Exception as e:
        record("P2", "Import multi-chain protein (4hhb)", "ERROR",
               error=f"{type(e).__name__}: {e}", notes=traceback.format_exc()[:500])

    # ----- P3: Change protein style -----
    try:
        scene = bpy.context.scene
        scene.selected_molecule_id = "1aki_001"
        scene.molecule_style = "spheres"
        # Verify by reading the list-item style
        item = next((it for it in scene.molecule_list_items if it.identifier == "1aki_001"), None)
        ok = item is not None and item.style == "spheres"
        shot = screenshot("P3_style_spheres")
        record("P3", "Change protein style ribbon→spheres",
               "PASS" if ok else "FAIL",
               error=None if ok else f"item.style={getattr(item,'style','<no item>')}",
               repro={"op": "scene.molecule_style = 'spheres'", "preconditions": "selected_molecule_id=1aki_001"},
               screenshot=shot)
    except Exception as e:
        record("P3", "Change protein style", "ERROR", error=f"{type(e).__name__}: {e}")

    # ----- P4: Duplicate protein -----
    try:
        before = set(sm().molecules.keys())
        bpy.ops.molecule.duplicate_protein(molecule_id="1aki_001")
        after = set(sm().molecules.keys())
        new = sorted(after - before)
        ok = len(new) == 1
        shot = screenshot("P4_duplicate")
        record("P4", "Duplicate protein (1aki_001)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"new molecules: {new}",
               repro={"op": "molecule.duplicate_protein", "props": {"molecule_id": "1aki_001"}},
               screenshot=shot)
    except Exception as e:
        record("P4", "Duplicate protein", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- P5: Toggle visibility -----
    try:
        obj = bpy.data.objects.get("4hhb")
        if obj:
            before_hide = obj.hide_get()
            bpy.ops.molecule.toggle_visibility(molecule_id="4hhb_001")
            after_hide = obj.hide_get()
            ok = before_hide != after_hide
            # restore
            bpy.ops.molecule.toggle_visibility(molecule_id="4hhb_001")
            record("P5", "Toggle protein visibility",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"hide unchanged: {before_hide}",
                   repro={"op": "molecule.toggle_visibility", "props": {"molecule_id": "4hhb_001"}})
        else:
            record("P5", "Toggle protein visibility", "SKIP", notes="4hhb missing")
    except Exception as e:
        record("P5", "Toggle protein visibility", "ERROR", error=f"{type(e).__name__}: {e}")

    # ----- P6: Center protein at origin -----
    try:
        obj = bpy.data.objects.get("4hhb")
        if obj:
            obj.location = (5.0, 3.0, 1.0)
            bpy.ops.molecule.center_protein(molecule_id="4hhb_001")
            new_loc = tuple(obj.location)
            ok = max(abs(x) for x in new_loc) < 1.0  # roughly at origin
            record("P6", "Center protein at origin",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"new loc {new_loc}",
                   repro={"op": "molecule.center_protein", "props": {"molecule_id": "4hhb_001"},
                          "precondition": "obj.location set to (5,3,1)"})
        else:
            record("P6", "Center protein at origin", "SKIP", notes="4hhb missing")
    except Exception as e:
        record("P6", "Center protein at origin", "ERROR", error=f"{type(e).__name__}: {e}")

    # ----- P7: Delete protein (one of two molecules) -----
    try:
        before = set(sm().molecules.keys())
        if "1aki_001" not in before:
            record("P7", "Delete protein (1aki_001)", "SKIP", notes="1aki_001 missing")
        else:
            bpy.ops.molecule.delete(molecule_id="1aki_001")
            after = set(sm().molecules.keys())
            obj_gone = bpy.data.objects.get("1aki") is None
            item_gone = not any(it.identifier == "1aki_001" for it in bpy.context.scene.molecule_list_items)
            ok = "1aki_001" not in after and obj_gone and item_gone
            shot = screenshot("P7_after_delete_1aki")
            record("P7", "Delete protein (1aki_001) — wrapper+obj+list_item all gone",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"wrapper_gone={'1aki_001' not in after} obj_gone={obj_gone} item_gone={item_gone}",
                   repro={"op": "molecule.delete", "props": {"molecule_id": "1aki_001"}},
                   screenshot=shot)
    except Exception as e:
        record("P7", "Delete protein", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_proteins()
print("\n--- Section complete ---\n")
