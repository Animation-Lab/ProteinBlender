"""Integration tests for the pivot-point operators.

The pivot operators (pivot_operators.py) move an outliner CHAIN/DOMAIN
object's *origin* to a chosen alpha-carbon location. They read their target
from the Protein Outliner: every row with ``is_selected == True`` whose
``item_type`` is CHAIN or DOMAIN and whose ``object_name`` resolves to a live
mesh becomes a target. The mesh must carry the ``is_alpha_carbon`` /
``chain_id`` / ``res_id`` attributes MolecularNodes stamps on protein meshes.

Covered operators:
  * proteinblender.set_pivot_first   (N-terminal alpha carbon)
  * proteinblender.set_pivot_last    (C-terminal alpha carbon)
  * proteinblender.set_pivot_center  (alpha-carbon centroid)
  * proteinblender.set_pivot_custom  (interactive gizmo — skipped, see below)
"""

import pytest
import bpy
import helpers as H


def _build_outliner():
    """Rebuild the Protein Outliner so CHAIN/DOMAIN rows exist for imports."""
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _select_one_chain(scene):
    """Select exactly one CHAIN outliner row that resolves to a live object.

    Returns (item, obj). Skips the test if no such row exists — pivot targets
    require a chain whose object_name points at a mesh with alpha carbons.
    """
    target = None
    for it in scene.outliner_items:
        it.is_selected = False
    for it in scene.outliner_items:
        if it.item_type != "CHAIN":
            continue
        if not it.object_name:
            continue
        obj = bpy.data.objects.get(it.object_name)
        if obj is None:
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None or "is_alpha_carbon" not in mesh.attributes:
            continue
        target = (it, obj)
        break
    if target is None:
        pytest.skip("no CHAIN row with an alpha-carbon-bearing object to pivot")
    item, obj = target
    item.is_selected = True
    return item, obj


def _origin_world(obj):
    """The object's origin (pivot) position in world space."""
    bpy.context.view_layer.update()
    return obj.matrix_world.translation.copy()


@pytest.mark.integration
def test_set_pivot_first_moves_origin(single_chain, scene):
    _build_outliner()
    _item, obj = _select_one_chain(scene)

    before = _origin_world(obj)
    res = bpy.ops.proteinblender.set_pivot_first()
    assert res == {"FINISHED"}
    after = _origin_world(obj)
    # The N-terminal residue of a real protein is not at the mesh origin, so
    # the pivot must have moved somewhere sensible.
    assert (after - before).length > 1e-4, "pivot did not move to first residue"


@pytest.mark.integration
def test_pivot_first_last_center_differ(single_chain, scene):
    _build_outliner()
    _item, obj = _select_one_chain(scene)

    # The world-space geometry doesn't move when only the origin is set, so
    # the three targets are computed against a stable structure.
    bpy.ops.proteinblender.set_pivot_first()
    first = _origin_world(obj)

    bpy.ops.proteinblender.set_pivot_last()
    last = _origin_world(obj)

    bpy.ops.proteinblender.set_pivot_center()
    center = _origin_world(obj)

    # First (N-terminus) and last (C-terminus) must be distinct points.
    assert (first - last).length > 1e-3, (
        f"first {tuple(first)} and last {tuple(last)} pivots coincide")
    # Centroid must differ from both endpoints.
    assert (center - first).length > 1e-4
    assert (center - last).length > 1e-4
    # The centroid should lie no farther from either endpoint than the
    # endpoints are from each other (it's an average of all alpha carbons).
    span = (first - last).length
    assert (center - first).length <= span + 1e-3
    assert (center - last).length <= span + 1e-3


@pytest.mark.integration
def test_pivot_reports_warning_when_nothing_selected(single_chain, scene):
    _build_outliner()
    for it in scene.outliner_items:
        it.is_selected = False
    res = bpy.ops.proteinblender.set_pivot_first()
    # No selected outliner rows -> operator cancels rather than moving anything.
    assert res == {"CANCELLED"}


