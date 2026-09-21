"""State libraries, timeline semantics, legacy migration, and transient browsing."""
import json

import bpy
import numpy as np
import pytest
import helpers as H

from proteinblender.core import morphsets as C, conformation_sets as S
from proteinblender.operators import conformation_browser as B
from proteinblender.operators.morphset_operators import morph_state_items
from test_morphsets import _row, _atoms, _set, _morph, _key

pytestmark = pytest.mark.integration


def library(source, name=''):
    assert bpy.ops.proteinblender.create_morphset(source=source, name=name) == {'FINISHED'}
    return S.subject(B.current(bpy.context.scene))


def key(morph, frame, index, transition='MORPH', visible=True):
    row = _row(morph, index)
    row.update(transition=transition, visible=visible)
    assert bpy.ops.proteinblender.create_keyframe(frame_number=frame, morph_items=[row]) == {'FINISHED'}


def coords(morph, index, slot=0):
    return C._coordinates(C.states(morph)[index]['members'][slot]['mesh'])


def test_import_models_direct_keyframes_and_explicit_bridge(scene):
    morph = library(H.import_local('1d3z.pdb.gz', '1D3Z'))
    assert len(C.morphs(scene)) == 1
    assert [C.state_label(s) for s in C.states(morph)] == [f'Model {i}' for i in range(1, 11)]
    assert [v.name for v in scene.pb_morph_browser.items] == [f'Model {i}' for i in range(1, 11)]
    assert len([r for r in scene.outliner_items if r.item_type == 'MORPH_MEMBER']) == 1
    for frame, index in [(1, 0), (50, 2), (75, 7), (100, 8)]:
        key(morph, frame, index)
    obj = C.outputs(scene)[0]
    for frame, expected in [(1, coords(morph, 0)), (50, coords(morph, 2)),
                            (60, coords(morph, 2)*.6 + coords(morph, 7)*.4),
                            (75, coords(morph, 7)), (100, coords(morph, 8))]:
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(obj), expected, atol=1e-6)
    assert S.timeline_context(scene, morph, 60) == ((50, 'Model 3', 'MORPH'), (75, 'Model 8', 'MORPH'))


def test_hold_cut_reverse_and_visibility(scene):
    morph = library(H.import_local('1d3z.pdb.gz', '1D3Z'))
    key(morph, 10, 0, 'HOLD')
    key(morph, 30, 7, visible=False)
    key(morph, 50, 0)
    obj = C.outputs(scene)[0]
    for frame in (1, 10, 20, 29):
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(obj), coords(morph, 0), atol=1e-6)
        assert not obj.hide_render
    scene.frame_set(30)
    assert obj.hide_render
    obj.hide_viewport = False
    bpy.context.view_layer.update()
    np.testing.assert_allclose(_atoms(obj), coords(morph, 7), atol=1e-6)
    assert obj.hide_render
    scene.frame_set(40)
    obj.hide_viewport = False
    bpy.context.view_layer.update()
    np.testing.assert_allclose(_atoms(obj), (coords(morph, 7)+coords(morph, 0))/2, atol=1e-6)
    scene.frame_set(50)
    assert not obj.hide_render
    assert S.timeline_context(scene, morph, 20)[0] == (10, 'Model 1', 'HOLD')


def test_repeat_create_focuses_existing_library_and_first_last_states_are_editable(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    morph = library(mid)
    uid = morph[C.MORPH]
    assert library(mid)[C.MORPH] == uid
    assert len(C.sets(scene)) == 1
    for state_uid in (C.states(morph)[0]['uid'], C.states(morph)[-1]['uid']):
        assert bpy.ops.proteinblender.remove_morph_state(morph_id=uid, state_id=state_uid) == {'FINISHED'}
    assert len(C.states(morph)) == 8
    old = C.states(morph)[0]['uid']
    key(morph, 1, 0)
    model = sm.molecules[mid].object.pb_conformations.states[9].uid
    assert bpy.ops.proteinblender.edit_morph_state(morph_id=uid, state_id=old, source=mid,
                                                  model=model, name='Chosen') == {'FINISHED'}
    assert C.keyframes(scene)['1'][uid]['state'] == old
    assert C.state(morph, old)['model_name'] == 'Model 10'
    assert bpy.ops.proteinblender.remove_morph_state(morph_id=uid, state_id=old) == {'CANCELLED'}


def test_two_subjects_can_choose_states_independently(scene):
    a = library(H.import_local('1d3z.pdb.gz', 'A'))
    b = library(H.import_local('1d3z.pdb.gz', 'B'))
    for m in (a, b):
        key(m, 1, 0)
    key(a, 45, 3)
    key(b, 90, 7)
    key(a, 90, 0)
    assert len(C.sets(scene)) == len(C.outputs(scene)) == 2
    assert C.keyframes(scene)['90'][b[C.MORPH]]['state'] == C.states(b)[7]['uid']
    scene.frame_set(45)
    np.testing.assert_allclose(_atoms(C.outputs(scene, a[C.MORPH])[0]), coords(a, 3), atol=1e-6)


@pytest.mark.parametrize('style', ['cartoon', 'spheres'])
def test_preview_restores_timeline_without_touching_keys(scene, style):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style=style) == {'FINISHED'}
    morph = library(mid)
    key(morph, 1, 0)
    key(morph, 90, 7)
    scene.frame_set(45)
    before = C.keyframes(scene)
    output = C.outputs(scene)[0]
    S.preview(bpy.context, morph, C.states(morph)[5]['uid'])
    preview = next(o for o in scene.objects if o.get(S.PREVIEW))
    assert preview.hide_render and output.hide_get()
    np.testing.assert_allclose(_atoms(preview), coords(morph, 5), atol=1e-6)
    assert C.keyframes(scene) == before
    scene.frame_set(46)
    assert not output.hide_get()
    assert preview.hide_viewport
    assert 'pb_conformation_preview' not in scene
    S.preview(bpy.context, morph, C.states(morph)[3]['uid'])
    S.end_preview_on_save()
    assert not any(o.get(S.PREVIEW) for o in scene.objects)
    assert not output.hide_get()
    assert C.keyframes(scene) == before
    S.preview(bpy.context, morph, C.states(morph)[0]['uid'])
    key(morph, 20, 1)
    assert not any(o.get(S.PREVIEW) for o in scene.objects)
    assert 'pb_conformation_preview' not in scene


