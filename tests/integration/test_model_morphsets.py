"""The member -> imported model -> frame workflow, through shipped operators."""
import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import morphsets as C, model_morphsets as M
from proteinblender.operators.keyframe_operators import get_keyframe_frames
from test_morphsets import _key, _row, _atoms

pytestmark = pytest.mark.integration


def make(mid, ids=None, name='Conformations'):
    members = [dict(name='', reason='', member_id=i, selected=True) for i in ids] if ids is not None else []
    assert bpy.ops.proteinblender.create_morphset(name=name, source=mid, members=members) == {'FINISHED'}
    root = next(r for r in C.sets(bpy.context.scene) if r.name == name)
    return root, M.subject(root)


def test_all_imported_models_and_nested_outliner(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    other = H.import_local('1aki.pdb', 'Other protein')
    mol = sm.molecules[mid]
    root, morph = make(mid)
    assert len(C.states(morph)) == 10
    assert [s['model_uid'] for s in C.states(morph)] == [s.uid for s in mol.object.pb_conformations.states]
    assert len(C.morphs(scene, root)) == 1
    assert root.parent == mol.object
    rows = list(scene.outliner_items)
    parent = next(r for r in rows if r.item_id == root[C.TAG])
    member = next(r for r in rows if r.item_type == 'MORPH_MEMBER')
    assert parent.parent_id == mid and parent.indent_level == 1
    assert member.parent_id == root[C.TAG] and member.indent_level == 2
    assert member.name == 'Chain A'
    names = [r.item_id for r in rows]
    assert names.index(mid) < names.index(root[C.TAG]) < names.index(member.item_id) < names.index(other)
    assert not C.keyframes(scene) and not C.outputs(scene)


def test_key_models_out_of_order_bridge_hold_reverse_edit_and_delete(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    uid = morph[C.MORPH]
    values = C.states(morph)
    points = [C._coordinates(s['members'][0]['mesh']) for s in values]
    # User's sequence, inserted nonchronologically, plus a hold and reverse.
    for frame, model in [(100, 8), (50, 2), (1, 0), (75, 7), (120, 8), (140, 0)]:
        assert _key(morph, frame, model) == {'FINISHED'}
    assert len(C.outputs(scene)) == 1
    obj = C.outputs(scene)[0]
    for frame, expected in [(0, points[0]), (1, points[0]), (50, points[2]),
                            (60, points[2]*.6 + points[7]*.4), (75, points[7]),
                            (100, points[8]), (110, points[8]),
                            (130, (points[8]+points[0])/2), (160, points[0])]:
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(obj), expected, atol=1e-6)
    assert M.neighbors(scene, morph, 75) == ('Model 3 at frame 50', 'Model 9 at frame 100')
    assert _key(morph, 75, 6) == {'FINISHED'}
    scene.frame_set(75)
    np.testing.assert_allclose(_atoms(C.outputs(scene)[0]), points[6], atol=1e-6)
    assert bpy.ops.proteinblender.remove_morph_key(morph_id=uid, frame=75) == {'FINISHED'}
    scene.frame_set(75)
    np.testing.assert_allclose(_atoms(C.outputs(scene)[0]), (points[2]+points[8])/2, atol=1e-6)
    assert get_keyframe_frames(bpy.context) == [1, 50, 100, 120, 140]


def test_single_key_and_unchecked_row_do_not_invent_transitions(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    assert _key(morph, 50, 6) == {'FINISHED'}
    expected = C._coordinates(C.states(morph)[6]['members'][0]['mesh'])
    for frame in (1, 50, 150):
        scene.frame_set(frame)
        np.testing.assert_allclose(_atoms(C.outputs(scene)[0]), expected, atol=1e-6)
    before = C.keyframes(scene)
    assert bpy.ops.proteinblender.create_keyframe(frame_number=50,
        morph_items=[_row(morph, 2, checked=False)]) == {'CANCELLED'}
    assert C.keyframes(scene) == before


def test_parent_transform_style_temperature_and_removal(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', '1D3Z')
    source = sm.molecules[mid].object
    domain = next(iter(sm.molecules[mid].domains.values())).object
    parent = domain.parent
    source.location = (1, 2, 3)
    source.rotation_euler.z = .35
    bpy.context.view_layer.update()
    original_atoms = H.evaluated_atom_positions([domain])
    root, morph = make(mid)
    assert _key(morph, 1, 0) == {'FINISHED'}
    obj = C.outputs(scene)[0]
    local = _atoms(obj)
    world = np.asarray(obj.matrix_world)
    np.testing.assert_allclose(local @ world[:3, :3].T + world[:3, 3], original_atoms, atol=1e-6)
    assert _key(morph, 45, 3) == {'FINISHED'}
    scene.frame_set(23)
    obj = C.outputs(scene)[0]
    old_matrix = obj.matrix_world.copy()
    source.location.x += 2
    bpy.context.view_layer.update()
    np.testing.assert_allclose(obj.matrix_world.translation, np.asarray(old_matrix.translation) + np.array([2,0,0]), atol=1e-6)
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='spheres',
        bfactor_motion=True) == {'FINISHED'}
    from proteinblender.core.visual_style import get_object_style
    assert get_object_style(C.outputs(scene)[0]) == 'spheres'
    assert source.get('pb_bfactor_enabled')
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon',
        bfactor_motion=False) == {'FINISHED'}
    assert get_object_style(C.outputs(scene)[0]) == 'cartoon'
    matrix = M.world_matrix(domain)
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=root[C.TAG]) == {'FINISHED'}
    assert domain.parent == parent
    np.testing.assert_allclose(domain.matrix_world, matrix, atol=1e-6)
    assert not C.outputs(scene) and not domain.hide_render and not domain.hide_get()


