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

def _chain_alphas(obj, chain_idx):
    from proteinblender.operators.pivot_operators import _collect_chain_filtered_alphas
    return _collect_chain_filtered_alphas([(obj, chain_idx)])


def _chain_rows_with_alphas(scene):
    """CHAIN rows whose object carries alpha carbons for that chain, with the
    resolved integer chain index. Skips tiny chains (e.g. 1ATN's chain B) that
    have no alpha carbons."""
    from proteinblender.operators.pivot_operators import _chain_index_for_item
    out = []
    for it in scene.outliner_items:
        if it.item_type != "CHAIN" or not it.object_name:
            continue
        obj = bpy.data.objects.get(it.object_name)
        if obj is None:
            continue
        idx = _chain_index_for_item(scene, it)
        if _chain_alphas(obj, idx):
            out.append((it, obj, idx))
    return out


@pytest.mark.integration
def test_full_chain_domain_default_pivot_is_center_of_mass(scene, sm):
    """A freshly imported full-chain domain must start pivoted at its centre of
    mass, not its first residue.

    The initial pivot was computed with ``_calculate_center_of_mass``, which read
    the *evaluated* mesh. At creation time that mesh is not reliably populated
    yet, so the read failed and fell back to the start residue -
    non-deterministically (1ATN chain A fell back; chain D did not, from the same
    code). The user then selects that chain, clicks "Set Pivot First", and
    nothing moves because the pivot is already sitting on the first residue -
    which reads as "the pivot buttons don't work".
    """
    import numpy as np
    from mathutils import Vector

    H.import_local("1atn.pdb", "1atn")
    _build_outliner()

    rows = _chain_rows_with_alphas(scene)
    assert rows, "no chain rows with alpha carbons"

    for it, obj, idx in rows:
        alphas = _chain_alphas(obj, idx)
        centroid = sum((p for p, _ in alphas), Vector()) / len(alphas)
        first = min(alphas, key=lambda pr: pr[1])[0]
        bpy.context.view_layer.update()
        origin = obj.matrix_world.translation.copy()

        d_centroid = (origin - centroid).length
        d_first = (origin - first).length
        assert d_centroid < d_first, (
            f"{it.object_name}: default pivot is on the first residue "
            f"(d={d_first:.3f}), not the centre of mass (d={d_centroid:.3f}) - "
            f"the evaluated-mesh centre-of-mass read fell back at creation time")
        assert d_centroid < 0.05, (
            f"{it.object_name}: default pivot is {d_centroid:.3f} from the "
            f"chain centroid; expected it on the centroid")


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
    _build_outliner()
    rows = _chain_rows_with_alphas(scene)
    # chain A specifically (the one with the bound ion)
    it, obj, idx = next((r for r in rows if r[1].get("chain_ids")
                         and "A" in list(r[1]["chain_ids"])
                         and r[2] == list(r[1]["chain_ids"]).index("A")), rows[0])

    def _run(op):
        for x in scene.outliner_items:
            x.is_selected = False
        it.is_selected = True
        assert op() == {"FINISHED"}
        bpy.context.view_layer.update()
        return obj.matrix_world.translation.copy()

    center = _run(bpy.ops.proteinblender.set_pivot_center)
    last = _run(bpy.ops.proteinblender.set_pivot_last)

    assert (last - center).length > 0.1, (
        f"Set Pivot Last landed {(last - center).length:.3f} from the chain "
        f"centre - it is on the central calcium ion, not the C-terminus")


@pytest.mark.integration
def test_first_center_last_move_the_pivot_and_land_correctly(scene, sm):
    """The user's exact flow: select a chain, click First / Center / Last.

    Each must move the origin and land it on that chain's N-terminal CA /
    centroid / C-terminal CA, and the three must be distinct. This is a no-op-
    proof version of the report: First must actually *move* the origin from the
    default, not silently coincide with it.
    """
    from mathutils import Vector

    H.import_local("1atn.pdb", "1atn")
    _build_outliner()
    rows = _chain_rows_with_alphas(scene)
    it, obj, idx = rows[0]

    alphas = _chain_alphas(obj, idx)
    alphas_sorted = sorted(alphas, key=lambda pr: pr[1])
    first_truth = alphas_sorted[0][0]
    last_truth = alphas_sorted[-1][0]
    centroid_truth = sum((p for p, _ in alphas), Vector()) / len(alphas)

    def _select_and_run(op):
        for x in scene.outliner_items:
            x.is_selected = False
        it.is_selected = True
        assert op() == {"FINISHED"}
        bpy.context.view_layer.update()
        return obj.matrix_world.translation.copy()

    default = obj.matrix_world.translation.copy()
    first = _select_and_run(bpy.ops.proteinblender.set_pivot_first)
    center = _select_and_run(bpy.ops.proteinblender.set_pivot_center)
    last = _select_and_run(bpy.ops.proteinblender.set_pivot_last)

    # Land on the right atoms.
    assert (first - first_truth).length < 1e-3, "First is not on the N-term CA"
    assert (last - last_truth).length < 1e-3, "Last is not on the C-term CA"
    assert (center - centroid_truth).length < 1e-3, "Center is not the centroid"

    # Distinct from each other.
    assert (first - last).length > 1e-3, "First and Last coincide"
    assert (center - first).length > 1e-3
    assert (center - last).length > 1e-3

    # And First actually moved the pivot off the default (the reported no-op):
    # since the default is now the centroid, First must differ from it.
    assert (first - default).length > 1e-3, (
        "Set Pivot First did not move the origin - it already sat on the first "
        "residue (default pivot was mis-placed)")
