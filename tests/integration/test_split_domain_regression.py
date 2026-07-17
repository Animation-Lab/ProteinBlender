"""Regression: splitting a domain after duplicate + delete must not crash.

Root cause (fixed in molecule_wrapper._create_domain_mask_nodes): the wrapper
cached live bpy node pointers for the domain-mask infrastructure
(`domain_join_node` / `join_nodes` / `final_not`). Duplicating a molecule and
then deleting the copy purges node groups, which reallocates the parent's node
collection and INVALIDATES those cached pointers. The next domain split
dereferenced a stale pointer:

  * Blender 5.1 — hard native crash (EXCEPTION_STACK_OVERFLOW / access
    violation) inside `last_join.inputs`.
  * Blender 5.0 — `KeyError: key "Result" not found` (the stale pointer landed
    on a different, valid node) at `last_join.outputs["Result"]`.

The fix re-resolves the infrastructure nodes by NAME at use time
(`_refresh_domain_node_refs`), the same approach `get_main_style_node` and
`_rebind_domain_infrastructure` already use.

Two tests:
  * `test_split_domain_after_duplicate_delete` — the exact user workflow.
  * `test_domain_mask_heals_stale_node_refs` — deterministically forces the
    stale-pointer state (a removed-node ref raises ReferenceError on access,
    the catchable analog of the native crash) and asserts it heals.
"""

import pytest
import bpy

import helpers as H


def _parent_node_group(wrapper):
    obj = wrapper.molecule.object
    mod = obj.modifiers.get("MolecularNodes")
    return mod.node_group if mod else None


def _infra_intact(wrapper):
    """True iff the wrapper's tracked last-join node is a real node in the
    parent group that still exposes a 'Result' output. Accessing a stale
    (removed) cached node raises ReferenceError — which surfaces as a test
    failure, exactly as intended."""
    ng = _parent_node_group(wrapper)
    if ng is None or not wrapper.join_nodes:
        return False
    last = wrapper.join_nodes[-1]
    return last.name in ng.nodes and last.outputs.get("Result") is not None


@pytest.mark.integration
def test_split_domain_after_duplicate_delete(scene, sm, multi_chain):
    """Import -> duplicate (PB operator) -> delete the copy -> split a domain.
    Must complete and leave the domain-mask infrastructure valid (not stale)."""
    mid = multi_chain
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)

    # Duplicate, then delete the copy — this is what invalidates the original
    # wrapper's cached node pointers.
    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=mid)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]
    bpy.ops.molecule.delete(molecule_id=copy_id)
    assert copy_id not in sm.molecules

    mol = sm.molecules[mid]
    idx = sorted(mol.chain_mapping.keys())[0]
    author = mol.chain_mapping[idx]
    lo, hi = mol.chain_residue_ranges[author]
    split_start, split_end = lo, min(lo + 10, hi - 1)

    n_before = len(mol.domains)
    res = bpy.ops.proteinblender.split_domain(
        chain_id=str(idx), molecule_id=mid,
        split_start=split_start, split_end=split_end)

    assert res == {'FINISHED'}
    # The split carved a new sub-domain...
    assert len(mol.domains) > n_before
    assert any(d.start == split_start and d.end == split_end
               for d in mol.domains.values())
    # ...and the mask infrastructure the split touched is valid, not stale.
    assert _infra_intact(mol)


