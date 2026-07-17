"""Invariants that must survive the domain mesh-sharing refactor.

Domains used to carry a private copy of the whole molecule's mesh purely so
``bpy.ops.object.origin_set`` could move their origin: origin_set mutates mesh
vertex data, so a shared mesh would have every domain jump whenever one had its
pivot set. Removing that copy means the pivot has to be represented explicitly
instead (see ``core.domain_space``).

These tests pin the behaviour that must NOT change while that representation is
swapped out underneath them. They deliberately assert through *production* code
paths (``_collect_chain_filtered_alphas``, the pivot operators, the outliner)
rather than recomputing coordinates locally, so they stay meaningful whether the
pivot lives in mesh data or on a geometry-nodes input.

The one thing they must never do is assume ``obj.matrix_world @ co`` is the
local->world mapping. That identity holds only while each domain owns a
privately-shifted mesh, and it is exactly what the refactor breaks.
"""

import numpy as np
import pytest
import bpy
from mathutils import Vector, Euler

import helpers as H
from proteinblender.operators.pivot_operators import (
    _collect_chain_filtered_alphas,
    _chain_index_for_item,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_rows(scene):
    """Every CHAIN outliner row that resolves to an alpha-carbon-bearing mesh.

    Returns ``[(item, obj, chain_idx), ...]`` sorted by item_id for stability.
    """
    rows = []
    for it in scene.outliner_items:
        if it.item_type != "CHAIN" or not it.object_name:
            continue
        obj = bpy.data.objects.get(it.object_name)
        if obj is None:
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None or "is_alpha_carbon" not in mesh.attributes:
            continue
        rows.append((it, obj, _chain_index_for_item(scene, it)))
    rows.sort(key=lambda r: r[0].item_id)
    return rows


def _select_only(scene, item):
    for it in scene.outliner_items:
        it.is_selected = False
    item.is_selected = True


def _alpha_world(obj, chain_idx):
    """World positions of ``obj``'s alpha carbons, as production computes them.

    Routed through the pivot operators' own collector so this tracks whatever
    local->world convention the product currently uses.
    """
    alphas = _collect_chain_filtered_alphas([(obj, chain_idx)])
    alphas.sort(key=lambda pr: pr[1])
    return np.array([tuple(pos) for pos, _ in alphas], dtype=np.float64)


def _origin(obj):
    bpy.context.view_layer.update()
    return obj.matrix_world.translation.copy()


# --------------------------------------------------------------------------
# The core invariant: setting a pivot must not move what the user sees
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_setting_pivot_does_not_move_geometry(multi_chain, scene):
    """Moving a domain's pivot relocates its origin, never its atoms.

    This is the invariant the whole refactor rests on. Under origin_set it holds
    because the mesh shift and the origin move cancel; under an explicit pivot it
    holds because the GN translate and the matrix_world translation cancel.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    assert rows, "no chain rows to pivot"
    item, obj, chain_idx = rows[0]

    before = _alpha_world(obj, chain_idx)
    assert len(before), "chain has no alpha carbons"

    _select_only(scene, item)
    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    after_first = _alpha_world(obj, chain_idx)

    assert bpy.ops.proteinblender.set_pivot_last() == {"FINISHED"}
    after_last = _alpha_world(obj, chain_idx)

    assert bpy.ops.proteinblender.set_pivot_center() == {"FINISHED"}
    after_center = _alpha_world(obj, chain_idx)

    for label, arr in (("first", after_first),
                       ("last", after_last),
                       ("center", after_center)):
        assert arr.shape == before.shape, f"{label}: atom count changed"
        np.testing.assert_allclose(
            arr, before, atol=1e-4,
            err_msg=f"set_pivot_{label} moved the chain's atoms in world space")


@pytest.mark.integration
def test_pivot_does_not_disturb_sibling_domains(multi_chain, scene):
    """Pivoting one chain must leave every other chain's atoms untouched.

    This is the failure mode a shared mesh introduces if the pivot is baked into
    mesh data: origin_set shifts the geometry for every user of the datablock but
    only compensates the active object's origin, so siblings visibly jump.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    assert len(rows) >= 2, "need >=2 chains (use 4hhb)"

    target_item, target_obj, target_idx = rows[0]
    siblings = rows[1:]
    before = {it.item_id: _alpha_world(o, idx) for it, o, idx in siblings}

    _select_only(scene, target_item)
    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}

    for it, o, idx in siblings:
        after = _alpha_world(o, idx)
        np.testing.assert_allclose(
            after, before[it.item_id], atol=1e-4,
            err_msg=(f"pivoting {target_item.item_id} moved sibling "
                     f"{it.item_id}'s atoms"))


