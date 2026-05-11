"""Section: linker creation, render modes, remove, save/load survival."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def setup_puppet_with_chains():
    """Returns (mid, puppet_id, [chain_a_id, chain_b_id])."""
    mid = import_pdb("4hhb")
    sm_module().build_outliner_hierarchy(bpy.context)
    scene = bpy.context.scene
    chain_ids = []
    for it in scene.outliner_items:
        if it.item_type == "CHAIN" and it.item_id.startswith(mid + "_"):
            # outliner item_id is like "4hhb_001_chain_0"; chain letter is in `name`
            # ("Chain A", "Chain B", ...). Match on name suffix.
            if "Chain A" in (it.name or "") or "Chain B" in (it.name or ""):
                chain_ids.append(it.item_id)
    # Select chains, create puppet
    for it in scene.outliner_items:
        it.is_selected = (it.item_id in chain_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="LinkerPuppet")
    puppet_id = None
    for it in scene.outliner_items:
        if it.item_type == "PUPPET" and it.name == "LinkerPuppet":
            puppet_id = it.item_id
            break
    return mid, puppet_id, chain_ids


def run_linkers():
    print("\n" + "=" * 60)
    print("SECTION: LINKERS")
    print("=" * 60)

    reset_scene()
    scene = bpy.context.scene
    mid, puppet_id, chain_ids = setup_puppet_with_chains()
    print(f"Setup: mid={mid} puppet_id={puppet_id} chains={chain_ids}")

    if not puppet_id or len(chain_ids) < 2:
        record("L0", "Linker prerequisites (puppet + 2 chains)", "FAIL",
               error=f"puppet_id={puppet_id} chains={chain_ids}")
        return

    # ----- L1: Create QUICK linker (Bezier-curve rendering) -----
    try:
        before_count = len(scene.pb2_linkers)
        # The operator expects endpoint_*_item with "A_" / "B_" prefix per the EnumProperty
        res = bpy.ops.pb2.add_linker(
            'EXEC_DEFAULT',
            puppet_selector=puppet_id,
            endpoint_a_item=f"A_{chain_ids[0]}",
            endpoint_a_residue=5,
            endpoint_b_item=f"B_{chain_ids[1]}",
            endpoint_b_residue=5,
            linker_name="L1_Quick",
            length_residues=15,
            style="TUBE",
            rendering_mode="QUICK",
            color=(0.2, 0.8, 0.2, 1.0),
        )
        after_count = len(scene.pb2_linkers)
        ok = after_count == before_count + 1
        shot = screenshot("L1_quick_linker")
        record("L1", "Create QUICK-mode tube linker between chain A:5 and chain B:5",
               "PASS" if ok else "FAIL",
               error=None if ok else f"linker count {before_count}->{after_count}, ops={res}",
               repro={"op": "pb2.add_linker",
                      "props": {"puppet_selector": puppet_id,
                                "endpoint_a_item": f"A_{chain_ids[0]}",
                                "endpoint_a_residue": 5,
                                "endpoint_b_item": f"B_{chain_ids[1]}",
                                "endpoint_b_residue": 5,
                                "rendering_mode": "QUICK",
                                "style": "TUBE"}},
               screenshot=shot)
    except Exception as e:
        record("L1", "Create QUICK linker", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- L2: Linker has an associated curve object -----
    try:
        if len(scene.pb2_linkers) > 0:
            link = scene.pb2_linkers[0]
            curve_obj = bpy.data.objects.get(link.curve_object_name) if hasattr(link, "curve_object_name") else None
            ok = curve_obj is not None
            record("L2", "Linker has a backing curve object in the scene",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"curve_object_name={getattr(link, 'curve_object_name', '<missing>')}",
                   repro={"check": "scene.pb2_linkers[0].curve_object_name resolves to a bpy.data.objects entry"})
        else:
            record("L2", "Linker curve check", "SKIP", notes="no linker")
    except Exception as e:
        record("L2", "Linker curve check", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- L3: Reject linker with same chain on both endpoints -----
    try:
        before_count = len(scene.pb2_linkers)
        try:
            res = bpy.ops.pb2.add_linker(
                'EXEC_DEFAULT',
                puppet_selector=puppet_id,
                endpoint_a_item=f"A_{chain_ids[0]}",
                endpoint_a_residue=10,
                endpoint_b_item=f"B_{chain_ids[0]}",  # same item
                endpoint_b_residue=20,
                linker_name="L3_SelfLink",
            )
        except RuntimeError as re:
            # Expected — operator reports error
            res = {'CANCELLED'}
        after_count = len(scene.pb2_linkers)
        ok = res == {'CANCELLED'} and after_count == before_count
        record("L3", "Reject linker connecting same chain to itself",
               "PASS" if ok else "FAIL",
               error=None if ok else f"ops={res}, count {before_count}->{after_count}",
               repro={"op": "pb2.add_linker", "preconditions": "endpoint_a_item == endpoint_b_item"})
    except Exception as e:
        record("L3", "Reject self-linker", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- L4: Toggle linker visibility -----
    try:
        if len(scene.pb2_linkers) > 0:
            link = scene.pb2_linkers[0]
            curve_obj = bpy.data.objects.get(link.curve_object_name) if hasattr(link, "curve_object_name") else None
            if curve_obj:
                before_hide = curve_obj.hide_get()
                bpy.ops.pb2.toggle_linker_visibility('EXEC_DEFAULT', linker_uid=link.uid)
                after_hide = curve_obj.hide_get()
                ok = before_hide != after_hide
                record("L4", "Toggle linker visibility",
                       "PASS" if ok else "FAIL",
                       error=None if ok else f"hide unchanged ({before_hide})",
                       repro={"op": "pb2.toggle_linker_visibility",
                              "props": {"linker_uid": link.uid}})
            else:
                record("L4", "Toggle linker visibility", "SKIP", notes="no curve object")
        else:
            record("L4", "Toggle linker visibility", "SKIP", notes="no linker")
    except Exception as e:
        record("L4", "Toggle linker visibility", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- L5: Remove linker -----
    try:
        if len(scene.pb2_linkers) > 0:
            link = scene.pb2_linkers[0]
            curve_name = getattr(link, "curve_object_name", None)
            before_count = len(scene.pb2_linkers)
            bpy.ops.pb2.remove_linker('EXEC_DEFAULT', linker_uid=link.uid)
            after_count = len(scene.pb2_linkers)
            curve_gone = (curve_name is None or bpy.data.objects.get(curve_name) is None)
            ok = after_count == before_count - 1 and curve_gone
            record("L5", "Remove linker — linker entry + curve object both removed",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"linker_count {before_count}->{after_count} curve_gone={curve_gone}",
                   repro={"op": "pb2.remove_linker", "props": {"linker_uid": "<uid>"}})
        else:
            record("L5", "Remove linker", "SKIP", notes="no linker")
    except Exception as e:
        record("L5", "Remove linker", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- L6: Puppet deletion cascades to linker cleanup -----
    try:
        # Create a fresh linker, then delete the puppet
        before_count = len(scene.pb2_linkers)
        bpy.ops.pb2.add_linker(
            'EXEC_DEFAULT',
            puppet_selector=puppet_id,
            endpoint_a_item=f"A_{chain_ids[0]}",
            endpoint_a_residue=5,
            endpoint_b_item=f"B_{chain_ids[1]}",
            endpoint_b_residue=5,
            linker_name="L6_ForDelete",
        )
        after_create = len(scene.pb2_linkers)
        # Now delete the puppet
        # delete_puppet appears unregistered (per audit notes) — fall back to manual.
        # Instead, call the puppet handler directly.
        try:
            res = bpy.ops.proteinblender.delete_puppet('EXEC_DEFAULT', puppet_id=puppet_id)
            via = "operator"
        except (AttributeError, RuntimeError) as e:
            # Manual cleanup
            from bl_ext.vscode_development.proteinblender.linkers import linker_handlers as lh
            lh.on_puppet_deleted(puppet_id)
            res = f"manual via on_puppet_deleted ({e})"
            via = "manual"
        after_delete = len(scene.pb2_linkers)
        ok = after_create == before_count + 1 and after_delete == before_count
        record("L6", f"Puppet deletion cascades linker cleanup (via {via})",
               "PASS" if ok else "FAIL",
               error=None if ok else f"counts: before={before_count} create={after_create} after_puppet_delete={after_delete}, ops={res}",
               repro={"op": "on_puppet_deleted(puppet_id) or proteinblender.delete_puppet",
                      "preconditions": "puppet has at least one linker"})
    except Exception as e:
        record("L6", "Puppet-delete cascade", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_linkers()
print("\n--- Section complete ---\n")