def test_incompatible_state_is_atomic_and_no_source_is_hidden(scene):
    morph = library(H.import_local('1ubq.pdb', 'ubiquitin'))
    other = H.import_local('1aki.pdb', 'lysozyme')
    count = len(bpy.data.meshes)
    states = [v['uid'] for v in C.states(morph)]
    assert bpy.ops.proteinblender.add_morph_state(morph_id=morph[C.MORPH], source=other,
                                                  name='Incompatible') == {'CANCELLED'}
    assert len(bpy.data.meshes) == count
    assert [v['uid'] for v in C.states(morph)] == states
    assert not C.keyframes(scene)


def sample(scene):
    result = {}
    for frame in (1, 23, 45, 67, 90):
        scene.frame_set(frame)
        result[frame] = [(o.hide_render, _atoms(o).copy()) for o in C.outputs(scene)]
    return result


def assert_samples(scene, expected):
    actual = sample(scene)
    for frame, values in expected.items():
        assert len(values) == len(actual[frame])
        for (hidden, positions), (new_hidden, new_positions) in zip(values, actual[frame]):
            assert hidden == new_hidden
            np.testing.assert_allclose(positions, new_positions, atol=1e-6)


def test_upgrade_shared_pairs_merges_duplicate_model_preserves_geometry_and_keys(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    states = sm.molecules[mid].object.pb_conformations.states
    root = _set()
    a = _morph(root, mid, '1 to 4', model=states[0].uid, end_model=states[3].uid)
    b = _morph(root, mid, '4 to 8', model=states[3].uid, end_model=states[7].uid)
    for m, f, index in ((a, 1, 0), (a, 45, -1), (b, 45, 0), (b, 90, -1)):
        _key(m, f, index)
    expected = sample(scene)
    action = a.animation_data.action
    S.upgrade(bpy.context)
    assert len(C.morphs(scene)) == len(C.sets(scene)) == 1
    morph = C.morphs(scene)[0]
    assert morph.animation_data.action == action
    assert [C.state_label(s) for s in C.states(morph)] == ['Model 1', 'Model 4', 'Model 8']
    assert sorted(map(int, C.keyframes(scene))) == [1, 45, 90]
    assert_samples(scene, expected)
    S.upgrade(bpy.context)
    assert_samples(scene, expected)


def test_upgrade_independent_subjects_preserves_keys_geometry_and_sources(scene, sm):
    a = H.import_local('1d3z.pdb.gz', 'A')
    b = H.import_local('1d3z.pdb.gz', 'B')
    root = _set()
    for mid in (a, b):
        states = sm.molecules[mid].object.pb_conformations.states
        morph = _morph(root, mid, mid + ' motion', model=states[0].uid, end_model=states[7].uid)
        _key(morph, 1, 0)
        _key(morph, 90, -1)
    expected = sample(scene)
    S.upgrade(bpy.context)
    assert len(C.sets(scene)) == 2
    assert all(len(C.morphs(scene, root)) == 1 for root in C.sets(scene))
    assert_samples(scene, expected)


def test_upgrade_partial_overlap_preserves_the_shared_animation(scene):
    mid = H.import_local('4hhb.pdb', 'complex')
    chains = [r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN']
    root = _set()
    both = _morph(root, mid, 'Both chains', member_ids=json.dumps(chains[:2]))
    one = _morph(root, mid, 'One chain', member_ids=json.dumps(chains[:1]))
    _key(both, 1, 0)
    _key(one, 45, -1)
    _key(both, 90, -1)
    expected = sample(scene)
    S.upgrade(bpy.context)
    assert len(C.sets(scene)) == 2
    assert len(C.outputs(scene)) == 2
    assert_samples(scene, expected)
