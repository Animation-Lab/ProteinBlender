"""Morph definitions and independent keyframing through public PB operators."""
import json

import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import morphsets
from proteinblender.operators.keyframe_operators import get_keyframe_frames

pytestmark = pytest.mark.integration


def _set(name='Activation'):
    assert bpy.ops.proteinblender.create_morphset(name=name) == {'FINISHED'}
    return next(s for s in morphsets.sets(bpy.context.scene) if s.name == name)


def _morph(root, mid, name='Closing', **kwargs):
    assert bpy.ops.proteinblender.add_morph(morphset_id=root[morphsets.TAG], name=name,
                                           source=mid, **kwargs) == {'FINISHED'}
    return next(m for m in morphsets.morphs(bpy.context.scene, root) if m.name == name)


def _row(morph, state_index=0, visible=None, checked=True):
    row = dict(visible=True, show_visibility=False, members=[], set_name=morph.parent.name, name=morph.name, morph_id=morph[morphsets.MORPH], use_morph=checked, transition='MORPH',
               state=morphsets.states(morph)[state_index]['uid'])
    if visible is not None:
        row['members'] = [dict(name=str(i), visible=v) for i, v in enumerate(visible)]
    return row


def _key(morph, frame, index=0, visible=None):
    return bpy.ops.proteinblender.create_keyframe(frame_number=frame,
                                                 morph_items=[_row(morph, index, visible)])


def _positions(obj):
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    result = np.empty((len(mesh.vertices), 3))
    mesh.vertices.foreach_get('co', result.ravel())
    return result


def _atoms(obj):
    for modifier in obj.modifiers:
        modifier.show_viewport = False
    bpy.context.view_layer.update()
    return _positions(obj)


def test_independent_morphs_interpolate_hold_reverse_and_preserve_unchecked(scene, sm):
    a = H.import_local('1d3z.pdb.gz', 'a')
    b = H.import_local('1d3z.pdb.gz', 'b')
    root = _set()
    ma = _morph(root, a, model=sm.molecules[a].object.pb_conformations.states[0].uid,
                end_model=sm.molecules[a].object.pb_conformations.states[6].uid,
                start_name='Open', end_name='Closed')
    mb = _morph(root, b, 'Bending', model=sm.molecules[b].object.pb_conformations.states[1].uid,
                end_model=sm.molecules[b].object.pb_conformations.states[8].uid)
    assert bpy.ops.proteinblender.create_keyframe(frame_number=1,
        morph_items=[_row(ma), _row(mb)]) == {'FINISHED'}
    assert _key(ma, 21, -1) == {'FINISHED'}
    assert _key(mb, 41, -1) == {'FINISHED'}
    assert _key(ma, 31, -1) == {'FINISHED'}
    assert _key(ma, 51, 0) == {'FINISHED'}
    # An unchecked row at an existing frame must not remove its key.
    before = morphsets.keyframes(scene)['1'][mb[morphsets.MORPH]]
    assert bpy.ops.proteinblender.create_keyframe(frame_number=1,
        morph_items=[_row(ma), _row(mb, -1, checked=False)]) == {'FINISHED'}
    assert morphsets.keyframes(scene)['1'][mb[morphsets.MORPH]] == before
    assert get_keyframe_frames(bpy.context) == [1, 21, 31, 41, 51]
    scene.frame_set(11)
    for morph, progress in [(ma, .5), (mb, .25)]:
        obj = morphsets.outputs(scene, morph[morphsets.MORPH])[0]
        values = morphsets.states(morph)
        start, end = [morphsets._coordinates(s['members'][0]['mesh']) for s in (values[0], values[-1])]
        assert np.max(np.abs(end-start)) > .001
        np.testing.assert_allclose(_atoms(obj), start*(1-progress)+end*progress, atol=1e-6)
    scene.frame_set(26)
    obj = morphsets.outputs(scene, ma[morphsets.MORPH])[0]
    assert obj.data.shape_keys.key_blocks[morphsets.states(ma)[-1]['uid']].value == pytest.approx(1)
    scene.frame_set(41)
    assert obj.data.shape_keys.key_blocks[morphsets.states(ma)[0]['uid']].value == pytest.approx(.5)


