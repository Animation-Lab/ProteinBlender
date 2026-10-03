"""Janet's 1STM assemblies, timeline retiming, and conformation cycling."""
import json

import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import assembly as A, morphsets as C, model_morphsets as M
from proteinblender.operators.keyframe_operators import get_keyframe_frames
from proteinblender.utils.animation import get_fcurves_from_action
from test_morphsets import _key, _atoms

pytestmark = pytest.mark.integration


def model_set(name='Models'):
    mid = H.import_local('1d3z.pdb.gz', name)
    bpy.ops.proteinblender.create_morphset(name=name + ' set', source=mid)
    return M.subject(next(s for s in C.sets(bpy.context.scene) if s.name == name + ' set'))


def retime(offset=0, scale=1):
    seen = set()
    for data in list(bpy.data.objects) + list(bpy.data.shape_keys):
        ad = data.animation_data
        if not ad or not ad.action:
            continue
        for curve in get_fcurves_from_action(ad.action, ad):
            if curve.as_pointer() in seen:
                continue
            seen.add(curve.as_pointer())
            for point in curve.keyframe_points:
                for co in (point.co, point.handle_left, point.handle_right):
                    co.x = co.x * scale + offset
            curve.update()


@pytest.mark.parametrize('insert_frame', [1, 8, 50])
def test_retimed_conformations_and_visibility_survive_insert_delete(scene, insert_frame):
    morph = model_set()
    uid = morph[C.MORPH]
    _key(morph, 1, 0, [True]); _key(morph, 21, 0, [False])
    _key(morph, 41, 4, [True])
    retime(offset=10)
    assert get_keyframe_frames(bpy.context) == [11, 31, 51]
    assert C.morph_keys(scene, uid)['31']['visible'] == [False]
    _key(morph, insert_frame, 2)
    assert get_keyframe_frames(bpy.context) == sorted({11, 31, 51, insert_frame})
    assert C.morph_keys(scene, uid)['31']['visible'] == [False]
    C.delete_key(bpy.context, 31, uid)
    assert '31' not in C.morph_keys(scene, uid)
    assert '21' not in C.morph_keys(scene, uid)
    scene.frame_set(51)
    np.testing.assert_allclose(_atoms(C.outputs(scene, uid)[0]),
                              C._coordinates(C.states(morph)[4]['members'][0]['mesh']), atol=1e-6)


def test_retiming_duplicate_delete_and_scale_preserves_sample_identity(scene):
    morph = model_set(); uid = morph[C.MORPH]
    _key(morph, 1, 0, [True]); _key(morph, 11, 0, [False]); _key(morph, 21, 3)
    retime(scale=2, offset=3)
    curve = next(c for c in C._curves(morph) if c.data_path == f'["{C.SAMPLE}"]')
    value = curve.keyframe_points[1].co.y
    curve.keyframe_points.insert(33, value)
    curve.keyframe_points.remove(curve.keyframe_points[0]); curve.update()
    _key(morph, 1, 1)
    keys = C.morph_keys(scene, uid)
    assert sorted(map(int, keys)) == [1, 25, 33, 45]
    assert keys['25']['visible'] == keys['33']['visible'] == [False]


