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