@pytest.mark.integration
def test_pivot_lands_on_the_requested_residue(multi_chain, scene):
    """set_pivot_first/last put the origin on the N-/C-terminal alpha carbon."""
    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, chain_idx = rows[0]
    _select_only(scene, item)

    alphas = _collect_chain_filtered_alphas([(obj, chain_idx)])
    first_pos = min(alphas, key=lambda pr: pr[1])[0]
    last_pos = max(alphas, key=lambda pr: pr[1])[0]

    bpy.ops.proteinblender.set_pivot_first()
    assert (_origin(obj) - first_pos).length < 1e-3, (
        "origin is not on the N-terminal alpha carbon")

    bpy.ops.proteinblender.set_pivot_last()
    assert (_origin(obj) - last_pos).length < 1e-3, (
        "origin is not on the C-terminal alpha carbon")


@pytest.mark.integration
def test_domain_rotates_about_its_pivot(multi_chain, scene):
    """Rotating a domain leaves the pivot-anchored atom fixed in world space.

    The point of a pivot: it is the one atom that does not move. If the pivot
    representation and the local->world mapping ever disagree, this is what
    catches it.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, chain_idx = rows[0]
    _select_only(scene, item)

    bpy.ops.proteinblender.set_pivot_first()
    pivot_world = _origin(obj)

    alphas = _collect_chain_filtered_alphas([(obj, chain_idx)])
    anchor_before = min(alphas, key=lambda pr: pr[1])[0]
    assert (anchor_before - pivot_world).length < 1e-3

    obj.rotation_euler = Euler((0.0, 0.0, 1.2), "XYZ")
    bpy.context.view_layer.update()

    alphas_after = _collect_chain_filtered_alphas([(obj, chain_idx)])
    anchor_after = min(alphas_after, key=lambda pr: pr[1])[0]

    assert (anchor_after - anchor_before).length < 1e-3, (
        f"the pivot atom moved under rotation: {tuple(anchor_before)} -> "
        f"{tuple(anchor_after)}; the domain is not rotating about its pivot")
    assert (_origin(obj) - pivot_world).length < 1e-3, (
        "the origin drifted under rotation")


@pytest.mark.integration
def test_setting_a_pivot_never_writes_to_mesh_data(multi_chain, scene):
    """The pivot must live on the modifier, not in mesh vertices.

    This is the whole reason domains can share a mesh. ``origin_set`` moved an
    origin by rewriting every vertex and compensating the object transform; on a
    shared datablock that reaches every sharer while only the active object's
    origin compensates, so the others jump. If this ever regresses to mutating
    mesh data, ``test_pivot_does_not_disturb_sibling_domains`` starts failing and
    the mesh sharing has to be reverted with it.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, _chain_idx = rows[0]

    mesh = obj.data
    before = np.zeros(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", before)

    _select_only(scene, item)
    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    assert bpy.ops.proteinblender.set_pivot_center() == {"FINISHED"}

    after = np.zeros(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", after)

    np.testing.assert_array_equal(
        after, before,
        err_msg="setting a pivot rewrote mesh vertices; the mesh cannot be "
                "shared between domains while that is true")


@pytest.mark.integration
def test_pivot_is_carried_on_the_modifier(multi_chain, scene):
    """The pivot is readable as a per-object geometry-nodes input."""
    from proteinblender.core import domain_space

    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, _ = rows[0]

    assert domain_space.pb_modifier(obj) is not None

    _select_only(scene, item)
    bpy.ops.proteinblender.set_pivot_first()
    first_pivot = domain_space.get_pivot(obj).copy()

    bpy.ops.proteinblender.set_pivot_last()
    last_pivot = domain_space.get_pivot(obj).copy()

    assert (first_pivot - last_pivot).length > 1e-3, (
        "the pivot input did not change between N- and C-terminal pivots")

    # The invariant the rest of the add-on relies on: the pivot's world position
    # is the object's origin.
    bpy.ops.proteinblender.set_pivot_first()
    bpy.context.view_layer.update()
    assert (domain_space.local_to_world(obj, domain_space.get_pivot(obj))
            - obj.matrix_world.translation).length < 1e-4, (
        "world(pivot) must equal the object's origin")


# --------------------------------------------------------------------------
# Masking: what each domain actually renders
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_each_chain_domain_masks_to_its_own_chain(multi_chain, sm, scene):
    """Every chain domain's GN tree selects exactly its own chain.

    The masking is what makes the mesh copy redundant, so it must be verified
    independently of the copy's existence.
    """
    mol = sm.molecules[multi_chain]
    assert len(mol.domains) == 4

    seen_ranges = []
    for domain in mol.domains.values():
        assert domain.object is not None
        mod = (domain.object.modifiers.get("DomainNodes")
               or domain.object.modifiers.get("MolecularNodes"))
        assert mod is not None and mod.node_group is not None, (
            f"domain {domain.name} has no geometry-nodes modifier")
        seen_ranges.append((domain.chain_id, domain.start, domain.end))

    # The four chain domains must cover four distinct chains.
    chains = {c for c, _, _ in seen_ranges}
    assert len(chains) == 4, f"expected 4 distinct chains, got {chains}"


# --------------------------------------------------------------------------
# Duplication cost (characterisation - inverted once the copy is gone)
# --------------------------------------------------------------------------

def _molecule_meshes(mol):
    """Mesh datablocks reachable from a molecule and its domains."""
    objs = [mol.object] + [d.object for d in mol.domains.values() if d.object]
    return [o.data for o in objs if o is not None]


@pytest.mark.integration
def test_domains_share_the_parent_mesh(multi_chain, sm):
    """Domains must not carry a private copy of the whole molecule's mesh.

    Each domain masks itself down to a residue range inside geometry nodes, so
    the mesh copy buys nothing: a domain covering 5% of a protein still stored
    100% of the atoms. 4hhb has 4 chains, so import used to yield 5 identical
    ~4558-atom datablocks (5.0x); stored atoms scaled as
    ``(1 + n_chains) x n_atoms``, which is what made large complexes untenable.
    """
    mol = sm.molecules[multi_chain]
    meshes = _molecule_meshes(mol)
    assert len(meshes) == 5, "expected parent + 4 chain domains"

    parent_mesh = mol.object.data
    n_atoms = len(parent_mesh.vertices)
    assert n_atoms > 4000, f"4hhb should have ~4558 atoms, got {n_atoms}"

    distinct = {m.name for m in meshes}
    assert distinct == {parent_mesh.name}, (
        f"domains own private mesh copies: {sorted(distinct)}. "
        f"Stored atoms = {sum(len(m.vertices) for m in set(meshes))} "
        f"vs {n_atoms} needed.")

    for d in mol.domains.values():
        assert d.object.data is parent_mesh, (
            f"domain {d.name} does not share the parent mesh datablock")


@pytest.mark.integration
def test_chain_alpha_world_positions(multi_chain, scene, geo_snapshot):
    """Pin every chain's alpha-carbon world positions.

    A geometry regression anywhere in the pivot/local->world rework shows up here
    as a snapshot diff rather than as a silently misplaced protein.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    assert len(rows) == 4, f"expected 4 chain rows, got {len(rows)}"

    stacked = np.concatenate([_alpha_world(o, idx) for _, o, idx in rows])
    assert geo_snapshot == np.round(stacked, 2)