def test_retimed_keys_survive_save_reopen_and_another_morph_edit(scene, tmp_path):
    first = model_set('First'); second = model_set('Second')
    uid = first[C.MORPH]; other_uid = second[C.MORPH]
    _key(first, 1, 0); _key(first, 21, 1, [False]); _key(second, 1, 3)
    retime(offset=10)
    path = str(tmp_path / 'retimed.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    _key(C.find(bpy.context.scene, other_uid), 1, 4)
    keys = C.morph_keys(bpy.context.scene, uid)
    assert set(keys) == {'11', '31'} and keys['31']['visible'] == [False]


@pytest.mark.parametrize('offset', [10, 80])
def test_legacy_state_curve_retiming_is_recovered(scene, offset):
    morph = model_set(); uid = morph[C.MORPH]
    _key(morph, 1, 0); _key(morph, 21, 0, [False]); _key(morph, 41, 2)
    saved = C.keyframes(scene)
    C._clear_curves(morph)
    del morph[C.SAMPLES]
    for frame, value in saved.items():
        morph['active_state'] = 2 if frame == '41' else 0
        morph.keyframe_insert('["active_state"]', frame=int(frame) + offset)
    _key(morph, 1, 3)
    keys = C.morph_keys(scene, uid)
    assert set(keys) == {'1'} | {str(f + offset) for f in (1, 21, 41)}
    assert keys[str(1 + offset)]['visible'] == [True]
    assert keys[str(21 + offset)]['visible'] == [False]


def cycle(morph, **kwargs):
    return bpy.ops.proteinblender.cycle_conformations(morph_id=morph[C.MORPH], **kwargs)


def test_cycle_order_wrap_spacing_existing_keys_and_other_sets(scene):
    morph = model_set('Cycle'); other = model_set('Other')
    _key(morph, 6, 7, [False]); _key(morph, 250, 8); _key(other, 6, 2)
    other_keys = C.morph_keys(scene, other[C.MORPH])
    assert cycle(morph, start_frame=1, end_frame=200, frame_step=5) == {'FINISHED'}
    keys = C.morph_keys(scene, morph[C.MORPH]); states = C.states(morph)
    assert len(keys) == 41 and '196' in keys and '200' not in keys
    assert keys['6']['state'] == states[7]['uid'] and keys['6']['visible'] == [False]
    assert keys['51']['state'] == states[0]['uid']
    assert C.morph_keys(scene, other[C.MORPH]) == other_keys
    assert cycle(morph, start_frame=1, end_frame=51, frame_step=10, existing='REPLACE') == {'FINISHED'}
    keys = C.morph_keys(scene, morph[C.MORPH])
    assert '6' not in keys and '250' in keys and '56' in keys
    assert C.morph_keys(scene, other[C.MORPH]) == other_keys


def test_random_cycle_is_repeatable_editable_and_validated_before_mutation(scene):
    morph = model_set(); uid = morph[C.MORPH]
    options = dict(start_frame=1, end_frame=60, frame_step=5, order='RANDOM', seed=17, existing='REPLACE')
    cycle(morph, **options); first = C.morph_keys(scene, uid)
    cycle(morph, **options); assert C.morph_keys(scene, uid) == first
    assert len({v['state'] for v in first.values()}) > 1
    before = C.keyframes(scene)
    assert cycle(morph, start_frame=20, end_frame=1) == {'CANCELLED'}
    assert C.keyframes(scene) == before
    retime(offset=10)
    _key(morph, 1, 0)
    assert set(C.morph_keys(scene, uid)) == {'1'} | {str(int(f) + 10) for f in first}


def capsid():
    return H.sm().molecules[H.import_local('1stm.cif.gz', '1STM')]


def instances():
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get(); graph.update()
    found = {}
    for i in graph.object_instances:
        if i.is_instance and i.parent:
            found.setdefault(i.parent.original.name, []).append(np.array(i.matrix_world))
    return found


@pytest.mark.parametrize('aid,counts', [
    ('1', [12, 12, 12, 12, 12]), ('2', [1, 0, 0, 0, 0]),
    ('3', [1, 1, 1, 1, 1]), ('4', [3, 1, 1, 1, 1]),
    ('5', [1, 0, 0, 0, 0]), ('6', [1, 1, 1, 1, 1]),
])
def test_1stm_deposited_chain_placements(scene, aid, counts):
    mol = capsid()
    assert len(A.buildable_assemblies(mol)) == 6
    assert A.get_assembly_info(mol, '1').description == 'complete icosahedral assembly'
    assert A.get_assembly_info(mol, '3').description == 'icosahedral pentamer'
    bpy.ops.molecule.symmetry_dialog(target_id=mol.identifier, source='BIOLOGICAL', assembly_id=aid)
    actual = instances()
    domains = sorted(mol.domains.values(), key=lambda d: str(d.chain_id))
    assert [len(actual.get(d.object.name, [])) for d in domains] == counts
    A.clear_assembly(mol)
    actual = instances()
    assert all(len(actual.get(d.object.name, [])) == 1 for d in domains)


@pytest.mark.parametrize('aid,factor,delay', [('1', 1, 0), ('1', .4, .7), ('1', 1, 1), ('5', 1, 0), ('4', .5, .2)])
def test_realization_preserves_each_chains_world_placements(scene, aid, factor, delay):
    mol = capsid()
    mol.object.location = (2, -1, 3)
    mol.object.rotation_euler = (.2, .4, -.3)
    bpy.context.view_layer.update()
    A.build_assembly(mol, aid)
    A.set_assembly_factor(mol, factor, delay)
    before = instances()
    sources = [d.object for d in mol.domains.values()]
    created = A.realize_copies(mol, force=True)
    assert created
    after = instances()
    for source in sources:
        expected = before.get(source.name, [])
        names = [o.name for o in created if o.name.startswith(source.name + '_copy_')]
        if not source.hide_get():
            names.append(source.name)
        actual = [m for name in names for m in after.get(name, [])]
        assert len(actual) == len(expected), source.name
        # Match each placement independently; instance order is not stable.
        for matrix in expected:
            error, index = min((np.max(np.abs(matrix - m)), i) for i, m in enumerate(actual))
            assert error < 2e-5, (source.name, error)
            actual.pop(index)


def test_maximum_copy_delay_still_finishes(scene):
    mol = capsid(); A.build_assembly(mol, '1')
    A.set_assembly_factor(mol, 1, 0); original = instances()
    A.set_assembly_factor(mol, 1, 1); delayed = instances()
    for name, matrices in original.items():
        for before, after in zip(matrices, delayed[name]):
            np.testing.assert_allclose(before, after, atol=2e-4)


def test_deposited_metadata_survives_save_reopen(scene, tmp_path):
    mol = capsid(); mid = mol.identifier
    path = str(tmp_path / 'assembly-metadata.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    H.scene_manager_module()._deferred_reconstruct_on_load()
    mol = H.sm().molecules[mid]
    assert A.get_assembly_info(mol, '3').description == 'icosahedral pentamer'
    A.build_assembly(mol, '2')
    actual = instances()
    domains = sorted(mol.domains.values(), key=lambda d: str(d.chain_id))
    assert [len(actual.get(d.object.name, [])) for d in domains] == [1, 0, 0, 0, 0]


def test_morph_key_edit_preserves_unrelated_transform_animation(scene):
    morph = model_set()
    morph.location.x = 2
    morph.keyframe_insert('location', frame=4)
    morph.location.x = 5
    morph.keyframe_insert('location', frame=24)
    before = [[tuple(p.co) for p in c.keyframe_points] for c in C._curves(morph)
              if c.data_path == 'location']
    _key(morph, 1, 0); _key(morph, 21, 3)
    after = [[tuple(p.co) for p in c.keyframe_points] for c in C._curves(morph)
             if c.data_path == 'location']
    assert before == after


@pytest.mark.parametrize('aid,expected', [('2', [0]), ('4', [0, 0, 0, 1, 2, 3, 4])])
def test_assembly_chain_subsets_without_domain_objects(scene, aid, expected):
    mol = capsid()
    for did in list(mol.domains):
        mol._delete_domain_direct(did)
    bpy.ops.proteinblender.edit_protein_visuals(item_id=mol.identifier, vs_style='cartoon')
    A.build_assembly(mol, aid)
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get(); graph.update()
    chains = []
    for instance in graph.object_instances:
        if instance.is_instance and instance.parent and instance.parent.original == mol.object:
            mesh = instance.object.to_mesh()
            assert len(mesh.vertices) > 0
            values = {v.value for v in mesh.attributes['chain_id'].data}
            assert len(values) == 1
            chains.extend(values)
            instance.object.to_mesh_clear()
    assert sorted(chains) == expected
    created = A.realize_copies(mol, force=True)
    assert len(created) == len(expected)
    assert mol.object.hide_get()
