"""Conformational playback uses residue correspondence and real deforming geometry."""
import json

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H
from proteinblender.core import conformation as C
from proteinblender.core import structural_alignment as A

pytestmark = pytest.mark.integration


def _pair(first='1ubq.pdb', second='1ubq.pdb'):
    return H.import_local(first, 'start'), H.import_local(second, 'end')


def _create(first, second, **kwargs):
    before = {o.name for o in C.transitions(bpy.context.scene)}
    assert bpy.ops.proteinblender.create_conformation(
        source_id=first, target_id=second, **kwargs) == {'FINISHED'}
    return next(o for o in C.transitions(bpy.context.scene) if o.name not in before)


def _coords(key):
    result = np.empty(len(key.data) * 3)
    key.data.foreach_get('co', result)
    return result.reshape(-1, 3)


def _raw_pdb_ca(filename, chain):
    import biotite.structure.io.pdb as pdb
    arr = pdb.PDBFile.read(H.data_path(filename)).get_structure(model=1)
    return arr.coord[(arr.chain_id == chain) & (arr.atom_name == 'CA') & ~arr.hetero]


def test_known_rigid_transform_has_no_conformational_motion(sm):
    first, second = _pair()
    source, target = sm.molecules[first], sm.molecules[second]
    original = A.positions(source.object).copy()
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    transformed = original @ rotation + [200, -75, 18]
    target.object.data.vertices.foreach_set('co', (transformed * .01).ravel())
    target.object.data.update()
    source.object.location = (4, -6, 12)
    source.object.rotation_euler = (.3, .7, 1.1)
    source.object.scale = (2, 2, 2)
    bpy.context.view_layer.update()
    displayed_source = H.evaluated_atom_positions(
        [source.object] + [d.object for d in source.domains.values()])
    assert len(displayed_source) > 100
    obj = _create(first, second, fit='ALL', smooth=False)
    keys = obj.data.shape_keys.key_blocks
    np.testing.assert_allclose(_coords(keys[0]), _coords(keys[1]), atol=1e-6)
    assert json.loads(obj['pb_match'])['rmsd'] < 1e-4
    assert obj.parent == source.object
    np.testing.assert_allclose(A.positions(source.object), original, atol=1e-6)
    np.testing.assert_allclose(A.positions(target.object), transformed, atol=1e-4)
    # Independent ground truth: the source atoms Blender displayed before
    # creation, not a second calculation with the product's pivot helper.
    original_ca = np.flatnonzero(np.asarray(source.working_array.atom_name) == 'CA')[0]
    expected = displayed_source[original_ca]
    transition_ca = next(i for i, a in enumerate(obj.data.attributes['is_alpha_carbon'].data) if a.value)
    actual = obj.matrix_world @ obj.data.vertices[transition_ca].co
    np.testing.assert_allclose(actual, expected, atol=1e-5)


