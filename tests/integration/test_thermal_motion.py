"""B-factor motion must preserve the visible cartoon and scale predictably."""
import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration


def _cartoon(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        points = np.empty((len(mesh.vertices), 3))
        mesh.vertices.foreach_get('co', points.ravel())
        return points, (len(mesh.vertices), len(mesh.edges), len(mesh.polygons))
    finally:
        evaluated.to_mesh_clear()


def test_cartoon_motion_preserves_ribbons(scene, sm, single_chain):
    """Ordinary 1UBQ must keep its ribbon faces throughout a jiggle cycle."""
    obj = next(iter(sm.molecules[single_chain].domains.values())).object
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_style='cartoon') == {'FINISHED'}
    reference, topology = _cartoon(obj)
    assert len(reference) > 100
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, bfactor_motion=True) == {'FINISHED'}
    frames = {}
    for frame in range(1, 49):
        scene.frame_set(frame)
        points, current = _cartoon(obj)
        frames[frame] = current
    assert set(frames.values()) == {topology}, (
        f'B-factor motion removes/recreates cartoon geometry: rest={topology}, frames={frames}')
    assert np.max(np.abs(points - reference)) > 1e-4


@pytest.mark.parametrize('intensity', [0.2, 5.0])
def test_all_chains_keep_cartoon_geometry_at_adjusted_intensity(scene, sm, multi_chain, intensity):
    objects = [d.object for d in sm.molecules[multi_chain].domains.values()]
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=multi_chain, vs_style='cartoon') == {'FINISHED'}
    rest = [_cartoon(obj)[1] for obj in objects]
    assert all(topology[0] > 100 for topology in rest)
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=multi_chain,
        bfactor_motion=True, bfactor_intensity=intensity) == {'FINISHED'}
    for frame in (1, 4, 8, 13, 21, 32, 48):
        scene.frame_set(frame)
        assert [_cartoon(obj)[1] for obj in objects] == rest


def test_intensity_scales_atoms_and_survives_toggle_style_and_split(scene, sm, single_chain):
    """Compare actual atom displacement against 0x, 0.25x and 2x motion."""
    import json
    from proteinblender.core.thermal_motion import NAME
    mol = sm.molecules[single_chain]
    obj = next(iter(mol.domains.values())).object
    scene.frame_set(7)
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, bfactor_motion=True, bfactor_intensity=0) == {'FINISHED'}
    for mod in obj.modifiers:
        if mod.name != NAME:
            mod.show_viewport = False
    rest = H.eval_positions(obj)
    assert len(rest) > 500
    samples = {}
    for value in (.25, 1, 2, 0):
        assert bpy.ops.proteinblender.edit_protein_visuals(
            item_id=single_chain, bfactor_intensity=value) == {'FINISHED'}
        bpy.context.view_layer.update()
        samples[value] = H.eval_positions(obj) - rest
    assert np.max(np.abs(samples[1])) > 1e-4
    np.testing.assert_allclose(samples[.25], samples[1] * .25, atol=1e-7)
    np.testing.assert_allclose(samples[2], samples[1] * 2, atol=1e-7)
    np.testing.assert_allclose(samples[0], 0, atol=1e-7)
    # Disabled settings retain the user's intensity, including script edits
    # that only mention style or intensity (never accidentally toggle motion).
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain,
        bfactor_motion=False, bfactor_intensity=.25) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, vs_style='cartoon') == {'FINISHED'}
    assert not obj.modifiers.get(NAME)
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=single_chain, bfactor_motion=True) == {'FINISHED'}
    np.testing.assert_allclose(H.eval_positions(obj) - rest, samples[.25], atol=1e-7)
    chain = next(r for r in scene.outliner_items if r.item_type == 'CHAIN')
    assert bpy.ops.proteinblender.edit_chain_domains(item_id=chain.item_id,
        layout_json=json.dumps([dict(name='First', start=1, end=38),
                                dict(name='Second', start=39, end=134)])) == {'FINISHED'}
    from proteinblender.utils.gn_compat import read_modifier_socket
    assert len(mol.domains) == 2
    for domain in mol.domains.values():
        mod = domain.object.modifiers[NAME]
        socket = next(s for s in mod.node_group.interface.items_tree if s.name == 'Intensity')
        assert read_modifier_socket(mod, socket.identifier) == pytest.approx(.25)


def test_real_backbone_gap_stays_open(scene, sm, tmp_path):
    """A missing stretch must not be joined just to prevent thermal flicker."""
    from pathlib import Path
    source = Path(H.data_path('1ubq.pdb')).read_text().splitlines()
    # Remove the middle of the long helix, leaving a genuine imported gap.
    path = tmp_path / 'gapped.pdb'
    path.write_text('\n'.join(line for line in source if not (
        line.startswith(('ATOM  ', 'HETATM')) and 28 <= int(line[22:26]) <= 32)) + '\n')
    assert bpy.ops.molecule.import_local(filepath=str(path), identifier_override='Gapped') == {'FINISHED'}
    obj = next(iter(sm.molecules['Gapped'].domains.values())).object
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id='Gapped', vs_style='cartoon') == {'FINISHED'}
    baseline = _cartoon(obj)[1]
    assert baseline[0] > 100
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id='Gapped',
        bfactor_motion=True, bfactor_intensity=5) == {'FINISHED'}
    for frame in (1, 8, 17, 32):
        scene.frame_set(frame)
        assert _cartoon(obj)[1] == baseline