@pytest.mark.integration
def test_domain_mask_heals_stale_node_refs(scene, sm, multi_chain):
    """Deterministic trigger: forcibly replace the wrapper's cached infra node
    pointers with a since-removed node, then drive the mask code. The old code
    dereferenced the stale pointer (native crash / KeyError); the fix
    re-resolves by name and succeeds."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    ng = _parent_node_group(mol)
    assert ng is not None
    # Precondition: the domain infrastructure exists (auto-domains built it).
    assert ng.nodes.get("Domain_Boolean_Join") is not None

    # Pick an existing domain to re-apply a mask for.
    did, dom = sorted(mol.domains.items())[0]

    # Forge the stale state: point every cached infra ref at a throwaway node,
    # then remove that node. The cached refs are now dangling — reading them
    # raises ReferenceError (Python's catchable stand-in for the native crash).
    dummy = ng.nodes.new("FunctionNodeBooleanMath")
    mol.domain_join_node = dummy
    mol.final_not = dummy
    mol.join_nodes = [dummy]
    ng.nodes.remove(dummy)
    with pytest.raises(ReferenceError):
        _ = mol.join_nodes[-1].name  # confirm the refs really are stale

    # Drive the code path that crashed. With the fix it re-resolves by name.
    mol._create_domain_mask_nodes(did, dom.chain_id, dom.start, dom.end)

    # Cached refs were healed back to real, valid nodes.
    assert _infra_intact(mol)
    assert mol.join_nodes[-1].name in ng.nodes


# --------------------------------------------------------------------------
# Splitting a chain on a copy must not move that chain
# --------------------------------------------------------------------------

def _chain_world(mol, chain_id):
    """Where *mol* draws the molecule's first canonical atom, via ``chain_id``.

    Every domain shares the parent's mesh, so vertex 0 is the same atom in every
    one of them. Whatever transform + pivot a domain carries, it must map that
    atom to the same world position as every other domain of the same molecule -
    and as the corresponding chain of an overlapping copy.
    """
    from proteinblender.core import domain_space

    d = next(d for d in mol.domains.values()
             if d.chain_id == chain_id and d.object is not None)
    return domain_space.local_to_world(d.object, d.object.data.vertices[0].co)


@pytest.mark.integration
def test_split_on_a_copy_does_not_move_the_split_chain(scene, sm):
    """Import 1ATN, Copy it, split chain D on the copy: it must not shift.

    Reported: the two proteins overlap perfectly until you split a chain on the
    copy, at which point that chain jumps (~0.39 units).

    Cause: a newly created domain inherits its parent molecule's pivot, and the
    copy's parent pivot was wrong. `_calculate_center_of_mass` measured the
    *evaluated* geometry, which is masked by Domain_Final_Not once domains exist
    - so the copy (which has domains by the time it is re-centred) computed a
    different centre than the original (which is centred at import, before any
    domain exists). The bad pivot sat harmlessly on the always-masked parent
    until a split created domains that inherited it.
    """
    orig_id = H.import_local("1atn.pdb", "1atn")
    orig = sm.molecules[orig_id]
    scene.selected_molecule_id = orig_id

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=orig_id)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]
    copy = sm.molecules[copy_id]

    chains = sorted({d.chain_id for d in orig.domains.values() if d.object}
                    & {d.chain_id for d in copy.domains.values() if d.object},
                    key=str)
    assert "D" in chains, f"expected a chain D on both molecules, got {chains}"

    # Precondition: the copy overlaps the original exactly.
    for ch in chains:
        sep = (_chain_world(orig, ch) - _chain_world(copy, ch)).length
        assert sep < 1e-4, f"copy chain {ch} does not overlap the original: {sep}"

    # Split chain D (1-51) on the COPY.
    scene.selected_molecule_id = copy_id
    key = next(k for k, d in copy.domains.items() if d.chain_id == "D")
    scene.split_domain_new_start = 1
    scene.split_domain_new_end = 51
    assert bpy.ops.molecule.split_domain(domain_id=key) == {"FINISHED"}

    # Every chain of the copy must STILL sit exactly on the original's.
    for ch in chains:
        sep = (_chain_world(orig, ch) - _chain_world(copy, ch)).length
        assert sep < 1e-4, (
            f"after splitting chain D on the copy, chain {ch} moved {sep:.6f} "
            f"away from the original - the two proteins no longer overlap")


@pytest.mark.integration
def test_parent_pivot_matches_its_domains(scene, sm):
    """A molecule's parent and its domains must agree on where the atoms are.

    The parent is masked out of the render, so a parent whose pivot disagrees
    with its domains looks fine - right up until a new domain is created and
    inherits that pivot. This asserts the agreement directly, so the disagreement
    is caught where it starts rather than where it eventually shows.
    """
    from proteinblender.core import domain_space

    orig_id = H.import_local("1atn.pdb", "1atn")
    orig = sm.molecules[orig_id]
    scene.selected_molecule_id = orig_id

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=orig_id)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]

    for label, mol in (("original", orig), ("copy", sm.molecules[copy_id])):
        parent = mol.object
        parent_world = domain_space.local_to_world(
            parent, parent.data.vertices[0].co)
        for d in mol.domains.values():
            if d.object is None:
                continue
            dom_world = domain_space.local_to_world(
                d.object, d.object.data.vertices[0].co)
            sep = (parent_world - dom_world).length
            assert sep < 1e-4, (
                f"{label}: parent draws atom 0 at {tuple(parent_world)} but "
                f"domain {d.name} draws it at {tuple(dom_world)} ({sep:.6f} "
                f"apart). Any domain created from this parent inherits the "
                f"parent's pivot and will land in the wrong place.")
