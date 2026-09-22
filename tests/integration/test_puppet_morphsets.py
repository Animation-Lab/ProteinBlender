"""Morphsets are persistent puppet components; model keys remain independent."""
import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import morphsets as C, model_morphsets as M
from proteinblender.panels.group_maker_panel import PROTEINBLENDER_OT_create_puppet as Create
from test_model_morphsets import make
from test_morphsets import _key, _row

pytestmark = pytest.mark.integration


def row(uid):
    return next(r for r in bpy.context.scene.outliner_items if r.item_id == uid)


def puppet(ids, name='Moving complex'):
    for item in bpy.context.scene.outliner_items:
        item.is_selected = item.item_id in ids
    assert bpy.ops.proteinblender.create_puppet(puppet_name=name) == {'FINISHED'}
    return next(r.item_id for r in bpy.context.scene.outliner_items
                if r.item_type == 'PUPPET' and r.name == name)


def atoms(morph):
    objects = C.outputs(bpy.context.scene, morph[C.MORPH])
    if not objects:
        objects = [m['object'] for m in C.records(morph)]
    points = H.evaluated_atom_positions(objects)
    assert len(points) > 100, 'Must observe actual atom geometry'
    return points


@pytest.mark.parametrize('animated', [False, True])
def test_create_morphset_puppet_moves_real_geometry_and_retains_hierarchy(scene, animated):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    if animated:
        _key(morph, 1, 0)
        _key(morph, 45, 3)
        scene.frame_set(23)
    before = atoms(morph)
    uid = root[C.TAG]
    assert Create._is_valid_puppet_item(row(uid)), 'Morphsets must be offered as puppet components'
    pid = puppet([uid])
    controller = bpy.data.objects[row(pid).controller_object_name]
    assert root.parent == controller
    np.testing.assert_allclose(atoms(morph), before, atol=1e-6)
    controller.location.x += 2
    bpy.context.view_layer.update()
    np.testing.assert_allclose(atoms(morph), before + (2, 0, 0), atol=1e-6)
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    assert row(pid).puppet_memberships == uid
    assert row(uid).puppet_memberships == pid
    ref = row(pid + '_ref_' + uid)
    assert ref.reference_target_id == uid
    assert any(r.parent_id == ref.item_id and r.item_type == 'MORPH_MEMBER'
               for r in scene.outliner_items)


def test_edit_adds_and_removes_animated_morphset_without_moving_atoms(scene):
    mid = H.import_local('1ubq.pdb', 'Companion')
    chain = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN' and r.parent_id == mid)
    pid = puppet([chain])
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    _key(morph, 1, 0)
    _key(morph, 45, 3)
    scene.frame_set(23)
    before, parent = atoms(morph), root.parent
    controller = bpy.data.objects[row(pid).controller_object_name]
    controller.location = (2, 3, 4)
    controller.rotation_euler.z = .4
    controller.scale = (1.2, 1.2, 1.2)
    bpy.context.view_layer.update()
    assert bpy.ops.proteinblender.edit_puppet(action='EDIT', puppet_id=pid,
        new_name='Complex', member_ids=chain + ',' + root[C.TAG]) == {'FINISHED'}
    assert root[C.TAG] in row(pid).puppet_memberships, 'Rebuilding must not discard Morphset membership'
    assert root.parent == controller, 'Editing must actually parent new members'
    np.testing.assert_allclose(atoms(morph), before, atol=1e-6)
    controller.location.y += 2
    bpy.context.view_layer.update()
    moved = atoms(morph)
    np.testing.assert_allclose(moved, before + (0, 2, 0), atol=1e-6)
    assert bpy.ops.proteinblender.edit_puppet(action='EDIT', puppet_id=pid,
        new_name='Complex', member_ids=chain) == {'FINISHED'}
    assert root.parent == parent
    np.testing.assert_allclose(atoms(morph), moved, atol=1e-6)


