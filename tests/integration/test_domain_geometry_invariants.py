"""Invariants that must survive the domain mesh-sharing refactor.

Domains used to carry a private copy of the whole molecule's mesh purely so
``bpy.ops.object.origin_set`` could move their origin: origin_set mutates mesh
vertex data, so a shared mesh would have every domain jump whenever one had its
pivot set. Removing that copy means the pivot has to be represented explicitly
instead (see ``core.domain_space``).

These tests pin the behaviour that must NOT change while that representation is
swapped out underneath them. Ground truth is kept *independent of the code under
test* (see CLAUDE.md): residue positions come from the PDB via biotite
(``H.pdb_amino_acid_cas``), "did it move on screen" comes from Blender's renderer
(``H.render_coverage``), and the origin comes from ``matrix_world`` - never from
the pivot operators' own alpha-carbon collector, which would let a test pass in
lock-step with a bug (that is how the bound-calcium C-terminus bug once slipped
through a green suite).

The one thing they must never do is assume ``obj.matrix_world @ co`` is the
local->world mapping. That identity holds only while each domain owns a
privately-shifted mesh, and it is exactly what the refactor breaks.
"""

import numpy as np
import pytest
import bpy
from mathutils import Vector, Euler

import helpers as H
from proteinblender.operators.pivot_operators import _chain_index_for_item


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


def _origin(obj):
    bpy.context.view_layer.update()
    return obj.matrix_world.translation.copy()