def test_intensity_updates_morph_output_without_rebuilding_keys(scene, sm):
    from test_model_morphsets import make
    from test_morphsets import _key
    from proteinblender.core import morphsets as C
    mid = H.import_local('1d3z.pdb.gz', 'Models')
    mol = sm.molecules[mid]
    # NMR models have zero B values. Supply explicit synthetic factors to
    # isolate how the control combines thermal and imported-model motion.
    for mesh in [mol.object.data] + [s.mesh for s in mol.object.pb_conformations.states]:
        attr = mesh.attributes.get('b_factor') or mesh.attributes.new('b_factor', 'FLOAT', 'POINT')
        attr.data.foreach_set('value', np.full(len(mesh.vertices), 20.0))
        mesh.update()
    root, morph = make(mid)
    for frame, model in ((1, 0), (45, 3), (90, 7)):
        assert _key(morph, frame, model) == {'FINISHED'}
    scene.frame_set(20)
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid,
        vs_style='spheres', bfactor_motion=True, bfactor_intensity=0) == {'FINISHED'}
    obj = C.outputs(scene)[0]
    rest = H.evaluated_atom_positions([obj])
    assert len(rest) > 1000
    keys, action = C.keyframes(scene), obj.data.shape_keys.animation_data.action
    samples = {}
    for value in (.25, 1, 2):
        assert bpy.ops.proteinblender.edit_protein_visuals(
            item_id=mid, bfactor_intensity=value) == {'FINISHED'}
        bpy.context.view_layer.update()
        assert C.outputs(scene)[0] == obj
        assert C.keyframes(scene) == keys
        assert obj.data.shape_keys.animation_data.action == action
        samples[value] = H.evaluated_atom_positions([obj]) - rest
    assert np.max(np.abs(samples[1])) > 1e-4
    np.testing.assert_allclose(samples[.25], samples[1] * .25, atol=1e-7)
    np.testing.assert_allclose(samples[2], samples[1] * 2, atol=1e-7)
    assert _key(morph, 60, 5) == {'FINISHED'}  # Rebuilt outputs inherit the dial.
    obj = C.outputs(scene)[0]
    from proteinblender.utils.gn_compat import read_modifier_socket
    mod = obj.modifiers['PB Temperature Motion']
    socket = next(s for s in mod.node_group.interface.items_tree if s.name == 'Intensity')
    assert read_modifier_socket(mod, socket.identifier) == pytest.approx(2)
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon',
        bfactor_intensity=0) == {'FINISHED'}
    # Compare with the same conformation without jiggle, at each model frame.
    for frame in (1, 20, 45, 60, 90):
        scene.frame_set(frame)
        obj = C.outputs(scene)[0]
        bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, bfactor_intensity=0)
        reference = _cartoon(obj)[1]
        bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, bfactor_intensity=2)
        assert _cartoon(obj)[1] == reference


def test_legacy_enabled_motion_is_upgraded_on_load(scene, sm, single_chain):
    from proteinblender.core import thermal_motion as T, cartoon_motion as C
    from proteinblender.core.visual_style import find_style_node
    from proteinblender.utils.molecularnodes.blender.nodes import swap
    from proteinblender.handlers.load_handlers import restore_temperature_motion_on_load
    mol = sm.molecules[single_chain]
    obj = next(iter(mol.domains.values())).object
    bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain, vs_style='cartoon')
    baseline = _cartoon(obj)[1]
    bpy.ops.proteinblender.edit_protein_visuals(item_id=single_chain, bfactor_motion=True)
    # Reconstruct the previous release's node graph and missing settings.
    tree = bpy.data.node_groups[T.NAME]
    for name in ('Intensity', 'Rest Position', 'Store Rest Position'):
        tree.nodes.remove(tree.nodes[name])
    socket = next(s for s in tree.interface.items_tree if s.name == 'Intensity')
    tree.interface.remove(socket)
    del tree['pb_thermal_version']
    tree.links.new(tree.nodes['Amplitude'].outputs['Attribute'], tree.nodes['Scale'].inputs['Scale'])
    tree.links.new(tree.nodes['Input'].outputs['Geometry'], tree.nodes['Move'].inputs['Geometry'])
    for target in (mol.object, obj):
        swap(find_style_node(target), 'Style Cartoon')
    del mol.object[T.INTENSITY]
    del mol.object.data[C.VERSION]
    assert restore_temperature_motion_on_load in bpy.app.handlers.load_post
    restore_temperature_motion_on_load(None)
    frames = []
    for frame in (1, 8, 17, 32):
        scene.frame_set(frame)
        points, topology = _cartoon(obj)
        assert topology == baseline
        frames.append(points)
    assert np.max(np.abs(frames[1] - frames[0])) > 1e-4, 'Upgrade silently stopped existing motion'


def test_nucleic_cartoon_can_enable_motion_without_peptide_backbone(scene, sm):
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / 'proteinblender/dna_builder/data/1BNA.pdb'
    assert bpy.ops.molecule.import_local(filepath=str(source), identifier_override='DNA') == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id='DNA', vs_style='cartoon') == {'FINISHED'}
    objects = [d.object for d in sm.molecules['DNA'].domains.values()]
    assert sum(len(H.eval_positions(o)) for o in objects) > 100
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id='DNA', bfactor_motion=True) == {'FINISHED'}
    for frame in (1, 8):
        scene.frame_set(frame)
        assert sum(len(H.eval_positions(o)) for o in objects) > 100