@pytest.mark.integration
@pytest.mark.skip(reason=(
    "set_pivot_custom is interactive: it spawns an orange gizmo Empty, forces "
    "the move tool via context.screen.areas (None in headless background) and "
    "finalises through a depsgraph deselection handler. It takes no residue "
    "index and cannot be driven non-interactively."))
def test_set_pivot_custom_interactive():
    pass


# --------------------------------------------------------------------------
# Initial (default) pivot placement, and the full First/Center/Last flow on a
# specific selected chain - the exact thing the user drives from the outliner.
# --------------------------------------------------------------------------

def _row_for_chain(scene, letter):
    """The CHAIN outliner row + object for chain ``letter`` (e.g. "A").

    Ground truth for *which* chain this is comes from obj["chain_ids"] (the
    string labels MolecularNodes stores), not from any pivot code.
    """
    from proteinblender.operators.pivot_operators import _chain_index_for_item
    for it in scene.outliner_items:
        if it.item_type != "CHAIN" or not it.object_name:
            continue
        obj = bpy.data.objects.get(it.object_name)
        if obj is None:
            continue
        idx = _chain_index_for_item(scene, it)
        labels = list(obj.get("chain_ids") or [])
        if idx is not None and idx < len(labels) and labels[idx] == letter:
            return it, obj
    return None, None


def _origin_after(scene, row_item, op):
    """Select ``row_item`` alone, run pivot operator ``op``, return the object's
    origin (matrix_world.translation - Blender's own value, independent of the
    addon's coordinate maths)."""
    it, obj = row_item
    for x in scene.outliner_items:
        x.is_selected = False
    it.is_selected = True
    assert op() == {"FINISHED"}
    bpy.context.view_layer.update()
    return obj.matrix_world.translation.copy()


@pytest.mark.integration
def test_full_chain_domain_default_pivot_is_center_of_mass(scene, sm):
    """A freshly imported full-chain domain starts pivoted at its centre of mass.

    The initial pivot was mis-placed on the first residue (an off-by-one in the
    full-chain test plus an evaluated-mesh read that fell back), so "Set Pivot
    First" looked like a no-op.

    Ground truth is the PDB (biotite), not the pivot operators' own alpha-carbon
    collector. We take three world points - the default origin, and the origins
    after First and Last - and require their pairwise distances to match the PDB
    (centroid, first-residue, last-residue) distances. A default sitting on the
    first residue collapses the default<->first distance and breaks the match.
    """
    import numpy as np

    mol = sm.molecules[H.import_local("1atn.pdb", "1atn")]
    scene.selected_molecule_id = mol.identifier
    _build_outliner()

    row = _row_for_chain(scene, "A")
    assert row[0] is not None, "no chain A row"
    _it, obj = row

    bpy.context.view_layer.update()
    default = obj.matrix_world.translation.copy()
    first = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_first)
    last = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_last)

    cas = H.pdb_amino_acid_cas("1atn.pdb", "A")
    res = sorted(cas)
    truth = {
        "default": tuple(np.mean([cas[r] for r in res], axis=0)),  # centroid
        "first": cas[res[0]],
        "last": cas[res[-1]],
    }
    H.assert_world_points_match_residues(
        {"default": default, "first": first, "last": last}, truth)


def _chain_a_alpha_res_ids(mol):
    """res_ids of chain-A atoms flagged is_alpha_carbon, read straight from the
    mesh - no pivot-operator helper involved, so this cannot be circular."""
    import numpy as np

    obj = mol.object
    mesh = obj.data
    n = len(mesh.vertices)
    is_alpha = np.zeros(n, dtype=bool)
    mesh.attributes["is_alpha_carbon"].data.foreach_get("value", is_alpha)
    chain = np.zeros(n, dtype=np.int32)
    mesh.attributes["chain_id"].data.foreach_get("value", chain)
    res = np.zeros(n, dtype=np.int32)
    mesh.attributes["res_id"].data.foreach_get("value", res)

    labels = list(obj.get("chain_ids") or [])
    a_idx = labels.index("A") if "A" in labels else 0
    return set(res[is_alpha & (chain == a_idx)].tolist()), res, chain, is_alpha, a_idx