def test_members_move_under_set_and_removal_restores_only_that_morph(scene, sm):
    a, b = H.import_local('1ubq.pdb', 'a'), H.import_local('1aki.pdb', 'b')
    obj = next(iter(sm.molecules[a].domains.values())).object
    parent, matrix = obj.parent, obj.matrix_world.copy()
    root = _set()
    ma, mb = _morph(root, a), _morph(root, b, 'Bending')
    assert obj.parent == root
    row = next(r for r in scene.outliner_items if r.item_type == 'MORPH_MEMBER' and r.object_name == obj.name)
    assert row.parent_id == root[morphsets.TAG]
    assert _key(ma, 1) == {'FINISHED'}
    assert _key(mb, 20) == {'FINISHED'}
    assert bpy.ops.proteinblender.remove_morph(morph_id=ma[morphsets.MORPH]) == {'FINISHED'}
    assert obj.parent == parent
    np.testing.assert_allclose(obj.matrix_world, matrix, atol=1e-6)
    assert not obj.hide_render and not obj.hide_viewport
    assert len(morphsets.morphs(scene)) == 1
    assert get_keyframe_frames(bpy.context) == [20]
    assert len(morphsets.outputs(scene)) == 1
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=root[morphsets.TAG]) == {'FINISHED'}
    assert not morphsets.outputs(scene) and not morphsets.sets(scene)
    assert b in sm.molecules


