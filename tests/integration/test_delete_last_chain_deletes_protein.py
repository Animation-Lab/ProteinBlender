"""Regression: deleting the last chain/domain of a protein deletes the protein.

Reported: clicking the trash can on a protein's only remaining chain (or its
only remaining domain) emptied the protein but left the PROTEIN row, its
wrapper, its Blender object and everything hanging off it (puppets, poses)
behind - a protein with nothing in it.

The last chain/domain deletion must therefore cascade exactly like the
protein-level Delete button does.
"""

import pytest
import bpy
import helpers as H


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _rows_for(mid):
    """Every outliner row belonging to this molecule: the protein row itself,
    plus any chain/domain row parented (directly or transitively) to it."""
    scene = bpy.context.scene
    owned = {mid}
    # Two passes is enough: protein -> chain -> domain.
    for _ in range(2):
        for it in scene.outliner_items:
            if it.parent_id in owned:
                owned.add(it.item_id)
    return [it for it in scene.outliner_items if it.item_id in owned]


def _real_puppets():
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "PUPPET" and it.item_id != "puppets_separator"]


def _object_names(sm, mid):
    """Names of the Blender objects the molecule owns (parent + domains)."""
    mol = sm.molecules[mid]
    names = []
    if mol.object:
        names.append(mol.object.name)
    for dom in mol.domains.values():
        obj = getattr(dom, "object", None)
        if obj:
            try:
                names.append(obj.name)
            except ReferenceError:
                pass
    return names


def _assert_protein_gone(sm, mid, obj_names):
    """The molecule left nothing behind anywhere the UI or the model looks."""
    scene = bpy.context.scene
    assert mid not in sm.molecules, "wrapper survived"
    assert sm.molecule_manager.get_molecule(mid) is None, "manager entry survived"
    assert H.list_item(mid) is None, "molecule_list_items entry survived"
    assert scene.selected_molecule_id != mid, "still the selected molecule"
    for name in obj_names:
        assert bpy.data.objects.get(name) is None, \
            f"Blender object {name!r} survived"
    assert not _rows_for(mid), \
        f"outliner rows survived: {[(r.item_type, r.item_id) for r in _rows_for(mid)]}"


# --------------------------------------------------------------------------
# Chain route
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_delete_only_chain_deletes_protein(scene, sm, single_chain):
    """A single-chain protein whose one chain is deleted must be deleted."""
    mid = single_chain
    scene.selected_molecule_id = mid
    _build_outliner()
    chains = _chain_items(mid)
    assert len(chains) == 1, f"1ubq should have one chain, got {len(chains)}"
    obj_names = _object_names(sm, mid)

    # INVOKE_DEFAULT: the outliner's trash can goes through invoke() (which
    # picks the "this deletes the protein" confirmation) before execute().
    res = bpy.ops.molecule.delete_chain('INVOKE_DEFAULT',
                                        chain_id=chains[0].chain_id,
                                        molecule_id=mid)
    assert res == {'FINISHED'}

    _assert_protein_gone(sm, mid, obj_names)


@pytest.mark.integration
def test_protein_survives_until_its_last_chain_goes(scene, sm, multi_chain):
    """Deleting chains one by one keeps the protein alive while chains remain,
    and removes it with the last one."""
    mid = multi_chain
    scene.selected_molecule_id = mid
    _build_outliner()
    chain_indices = [it.chain_id for it in _chain_items(mid)]
    assert len(chain_indices) == 4, f"4hhb should have 4 chains, got {len(chain_indices)}"
    obj_names = _object_names(sm, mid)

    for chain_index in chain_indices[:-1]:
        bpy.ops.molecule.delete_chain('EXEC_DEFAULT',
                                      chain_id=chain_index, molecule_id=mid)
        assert mid in sm.molecules, \
            "protein must survive while it still has chains"

    bpy.ops.molecule.delete_chain('EXEC_DEFAULT',
                                  chain_id=chain_indices[-1], molecule_id=mid)
    _assert_protein_gone(sm, mid, obj_names)


# --------------------------------------------------------------------------
# Domain route
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_delete_only_domain_deletes_protein(scene, sm, single_chain):
    """The same rule via the domain trash can: the protein's last domain is
    also its last chain, so the protein goes with it."""
    mid = single_chain
    scene.selected_molecule_id = mid
    mol = sm.molecules[mid]
    assert len(mol.domains) == 1
    domain_id = next(iter(mol.domains))
    obj_names = _object_names(sm, mid)

    res = bpy.ops.molecule.delete_domain('INVOKE_DEFAULT',
                                         domain_id=domain_id, molecule_id=mid)
    assert res == {'FINISHED'}

    _assert_protein_gone(sm, mid, obj_names)