@pytest.mark.integration
def test_calcium_ion_is_not_counted_as_an_alpha_carbon(scene, sm):
    """1ATN's actin binds a Ca(2+) ion: HETATM, element Ca, atom name 'CA',
    residue 373, sitting in the centre of the chain.

    is_alpha_carbon matched any atom named 'CA', so the ion was flagged as an
    alpha carbon. It has the highest res_id in the chain, so 'Set Pivot Last'
    (which takes the max-res_id alpha carbon) landed on it - in the middle of the
    protein. The real C-terminus is residue 372, out at the periphery.

    Ground truth here is the mesh attributes and the known structure, not any
    pivot-operator code.
    """
    mol = sm.molecules[H.import_local("1atn.pdb", "1atn")]
    alpha_res, res, chain, is_alpha, a_idx = _chain_a_alpha_res_ids(mol)

    # The ion's residue (373) exists in chain A...
    assert 373 in set(res[chain == a_idx].tolist()), "test fixture changed: no res 373 in chain A"
    # ...but it must NOT be an alpha carbon.
    assert 373 not in alpha_res, (
        "the calcium ion (chain A res 373) is flagged is_alpha_carbon; "
        "'Set Pivot Last' will land on it, in the centre of the chain")
    # The last alpha-carbon residue is the true C-terminus, 372.
    assert max(alpha_res) == 372, (
        f"chain A's last alpha carbon is res {max(alpha_res)}, expected the "
        f"C-terminus at 372")


@pytest.mark.integration
def test_set_pivot_last_lands_on_the_terminus_not_the_center(scene, sm):
    """The user-facing symptom: Set Pivot Last must reach the peripheral
    C-terminus, not the central calcium ion.

    Independent of the pivot helper: it compares Last against Center (the
    centroid) and asserts Last is genuinely off-centre. The Ca ion sat ~2.6 A
    (~0.026 blender units) from the centroid; the real terminus is ~24 A (~0.24
    units) out. A threshold of 0.1 units cleanly separates them.
    """
    mol = sm.molecules[H.import_local("1atn.pdb", "1atn")]
    scene.selected_molecule_id = mol.identifier
    _build_outliner()
    row = _row_for_chain(scene, "A")   # the chain with the bound ion
    assert row[0] is not None

    center = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_center)
    last = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_last)

    assert (last - center).length > 0.1, (
        f"Set Pivot Last landed {(last - center).length:.3f} from the chain "
        f"centre - it is on the central calcium ion, not the C-terminus")


@pytest.mark.integration
def test_first_center_last_move_the_pivot_and_land_correctly(scene, sm):
    """The user's exact flow: select a chain, click First / Center / Last.

    Ground truth is the PDB (biotite), not the pivot operators' own collector:
    the three origins' pairwise distances must match the PDB's
    (first-residue, centroid, last-residue) distances. Plus First must actually
    *move* the origin off the default - the reported no-op.
    """
    import numpy as np

    mol = sm.molecules[H.import_local("1atn.pdb", "1atn")]
    scene.selected_molecule_id = mol.identifier
    _build_outliner()
    row = _row_for_chain(scene, "A")
    assert row[0] is not None
    _it, obj = row

    bpy.context.view_layer.update()
    default = obj.matrix_world.translation.copy()
    first = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_first)
    center = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_center)
    last = _origin_after(scene, row, bpy.ops.proteinblender.set_pivot_last)

    cas = H.pdb_amino_acid_cas("1atn.pdb", "A")
    res = sorted(cas)
    truth = {
        "first": cas[res[0]],
        "center": tuple(np.mean([cas[r] for r in res], axis=0)),
        "last": cas[res[-1]],
    }
    # Each lands on its intended residue (transform-invariant, independent truth).
    H.assert_world_points_match_residues(
        {"first": first, "center": center, "last": last}, truth)

    # Distinct from each other.
    assert (first - last).length > 1e-3, "First and Last coincide"
    assert (center - first).length > 1e-3
    assert (center - last).length > 1e-3

    # First actually moved the origin off the default centroid (the reported
    # no-op was First silently coinciding with a mis-placed default).
    assert (first - default).length > 1e-3, (
        "Set Pivot First did not move the origin")
