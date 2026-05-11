"""Section: puppet create / edit (rename, add/remove members) / delete."""
exec(open(r"c:/Users/dlee1/BlenderProjects/ProteinBlender/tests/feature_audit/harness.py").read())

import traceback
load_existing_results()


def find_outliner_items_for_chains(mid, chain_ids=("A", "B")):
    """Return outliner CHAIN item_ids that belong to molecule `mid` and chain_ids."""
    ids = []
    for it in bpy.context.scene.outliner_items:
        if it.item_type != "CHAIN":
            continue
        # item_id is something like "4hhb_001_A_1_198_Chain_A"
        if not it.item_id.startswith(mid + "_"):
            continue
        # Look at chain_id property
        if hasattr(it, "chain_id") and it.chain_id in chain_ids:
            ids.append(it.item_id)
        else:
            # Fallback: parse name
            for cid in chain_ids:
                if f"Chain {cid}" in (it.name or "") or f"_{cid}_" in it.item_id:
                    ids.append(it.item_id)
                    break
    return ids


def run_puppets():
    print("\n" + "=" * 60)
    print("SECTION: PUPPETS")
    print("=" * 60)

    reset_scene()
    mid = import_pdb("4hhb")
    scene = bpy.context.scene
    # Rebuild outliner so chain items appear
    sm_module().build_outliner_hierarchy(bpy.context)

    chain_ab_ids = find_outliner_items_for_chains(mid, ("A", "B"))
    print(f"Found chain outliner items for A/B: {chain_ab_ids}")

    # ----- PU1: Create puppet from chains A + B -----
    try:
        # Select A + B in outliner
        for it in scene.outliner_items:
            it.is_selected = (it.item_id in chain_ab_ids)
        res = bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="Puppet_AB")
        # Check puppet appeared in outliner
        puppet_items = [it for it in scene.outliner_items if it.item_type == "PUPPET" and it.name == "Puppet_AB"]
        ok = len(puppet_items) == 1
        controller = None
        if puppet_items and puppet_items[0].controller_object_name:
            controller = bpy.data.objects.get(puppet_items[0].controller_object_name)
        shot = screenshot("PU1_create_puppet")
        record("PU1", "Create puppet 'Puppet_AB' from chain A + chain B",
               "PASS" if ok and controller is not None else "FAIL",
               error=None if (ok and controller) else f"puppet_items={[(i.name, i.controller_object_name) for i in puppet_items]} ops={res}",
               repro={"op": "proteinblender.create_puppet",
                      "props": {"puppet_name": "Puppet_AB"},
                      "precondition": "two chain items have is_selected=True in outliner"},
               screenshot=shot,
               notes=f"controller_obj={controller.name if controller else None}")
    except Exception as e:
        record("PU1", "Create puppet", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PU2: Verify domains are parented to controller -----
    try:
        puppet_items = [it for it in scene.outliner_items if it.item_type == "PUPPET" and it.name == "Puppet_AB"]
        if puppet_items:
            controller = bpy.data.objects.get(puppet_items[0].controller_object_name)
            if controller:
                # Get the chain objects that should now be parented to the controller
                children = [o for o in bpy.data.objects if o.parent is controller]
                ok = len(children) >= 2
                record("PU2", "Puppet controller has >=2 chain children (parented)",
                       "PASS" if ok else "FAIL",
                       error=None if ok else f"controller={controller.name} children={[c.name for c in children]}",
                       repro={"check": "list bpy.data.objects with parent == puppet controller"},
                       notes=f"children: {[c.name for c in children]}")
            else:
                record("PU2", "Puppet controller children", "FAIL", error="controller object missing")
        else:
            record("PU2", "Puppet controller children", "SKIP", notes="no puppet")
    except Exception as e:
        record("PU2", "Puppet children", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PU3: Move puppet controller — all chains follow by the same delta -----
    try:
        puppet_items = [it for it in scene.outliner_items if it.item_type == "PUPPET" and it.name == "Puppet_AB"]
        if puppet_items:
            controller = bpy.data.objects.get(puppet_items[0].controller_object_name)
            children = [o for o in bpy.data.objects if o.parent is controller]
            if controller and children:
                # Record world positions and controller's starting position
                before_ctrl = tuple(controller.location)
                before = {c.name: tuple(c.matrix_world.translation) for c in children}
                controller.location = (5.0, 3.0, 1.0)
                bpy.context.view_layer.update()
                after = {c.name: tuple(c.matrix_world.translation) for c in children}
                # Children should move by the SAME delta as the controller —
                # which is (setpoint - old_controller_location), not the raw
                # setpoint. The controller starts at the bbox centre of its
                # children, not at the origin.
                expected_delta = (5.0 - before_ctrl[0], 3.0 - before_ctrl[1], 1.0 - before_ctrl[2])
                deltas = [
                    tuple(after[n][i] - before[n][i] for i in range(3))
                    for n in before
                ]
                tol = 0.01
                ok = all(
                    abs(d[i] - expected_delta[i]) < tol for d in deltas for i in range(3)
                )
                shot = screenshot("PU3_move_puppet")
                record("PU3", "Move puppet controller — children follow by matching delta",
                       "PASS" if ok else "FAIL",
                       error=None if ok else f"expected_delta={expected_delta} deltas={deltas}",
                       repro={"op": "set controller.location = (5, 3, 1)",
                              "check": "children matrix_world.translation delta == (setpoint - old_controller_loc)"},
                       screenshot=shot)
            else:
                record("PU3", "Move puppet", "SKIP", notes="no controller or children")
        else:
            record("PU3", "Move puppet", "SKIP", notes="no puppet")
    except Exception as e:
        record("PU3", "Move puppet", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PU4: Try to create another puppet from already-puppeted chain -> should fail -----
    try:
        for it in scene.outliner_items:
            it.is_selected = (it.item_id in chain_ab_ids[:1])
        before_puppets = len([it for it in scene.outliner_items if it.item_type == "PUPPET"])
        rejected = False
        try:
            res = bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="Conflicting")
            rejected = (res == {'CANCELLED'})
        except RuntimeError as re_err:
            # EXEC_DEFAULT raises when the operator returns CANCELLED with a
            # reported error. The exception message contains the rejection
            # reason — treat this as the expected rejection.
            rejected = "already in a puppet" in str(re_err)
            res = {'CANCELLED'}
        after_puppets = len([it for it in scene.outliner_items if it.item_type == "PUPPET"])
        ok = rejected and before_puppets == after_puppets
        record("PU4", "Create-puppet on already-puppeted chain is rejected",
               "PASS" if ok else "FAIL",
               error=None if ok else f"ops={res}, puppet_count {before_puppets}->{after_puppets}",
               repro={"op": "proteinblender.create_puppet",
                      "precondition": "selected chain is already in another puppet"})
    except Exception as e:
        record("PU4", "Reject duplicate puppet", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PU5: Edit puppet — rename -----
    try:
        puppet_items = [it for it in scene.outliner_items if it.item_type == "PUPPET" and it.name == "Puppet_AB"]
        if puppet_items:
            puppet_id = puppet_items[0].item_id
            res = bpy.ops.proteinblender.edit_puppet(
                'EXEC_DEFAULT', action='RENAME', puppet_id=puppet_id, new_name="Renamed_Puppet"
            )
            updated = next((it for it in scene.outliner_items if it.item_id == puppet_id), None)
            ok = updated is not None and updated.name == "Renamed_Puppet"
            record("PU5", "Rename puppet via edit_puppet(action='RENAME')",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"name now {getattr(updated, 'name', None)!r}, ops={res}",
                   repro={"op": "proteinblender.edit_puppet",
                          "props": {"action": "RENAME", "puppet_id": puppet_id,
                                    "new_name": "Renamed_Puppet"}})
        else:
            record("PU5", "Rename puppet", "SKIP", notes="no puppet")
    except Exception as e:
        record("PU5", "Rename puppet", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])

    # ----- PU6: Delete puppet — children un-parented, controller removed -----
    try:
        # Filter out the "── Puppets ──" separator row; it has
        # item_type='PUPPET' but item_id='puppets_separator'.
        puppet_items = [it for it in scene.outliner_items
                        if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]
        if puppet_items:
            target = puppet_items[0]
            puppet_id = target.item_id
            controller_name = target.controller_object_name
            res = bpy.ops.proteinblender.delete_puppet('EXEC_DEFAULT', puppet_id=puppet_id)
            puppet_gone = not any(it.item_id == puppet_id for it in scene.outliner_items)
            controller_gone = bpy.data.objects.get(controller_name) is None if controller_name else True
            ok = puppet_gone and controller_gone
            shot = screenshot("PU6_after_delete")
            record("PU6", "Delete puppet removes outliner item + controller",
                   "PASS" if ok else "FAIL",
                   error=None if ok else f"puppet_gone={puppet_gone} controller_gone={controller_gone} ops={res}",
                   repro={"op": "proteinblender.delete_puppet",
                          "props": {"puppet_id": puppet_id}},
                   screenshot=shot)
        else:
            record("PU6", "Delete puppet", "SKIP", notes="no puppet")
    except Exception as e:
        record("PU6", "Delete puppet", "ERROR", error=f"{type(e).__name__}: {e}",
               notes=traceback.format_exc()[:500])


run_puppets()
print("\n--- Section complete ---\n")
