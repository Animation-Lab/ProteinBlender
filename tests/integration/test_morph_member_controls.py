"""Color and pivot controls must follow a chain into its Morphset."""
import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H
from proteinblender.core import morphsets as C
from test_model_morphsets import make
from test_morphsets import _key
from test_outliner_colors import _rendered_rgb

pytestmark = pytest.mark.integration


def row(identifier):
    return next(r for r in bpy.context.scene.outliner_items if r.item_id == identifier)


def test_member_color_swatch_reaches_source_output_and_new_keys(scene):
    from proteinblender.core.outliner_colors import row_has_swatch
    mid = H.import_local('1d3z.pdb.gz', 'Colors')
    root, morph = make(mid)
    identifier = morph[C.MORPH] + ':0'
    assert row_has_swatch(row(identifier)), 'Morphset chains must keep their color swatch'
    color = (.13, .54, .86, 1)
    row(identifier).row_color = color
    original = C.records(morph)[0]['object']
    assert _rendered_rgb(original) == pytest.approx(color[:3])
    assert _key(morph, 1) == {'FINISHED'}
    assert _rendered_rgb(C.outputs(scene)[0]) == pytest.approx(color[:3])
    second = (.7, .2, .35, 1)
    assert bpy.ops.proteinblender.outliner_color_picker(item_id=identifier,
        item_type='MORPH_MEMBER', color=second, color_edited=True) == {'FINISHED'}
    for obj in (original, C.outputs(scene)[0]):
        assert _rendered_rgb(obj) == pytest.approx(second[:3])
    assert _key(morph, 50, 3) == {'FINISHED'}
    assert _rendered_rgb(C.outputs(scene)[0]) == pytest.approx(second[:3])
    np.testing.assert_allclose(row(identifier).row_color, second, atol=1e-5)
    row(mid).row_color = color
    assert _rendered_rgb(C.outputs(scene)[0]) == pytest.approx(color[:3])
    np.testing.assert_allclose(row(identifier).row_color, color, atol=1e-5)


@pytest.mark.parametrize('keyed', [False, True])
def test_member_custom_pivot_keeps_geometry_and_survives_key_edits(scene, keyed):
    from proteinblender.operators.pivot_operators import PIVOT_HELPER, pivot_edit_key
    root, morph = make(H.import_local('1d3z.pdb.gz', 'Pivot'))
    identifier = morph[C.MORPH] + ':0'
    original = C.records(morph)[0]['object']
    if keyed:
        assert _key(morph, 1) == {'FINISHED'}
        assert _key(morph, 50, 3) == {'FINISHED'}
    scene.frame_set(1)
    target = C.outputs(scene)[0] if keyed else original
    before = H.evaluated_atom_positions([target])
    assert len(before) > 500, 'The test must measure rendered atoms'
    assert bpy.ops.proteinblender.set_pivot_custom(item_id=identifier) == {'FINISHED'}
    assert pivot_edit_key(scene) == identifier
    helper = bpy.data.objects[PIVOT_HELPER]
    helper.location += Vector((.23, -.17, .08))
    bpy.context.view_layer.update()
    expected_pivot = helper.matrix_world.translation.copy()
    assert bpy.ops.proteinblender.set_pivot_custom(item_id=identifier) == {'FINISHED'}
    assert not pivot_edit_key(scene) and PIVOT_HELPER not in bpy.data.objects
    np.testing.assert_allclose(target.matrix_world.translation, expected_pivot, atol=1e-6)
    np.testing.assert_allclose(H.evaluated_atom_positions([target]), before, atol=1e-6)
    assert _key(morph, 1) == {'FINISHED'}
    target = C.outputs(scene)[0]
    np.testing.assert_allclose(target.matrix_world.translation, expected_pivot, atol=1e-6)
    np.testing.assert_allclose(H.evaluated_atom_positions([target]), before, atol=1e-6)
    assert _key(morph, 50, 3) == {'FINISHED'}
    scene.frame_set(25)
    target = C.outputs(scene)[0]
    halfway = H.evaluated_atom_positions([target])
    assert len(halfway) == len(before)
    assert np.max(np.abs(halfway-before)) > 1e-4, 'Morphing must still move atoms'
    assert _key(morph, 75, 7) == {'FINISHED'}
    scene.frame_set(25)
    target = C.outputs(scene)[0]
    np.testing.assert_allclose(target.matrix_world.translation, expected_pivot, atol=1e-6)
    np.testing.assert_allclose(H.evaluated_atom_positions([target]), halfway, atol=1e-6)
    # The chosen pivot must actually control rotation and survive key rebuilding.
    target.rotation_euler.z = .4
    bpy.context.view_layer.update()
    rotated = H.evaluated_atom_positions([target])
    assert np.max(np.abs(rotated-halfway)) > 1e-4
    assert _key(morph, 100, 8) == {'FINISHED'}
    scene.frame_set(25)
    np.testing.assert_allclose(H.evaluated_atom_positions(C.outputs(scene)), rotated, atol=1e-6)
    target = C.outputs(scene)[0]
    mask = np.zeros(len(target.data.vertices), dtype=bool)
    target.data.attributes['is_alpha_carbon'].data.foreach_get('value', mask)
    assert len(mask) == len(rotated)
    expected_center = rotated[mask].mean(axis=0)
    assert bpy.ops.proteinblender.set_pivot_center(item_id=identifier) == {'FINISHED'}
    np.testing.assert_allclose(target.matrix_world.translation, expected_center, atol=1e-6)
    np.testing.assert_allclose(H.evaluated_atom_positions([target]), rotated, atol=1e-6)