def test_member_visibility_is_constant_and_can_be_keyed_independently(scene):
    mid = H.import_local('4hhb.pdb', 'chains')
    chains = [r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN']
    root = _set()
    morph = _morph(root, mid, member_ids=json.dumps(chains[:2]))
    assert len(morphsets.records(morph)) == 2
    assert len([r for r in scene.outliner_items if r.item_type == 'CHAIN']) == 2
    assert _key(morph, 1, visible=[True, False]) == {'FINISHED'}
    assert _key(morph, 20, -1, [False, True]) == {'FINISHED'}
    scene.frame_set(19)
    assert [o.hide_render for o in morphsets.outputs(scene)] == [False, True]
    scene.frame_set(20)
    assert [o.hide_render for o in morphsets.outputs(scene)] == [True, False]
    row = _row(morph)
    row['visible'] = False
    assert bpy.ops.proteinblender.create_keyframe(frame_number=30, morph_items=[row]) == {'FINISHED'}
    scene.frame_set(30)
    assert all(o.hide_render for o in morphsets.outputs(scene))


def test_extra_named_state_and_remove_key(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'ensemble')
    library = sm.molecules[mid].object.pb_conformations
    morph = _morph(_set(), mid, model=library.states[0].uid, end_model=library.states[9].uid)
    assert bpy.ops.proteinblender.add_morph_state(morph_id=morph[morphsets.MORPH],
        name='Half closed', source=mid, model=library.states[4].uid) == {'FINISHED'}
    middle = morphsets.states(morph)[1]['uid']
    assert [s['name'] for s in morphsets.states(morph)] == ['Start', 'Half closed', 'End']
    for frame, index in [(1, 0), (10, 1), (20, 2)]:
        assert _key(morph, frame, index) == {'FINISHED'}
    assert bpy.ops.proteinblender.rename_morph_state(morph_id=morph[morphsets.MORPH],
        state_id=middle, name='Intermediate') == {'FINISHED'}
    assert bpy.ops.proteinblender.remove_morph_state(morph_id=morph[morphsets.MORPH], state_id=middle) == {'CANCELLED'}
    assert bpy.ops.proteinblender.remove_morph_key(morph_id=morph[morphsets.MORPH], frame=10) == {'FINISHED'}
    assert bpy.ops.proteinblender.remove_morph_state(morph_id=morph[morphsets.MORPH], state_id=middle) == {'FINISHED'}
    assert len(morphsets.states(morph)) == 2
    for frame in [1, 20]:
        assert bpy.ops.proteinblender.delete_keyframe(frame=frame) == {'FINISHED'}
    assert not morphsets.outputs(scene)
    assert not morphsets.records(morph)[0]['object'].hide_render


def test_1d3z_three_models_and_editing_keyed_end_state(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    library = sm.molecules[mid].object.pb_conformations.states
    model_ids = [library[i].uid for i in (0, 3, 7)]
    morph = _morph(_set(), mid, model=model_ids[0], end_model=model_ids[1])
    uid = morph[morphsets.MORPH]
    end_uid = morphsets.states(morph)[-1]['uid']
    assert _key(morph, 1) == {'FINISHED'}
    assert _key(morph, 90, -1) == {'FINISHED'}
    previous_keys = morphsets.keyframes(scene)
    # Correct the already-keyed End from Model 4 to Model 8.
    assert bpy.ops.proteinblender.edit_morph_state(morph_id=uid, state_id=end_uid,
        model=model_ids[2]) == {'FINISHED'}
    assert morphsets.keyframes(scene) == previous_keys
    assert morphsets.states(morph)[-1]['uid'] == end_uid
    # Add Model 4 using the default existing members, without reselecting a protein.
    assert bpy.ops.proteinblender.add_morph_state(morph_id=uid,
        model=model_ids[1]) == {'FINISHED'}
    assert _key(morph, 45, 1) == {'FINISHED'}
    values = morphsets.states(morph)
    assert [s['model_uid'] for s in values] == model_ids
    assert [morphsets.state_label(s) for s in values] == ['Model 1', 'Model 4', 'Model 8']
    assert get_keyframe_frames(bpy.context) == [1, 45, 90]
    captured = [morphsets._coordinates(s['members'][0]['mesh']) for s in values]
    from proteinblender.core.conformation_library import read_mesh
    for i, model_index in enumerate((0, 3, 7)):
        # Saved snapshots must contain the selected imported model's atom motion.
        np.testing.assert_allclose(captured[i] - captured[0],
            read_mesh(library[model_index].mesh) - read_mesh(library[0].mesh), atol=1e-6)
    for frame, expected in [(1, captured[0]), (45, captured[1]), (90, captured[2]),
                            (23, (captured[0] + captured[1]) / 2),
                            (67, captured[1] + (captured[2] - captured[1]) * 22 / 45)]:
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(morphsets.outputs(scene, uid)[0]), expected, atol=1e-6)
    # Renaming alone keeps snapshots and all animation untouched.
    meshes = [s['members'][0]['mesh'] for s in values]
    before = morphsets.keyframes(scene)
    assert bpy.ops.proteinblender.edit_morph_state(morph_id=uid, state_id=end_uid,
        name='Final shape') == {'FINISHED'}
    assert [s['members'][0]['mesh'] for s in morphsets.states(morph)] == meshes
    assert morphsets.keyframes(scene) == before


def test_edit_state_rejects_mismatch_and_preserves_snapshot(scene):
    a, b = H.import_local('1ubq.pdb', 'a'), H.import_local('1aki.pdb', 'b')
    morph = _morph(_set(), a)
    uid = morphsets.states(morph)[-1]['uid']
    before = morphsets.state(morph, uid).to_dict()
    meshes = set(bpy.data.meshes)
    assert bpy.ops.proteinblender.edit_morph_state(morph_id=morph[morphsets.MORPH],
        state_id=uid, source=b, model='CURRENT', name='Invalid') == {'CANCELLED'}
    assert morphsets.state(morph, uid).to_dict() == before
    assert set(bpy.data.meshes) == meshes


def test_repeated_model_and_key_edits_keep_controller_action_bound(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'repeated')
    models = sm.molecules[mid].object.pb_conformations.states
    morph = _morph(_set(), mid, model=models[0].uid, end_model=models[7].uid)
    uid, end = morph[morphsets.MORPH], morphsets.states(morph)[-1]['uid']
    assert _key(morph, 1) == {'FINISHED'}
    action = morph.animation_data.action
    # Repeatedly replace a keyed snapshot and evaluate it, as iterative editing does.
    for index in range(12):
        model_index = 3 if index % 2 else 7
        assert _key(morph, 90, -1) == {'FINISHED'}
        assert bpy.ops.proteinblender.edit_morph_state(morph_id=uid, state_id=end,
            model=models[model_index].uid) == {'FINISHED'}
        scene.frame_set(45)
        assert morph.animation_data.action == action
        assert get_keyframe_frames(bpy.context) == [1, 90]
        assert len(morphsets.outputs(scene, uid)) == 1


def test_mismatch_and_invalid_visibility_leave_scene_unchanged(scene):
    a, b = H.import_local('1ubq.pdb', 'a'), H.import_local('1aki.pdb', 'b')
    root = _set()
    before = set(bpy.data.meshes)
    assert bpy.ops.proteinblender.add_morph(morphset_id=root[morphsets.TAG], source=a,
                                           end_source=b) == {'CANCELLED'}
    assert not morphsets.morphs(scene)
    assert set(bpy.data.meshes) == before
    morph = _morph(root, a)
    assert _key(morph, 1) == {'FINISHED'}
    before = morphsets.outputs(scene)[0]
    assert _key(morph, 20, visible=[False, True]) == {'CANCELLED'}
    assert morphsets.outputs(scene)[0] == before


def _shared_sequence(scene, sm, separate_sets=False):
    mid = H.import_local('1d3z.pdb.gz', 'shared_1d3z')
    library = sm.molecules[mid].object.pb_conformations.states
    root = _set()
    a = _morph(root, mid, 'Models 1 to 4', model=library[0].uid, end_model=library[3].uid)
    assert _key(a, 1) == {'FINISHED'}
    assert _key(a, 45, -1) == {'FINISHED'}
    b = _morph(_set('Later transitions') if separate_sets else root, mid, 'Models 4 to 8',
               model=library[3].uid, end_model=library[7].uid)
    assert _key(b, 45) == {'FINISHED'}
    assert _key(b, 90, -1) == {'FINISHED'}
    return mid, a, b


def test_same_protein_can_have_two_morphs_with_one_animation(scene, sm):
    mid, a, b = _shared_sequence(scene, sm)
    assert len(morphsets.morphs(scene)) == 2
    assert morphsets.records(a)[0]['object'] == morphsets.records(b)[0]['object']
    assert morphsets.outputs(scene, a[morphsets.MORPH]) == morphsets.outputs(scene, b[morphsets.MORPH])
    assert len(morphsets.outputs(scene)) == 1
    points = [morphsets._coordinates(s['members'][0]['mesh']) for s in
              [morphsets.states(a)[0], morphsets.states(a)[-1], morphsets.states(b)[-1]]]
    for frame, expected in [(1, points[0]), (45, points[1]), (90, points[2]),
                            (23, (points[0] + points[1]) / 2),
                            (67, points[1] + (points[2] - points[1]) * 22 / 45)]:
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(morphsets.outputs(scene)[0]), expected, atol=1e-6)
    assert get_keyframe_frames(bpy.context) == [1, 45, 90]
    for morph in (a, b):
        row_id = morph[morphsets.MORPH] + ':0'
        assert bpy.ops.proteinblender.outliner_select(item_id=row_id) == {'FINISHED'}
        assert morphsets.outputs(scene)[0].select_get()
        assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'CANCELLED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon',
        bfactor_motion=True) == {'FINISHED'}
    assert all(morphsets.records(m)[0]['style'] == 'cartoon' for m in (a, b))
    assert len(morphsets.outputs(scene)) == 1


