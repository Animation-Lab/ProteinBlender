"""Regression: linkers on puppets whose chains were split (and pruned).

Reported (Janet, Blender 5.2):
  * The endpoint dropdown listed the split parent chain (Chain A / Chain B)
    alongside its domain, which resolves to no residues ("Valid range 1-999")
    and made every linker fail with "Could not find residue".
  * The default endpoint residue was a hard-coded 1, which doesn't exist on a
    domain that starts at residue 51 - another "Could not find residue".
  * Random Coil should be the default behaviour (Gravity is irrelevant at this
    scale), and the Coil Width slider was silently ignored.

Ground truth (chain letters, domain ranges, membership) comes from the molecule
model and the split we drive here, not from the linker code under test.
"""

import pytest
import bpy
import helpers as H

from proteinblender.linkers.linker_operators import (
    _build_chain_items_for_puppet, get_residue_range_for_item,
    get_chain_letter_for_item,
)


def _bo():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_items(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _split_delete_puppet(scene, sm, mid, split_letters=("A", "B")):
    """Split each of *split_letters* at 1-50, delete the 1-50 piece, then puppet
    all four chains. Returns (puppet_id, {letter: remaining_domain_id})."""
    scene.selected_molecule_id = mid
    _bo()
    mol = sm.molecules[mid]
    for letter in split_letters:
        assert H.split_domain_from_outliner(mid, letter, 1, 50) == {"FINISHED"}
    _bo()
    remaining = {}
    for letter in split_letters:
        did = next(d for d, dm in mol.domains.items()
                   if dm.chain_id == letter and dm.start == 1 and dm.end == 50)
        bpy.ops.molecule.delete_domain('EXEC_DEFAULT', domain_id=did, molecule_id=mid)
    _bo()
    for letter in split_letters:
        remaining[letter] = next(
            d for d, dm in mol.domains.items()
            if dm.chain_id == letter and dm.start == 51)

    chain_ids = [it.item_id for it in _chain_items(mid)]
    for it in scene.outliner_items:
        it.is_selected = it.item_id in set(chain_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="P4")
    puppet_id = next(p.item_id for p in scene.outliner_items
                     if p.item_type == "PUPPET" and p.name == "P4")
    return puppet_id, remaining


@pytest.mark.integration
def test_endpoint_list_offers_domains_not_split_parent_chains(scene, sm, multi_chain):
    mid = multi_chain
    puppet_id, remaining = _split_delete_puppet(scene, sm, mid)

    ids = {iid for iid, _l, _d in _build_chain_items_for_puppet(bpy.context, puppet_id)}

    # The split chains contribute their DOMAIN, never the parent chain row.
    assert remaining["A"] in ids and remaining["B"] in ids
    assert f"{mid}_chain_0" not in ids, "split Chain A must not be selectable"
    assert f"{mid}_chain_1" not in ids, "split Chain B must not be selectable"
    # Unsplit chains C and D are still offered as whole chains.
    assert f"{mid}_chain_2" in ids and f"{mid}_chain_3" in ids


@pytest.mark.integration
def test_domain_endpoint_range_is_the_domain_not_its_chain(scene, sm, multi_chain):
    mid = multi_chain
    _puppet_id, remaining = _split_delete_puppet(scene, sm, mid)
    mol = sm.molecules[mid]

    dom_id = remaining["A"]
    dom = mol.domains[dom_id]
    lo, hi = get_residue_range_for_item(dom_id, get_chain_letter_for_item(dom_id))
    # Independent truth: the domain's own start/end from the molecule model.
    assert (lo, hi) == (dom.start, dom.end)
    assert lo == 51, "the domain starts at 51, so 1 must NOT be the first residue"


@pytest.mark.integration
def test_create_linker_between_split_domains_defaults_to_first_real_residue(
        scene, sm, multi_chain):
    mid = multi_chain
    puppet_id, remaining = _split_delete_puppet(scene, sm, mid)
    mol = sm.molecules[mid]

    n_before = len(scene.pb2_linkers)
    # No residues supplied - exercise the default/first-existing path.
    res = bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT', puppet_selector=puppet_id,
        endpoint_a_item=f"A_{remaining['A']}",
        endpoint_b_item=f"B_{remaining['B']}",
        linker_name="L", length_residues=30, style="TUBE", rendering_mode="QUICK")
    assert res == {'FINISHED'}
    assert len(scene.pb2_linkers) == n_before + 1

    linker = scene.pb2_linkers[-1]
    assert linker.is_valid is True
    assert bpy.data.objects.get(linker.curve_object_name) is not None
    # The endpoints land on residues that actually exist in each domain (>= 51),
    # not the old hard-coded 1.
    assert linker.endpoint_a_residue >= mol.domains[remaining["A"]].start
    assert linker.endpoint_b_residue >= mol.domains[remaining["B"]].start