def test_member_pivot_is_scoped_and_follows_membership_reordering(scene, sm):
    from proteinblender.operators.pivot_operators import PIVOT_HELPER
    mid = H.import_local('2bbn.pdb.gz', 'Two chains')
    root, morph = make(mid)
    ids = list(sm.molecules[mid].domains)
    assert _key(morph, 1) == {'FINISHED'}
    assert _key(morph, 50, 3) == {'FINISHED'}
    source = sm.molecules[mid].object
    source.location = (1, 2, 3)
    source.rotation_euler.z = .4
    source.scale = (1.2, .9, 1.1)
    scene.frame_set(25)
    before = [H.evaluated_atom_positions([obj]) for obj in C.outputs(scene)]
    identifier = morph[C.MORPH] + ':1'
    assert bpy.ops.proteinblender.set_pivot_custom(item_id=identifier) == {'FINISHED'}
    helper = bpy.data.objects[PIVOT_HELPER]
    helper.location += Vector((.2,.1,-.3))
    bpy.context.view_layer.update()
    pivot = helper.matrix_world.translation.copy()
    assert bpy.ops.proteinblender.set_pivot_custom(item_id=identifier) == {'FINISHED'}
    for obj, expected in zip(C.outputs(scene), before):
        np.testing.assert_allclose(H.evaluated_atom_positions([obj]), expected, atol=1e-6)
    # Put the edited second chain first; saved display state must follow the
    # chain object, not the old row slot or the former output's binding index.
    assert bpy.ops.proteinblender.edit_morphset(morphset_id=root[C.TAG], name=root.name,
        members=[dict(name='', reason='', member_id=i, selected=True) for i in ids[::-1]]) == {'FINISHED'}
    scene.frame_set(25)
    for obj, expected in zip(C.outputs(scene), before[::-1]):
        np.testing.assert_allclose(H.evaluated_atom_positions([obj]), expected, atol=2e-6)
    np.testing.assert_allclose(C.outputs(scene)[0].matrix_world.translation, pivot, atol=1e-6)
    assert 'display_pivot' in C.records(morph)[0]
    assert 'display_pivot' not in C.records(morph)[1]