def test_morph_children_cannot_be_detached_into_a_puppet(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    child = next(r for r in scene.outliner_items if r.item_type == 'MORPH_MEMBER')
    assert not Create._is_valid_puppet_item(child), 'Puppet the whole Morphset, not its hidden source'


def test_puppet_edit_rejects_already_owned_morphset_without_mutation(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    pid = puppet([root[C.TAG]], 'First')
    mid = H.import_local('1ubq.pdb', 'Companion')
    chain = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN' and r.parent_id == mid)
    other = puppet([chain], 'Second')
    with pytest.raises(RuntimeError, match='already in'):
        bpy.ops.proteinblender.edit_puppet(action='EDIT', puppet_id=other,
            new_name='Must not change', member_ids=chain + ',' + root[C.TAG])
    assert row(other).name == 'Second' and row(other).puppet_memberships == chain
    assert root.parent == bpy.data.objects[row(pid).controller_object_name]


def test_puppet_visibility_reaches_morph_members_and_survives_new_keys(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    _key(morph, 1, 0)
    _key(morph, 45, 3)
    pid = puppet([root[C.TAG]])
    assert bpy.ops.proteinblender.toggle_visibility(item_id=pid) == {'FINISHED'}
    for frame in (1, 23, 45):
        scene.frame_set(frame)
        assert all(o.hide_render and o.hide_viewport for o in C.outputs(scene))
    _key(morph, 90, 7)
    assert all(o.hide_render for o in C.outputs(scene))
    assert bpy.ops.proteinblender.toggle_visibility(item_id=pid) == {'FINISHED'}
    assert all(not o.hide_render for o in C.outputs(scene))
    assert all(m['object'].hide_get() for m in C.records(morph))


def test_delete_puppet_restores_morphset_parent_and_retains_animation(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    original_parent = root.parent
    _key(morph, 1, 0)
    _key(morph, 45, 3)
    pid = puppet([root[C.TAG]])
    controller = bpy.data.objects[row(pid).controller_object_name]
    controller.location = (3, 4, 5)
    controller.rotation_euler.z = .6
    controller.scale = (1.3, 1.3, 1.3)
    scene.frame_set(23)
    before, keys = atoms(morph), C.keyframes(scene)
    assert bpy.ops.proteinblender.delete_puppet(puppet_id=pid) == {'FINISHED'}
    assert root.parent == original_parent and not row(root[C.TAG]).puppet_memberships
    np.testing.assert_allclose(atoms(morph), before, atol=1e-6)
    assert C.keyframes(scene) == keys
    _key(morph, 90, 7)
    scene.frame_set(23)
    np.testing.assert_allclose(atoms(morph), before, atol=1e-6)


def test_two_morphsets_with_chain_puppet_keys_and_model_rebuilds(scene):
    from mathutils import Matrix
    from proteinblender.utils.chain_utils import get_puppet_member_objects
    from proteinblender.panels.pose_library_panel import get_puppet_objects
    a, ma = make(H.import_local('1d3z.pdb.gz', 'A'), name='A models')
    b, mb = make(H.import_local('1d3z.pdb.gz', 'B'), name='B models')
    mid = H.import_local('1ubq.pdb', 'Companion')
    chain = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN' and r.parent_id == mid)
    for morph, last in ((ma, 3), (mb, 7)):
        _key(morph, 1, 0)
        _key(morph, 45, last)
    baseline = {}
    for frame in (1, 23, 45):
        scene.frame_set(frame)
        baseline[frame] = [atoms(m).copy() for m in (ma, mb)]
    pid = puppet([a[C.TAG], b[C.TAG], chain])
    controller = bpy.data.objects[row(pid).controller_object_name]
    initial = controller.matrix_world.copy()
    target = Matrix.Translation((2, 3, 4)) @ Matrix.Rotation(.7, 4, 'Z') @ Matrix.Scale(1.4, 4)
    settings = dict(name="", item_kind='PUPPET', brownian_enabled=False,
                    puppet_id=pid, puppet_name=row(pid).name,
                    controller_object_name=controller.name, use_puppet=True,
                    keyframe_location=True, keyframe_rotation=True,
                    keyframe_scale=True, keyframe_pose=True, keyframe_color=False)
    # Puppet pose targets must be persistent controllers, not rebuilt meshes.
    members = get_puppet_member_objects(scene, H.sm(), row(pid))
    assert a in members and b in members and len(members) == 3
    assert get_puppet_objects(bpy.context, pid) == members
    for frame, matrix in ((1, initial), (45, target)):
        scene.frame_set(frame)
        controller.matrix_world = matrix
        bpy.context.view_layer.update()
        assert bpy.ops.proteinblender.create_keyframe(frame_number=frame,
            puppet_items=[settings], morph_items=[_row(ma, 0 if frame == 1 else 3),
                                                 _row(mb, 0 if frame == 1 else 7)]) == {'FINISHED'}
    for frame in (1, 23, 45):
        scene.frame_set(frame)
        transform = np.asarray(controller.matrix_world @ initial.inverted())
        for index, morph in enumerate((ma, mb)):
            points = baseline[frame][index]
            np.testing.assert_allclose(atoms(morph), points @ transform[:3, :3].T + transform[:3, 3], atol=1e-6)
    scene.frame_set(23)
    before = atoms(ma)
    _key(ma, 90, 8)
    scene.frame_set(23)
    np.testing.assert_allclose(atoms(ma), before, atol=1e-6)
    assert a.parent == controller and b.parent == controller


def test_delete_morphset_keeps_released_chains_in_puppet(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    _key(morph, 1, 0)
    pid = puppet([root[C.TAG]])
    controller = bpy.data.objects[row(pid).controller_object_name]
    controller.location = (2, 3, 4)
    bpy.context.view_layer.update()
    original = C.records(morph)[0]['object']
    matrix = M.world_matrix(original)
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=root[C.TAG]) == {'FINISHED'}
    assert original.parent == controller
    np.testing.assert_allclose(original.matrix_world, matrix, atol=1e-6)
    members = row(pid).puppet_memberships.split(',')
    assert members and all(row(uid).item_type in {'CHAIN', 'DOMAIN'} for uid in members)


def test_domain_morphset_mixed_with_ordinary_domain_and_member_controls(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'Domains')
    assert H.split_domain_from_outliner(mid, 'A', 1, 38) == {'FINISHED'}
    domains = sorted(sm.molecules[mid].domains.values(), key=lambda d: d.start)
    ids = [next(uid for uid, d in sm.molecules[mid].domains.items() if d.object == domain.object)
           for domain in domains]
    root, morph = make(mid, ids=ids[:1])
    pid = puppet([root[C.TAG], ids[1]])
    _key(morph, 1, 0)
    _key(morph, 45, 3)
    scene.frame_set(23)
    before = atoms(morph)
    controller = bpy.data.objects[row(pid).controller_object_name]
    controller.location.z += 2
    bpy.context.view_layer.update()
    np.testing.assert_allclose(atoms(morph), before + (0, 0, 2), atol=1e-6)
    member_id = morph[C.MORPH] + ':0'
    assert bpy.ops.proteinblender.edit_morph_member(item_id=member_id, new_name='Moving domain',
        vs_style='cartoon', vs_color=(.2, .7, .3, 1)) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, bfactor_motion=True) == {'FINISHED'}
    from proteinblender.core.visual_style import get_object_style, get_object_color
    assert get_object_style(C.outputs(scene)[0]) == 'cartoon'
    assert bpy.ops.proteinblender.edit_morph_member(item_id=member_id, new_name='Moving domain',
        vs_style='spheres', vs_color=(.2, .7, .3, 1)) == {'FINISHED'}
    _key(morph, 90, 7)
    assert get_object_style(C.outputs(scene)[0]) == 'spheres'
    np.testing.assert_allclose(get_object_color(C.outputs(scene)[0]), (.2, .7, .3, 1), atol=1e-6)
    ref_id = pid + '_ref_' + member_id
    assert bpy.ops.proteinblender.outliner_select(item_id=ref_id) == {'FINISHED'}
    assert bpy.context.view_layer.objects.active == C.outputs(scene)[0]
    assert root.parent == controller


def test_partial_chain_cannot_pull_a_domain_out_of_its_morphset(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'Domains')
    assert H.split_domain_from_outliner(mid, 'A', 1, 38) == {'FINISHED'}
    uid = min(sm.molecules[mid].domains, key=lambda i: sm.molecules[mid].domains[i].start)
    root, morph = make(mid, ids=[uid])
    chain = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN' and r.parent_id == mid)
    with pytest.raises(RuntimeError, match='Morphset'):
        puppet([chain])
    assert C.records(morph)[0]['object'].parent == root


def test_removing_puppet_with_pose_keys_keeps_morphset_placement_on_scrub(scene):
    root, morph = make(H.import_local('1d3z.pdb.gz', '1D3Z'))
    pid = puppet([root[C.TAG]])
    controller = bpy.data.objects[row(pid).controller_object_name]
    settings = dict(name='', item_kind='PUPPET', brownian_enabled=False,
                    puppet_id=pid, puppet_name=row(pid).name, controller_object_name=controller.name,
                    use_puppet=True, keyframe_location=True, keyframe_rotation=True,
                    keyframe_scale=True, keyframe_pose=True, keyframe_color=False)
    for frame, model in ((1, 0), (45, 3)):
        scene.frame_set(frame)
        controller.location = (2, 3, 4)
        bpy.context.view_layer.update()
        assert bpy.ops.proteinblender.create_keyframe(frame_number=frame,
            puppet_items=[settings], morph_items=[_row(morph, model)]) == {'FINISHED'}
    scene.frame_set(23)
    before = atoms(morph)
    assert bpy.ops.proteinblender.delete_puppet(puppet_id=pid) == {'FINISHED'}
    scene.frame_set(1)
    scene.frame_set(23)
    np.testing.assert_allclose(atoms(morph), before, atol=1e-6)
    pid = puppet([root[C.TAG]], 'New puppet')
    controller = bpy.data.objects[row(pid).controller_object_name]
    controller.location.x += 2
    bpy.context.view_layer.update()
    scene.frame_set(1)
    scene.frame_set(23)
    np.testing.assert_allclose(atoms(morph), before + (2, 0, 0), atol=1e-6)