def test_shared_key_conflicts_leave_animation_and_models_unchanged(scene, sm):
    mid, a, b = _shared_sequence(scene, sm)
    keys = morphsets.keyframes(scene)
    output = morphsets.outputs(scene)[0]
    assert _key(b, 45, -1) == {'CANCELLED'}
    assert _key(b, 45, 0, [False]) == {'CANCELLED'}
    end = morphsets.states(a)[-1]
    snapshot, uid = end['members'][0]['mesh'], end['uid']
    meshes = set(bpy.data.meshes)
    assert bpy.ops.proteinblender.edit_morph_state(morph_id=a[morphsets.MORPH], state_id=uid,
        model=sm.molecules[mid].object.pb_conformations.states[7].uid) == {'CANCELLED'}
    assert morphsets.state(a, uid)['members'][0]['mesh'] == snapshot
    assert set(bpy.data.meshes) == meshes
    assert morphsets.keyframes(scene) == keys
    assert morphsets.outputs(scene)[0] == output


@pytest.mark.parametrize('remove_first', [True, False])
def test_removing_shared_morph_restores_original_only_after_last_user(scene, sm, remove_first):
    mid, a, b = _shared_sequence(scene, sm, separate_sets=True)
    obj = morphsets.records(a)[0]['object']
    parent = morphsets.records(a)[0]['parent']
    first, last = (a, b) if remove_first else (b, a)
    assert bpy.ops.proteinblender.remove_morph(morph_id=first[morphsets.MORPH]) == {'FINISHED'}
    assert obj.parent == last.parent
    assert obj['pb_morphset_owner'] == last
    assert obj.hide_viewport
    assert len(morphsets.outputs(scene)) == 1
    assert morphsets.outputs(scene)[0].parent == last
    assert bpy.ops.proteinblender.remove_morph(morph_id=last[morphsets.MORPH]) == {'FINISHED'}
    assert obj.parent == parent
    assert not obj.hide_viewport and not obj.hide_get()
    assert 'pb_morphset_owner' not in obj
    assert not morphsets.outputs(scene)