def test_duplicate_members_single_model_and_invalid_selection_leave_scene_unchanged(scene, sm):
    single = H.import_local('1ubq.pdb', 'Single')
    before = set(bpy.data.objects), set(bpy.data.meshes)
    assert bpy.ops.proteinblender.create_morphset(source=single) == {'CANCELLED'}
    assert (set(bpy.data.objects), set(bpy.data.meshes)) == before
    mid = H.import_local('1d3z.pdb.gz', 'Models')
    root, morph = make(mid)
    before = set(bpy.data.objects), set(bpy.data.meshes)
    assert bpy.ops.proteinblender.create_morphset(source=mid) == {'CANCELLED'}
    assert bpy.ops.proteinblender.create_morphset(source=mid,
        members=[dict(name='', reason='', member_id='missing', selected=True)]) == {'CANCELLED'}
    assert bpy.ops.proteinblender.create_morphset(source=mid,
        members=[dict(name='', reason='', member_id=next(iter(sm.molecules[mid].domains)), selected=False)]) == {'CANCELLED'}
    assert (set(bpy.data.objects), set(bpy.data.meshes)) == before


def test_incompatible_model_is_atomic(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'Invalid coordinates')
    sm.molecules[mid].object.pb_conformations.states[5].mesh.vertices[0].co.x = float('nan')
    before = set(bpy.data.objects), set(bpy.data.meshes)
    assert bpy.ops.proteinblender.create_morphset(source=mid) == {'CANCELLED'}
    assert (set(bpy.data.objects), set(bpy.data.meshes)) == before