@pytest.mark.integration
def test_delete_domain_keeps_protein_when_siblings_remain(scene, sm, single_chain):
    """Splitting the one chain in two and deleting one half leaves the protein
    (and the other half) alone - the cascade must not over-fire."""
    mid = single_chain
    scene.selected_molecule_id = mid
    _build_outliner()
    chain_item = _chain_items(mid)[0]
    H.split_domain_from_outliner(mid, chain_item.chain_id,
                                 chain_item.chain_start,
                                 (chain_item.chain_start + chain_item.chain_end) // 2)
    mol = sm.molecules[mid]
    assert len(mol.domains) == 2, f"split failed, domains: {len(mol.domains)}"

    domain_id = next(iter(mol.domains))
    bpy.ops.molecule.delete_domain('EXEC_DEFAULT',
                                   domain_id=domain_id, molecule_id=mid)

    assert mid in sm.molecules, "protein must survive while a domain remains"
    assert len(sm.molecules[mid].domains) == 1


# --------------------------------------------------------------------------
# The warning the confirmation dialog is worded from
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_last_chain_is_recognised_before_the_delete(scene, sm, multi_chain):
    """The check behind the "this deletes the whole protein" confirmation must
    fire for the protein's last chain only."""
    from proteinblender.utils.scene_manager import molecule_would_be_emptied

    mol = sm.molecules[multi_chain]
    by_chain = {}
    for domain_id, domain in mol.domains.items():
        by_chain.setdefault(domain.chain_id, []).append(domain_id)
    assert len(by_chain) == 4, "4hhb should have 4 chains"

    # One chain out of four: the protein survives, so no warning.
    assert molecule_would_be_emptied(mol, next(iter(by_chain.values()))) is False
    # Every domain at once: the protein would be emptied, so warn.
    assert molecule_would_be_emptied(mol, list(mol.domains)) is True


# --------------------------------------------------------------------------
# Cascade
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_last_chain_deletion_clears_puppets_and_poses(scene, sm, multi_chain):
    """Deleting the final chain must tear down the puppets and poses that were
    built on the protein, exactly as the protein-level Delete does."""
    mid = multi_chain
    _build_outliner()
    chains = _chain_items(mid)
    a, b = chains[0], chains[1]

    for it in scene.outliner_items:
        it.is_selected = it.item_id in {a.item_id, b.item_id}
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="PAB")
    puppet_id = next(p.item_id for p in _real_puppets() if p.name == "PAB")

    pose = scene.pose_library.add()
    pose.name = "P"
    pose.puppet_ids = puppet_id
    bpy.ops.proteinblender.capture_pose('EXEC_DEFAULT', pose_index=0)
    assert len(scene.pose_library[0].transforms) > 0, "pose captured nothing"

    obj_names = _object_names(sm, mid)
    for chain_index in [it.chain_id for it in _chain_items(mid)]:
        bpy.ops.molecule.delete_chain('EXEC_DEFAULT',
                                      chain_id=chain_index, molecule_id=mid)

    _assert_protein_gone(sm, mid, obj_names)
    assert not _real_puppets(), "puppet outlived the protein it was built on"
    assert len(scene.pose_library) == 0, \
        f"pose library still holds {[p.name for p in scene.pose_library]}"


@pytest.mark.integration
def test_deleting_a_puppets_only_domain_clears_the_puppet(scene, sm, single_chain):
    """A puppet built on one domain must not outlive that domain - even though
    the protein itself survives, nothing may keep pointing at what is gone."""
    mid = single_chain
    _build_outliner()
    chain_item = _chain_items(mid)[0]
    H.split_domain_from_outliner(mid, chain_item.chain_id,
                                 chain_item.chain_start,
                                 (chain_item.chain_start + chain_item.chain_end) // 2)
    _build_outliner()
    domain_rows = [it for it in scene.outliner_items if it.item_type == "DOMAIN"]
    assert len(domain_rows) == 2, f"split gave {len(domain_rows)} domain rows"
    doomed = domain_rows[0].item_id

    for it in scene.outliner_items:
        it.is_selected = it.item_id == doomed
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="PD")
    assert [p.name for p in _real_puppets()] == ["PD"], "puppet setup failed"

    pose = scene.pose_library.add()
    pose.name = "P"
    pose.puppet_ids = next(p.item_id for p in _real_puppets())
    bpy.ops.proteinblender.capture_pose('EXEC_DEFAULT', pose_index=0)
    assert len(scene.pose_library[0].transforms) > 0, "pose captured nothing"

    bpy.ops.molecule.delete_domain('EXEC_DEFAULT', domain_id=doomed, molecule_id=mid)

    assert mid in sm.molecules, "the protein still has a domain and must survive"
    assert not _real_puppets(), "puppet outlived its only member"
    assert len(scene.pose_library) == 0, \
        f"pose library still holds {[p.name for p in scene.pose_library]}"


@pytest.mark.integration
def test_last_chain_deletion_clears_linkers(scene, sm, multi_chain):
    """No linker may outlive the protein its endpoints belonged to."""
    mid = multi_chain
    _build_outliner()
    chains = _chain_items(mid)
    a, b = chains[0], chains[1]

    for it in scene.outliner_items:
        it.is_selected = it.item_id in {a.item_id, b.item_id}
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="PAB")
    puppet_id = next(p.item_id for p in _real_puppets() if p.name == "PAB")

    by_id = {it.item_id: it for it in scene.outliner_items}
    a, b = by_id[a.item_id], by_id[b.item_id]
    bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT',
        puppet_selector=puppet_id,
        endpoint_a_item=f"A_{a.item_id}",
        endpoint_a_residue=max(a.chain_start, (a.chain_start + a.chain_end) // 2),
        endpoint_b_item=f"B_{b.item_id}",
        endpoint_b_residue=max(b.chain_start, (b.chain_start + b.chain_end) // 2),
        linker_name="L", length_residues=30, style="TUBE", rendering_mode="QUICK",
    )
    assert len(scene.pb2_linkers) == 1, "linker setup failed"

    obj_names = _object_names(sm, mid)
    for chain_index in [it.chain_id for it in _chain_items(mid)]:
        bpy.ops.molecule.delete_chain('EXEC_DEFAULT',
                                      chain_id=chain_index, molecule_id=mid)

    _assert_protein_gone(sm, mid, obj_names)
    assert len(scene.pb2_linkers) == 0, "linker outlived the protein"