def test_shared_members_survive_source_deletion_without_duplicate_copies(scene, sm):
    mid, a, b = _shared_sequence(scene, sm)
    assert bpy.ops.molecule.delete(molecule_id=mid) == {'FINISHED'}
    assert morphsets.records(a)[0]['object'] == morphsets.records(b)[0]['object']
    assert _key(b, 120, -1) == {'FINISHED'}
    assert len(morphsets.outputs(scene)) == 1
    assert bpy.ops.proteinblender.remove_morph(morph_id=a[morphsets.MORPH]) == {'FINISHED'}
    assert len(morphsets.outputs(scene)) == 1
    assert bpy.ops.proteinblender.remove_morph(morph_id=b[morphsets.MORPH]) == {'FINISHED'}
    assert not morphsets.outputs(scene)


def test_partial_chain_overlap_shares_only_the_reused_chain(scene, sm):
    mid = H.import_local('4hhb.pdb', 'overlap')
    domain_ids = list(sm.molecules[mid].domains)
    root = _set()
    a = _morph(root, mid, 'All chains')
    b = _morph(root, domain_ids[1], 'Second chain')
    assert _key(a, 1) == {'FINISHED'}
    assert _key(b, 45) == {'FINISHED'}
    assert len(morphsets.outputs(scene)) == 4
    shared = morphsets.outputs(scene, b[morphsets.MORPH])[0]
    assert morphsets.output_slot(shared, a[morphsets.MORPH]) == 1
    assert morphsets.output_slot(shared, b[morphsets.MORPH]) == 0
    row = next(r for r in scene.outliner_items if r.item_id == b[morphsets.MORPH] + ':0')
    assert morphsets.row_object(scene, row) == shared
    assert bpy.ops.proteinblender.remove_morph(morph_id=a[morphsets.MORPH]) == {'FINISHED'}
    assert len(morphsets.outputs(scene)) == 1


@pytest.mark.parametrize('motion', [False, True])
def test_style_and_temperature_survive_key_edits(scene, sm, single_chain, motion):
    from test_visual_edit_dialogs import _style_node_tree_name
    morph = _morph(_set(), single_chain)
    assert _key(morph, 1) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain, bfactor_motion=motion) == {'FINISHED'}
    output = morphsets.outputs(scene)[0]
    shape_keys = output.data.shape_keys
    for style, label in [('surface', 'Surface'), ('cartoon', 'Cartoon')]:
        assert bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain, vs_style=style) == {'FINISHED'}
        assert morphsets.outputs(scene)[0] == output
        assert output.data.shape_keys == shape_keys
        assert f'Style {label}' in _style_node_tree_name(output)
        assert len(H.eval_positions(output)) > 0
    assert 'Continuous Motion' in _style_node_tree_name(output)
    assert _key(morph, 20, -1, [False]) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain, bfactor_motion=not motion) == {'FINISHED'}
    assert 'Style Cartoon' in _style_node_tree_name(morphsets.outputs(scene)[0])