def test_adenylate_kinase_matches_external_fit_and_endpoints(scene, sm):
    import biotite.structure as struc
    first, second = _pair('1ake.pdb', '4ake.pdb')
    obj = _create(first, second, source_chain='A', target_chain='A',
                  fit='ALL', start_frame=10, duration=2, smooth=False)
    report = json.loads(obj['pb_match'])
    fixed, moving = _raw_pdb_ca('1ake.pdb', 'A'), _raw_pdb_ca('4ake.pdb', 'A')
    fitted, _ = struc.superimpose(fixed, moving)
    assert report['residues'] == 214 and report['identity'] == 1
    assert report['mapping'] == ['A → A']
    assert report['rmsd'] == pytest.approx(float(struc.rmsd(fixed, fitted)), abs=1e-4)
    assert report['rmsd'] > 5
    assert len(obj.data.vertices) > 1600
    keys = obj.data.shape_keys.key_blocks
    a, b = _coords(keys[0]), _coords(keys[1])
    assert np.max(np.linalg.norm(a - b, axis=1)) > .1
    # Observe actual evaluated vertices with GN temporarily disabled, so this
    # checks Blender's shape-key evaluation, not the key values we inserted.
    obj.modifiers[0].show_viewport = False
    for frame, expected in ((obj['pb_start_frame'], a),
                            ((obj['pb_start_frame'] + obj['pb_end_frame']) // 2, (a + b) / 2),
                            (obj['pb_end_frame'], b)):
        scene.frame_set(frame)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        result = np.array([v.co[:] for v in evaluated.data.vertices])
        np.testing.assert_allclose(result, expected, atol=1e-6)
    obj.modifiers[0].show_viewport = True
    scene.frame_set(obj['pb_start_frame'])
    geometry_a = H.eval_positions(obj)
    scene.frame_set(obj['pb_end_frame'])
    geometry_b = H.eval_positions(obj)
    assert len(geometry_a) > 100 and len(geometry_b) > 100
    assert not np.allclose(np.mean(geometry_a, axis=0), np.mean(geometry_b, axis=0), atol=.0001)


def test_whole_protein_chains_and_visibility_lifecycle(scene, sm):
    first, second = _pair('4hhb.pdb', '4hhb.pdb')
    original_objects = list(scene.objects)
    original_objects[0].hide_render = True
    baseline = {o.name: (o.hide_get(), o.hide_render) for o in original_objects}
    obj = _create(first, second)
    assert json.loads(obj['pb_match'])['mapping'] == ['A → A', 'B → B', 'C → C', 'D → D']
    row = next(r for r in scene.outliner_items if r.item_type == 'TRANSITION')
    identifier = row.item_id
    assert row.parent_id == first
    assert all(o.hide_get() and o.hide_render for o in original_objects)
    selected = obj.select_get()
    assert bpy.ops.proteinblender.outliner_select(item_id=identifier) == {'FINISHED'}
    assert obj.select_get() != selected
    assert bpy.ops.proteinblender.toggle_visibility(item_id=identifier) == {'FINISHED'}
    assert obj.hide_get() and obj.hide_render
    other = _create(first, second)
    assert bpy.ops.proteinblender.delete_conformation(transition_id=identifier) == {'FINISHED'}
    assert all(o.hide_get() and o.hide_render for o in original_objects)
    assert bpy.ops.proteinblender.delete_conformation(transition_id=other[C.TAG]) == {'FINISHED'}
    assert {o.name: (o.hide_get(), o.hide_render) for o in original_objects} == baseline
    assert not any(r.item_type == 'TRANSITION' for r in scene.outliner_items)


def test_deleting_start_cascades_but_end_is_not_required_for_playback(scene):
    first, second = _pair()
    obj = _create(first, second)
    identifier = obj[C.TAG]
    assert bpy.ops.molecule.delete(molecule_id=second) == {'FINISHED'}
    assert C.find(scene, identifier) is not None
    assert bpy.ops.proteinblender.conformation_preview(transition_id=identifier, action='END') == {'FINISHED'}
    assert obj.data.shape_keys.key_blocks[1].value == pytest.approx(1)
    assert bpy.ops.molecule.delete(molecule_id=first) == {'FINISHED'}
    assert not C.transitions(scene)


def test_invalid_same_structure_and_mismatched_scope_leave_scene_untouched(scene):
    first, second = _pair()
    baseline = set(scene.objects)
    assert bpy.ops.proteinblender.create_conformation(source_id=first, target_id=first) == {'CANCELLED'}
    assert bpy.ops.proteinblender.create_conformation(source_id=first, target_id=second,
                                                     source_chain='A') == {'CANCELLED'}
    assert set(scene.objects) == baseline
    assert not any(o.get('pb_transition_visibility') for o in scene.objects)


def test_timing_style_update_and_preview_buttons(scene):
    first, second = _pair()
    obj = _create(first, second)
    identifier = obj[C.TAG]
    before = scene.frame_start, scene.frame_end
    assert bpy.ops.proteinblender.edit_conformation(
        transition_id=identifier, start_frame=50, duration=1.5, smooth=False,
        style='spheres', hide_originals=False) == {'FINISHED'}
    assert obj['pb_end_frame'] == 50 + round(1.5 * scene.render.fps / scene.render.fps_base)
    for action, value in [('END', 1), ('START', 0)]:
        assert bpy.ops.proteinblender.conformation_preview(transition_id=identifier, action=action) == {'FINISHED'}
        assert obj.data.shape_keys.key_blocks[1].value == pytest.approx(value)
    assert (scene.frame_start, scene.frame_end) == before
    assert obj['pb_transition_style'] == 'spheres'
    assert len(H.evaluated_atom_positions([obj])) > 100


@pytest.mark.parametrize('workflow', ['new', 'existing', 'reopened', 'style_switch', 'whole_protein'])
def test_cartoon_arrows_move_continuously_between_frames(scene, workflow):
    from scipy.spatial import cKDTree
    from proteinblender.utils.molecularnodes.blender.nodes import swap
    first, second = _pair('1ake.pdb', '4ake.pdb')
    previous_keys = set(bpy.data.shape_keys)
    chain = 'ALL' if workflow == 'whole_protein' else 'A'
    obj = _create(first, second, source_chain=chain, target_chain=chain, smooth=False)
    assert set(bpy.data.shape_keys) - previous_keys == {obj.data.shape_keys}
    tree = obj.modifiers[0].node_group
    style = next(n for n in tree.nodes if n.type == 'GROUP' and 'Style Cartoon' in n.node_tree.name)
    if workflow in ('existing', 'reopened'):
        # Recreate a transition saved before orientation stabilization existed.
        if workflow == 'reopened':
            # Blender drops unused original templates when saving a transition
            # that references its own copied renderer.
            style.node_tree['pb_cartoon_motion_version'] = 1
            bpy.data.node_groups.remove(bpy.data.node_groups['Style Cartoon'])
        else:
            swap(style, 'Style Cartoon')
        for attribute in list(obj.data.attributes):
            if attribute.name.startswith('pb_cartoon_'):
                obj.data.attributes.remove(attribute)
        for key in list(obj.data.keys()):
            if key.startswith('pb_cartoon_'):
                del obj.data[key]
        scene.frame_set(50)
        assert bpy.ops.proteinblender.edit_conformation(
            transition_id=obj[C.TAG], smooth=False) == {'FINISHED'}
    elif workflow == 'style_switch':
        for representation in ('spheres', 'surface', 'cartoon'):
            assert bpy.ops.proteinblender.edit_conformation(
                transition_id=obj[C.TAG], style=representation, smooth=False) == {'FINISHED'}
    keys = obj.data.shape_keys.key_blocks
    frames = obj['pb_end_frame'] - obj['pb_start_frame']
    atom_step = np.linalg.norm(_coords(keys[1]) - _coords(keys[0]), axis=1).max() / frames
    assert 0 < atom_step < .01  # Atoms move less than 1 Å per frame in either scope.
    scene.frame_set(obj['pb_start_frame'])
    previous = H.eval_positions(obj)
    assert len(previous) > 1000
    # Independent appearance control: the untouched bundled MN cartoon asset.
    # The correction should preserve the starting cartoon, including its arrows.
    control = tree.copy()
    try:
        style = next(n for n in control.nodes if n.type == 'GROUP' and 'Style Cartoon' in n.node_tree.name)
        swap(style, 'Style Cartoon')
        obj.modifiers[0].node_group = control
        original = H.eval_positions(obj)
        assert original.shape == previous.shape
        # A 180° correction permutes a rectangular profile's vertex indices
        # without changing its surface. Compare geometry, not that indexing.
        assert cKDTree(original).query(previous)[0].max() < 1e-6
        assert cKDTree(previous).query(original)[0].max() < 1e-6
    finally:
        obj.modifiers[0].node_group = tree
        bpy.data.node_groups.remove(control)
    beginning = previous.copy()
    observations = {obj['pb_start_frame']: beginning}
    worst = (0.0, 0)
    for frame in range(obj['pb_start_frame'] + 1, obj['pb_end_frame'] + 1):
        scene.frame_set(frame)
        current = H.eval_positions(obj)
        assert current.shape == previous.shape, 'Cartoon topology changed during playback'
        step = np.linalg.norm(current - previous, axis=1).max()
        worst = max(worst, (float(step), frame))
        if frame in (25, 37, 72):
            observations[frame] = current.copy()
        previous = current
    # A slowly moving backbone must not produce a several-Å arrow snap.
    # Compare actual evaluated vertices with the independent raw atom step.
    assert worst[0] < 2 * atom_step, f'Arrow jumped {worst[0] / .01:.2f} Å at frame {worst[1]}'
    assert np.linalg.norm(current - beginning, axis=1).max() > .1
    for frame in (72, 1, 37, 25):
        scene.frame_set(frame)
        np.testing.assert_allclose(H.eval_positions(obj), observations[frame], atol=1e-6)


def test_residue_renumbering_and_insertion_codes_keep_sequence_correspondence(tmp_path, sm):
    source = H.import_local('1ubq.pdb')
    lines = []
    for line in open(H.data_path('1ubq.pdb')):
        if line.startswith(('ATOM  ', 'HETATM')):
            res = int(line[22:26])
            # Insertion codes distinguish two neighbouring residues with the
            # same author number. The rest are uniformly renumbered.
            number, ins = (120, 'A') if res == 21 else (res + 100, ' ')
            line = line[:21] + 'Z' + f'{number:4d}' + ins + line[27:]
        lines.append(line)
    path = tmp_path / 'renumbered.pdb'
    path.write_text(''.join(lines))
    before = set(sm.molecules)
    assert bpy.ops.molecule.import_local(filepath=str(path)) == {'FINISHED'}
    target = (set(sm.molecules) - before).pop()
    obj = _create(source, target, fit='ALL')
    info = json.loads(obj['pb_match'])
    assert info['residues'] == 76
    assert info['rmsd'] < 1e-5
    assert info['residue_pairs'][20] == [['A', 21, ''], ['Z', 120, 'A']]
    saved = json.loads(sm.molecules[target].object.data[A.IDENTITY_KEY])
    assert 'A' in saved['insertion']


def test_missing_residues_and_mutation_omit_unmatched_atoms(tmp_path, sm):
    first = H.import_local('1ubq.pdb', 'complete')
    lines = []
    for line in open(H.data_path('1ubq.pdb')):
        if line.startswith(('ATOM  ', 'HETATM')):
            res, atom = int(line[22:26]), line[12:16].strip()
            if res in (36, 37, 38, 39):
                continue
            if res == 54:
                if atom not in {'N', 'CA', 'C', 'O', 'CB'}:
                    continue
                line = line[:17] + 'ALA' + line[20:]
        if not line.startswith('CONECT'):
            lines.append(line)
    path = tmp_path / 'partial_mutant.pdb'
    path.write_text(''.join(lines))
    before = set(sm.molecules)
    assert bpy.ops.molecule.import_local(filepath=str(path)) == {'FINISHED'}
    second = (set(sm.molecules) - before).pop()
    obj = _create(first, second, fit='ALL')
    report = json.loads(obj['pb_match'])
    assert report['residues'] == 72
    assert report['source_residues'] == 76 and report['target_residues'] == 72
    assert report['rmsd'] < 1e-5
    assert not {36, 37, 38, 39}.intersection(v.value for v in obj.data.attributes['res_id'].data)
    residue = obj.data.attributes['res_id'].data
    atoms = obj.data.attributes['atom_name'].data
    assert {atoms[i].value for i, r in enumerate(residue) if r.value == 54} == {1, 2, 3, 4}
    # Atom order remains correct after mesh subsetting; a wrong pairing here
    # would move atoms despite the input coordinates being identical.
    np.testing.assert_allclose(_coords(obj.data.shape_keys.key_blocks[0]),
                               _coords(obj.data.shape_keys.key_blocks[1]), atol=1e-6)


@pytest.mark.visual
@pytest.mark.parametrize('representation', ['cartoon', 'surface'])
def test_render_observes_transition_at_three_frames(tmp_path, scene, representation):
    first, second = _pair('1ake.pdb', '4ake.pdb')
    obj = _create(first, second, source_chain='A', target_chain='A', smooth=False)
    assert bpy.ops.proteinblender.edit_conformation(
        transition_id=obj[C.TAG], style=representation, smooth=False) == {'FINISHED'}
    assert obj['pb_transition_style'] == representation
    cam_data = bpy.data.cameras.new('Transition render camera')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = 1.1
    camera = bpy.data.objects.new('Transition render camera', cam_data)
    scene.collection.objects.link(camera)
    # Molecular fixture fits well within a 1.1 Blender-unit square; this view
    # includes both endpoints and the moving lid without refitting the camera.
    camera.location = (0, -2, .2)
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = camera
    assert bpy.ops.proteinblender.setup_lighting(preview=False) == {'FINISHED'}
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 4
    scene.cycles.device = 'CPU'
    scene.render.resolution_x = scene.render.resolution_y = 192
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    images = []
    for frame in (obj['pb_start_frame'], (obj['pb_start_frame'] + obj['pb_end_frame']) // 2,
                  obj['pb_end_frame']):
        scene.frame_set(frame)
        scene.render.filepath = str(tmp_path / f'transition-{frame}.png')
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath)
        pixels = np.asarray(image.pixels[:]).reshape(-1, 4)
        assert np.count_nonzero(pixels[:, 3] > .5) > 150
        covered = pixels[:, 3] > .95
        assert pixels[covered, 2].mean() > pixels[covered, 0].mean() * 1.1, 'Transition should render its blue color'
        images.append(pixels)
        bpy.data.images.remove(image)
    for a, b in zip(images, images[1:]):
        assert np.count_nonzero(np.abs(a[:, 3] - b[:, 3]) > .5) > 100
    assert bpy.ops.proteinblender.edit_conformation(
        transition_id=obj[C.TAG], style=representation,
        color=(.9, .1, .1, 1.0)) == {'FINISHED'}
    scene.render.filepath = str(tmp_path / 'transition-red.png')
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath)
    pixels = np.asarray(image.pixels[:]).reshape(-1, 4)
    covered = pixels[:, 3] > .95
    assert covered.sum() > 150
    assert pixels[covered, 0].mean() > pixels[covered, 2].mean() * 1.1
    bpy.data.images.remove(image)


def test_stable_core_never_fits_fewer_than_half_the_pairs(sm):
    first, second = _pair('1ake.pdb', '1ake.pdb')
    target = sm.molecules[second].object
    points = np.array([v.co[:] for v in target.data.vertices])
    points += np.random.default_rng(42).normal(0, .2, points.shape)
    target.data.vertices.foreach_set('co', points.ravel())
    target.data.update()
    obj = _create(first, second, source_chain='A', target_chain='A')
    report = json.loads(obj['pb_match'])
    assert report['residues'] == 214
    assert report['fit_residues'] >= 107