@pytest.mark.integration
def test_new_linker_defaults_to_random_coil(scene, sm, multi_chain):
    mid = multi_chain
    puppet_id, remaining = _split_delete_puppet(scene, sm, mid)
    # Drive add_linker without passing behavior, so the operator default applies.
    res = bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT', puppet_selector=puppet_id,
        endpoint_a_item=f"A_{remaining['A']}",
        endpoint_b_item=f"B_{remaining['B']}",
        linker_name="L", length_residues=30, style="TUBE", rendering_mode="QUICK")
    assert res == {'FINISHED'}
    assert scene.pb2_linkers[-1].behavior == 'RANDOM_COIL'


@pytest.mark.integration
def test_coil_width_actually_changes_the_coil(scene):
    """The Coil Width slider must affect the generated coil (it was ignored)."""
    from mathutils import Vector
    from proteinblender.linkers.linker_geometry import compute_random_coil_points

    start, end = Vector((0, 0, 0)), Vector((1.0, 0, 0))
    total_length = 3.0
    tight = compute_random_coil_points(start, end, total_length, num_residues=30,
                                       seed=1, coil_width=0.01)
    loose = compute_random_coil_points(start, end, total_length, num_residues=30,
                                       seed=1, coil_width=0.12)
    # Same seed + endpoints, different width => a genuinely different path.
    assert len(tight) != len(loose) or any(
        (a - b).length > 1e-4 for a, b in zip(tight, loose)), \
        "coil_width had no effect on the generated coil"


@pytest.mark.integration
def test_endpoint_list_has_no_duplicate_domains(scene, sm):
    """A puppet whose membership holds a split chain AND its own domains (which
    happens when selecting the chain cascades to its domain rows) must not list
    each domain twice - and never with duplicate enum identifiers.

    Reported (Janet): the Add Linker dropdown showed "Chain A: Residues 1-51"
    and "Chain A: Residues 52-375" twice each.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    scene.selected_molecule_id = mid
    _bo()
    assert H.split_domain_from_outliner(mid, "A", 1, 51) == {"FINISHED"}
    _bo()

    chain_a = next(it.item_id for it in scene.outliner_items
                   if it.item_type == "CHAIN" and it.name.startswith("Chain A")
                   and it.parent_id == mid)
    doms = [it.item_id for it in scene.outliner_items
            if it.item_type == "DOMAIN" and it.parent_id == chain_a]
    assert len(doms) == 2
    # Puppet the chain AND both domains together.
    sel = {chain_a, *doms}
    for it in scene.outliner_items:
        it.is_selected = it.item_id in sel
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="P1")
    puppet_id = next(p.item_id for p in scene.outliner_items
                     if p.item_type == "PUPPET" and p.name == "P1")

    ids = [iid for iid, _l, _d in _build_chain_items_for_puppet(bpy.context, puppet_id)]
    assert len(ids) == len(set(ids)), f"duplicate endpoint ids: {ids}"
    assert set(ids) == set(doms), \
        f"expected exactly the two domains once each, got {ids}"