def test_selection_filters_to_independent_morph(scene):
    from proteinblender.operators.keyframe_operators import get_filtered_keyframe_targets
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    root = _set()
    ma = _morph(root, H.import_local('1ubq.pdb', 'a'))
    mb = _morph(root, H.import_local('1aki.pdb', 'b'), 'Bending')
    assert _key(ma, 1) == {'FINISHED'}
    assert _key(mb, 20) == {'FINISHED'}
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    update_outliner_from_blender_selection()
    row_id = ma[morphsets.MORPH] + ':0'
    assert bpy.ops.proteinblender.outliner_select(item_id=row_id) == {'FINISHED'}
    assert morphsets.outputs(scene, ma[morphsets.MORPH])[0].select_get()
    update_outliner_from_blender_selection()
    assert next(r for r in scene.outliner_items if r.item_id == row_id).is_selected
    targets, _ = get_filtered_keyframe_targets(bpy.context)
    assert [item_id for _, _, kind, item_id in targets if kind == 'MORPHSET'] == [ma[morphsets.MORPH]]


def test_deleting_source_preserves_morph(scene, single_chain):
    morph = _morph(_set(), single_chain)
    assert _key(morph, 1) == {'FINISHED'}
    assert bpy.ops.molecule.delete(molecule_id=single_chain) == {'FINISHED'}
    assert morphsets.records(morph)[0]['object'] is not None
    assert _key(morph, 21, -1) == {'FINISHED'}
    for frame in [1, 21]:
        assert bpy.ops.proteinblender.delete_keyframe(frame=frame) == {'FINISHED'}
    assert not morphsets.records(morph)[0]['object'].hide_render


def test_prepared_alignment_is_preserved(scene, sm, tmp_path):
    from pathlib import Path
    first = H.import_local('1ubq.pdb', 'aligned_a')
    lines = Path(H.data_path('1ubq.pdb')).read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(('ATOM  ', 'HETATM')):
            lines[i] = line[:30] + f'{float(line[30:38]) + 10:8.3f}' + line[38:]
    path = tmp_path / 'translated.pdb'
    path.write_text('\n'.join(lines) + '\n')
    assert bpy.ops.molecule.import_local(filepath=str(path), identifier_override='aligned_b') == {'FINISHED'}
    morph = _morph(_set(), first, end_source='aligned_b')
    values = morphsets.states(morph)
    delta = morphsets._coordinates(values[-1]['members'][0]['mesh']) - morphsets._coordinates(values[0]['members'][0]['mesh'])
    np.testing.assert_allclose(delta, np.tile((.1, 0, 0), (len(delta), 1)), atol=2e-6)


def test_temperature_motion_changes_geometry_and_restores(scene, sm, single_chain):
    mol = sm.molecules[single_chain]
    obj = next(iter(mol.domains.values())).object
    original = np.array([v.co[:] for v in obj.data.vertices])
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, bfactor_motion=True) == {'FINISHED'}
    from proteinblender.core.thermal_motion import NAME
    # Observe the atom modifier directly, without expensive surface generation.
    other = [m for m in obj.modifiers if m.name != NAME]
    for mod in other:
        mod.show_viewport = False
    scene.frame_set(1)
    first = _positions(obj)
    scene.frame_set(8)
    second = _positions(obj)
    assert np.max(np.abs(second - first)) > 1e-4
    scene.frame_set(1)
    np.testing.assert_allclose(_positions(obj), first, atol=1e-7)
    np.testing.assert_array_equal(np.array([v.co[:] for v in obj.data.vertices]), original)
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, bfactor_motion=False) == {'FINISHED'}
    assert not any(m.name.startswith(NAME) for m in obj.modifiers)
    np.testing.assert_allclose(_positions(obj), original, atol=1e-7)