def test_grouped_chains_membership_edit_and_independent_timing(scene, sm):
    mid = H.import_local('2bbn.pdb.gz', 'Complex')
    mol = sm.molecules[mid]
    ids = list(mol.domains)
    assert len(ids) == 2
    root, morph = make(mid)
    assert len(C.states(morph)) == 21 and len(C.records(morph)) == 2
    assert _key(morph, 1, 0, [True, False]) == {'FINISHED'}
    assert _key(morph, 51, 5) == {'FINISHED'}
    keys = C.keyframes(scene)
    source_uids = [s['uid'] for s in C.states(morph)]
    # Remove the second member while keeping every existing key/model identity.
    assert bpy.ops.proteinblender.edit_morphset(morphset_id=root[C.TAG], name='First chain',
        members=[dict(name='', reason='', member_id=ids[0], selected=True)]) == {'FINISHED'}
    assert [s['uid'] for s in C.states(morph)] == source_uids
    assert len(C.records(morph)) == len(C.outputs(scene)) == 1
    assert not mol.domains[ids[1]].object.hide_render
    for f, rows in keys.items():
        assert C.keyframes(scene)[f][morph[C.MORPH]]['state'] == rows[morph[C.MORPH]]['state']
    second, other = make(mid, [ids[1]], 'Second chain')
    assert _key(other, 1, 0) == {'FINISHED'}
    assert _key(other, 101, 20) == {'FINISHED'}
    scene.frame_set(26)
    for m, progress, last in [(morph, .5, 5), (other, .25, 20)]:
        values = C.states(m)
        a, b = [C._coordinates(values[i]['members'][0]['mesh']) for i in (0, last)]
        np.testing.assert_allclose(_atoms(C.outputs(scene, m[C.MORPH])[0]), a*(1-progress)+b*progress, atol=1e-6)
    # Can't reclaim the independently controlled chain, even through Edit.
    before = C.keyframes(scene), set(bpy.data.meshes)
    assert bpy.ops.proteinblender.edit_morphset(morphset_id=root[C.TAG], name='Conflict',
        members=[dict(name='', reason='', member_id=i, selected=True) for i in ids]) == {'CANCELLED'}
    assert (C.keyframes(scene), set(bpy.data.meshes)) == before
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=second[C.TAG]) == {'FINISHED'}
    # Editing membership after moving the protein must not double-transform it.
    mol.object.location.x += 2
    bpy.context.view_layer.update()
    obj = C.outputs(scene, morph[C.MORPH])[0]
    old_points = _atoms(obj).copy()
    old_matrix = obj.matrix_world.copy()
    assert bpy.ops.proteinblender.edit_morphset(morphset_id=root[C.TAG], name='Together',
        members=[dict(name='', reason='', member_id=i, selected=True) for i in ids]) == {'FINISHED'}
    scene.frame_set(26)
    obj = C.outputs(scene, morph[C.MORPH])[0]
    np.testing.assert_allclose(_atoms(obj), old_points, atol=1e-6)
    np.testing.assert_allclose(obj.matrix_world, old_matrix, atol=1e-6)
    assert len(C.outputs(scene)) == 2
    scene.frame_set(1)
    assert not C.outputs(scene)[0].hide_render
    assert not C.outputs(scene)[1].hide_render


def test_domains_are_independent_and_eligibility_is_checked_per_member(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'Domains')
    assert H.split_domain_from_outliner(mid, 'A', 1, 35) == {'FINISHED'}
    mol = sm.molecules[mid]
    ids = list(mol.domains)
    assert len(ids) == 2
    root, morph = make(mid, [ids[0]])
    other, second = make(mid, [ids[1]], 'Second domain')
    assert _key(morph, 1, 0) == {'FINISHED'}
    assert _key(morph, 41, 3) == {'FINISHED'}
    assert _key(second, 1, 0) == {'FINISHED'}
    assert _key(second, 81, 7) == {'FINISHED'}
    assert len(C.outputs(scene)) == 2
    for m, progress, model in [(morph, .5, 3), (second, .25, 7)]:
        scene.frame_set(21)
        a, b = [C._coordinates(C.states(m)[i]['members'][0]['mesh']) for i in (0,model)]
        np.testing.assert_allclose(_atoms(C.outputs(scene,m[C.MORPH])[0]), a*(1-progress)+b*progress, atol=1e-6)


