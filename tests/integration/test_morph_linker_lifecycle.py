"""A linker between Morphset chains through the rest of the Morphset's life.

Follows ``test_morph_linkers.py`` (Janet, 2026-11-03: a linker between the two
morphing chains of a ChimeraX morph). Once such a linker exists, the user can
still remove the Morphset, delete the protein it was made from, or drag one
of its chains, and the linker has to behave as it does between plain chains:

* removing the Morphset gives its chains back to the puppet, so the linker
  stays and joins those chains, and only goes when a chain it joins is gone;
* deleting the source protein leaves the Morphset in place (its chains are
  kept as copies), so the linker stays on them;
* dragging a chain the Morphset draws updates the linker at once and is held
  back at the linker's reach, as dragging a plain chain is.

Ground truth is what Blender draws: the evaluated Spheres point cloud of each
chain (``helpers.visible_alpha_carbon``), never the add-on's residue lookup.
"""

import numpy as np
import pytest
import bpy
from mathutils import Vector

import helpers as H
from proteinblender.core import morphsets as C
from proteinblender.linkers.linker_geometry import BU_PER_RESIDUE
from test_morph_linkers import morph_ab, _add_morph_linker, _linker_ends  # noqa: F401

pytestmark = pytest.mark.integration


def _row(item_id):
    return next((r for r in bpy.context.scene.outliner_items if r.item_id == item_id), None)


def _linker_curves():
    """Names of every curve object a linker made, in the scene or not."""
    return sorted(o.name for o in bpy.data.objects
                  if o.type == 'CURVE' and o.name.startswith('Linker_'))


def _drawn_objects(row):
    """The objects that draw an endpoint row, read off the scene, not the add-on.

    A Morphset chain is drawn by its output once keyed; a plain chain by its
    own object.
    """
    if row.item_type == 'MORPH_MEMBER':
        return [H.morph_output_named(row.name)]
    return [row.object_name]


def _assert_on_visible_alpha_carbons(linker, label):
    a, b = _row(linker.endpoint_a_item_id), _row(linker.endpoint_b_item_id)
    assert a is not None and b is not None, f"{label}: an endpoint row is gone"
    start, end = _linker_ends(linker)
    np.testing.assert_allclose(
        start, H.visible_alpha_carbon(_drawn_objects(a), linker.endpoint_a_residue),
        atol=1e-4, err_msg=f"{label}: end A is off the alpha carbon Blender draws")
    np.testing.assert_allclose(
        end, H.visible_alpha_carbon(_drawn_objects(b), linker.endpoint_b_residue),
        atol=1e-4, err_msg=f"{label}: end B is off the alpha carbon Blender draws")


def _morphset_root(scene):
    (root,) = C.sets(scene)
    return root


def test_curve_marker_identifies_linker_curves(morph_ab):
    """Guards the helper above: it finds a new linker's curve and nothing else."""
    linker, *_ = _add_morph_linker(morph_ab)
    assert _linker_curves() == [linker.curve_object_name]


def test_removing_the_morphset_keeps_the_linker_on_its_chains(morph_ab):
    scene = bpy.context.scene
    linker, *_ = _add_morph_linker(morph_ab)
    chain_of = morph_ab['chain_of']
    letters = [chain_of[m] for m in morph_ab['members']]

    assert bpy.ops.proteinblender.delete_morphset(
        morphset_id=_morphset_root(scene)[C.TAG]) == {'FINISHED'}

    assert len(scene.pb2_linkers) == 1, "the linker went with the Morphset"
    linker = scene.pb2_linkers[0]
    rows = [_row(linker.endpoint_a_item_id), _row(linker.endpoint_b_item_id)]
    assert all(r is not None for r in rows), "the linker's ends no longer name a row"
    assert [r.item_type for r in rows] == ['CHAIN', 'CHAIN']
    assert [r.name.split()[-1] for r in rows] == letters
    for frame in (10, 40):
        scene.frame_set(frame)
        assert linker.is_valid
        _assert_on_visible_alpha_carbons(linker, f"after removal, frame {frame}")
    assert _linker_curves() == [linker.curve_object_name]


def test_deleting_the_source_keeps_the_linker_on_the_morphset(morph_ab):
    scene = bpy.context.scene
    linker, *_ = _add_morph_linker(morph_ab)
    ends = (linker.endpoint_a_item_id, linker.endpoint_b_item_id)

    assert bpy.ops.molecule.delete(molecule_id=morph_ab['mid']) == {'FINISHED'}
    assert C.sets(scene), "precondition: the Morphset outlives its source"

    assert len(scene.pb2_linkers) == 1, "the linker went with the source protein"
    linker = scene.pb2_linkers[0]
    assert (linker.endpoint_a_item_id, linker.endpoint_b_item_id) == ends
    for frame in (1, 50, 25):
        scene.frame_set(frame)
        assert linker.is_valid
        _assert_on_visible_alpha_carbons(linker, f"source deleted, frame {frame}")


def test_removing_the_morphset_after_its_source_removes_the_linker(morph_ab):
    """With the source gone the chains exist only as the Morphset's copies, so
    removing the Morphset removes the chains, and the linker with them."""
    scene = bpy.context.scene
    _add_morph_linker(morph_ab)
    assert bpy.ops.molecule.delete(molecule_id=morph_ab['mid']) == {'FINISHED'}
    assert bpy.ops.proteinblender.delete_morphset(
        morphset_id=_morphset_root(scene)[C.TAG]) == {'FINISHED'}
    assert len(scene.pb2_linkers) == 0
    assert _linker_curves() == []


def _drag(case, member, offset):
    scene = bpy.context.scene
    output = bpy.data.objects[H.morph_output_named(_row(member).name)]
    source = bpy.data.objects[_row(member).object_name]
    source_world = source.matrix_world.copy()
    output.location += Vector(offset)
    bpy.context.view_layer.update()
    return output, source, source_world


def test_dragging_a_morph_chain_moves_its_linker_end(morph_ab):
    scene = bpy.context.scene
    linker, *_ = _add_morph_linker(morph_ab)
    scene.frame_set(25)
    _assert_on_visible_alpha_carbons(linker, "before the drag")
    _drag(morph_ab, linker.endpoint_a_item_id, (0.3, -0.1, 0.05))
    # No frame change: the drag alone has to bring the linker along.
    _assert_on_visible_alpha_carbons(linker, "after dragging chain A")


def test_dragging_a_morph_chain_past_reach_is_held_back(morph_ab):
    scene = bpy.context.scene
    linker, *_ = _add_morph_linker(morph_ab)
    scene.frame_set(25)
    reach = linker.length_residues * BU_PER_RESIDUE
    output, source, source_world = _drag(
        morph_ab, linker.endpoint_a_item_id, (reach * 3, 0, 0))

    a, b = _row(linker.endpoint_a_item_id), _row(linker.endpoint_b_item_id)
    ca_a = H.visible_alpha_carbon(_drawn_objects(a), linker.endpoint_a_residue)
    ca_b = H.visible_alpha_carbon(_drawn_objects(b), linker.endpoint_b_residue)
    distance = np.linalg.norm(ca_a - ca_b)
    assert distance <= reach + 1e-3, (
        f"chain A was dragged {distance:.3f} from B, past the linker's reach {reach:.3f}")
    assert source.matrix_world == source_world, "the hidden source chain was moved"