def test_morph_and_puppet_keyframe_capture_edits_together(scene):
    moving = H.import_local('4hhb.pdb', 'moving')
    chain_ids = [r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN' and r.parent_id == moving][:2]
    for row in scene.outliner_items:
        row.is_selected = row.item_id in chain_ids
    assert bpy.ops.proteinblender.create_puppet(puppet_name='Moving puppet') == {'FINISHED'}
    puppet = next(r for r in scene.outliner_items if r.item_type == 'PUPPET' and r.controller_object_name)
    controller = bpy.data.objects[puppet.controller_object_name]
    settings = dict(name=puppet.name, puppet_name=puppet.name, puppet_id=puppet.item_id,
                    controller_object_name=controller.name, item_kind='PUPPET', use_puppet=True,
                    keyframe_location=True, keyframe_rotation=False, keyframe_scale=False,
                    keyframe_pose=False, keyframe_color=False, brownian_enabled=False)
    morph = _morph(_set(), H.import_local('1ubq.pdb', 'morphing'))
    controller.location.x = 0
    assert bpy.ops.proteinblender.create_keyframe(frame_number=1,
        puppet_items=[settings], morph_items=[_row(morph)]) == {'FINISHED'}
    scene.frame_set(21)
    controller.location.x = 3
    assert bpy.ops.proteinblender.create_keyframe(frame_number=21,
        puppet_items=[settings], morph_items=[_row(morph, -1)]) == {'FINISHED'}
    scene.frame_set(1)
    assert controller.location.x == pytest.approx(0)
    scene.frame_set(21)
    assert controller.location.x == pytest.approx(3)
    assert set(morphsets.keyframes(scene)) == {'1', '21'}


def test_previous_morphset_format_migrates_without_losing_states_or_keys(scene, sm):
    # Build the prior on-disk schema explicitly: one root and member per state.
    # This is a serialization compatibility fixture, not a mock Blender API.
    from mathutils import Matrix
    a, b = H.import_local('1ubq.pdb', 'old_a'), H.import_local('1ubq.pdb', 'old_b')
    roots, meshes = [], []
    for index, mid in enumerate([a, b]):
        mol = sm.molecules[mid]
        obj = next(iter(mol.domains.values())).object
        obj.location.x += index
        captured, _ = morphsets._capture(bpy.context, [mid])
        mesh = captured[0]['mesh']
        meshes.append(mesh)
        root = bpy.data.objects.new('Old state ' + str(index), None)
        scene.collection.objects.link(root)
        root[morphsets.TAG] = 'old-state-' + str(index)
        root['pb_order'] = index
        member = dict(captured[0], object=obj, generated=False, parent=obj.parent,
                      parent_inverse=[v for row in Matrix.Identity(4) for v in row],
                      render=False, viewport=False, hidden=False)
        root['pb_members'] = [member]
        matrix = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = matrix
        obj['pb_morphset_owner'] = root
        roots.append(root)
    morphsets.track(scene, True)['pb_morph_keys'] = json.dumps({
        '1': dict(set='old-state-0', visible=[True]),
        '21': dict(set='old-state-1', visible=[False])})
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    assert len(morphsets.sets(scene)) == len(morphsets.morphs(scene)) == 1
    morph = morphsets.morphs(scene)[0]
    assert [s['members'][0]['mesh'] for s in morphsets.states(morph)] == meshes
    assert get_keyframe_frames(bpy.context) == [1, 21]
    scene.frame_set(11)
    obj = morphsets.outputs(scene)[0]
    assert obj.data.shape_keys.key_blocks['old-state-0'].value == pytest.approx(.5)
    scene.frame_set(21)
    assert obj.hide_render
    assert _key(morph, 41) == {'FINISHED'}
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=morph.parent[morphsets.TAG]) == {'FINISHED'}
    assert not next(iter(sm.molecules[b].domains.values())).object.hide_render


def test_unkeyed_morph_keeps_its_outliner_visibility_control(scene):
    root = _set()
    a = _morph(root, H.import_local('1ubq.pdb', 'keyed'))
    b = _morph(root, H.import_local('1aki.pdb', 'unkeyed'), 'Unkeyed')
    assert _key(a, 1) == {'FINISHED'}
    assert bpy.ops.proteinblender.toggle_visibility(item_id=b[morphsets.MORPH] + ':0') == {'FINISHED'}
    assert morphsets.records(b)[0]['object'].hide_get()
    assert bpy.ops.proteinblender.toggle_visibility(item_id=a[morphsets.MORPH] + ':0') == {'CANCELLED'}
