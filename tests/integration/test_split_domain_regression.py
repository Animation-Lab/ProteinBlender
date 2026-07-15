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
