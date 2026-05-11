"""Section: domain split / merge / rename / color / style / delete."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def run_domains():
    print("\n" + "=" * 60)
    print("SECTION: DOMAINS")
    print("=" * 60)

    # Set up: 4hhb gives us 4 auto-domains to play with
    reset_scene()
    mid = import_pdb("4hhb")
    mol = sm().molecules[mid]
    initial_domain_ids = sorted(mol.domains.keys())
    print(f"initial domains: {initial_domain_ids}")

    # ----- D1: Auto-chain-domain creation on import -----
    ok = len(initial_domain_ids) == 4
    shot = screenshot("D1_initial_4hhb_4chains")
    record("D1", "Auto-chain-domain creation (4 chains -> 4 auto-domains)",
           "PASS" if ok else "FAIL",
           error=None if ok else f"got {len(initial_domain_ids)} domains",
           repro={"op": "molecule.import_protein", "props": {"pdb_id": "4hhb"}},
           screenshot=shot)

    # ----- D2: Update domain color via custom property -----
    try:
        first_did = initial_domain_ids[0]
        domain = mol.domains[first_did]
        if domain.object:
            domain.object.domain_color = (1.0, 0.2, 0.2, 1.0)
            shot = screenshot("D2_domain_color")
            # Verify the color stuck on the runtime domain
            ok = abs(domain.object.domain_color[0] - 1.0) < 0.01
            record("D2", "Set domain color via obj.domain_color property",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"color {tuple(domain.object.domain_color)}",
                   repro={"op": "set obj.domain_color = (1, 0.2, 0.2, 1)", "domain_id": first_did},
                   screenshot=shot)
        else:
            record("D2", "Set domain color", "SKIP", notes=f"{first_did} has no object")
    except Exception as e:
        record("D2", "Set domain color", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- D3: Update domain style via custom property -----
    try:
        first_did = initial_domain_ids[1]
        domain = mol.domains[first_did]
        if domain.object:
            domain.object.domain_style = "spheres"
            ok = domain.object.domain_style == "spheres"
            record("D3", "Set domain style via obj.domain_style",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"style {domain.object.domain_style}",
                   repro={"op": "set obj.domain_style = 'spheres'", "domain_id": first_did})
        else:
            record("D3", "Set domain style", "SKIP")
    except Exception as e:
        record("D3", "Set domain style", "ERROR", error=f"{type(e).__name__}: {e}")

    # ----- D4: Split domain (extracts residues 1..99 of chain A as a new sub-domain) -----
    # proteinblender.split_domain takes (chain_id, molecule_id, split_start, split_end)
    # and CARVES OUT a new domain covering split_start..split_end from the chain.
    try:
        before_count = len(mol.domains)
        scene = bpy.context.scene
        scene.selected_molecule_id = mid
        # Make sure no outliner items are selected (the op falls back to selection in invoke,
        # but execute() reads its own properties).
        for it in scene.outliner_items:
            it.is_selected = False
        res = bpy.ops.proteinblender.split_domain(
            chain_id="A", molecule_id=mid,
            split_start=1, split_end=99,
        )
        after_count = len(mol.domains)
        ok = after_count == before_count + 1
        shot = screenshot("D4_split_domain")
        record("D4", "Split chain A: extract residues 1-99 as a new sub-domain",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count {before_count} -> {after_count}, ops result {res}",
               repro={"op": "proteinblender.split_domain",
                      "props": {"chain_id": "A", "molecule_id": mid, "split_start": 1, "split_end": 99}},
               screenshot=shot,
               notes=f"After split, domain keys: {sorted(mol.domains.keys())}")
    except Exception as e:
        record("D4", "Split domain", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- D5: Rename domain via outliner selection -----
    try:
        # rename_domain reads domain_id from the outliner selection in invoke,
        # then opens a dialog. We bypass dialog by calling execute() directly
        # with both kwargs set.
        scene = bpy.context.scene
        # Find the outliner item for a domain to rename
        target_did = sorted(mol.domains.keys())[-1]
        original_name = mol.domains[target_did].name
        new_name = "Renamed_X"
        # Select corresponding outliner row (so any UI redraw doesn't crash)
        for it in scene.outliner_items:
            it.is_selected = (it.item_type == "DOMAIN" and it.item_id == target_did)
        # Call execute with kwargs (Blender will set the StringProperty fields)
        res = bpy.ops.proteinblender.rename_domain(
            'EXEC_DEFAULT', domain_id=target_did, new_name=new_name
        )
        ok = mol.domains[target_did].name == new_name
        record("D5", "Rename domain (via outliner selection + EXEC_DEFAULT)",
               "PASS" if ok else "FAIL",
               error=None if ok else f"name still {mol.domains[target_did].name!r}, ops result {res}",
               repro={"op": "proteinblender.rename_domain",
                      "props": {"domain_id": target_did, "new_name": new_name},
                      "precondition": "outliner item is_selected=True for target domain",
                      "original_name": original_name})
    except Exception as e:
        record("D5", "Rename domain", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- D6: Merge domains (driven by outliner selection) -----
    try:
        all_dids = sorted(mol.domains.keys())
        if len(all_dids) < 2:
            record("D6", "Merge domains", "SKIP", notes="need >=2 domains")
        else:
            scene = bpy.context.scene
            # Pick the two split halves of chain A — they share chain_id "A".
            chain_a_dids = [d for d in all_dids if mol.domains[d].chain_id == "A"]
            if len(chain_a_dids) < 2:
                # Fall back to first two
                d1, d2 = all_dids[0], all_dids[1]
            else:
                d1, d2 = chain_a_dids[0], chain_a_dids[1]
            before_count = len(mol.domains)
            # Select both in the outliner
            for it in scene.outliner_items:
                it.is_selected = (it.item_type == "DOMAIN" and it.item_id in (d1, d2))
            res = bpy.ops.proteinblender.merge_domains('EXEC_DEFAULT')
            after_count = len(mol.domains)
            ok = after_count == before_count - 1
            shot = screenshot("D6_merged")
            record("D6", "Merge two domains (outliner-selected)",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"count {before_count} -> {after_count}, ops result {res}",
                   repro={"op": "proteinblender.merge_domains (no kwargs — reads outliner selection)",
                          "selected": [d1, d2]},
                   screenshot=shot)
    except Exception as e:
        record("D6", "Merge domains", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- D7: Delete domain -----
    try:
        target_did = sorted(mol.domains.keys())[-1]  # delete the last one
        before_count = len(mol.domains)
        bpy.ops.molecule.delete_domain(molecule_id=mid, domain_id=target_did)
        after_count = len(mol.domains)
        ok = after_count == before_count - 1
        record("D7", "Delete domain",
               "PASS" if ok else "FAIL",
               error=None if ok else f"count {before_count} -> {after_count}",
               repro={"op": "molecule.delete_domain",
                      "props": {"molecule_id": mid, "domain_id": target_did}})
    except Exception as e:
        record("D7", "Delete domain", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_domains()
print("\n--- Section complete ---\n")
