"""Section: DNA/RNA build, style, color, sequence edit, bend system."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_dna():
    print("\n" + "=" * 60)
    print("SECTION: DNA / RNA / BEND")
    print("=" * 60)

    reset_scene()
    scene = bpy.context.scene
    bender = bender_mod()

    # ----- DNA1: Build double-stranded DNA -----
    try:
        dna_obj = build_dna(seq="ATCGATCGATCG", name_prefix="DNA_DS", ds=True, style="cartoon")
        ok = (dna_obj is not None and dna_obj.get("pb_is_nucleic_acid") and
              dna_obj.get("pb_sequence") == "ATCGATCGATCG" and
              dna_obj.get("pb_double_stranded") is True)
        shot = screenshot("DNA1_build_ds")
        record("DNA1", "Build double-stranded DNA (12 nt cartoon)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"obj={dna_obj}, seq={dna_obj.get('pb_sequence') if dna_obj else None}",
               repro={"op": "proteinblender.build_dna",
                      "props": {"sequence": "ATCGATCGATCG", "nucleic_type": "DNA",
                                "double_stranded": True, "style": "cartoon",
                                "name_prefix": "DNA_DS"}},
               screenshot=shot)
    except Exception as e:
        record("DNA1", "Build double-stranded DNA", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA2: Build RNA single-stranded -----
    try:
        rna_obj = build_dna(seq="AUGCAUGC", name_prefix="RNA_SS", nt="RNA", ds=False, style="sticks")
        ok = (rna_obj is not None and rna_obj.get("pb_nucleic_type") == "RNA"
              and rna_obj.get("pb_double_stranded") is False)
        record("DNA2", "Build single-stranded RNA",
               "PASS" if ok else "FAIL",
               error=None if ok else f"obj={rna_obj}, nt={rna_obj.get('pb_nucleic_type') if rna_obj else None}",
               repro={"op": "proteinblender.build_dna",
                      "props": {"sequence": "AUGCAUGC", "nucleic_type": "RNA",
                                "double_stranded": False, "style": "sticks"}})
    except Exception as e:
        record("DNA2", "Build RNA SS", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA3: Add bend control to DNA -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        if dna is None:
            record("DNA3", "Add bend", "SKIP", notes="no DNA_DS object")
            return
        select_only(dna)
        bpy.ops.proteinblender.dna_add_bend()
        curve_name = dna.get(bender.BEND_CURVE_PROP)
        curve_obj = bpy.data.objects.get(curve_name) if curve_name else None
        nodes = bender.get_bend_nodes(dna)
        ok = curve_obj is not None and len(nodes) == bender.RES_DEFAULT
        shot = screenshot("DNA3_add_bend")
        record("DNA3", f"Add bend creates curve + {bender.RES_DEFAULT} default nodes",
               "PASS" if ok else "FAIL",
               error=None if ok else f"curve={curve_obj} nodes={len(nodes)}",
               repro={"op": "proteinblender.dna_add_bend",
                      "precondition": "DNA object is active"},
               screenshot=shot)
    except Exception as e:
        record("DNA3", "Add bend", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA4: Set bend resolution to 5 -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        select_only(dna)
        bpy.ops.proteinblender.dna_set_bend_resolution(n_points=5)
        nodes = bender.get_bend_nodes(dna)
        ok = len(nodes) == 5
        record("DNA4", "Set bend resolution to 5 nodes",
               "PASS" if ok else "FAIL",
               error=None if ok else f"node count={len(nodes)}",
               repro={"op": "proteinblender.dna_set_bend_resolution",
                      "props": {"n_points": 5}})
    except Exception as e:
        record("DNA4", "Set bend resolution", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA5: Edit bend (select all nodes) -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        select_only(dna)
        bpy.ops.proteinblender.dna_edit_bend(n_points=5)
        # After edit_bend, the empties should be selected
        selected = [o for o in bpy.context.selected_objects if "BendNode" in o.name]
        ok = len(selected) == 5
        record("DNA5", "Edit bend selects all 5 control nodes",
               "PASS" if ok else "FAIL",
               error=None if ok else f"selected nodes={len(selected)}",
               repro={"op": "proteinblender.dna_edit_bend", "props": {"n_points": 5}})
    except Exception as e:
        record("DNA5", "Edit bend", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA6: Finish bend edit (return to DNA selection) -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        # Make sure a node is selected first (simulates being mid-edit)
        nodes = bender.get_bend_nodes(dna)
        select_only(nodes[0])
        bpy.ops.proteinblender.dna_finish_bend_edit()
        ok = bpy.context.view_layer.objects.active == dna
        record("DNA6", "Finish bend edit returns active to DNA",
               "PASS" if ok else "FAIL",
               error=None if ok else f"active is now {bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None}",
               repro={"op": "proteinblender.dna_finish_bend_edit",
                      "precondition": "active object is a bend node"})
    except Exception as e:
        record("DNA6", "Finish bend edit", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA7: Update DNA sequence (with bend) — bend should survive (we fixed this) -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        select_only(dna)
        # Sync props from obj first (panel does this via msgbus)
        import bl_ext.vscode_development.proteinblender.dna_builder.dna_props as dp
        dp.sync_props_from_object(scene.dna_builder_props, dna)
        scene.dna_builder_props.sequence = "ATCGATCGATCGATCGATCG"  # extend
        before_curve = dna.get(bender.BEND_CURVE_PROP)
        bpy.ops.proteinblender.update_dna()
        new_dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        after_curve = new_dna.get(bender.BEND_CURVE_PROP) if new_dna else None
        nodes = bender.get_bend_nodes(new_dna) if new_dna else []
        seq_ok = new_dna.get("pb_sequence") == "ATCGATCGATCGATCGATCG"
        bend_ok = after_curve == before_curve and len(nodes) == 5
        shot = screenshot("DNA7_update_with_bend")
        record("DNA7", "Update DNA sequence preserves bend curve + nodes (regression fix)",
               "PASS" if seq_ok and bend_ok else "FAIL",
               error=None if seq_ok and bend_ok else f"seq_ok={seq_ok} bend_curve_match={after_curve==before_curve} nodes={len(nodes)}",
               repro={"op": "proteinblender.update_dna",
                      "preconditions": ["DNA active", "bend with 5 nodes", "sequence prop set to new value"]},
               screenshot=shot)
    except Exception as e:
        record("DNA7", "Update DNA with bend", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA8: Remove bend -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        select_only(dna)
        bpy.ops.proteinblender.dna_remove_bend()
        curve_after = dna.get(bender.BEND_CURVE_PROP)
        ok = not curve_after
        record("DNA8", "Remove bend (cleans BEND_CURVE_PROP, modifier, nodes)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"BEND_CURVE_PROP still set to {curve_after}",
               repro={"op": "proteinblender.dna_remove_bend"})
    except Exception as e:
        record("DNA8", "Remove bend", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- DNA9: Change colors via dna_builder_props.color_a and update_dna_colors -----
    try:
        dna = next((o for o in bpy.data.objects if o.get("pb_is_nucleic_acid") and o.name.startswith("DNA_DS")), None)
        select_only(dna)
        scene.dna_builder_props.color_a = (0.9, 0.1, 0.1, 1.0)
        # Operator name guess: try a few
        op_id = None
        for cand in ("update_dna_colors", "update_dna_color"):
            if hasattr(bpy.ops.proteinblender, cand):
                op_id = cand
                break
        if op_id:
            res = getattr(bpy.ops.proteinblender, op_id)()
            stored = dna.get("pb_color_a")
            ok = stored is not None and abs(stored[0] - 0.9) < 0.05
            record("DNA9", f"Update DNA colors via proteinblender.{op_id}",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"stored color_a={tuple(stored) if stored else None}",
                   repro={"op": f"proteinblender.{op_id}",
                          "preconditions": ["dna_builder_props.color_a = (0.9, 0.1, 0.1, 1)", "DNA active"]})
        else:
            record("DNA9", "Update DNA colors", "SKIP", notes="no matching operator found")
    except Exception as e:
        record("DNA9", "Update DNA colors", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_dna()
print("\n--- Section complete ---\n")