# --------------------------------------------------------------------------
# The core invariant: setting a pivot must not move what the user sees
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_setting_pivot_does_not_move_what_is_rendered(multi_chain, scene, tmp_path):
    """Moving a domain's pivot relocates its origin, never what is drawn.

    Measured with Blender's *renderer* (pixel coverage), not the addon's
    coordinate maths: setting a pivot changes matrix_world and the GN pivot
    input together, and if that maths is self-consistent-but-wrong the addon's
    own local->world would still report "no movement". The rendered image is the
    only witness that cannot move with the bug.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    assert rows, "no chain rows to pivot"
    item, obj, _idx = rows[0]

    bpy.context.view_layer.update()
    before = H.render_coverage(tmp_path)
    assert before.sum() > 0, "nothing rendered to begin with"

    _select_only(scene, item)
    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    assert bpy.ops.proteinblender.set_pivot_last() == {"FINISHED"}
    assert bpy.ops.proteinblender.set_pivot_center() == {"FINISHED"}
    bpy.context.view_layer.update()

    after = H.render_coverage(tmp_path)
    # Identical pixels covered - the molecule did not move on screen.
    changed = int(np.logical_xor(before, after).sum())
    assert changed == 0, (
        f"{changed} pixels changed after setting pivots; the geometry moved on "
        f"screen when it should not have")


@pytest.mark.integration
def test_pivot_lands_on_the_requested_residue(scene, sm):
    """set_pivot_first/center/last land the origin on the chain's N-terminus /
    centroid / C-terminus.

    Ground truth is the PDB parsed with biotite - not the pivot operators' own
    alpha collector, which would make this pass even if both were wrong (that is
    how the bound-calcium C-terminus bug slipped through). Compared via
    transform-invariant pairwise distances, since the mesh is scaled/re-centred.
    """
    mol = sm.molecules[H.import_local("4hhb.pdb", "4hhb")]
    scene.selected_molecule_id = mol.identifier
    _build_outliner()

    # A chain that resolves to an alpha-carbon mesh, and its letter.
    rows = _chain_rows(scene)
    assert rows
    item, obj, idx = rows[0]
    labels = list(obj.get("chain_ids") or [])
    letter = labels[idx]

    _select_only(scene, item)

    def _run(op):
        assert op() == {"FINISHED"}
        return _origin(obj)

    first = _run(bpy.ops.proteinblender.set_pivot_first)
    center = _run(bpy.ops.proteinblender.set_pivot_center)
    last = _run(bpy.ops.proteinblender.set_pivot_last)

    cas = H.pdb_amino_acid_cas("4hhb.pdb", letter)
    res = sorted(cas)
    truth = {
        "first": cas[res[0]],
        "center": tuple(np.mean([cas[r] for r in res], axis=0)),
        "last": cas[res[-1]],
    }
    H.assert_world_points_match_residues(
        {"first": first, "center": center, "last": last}, truth)


@pytest.mark.integration
def test_domain_rotates_about_its_pivot(multi_chain, scene, tmp_path):
    """A rotated domain still renders, and its origin is the fixed point.

    Independent instruments only: the origin (matrix_world.translation, from
    Blender) must not move under a pure rotation about it, the rotation part of
    matrix_world must actually change, and the molecule must still be on screen
    (renderer). No addon coordinate maths involved.
    """
    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, _idx = rows[0]
    _select_only(scene, item)

    assert bpy.ops.proteinblender.set_pivot_first() == {"FINISHED"}
    origin_before = _origin(obj)
    rot_before = np.array(obj.matrix_world.to_3x3())

    obj.rotation_euler = Euler((0.0, 0.0, 1.2), "XYZ")
    bpy.context.view_layer.update()

    assert (_origin(obj) - origin_before).length < 1e-4, (
        "the origin (pivot) moved under a pure rotation about it")
    rot_after = np.array(obj.matrix_world.to_3x3())
    assert not np.allclose(rot_before, rot_after), "the rotation did not apply"
    assert H.render_coverage(tmp_path).sum() > 0, "nothing rendered after rotating"


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
    from mathutils import Vector

    _build_outliner()
    rows = _chain_rows(scene)
    item, obj, chain_idx = rows[0]

    assert domain_space.pb_modifier(obj) is not None

    _select_only(scene, item)
    bpy.ops.proteinblender.set_pivot_first()
    first_pivot = domain_space.get_pivot(obj).copy()

    bpy.ops.proteinblender.set_pivot_last()
    last_pivot = domain_space.get_pivot(obj).copy()

    assert (first_pivot - last_pivot).length > 1e-3, (
        "the pivot input did not change between N- and C-terminal pivots")

    # After set_pivot_first, the modifier's Pivot input (canonical mesh space)
    # must equal the raw-mesh coordinate of this chain's first-residue alpha
    # carbon. Read straight from mesh attributes - not through local_to_world
    # (whose composition with the pivot is true by construction and proves
    # nothing).
    mesh = obj.data
    n = len(mesh.vertices)
    isa = np.zeros(n, dtype=bool)
    mesh.attributes["is_alpha_carbon"].data.foreach_get("value", isa)
    chain = np.zeros(n, dtype=np.int32)
    mesh.attributes["chain_id"].data.foreach_get("value", chain)
    res = np.zeros(n, dtype=np.int32)
    mesh.attributes["res_id"].data.foreach_get("value", res)
    co = np.zeros(n * 3); mesh.vertices.foreach_get("co", co); co = co.reshape(-1, 3)

    sel = isa & (chain == chain_idx)
    first_res_co = Vector(co[sel][np.argmin(res[sel])].tolist())

    bpy.ops.proteinblender.set_pivot_first()
    assert (domain_space.get_pivot(obj) - first_res_co).length < 1e-4, (
        "the Pivot input is not the first residue's canonical mesh coordinate")


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
def test_rendered_molecule_has_stable_coverage(multi_chain, scene, tmp_path):
    """Pin how much of the frame the molecule covers when rendered.

    Absolute-geometry regression signal (e.g. a centring change that shifts the
    whole molecule) measured by Blender's renderer, independent of any addon
    coordinate maths. This replaces an earlier snapshot that pinned the output of
    the pivot operators' own alpha-carbon collector - which would have pinned the
    bound-calcium bug's positions as "correct" rather than flagging them.

    A wide band is used deliberately: the goal is to catch a gross shift/scale
    change, not to re-baseline on every sub-pixel Cycles wobble.
    """
    _build_outliner()
    bpy.context.view_layer.update()
    covered = int(H.render_coverage(tmp_path).sum())
    assert 20 < covered < 4000, (
        f"rendered coverage {covered}px is outside the expected band for 4hhb - "
        f"the molecule may have shifted, scaled, or stopped rendering")