def test_puppet_members_explain_why_they_cannot_morph(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'Puppet member')
    for row in scene.outliner_items:
        row.is_selected = row.item_type == 'CHAIN'
    assert bpy.ops.proteinblender.create_puppet(puppet_name='Puppet') == {'FINISHED'}
    domain = next(iter(sm.molecules[mid].domains.values()))
    assert 'puppet' in M.member_issue(bpy.context, sm.molecules[mid], domain)
    assert bpy.ops.proteinblender.create_morphset(source=mid) == {'CANCELLED'}
    assert not C.sets(scene)


def test_member_eye_preserves_keys_and_output_across_scrubbing_and_rebuilds(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    row_id = morph[C.MORPH] + ':0'
    original = C.records(morph)[0]['object']
    assert _key(morph, 1, 0) == {'FINISHED'}
    assert _key(morph, 50, 3, [False]) == {'FINISHED'}
    keys = C.keyframes(scene)
    output = C.outputs(scene)[0]
    scene.frame_set(1)
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'FINISHED'}
    assert not C.member_visible(scene, row_id)
    for frame in (1, 25, 50, 75):
        scene.frame_set(frame)
        assert output.hide_viewport and output.hide_render
        assert original.hide_get() and original.hide_render
    assert C.keyframes(scene) == keys
    assert C.outputs(scene)[0] == output, 'The eye must not replace animated geometry'
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'FINISHED'}
    for frame in (1, 25, 50, 75):
        scene.frame_set(frame)
        assert output.hide_render == (frame >= 50)
        assert output.hide_viewport == (frame >= 50)
    scene.frame_set(1)
    assert bpy.ops.proteinblender.outliner_select(item_id=row_id) == {'FINISHED'}
    assert output.select_get() and bpy.context.view_layer.objects.active == output
    assert not original.select_get()
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'FINISHED'}
    assert _key(morph, 90, 7) == {'FINISHED'}
    scene.frame_set(90)
    assert C.outputs(scene)[0].hide_render
    C.compile_animation(bpy.context, {})
    assert original.hide_get() and original.hide_render
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'FINISHED'}
    assert not original.hide_get() and not original.hide_render and not original.hide_viewport
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row_id) == {'FINISHED'}
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=root[C.TAG]) == {'FINISHED'}
    assert original.hide_get() and original.hide_render
    assert 'pb_morphset_hidden' not in original
    restored = next(r for r in scene.outliner_items if r.item_type == 'CHAIN')
    assert bpy.ops.proteinblender.toggle_visibility(item_id=restored.item_id) == {'FINISHED'}
    assert not original.hide_get() and not original.hide_render and not original.hide_viewport


def test_member_edit_updates_visible_output_and_survives_new_keys(scene):
    from proteinblender.core.visual_style import get_object_style, get_object_color
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    row_id = morph[C.MORPH] + ':0'
    assert _key(morph, 1, 0) == {'FINISHED'}
    color = (.2, .6, .1, 1)
    assert bpy.ops.proteinblender.edit_morph_member(item_id=row_id, new_name='Ubiquitin chain',
        vs_style='spheres', vs_color=color) == {'FINISHED'}
    assert next(r for r in scene.outliner_items if r.item_id == row_id).name == 'Ubiquitin chain'
    for obj in (C.records(morph)[0]['object'], C.outputs(scene)[0]):
        assert get_object_style(obj) == 'spheres'
        np.testing.assert_allclose(get_object_color(obj), color)
    assert _key(morph, 45, 3) == {'FINISHED'}
    assert get_object_style(C.outputs(scene)[0]) == 'spheres'
    np.testing.assert_allclose(get_object_color(C.outputs(scene)[0]), color)
    before = C.keyframes(scene)
    assert bpy.ops.proteinblender.edit_morph_member(item_id=row_id, vs_style='cartoon') == {'FINISHED'}
    assert C.keyframes(scene) == before
    np.testing.assert_allclose(get_object_color(C.outputs(scene)[0]), color)
