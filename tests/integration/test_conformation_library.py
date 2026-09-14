"""Public library actions against deposited ensembles and rendered atom geometry."""
import gzip
from pathlib import Path

import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import conformation_library as L
from proteinblender.core import conformation as C
from proteinblender.core import structural_alignment as A

pytestmark = pytest.mark.integration


def ensemble(filename='1d3z.pdb.gz'):
    mid = H.import_local(filename, 'ensemble')
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    mol = ProteinBlenderScene.get_instance().molecules[mid]
    assert bpy.ops.proteinblender.browse_conformations(molecule_id=mid) == {'FINISHED'}
    return mol, mol.object.pb_conformations


def original_models():
    import io
    from biotite.structure.io import pdb
    return pdb.PDBFile.read(io.StringIO(gzip.decompress(Path(H.data_path('1d3z.pdb.gz')).read_bytes()).decode())).get_structure()


def test_popup_apply_targets_its_protein_and_rejects_invalid_fit_atomically(scene, sm):
    mol, library = ensemble()
    other_id = H.import_local('1ubq.pdb', 'unrelated')
    other = sm.molecules[other_id]
    untouched = L.read_mesh(other.object.data).copy()
    scene.frame_set(119)
    # The active object and browser context can both point elsewhere.
    bpy.context.view_layer.objects.active = other.object
    scene.pb_conformation_browser = other_id
    args = dict(molecule_id=mol.identifier, state_uid=library.states[7].uid,
                target_uid=library.states[9].uid, reference_uid=library.states[0].uid,
                fit='NONE')
    assert bpy.ops.proteinblender.apply_conformation_view(**args) == {'FINISHED'}
    np.testing.assert_allclose(L.read_mesh(mol.object.data), original_models()[7].coord * .01, atol=1e-7)
    np.testing.assert_array_equal(L.read_mesh(other.object.data), untouched)
    assert library.start_uid == library.states[7].uid and library.end_uid == library.states[9].uid
    assert scene.frame_current == 119
    shown = L.read_mesh(mol.object.data).copy()
    args.update(state_uid=library.states[5].uid, fit='REGION', fit_region='A:999-1000')
    assert bpy.ops.proteinblender.apply_conformation_view(**args) == {'CANCELLED'}
    assert library.active_index == 7 and library.fit == 'NONE'
    assert library.start_uid == library.states[7].uid
    np.testing.assert_array_equal(L.read_mesh(mol.object.data), shown)
    np.testing.assert_array_equal(L.read_mesh(other.object.data), untouched)
    library.show_comparison = True
    assert any(o.get('pb_state_preview_owner') == mol.object for o in scene.objects)
    # Confirmation closes even when execution fails. It must clean up only
    # its own helpers and preserve the previous Apply and unrelated browser.
    assert bpy.ops.proteinblender.browse_conformations(**args) == {'CANCELLED'}
    assert not library.show_comparison
    assert not any(o.get('pb_state_preview_owner') == mol.object for o in scene.objects)
    assert scene.pb_conformation_browser == other_id
    np.testing.assert_array_equal(L.read_mesh(mol.object.data), shown)


@pytest.mark.parametrize('filename', ['1d3z.pdb.gz', '1d3z.cif.gz'])
def test_deposited_ensemble_import_and_exact_switch(filename, scene):
    mol, library = ensemble(filename)
    assert len(library.states) == 10
    assert [s.model for s in library.states] == [str(i) for i in range(1, 11)]
    assert 'NMR' in library.method
    assert len([r for r in scene.outliner_items if r.item_type == 'PROTEIN']) == 1
    raw = original_models()
    library.fit = 'NONE'
    scene.frame_set(147)
    transforms = {o.name: o.matrix_world.copy() for o in [mol.object] + [d.object for d in mol.domains.values()]}
    for index in (9, 1, 0):
        assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=index) == {'FINISHED'}
        np.testing.assert_allclose(L.read_mesh(mol.object.data), raw[index].coord * .01, atol=1e-7)
        assert scene.frame_current == 147
        assert all(bpy.data.objects[n].matrix_world == m for n, m in transforms.items())
        # The displayed chain must use the chosen coordinates, not MN's old
        # scene-time interpolation from its original frame collection.
        displayed = H.evaluated_atom_positions([d.object for d in mol.domains.values()])
        from scipy.spatial import cKDTree
        from proteinblender.core.domain_space import get_pivot
        expected = (L.read_mesh(mol.object.data) - np.asarray(get_pivot(mol.object)))
        expected = expected @ np.asarray(mol.object.matrix_world)[:3, :3].T + np.asarray(mol.object.matrix_world)[:3, 3]
        assert len(displayed) == len(expected)
        assert cKDTree(expected).query(displayed)[0].max() < 2e-5


def test_reference_alignment_is_stable_and_originals_immutable(scene):
    mol, library = ensemble()
    baseline = [L.read_mesh(s.mesh).copy() for s in library.states]
    library.fit = 'ALL'
    assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=5) == {'FINISHED'}
    shown = L.read_mesh(mol.object.data).copy()
    for index in (2, 8, 1, 5):
        assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=index) == {'FINISHED'}
    np.testing.assert_array_equal(L.read_mesh(mol.object.data), shown)
    for item, before in zip(library.states, baseline):
        np.testing.assert_array_equal(L.read_mesh(item.mesh), before)
    library.fit_region = 'A:1-20'
    library.fit = 'REGION'
    assert not library.error
    old = L.read_mesh(mol.object.data).copy()
    library.fit_region = 'A:999-1000'
    assert library.error
    np.testing.assert_array_equal(L.read_mesh(mol.object.data), old)


def test_legacy_assembly_models_are_simultaneous_copies(scene):
    mid = H.import_local('1out.pdb1.gz', 'assembly_copies')
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    mol = ProteinBlenderScene.get_instance().molecules[mid]
    assert len(mol.object.pb_conformations.states) == 1
    assert len(mol.domains) == 4
    assert set(A.read_identity(mol).chain) == {'A_1', 'B_1', 'A_2', 'B_2'}


def test_ambiguous_file_needs_explicit_model_interpretation(tmp_path, sm):
    text = gzip.decompress(Path(H.data_path('1d3z.pdb.gz')).read_bytes()).decode()
    path = tmp_path / 'unknown.pdb'
    path.write_text('\n'.join(line for line in text.splitlines() if not line.startswith('EXPDTA')))
    before = set(sm.molecules)
    with pytest.raises(RuntimeError, match='multiple models'):
        bpy.ops.molecule.import_local(filepath=str(path), identifier_override='ambiguous')
    assert set(sm.molecules) == before
    assert bpy.ops.molecule.import_local(filepath=str(path), identifier_override='explicit',
                                       model_interpretation='CONFORMATIONS') == {'FINISHED'}
    assert len(sm.molecules['explicit'].object.pb_conformations.states) == 10


def test_compare_helpers_and_close_preserve_presentation(scene):
    mol, library = ensemble()
    objects = [mol.object] + [d.object for d in mol.domains.values()]
    before = {o.name: (o.hide_get(), o.hide_render, o.matrix_world.copy()) for o in objects}
    library.active_index = 8
    library.show_comparison = True
    library.motion_threshold = .1
    library.highlight_motion = True
    assert not library.error
    helpers = [o for o in scene.objects if o.get('pb_state_preview_owner') == mol.object]
    assert {o['pb_state_preview_kind'] for o in helpers} == {'REFERENCE', 'MOTION'}
    for obj in helpers:
        assert obj.hide_render and obj.hide_select
        assert len(H.eval_positions(obj)) > 0
        assert all(r.object_name != obj.name for r in scene.outliner_items)
    assert bpy.ops.proteinblender.close_conformations() == {'FINISHED'}
    assert not library.show_comparison and not library.highlight_motion
    assert not any(o.get('pb_state_preview_owner') == mol.object for o in scene.objects)
    assert {o.name: (o.hide_get(), o.hide_render, o.matrix_world.copy()) for o in objects} == before


def test_named_library_endpoints_create_independent_breathing_morph(scene):
    mol, library = ensemble()
    library.fit = 'NONE'
    library.states[0].name = 'Start state'
    library.states[5].name = 'End state'
    assert bpy.ops.proteinblender.mark_conformation(molecule_id=mol.identifier, endpoint='START') == {'FINISHED'}
    assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=5) == {'FINISHED'}
    assert bpy.ops.proteinblender.mark_conformation(molecule_id=mol.identifier, endpoint='END') == {'FINISHED'}
    # Displaying a third state must not change either chosen endpoint.
    assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=8) == {'FINISHED'}
    assert bpy.ops.proteinblender.create_conformation(source_id=mol.identifier, target_id=mol.identifier,
        source_state=library.start_uid, target_state=library.end_uid, fit='NONE',
        start_frame=10, end_frame=30, return_to_start=True, return_frame=50,
        repeat=True, smooth=False) == {'FINISHED'}
    obj = C.transitions(scene)[0]
    assert obj['pb_start_label'] == 'Start state' and obj['pb_end_label'] == 'End state'
    assert obj.parent is None and not obj.children
    key = obj.data.shape_keys.key_blocks['End conformation']
    for frame, value in [(10,0), (20,.5), (30,1), (50,0), (70,1)]:
        scene.frame_set(frame)
        assert key.value == pytest.approx(value)
    import json
    from proteinblender.core.domain_space import get_pivot
    atom_mask = np.isin(A.read_identity(mol).residue_name, list(A.AA))
    for item, endpoint in zip([library.states[0],library.states[5]], obj.data.shape_keys.key_blocks):
        coords = np.empty((len(endpoint.data), 3))
        endpoint.data.foreach_get('co', coords.ravel())
        np.testing.assert_allclose(coords, L.read_mesh(item.mesh)[atom_mask] - np.asarray(get_pivot(mol.object)), atol=1e-6)
    assert bpy.ops.molecule.delete(molecule_id=mol.identifier) == {'FINISHED'}
    assert C.find(scene, obj[C.TAG]) is not None


def test_morph_can_pair_stored_states_from_different_proteins(scene, sm):
    first, library = ensemble()
    second_id = H.import_local('1d3z.pdb.gz', 'second ensemble')
    second = sm.molecules[second_id]
    # Choose endpoints that differ from both proteins' displayed states.
    assert bpy.ops.proteinblender.create_conformation(
        source_id=first.identifier, target_id=second_id,
        source_state=library.states[2].uid,
        target_state=second.object.pb_conformations.states[7].uid,
        fit='NONE', start_frame=10, end_frame=30) == {'FINISHED'}
    obj = C.transitions(scene)[0]
    raw = original_models()
    from proteinblender.core.domain_space import get_pivot
    mask = np.isin(A.read_identity(first).residue_name, list(A.AA))
    for index, block in zip((2, 7), obj.data.shape_keys.key_blocks):
        coords = np.empty((len(block.data), 3))
        block.data.foreach_get('co', coords.ravel())
        np.testing.assert_allclose(coords, raw[index].coord[mask] * .01 - np.asarray(get_pivot(first.object)), atol=1e-6)


def test_file_append_rejects_mismatch_without_partial_change(scene):
    mol, library = ensemble()
    before = L.read_mesh(mol.object.data).copy()
    assert bpy.ops.proteinblender.add_conformation_file(molecule_id=mol.identifier,
        filepath=H.data_path('1d3z.pdb.gz')) == {'FINISHED'}
    assert len(library.states) == 20
    assert bpy.ops.proteinblender.add_conformation_file(molecule_id=mol.identifier,
        filepath=H.data_path('1ubq.pdb')) == {'CANCELLED'}
    assert len(library.states) == 20
    np.testing.assert_array_equal(L.read_mesh(mol.object.data), before)


def test_capture_adds_library_state_without_scene_protein(scene):
    mol, library = ensemble()
    domains = [d.object for d in mol.domains.values()]
    domains[0].location.x += .3
    scene.view_layers[0].update()
    observed = H.evaluated_atom_positions(domains)
    count = len(scene.molecule_list_items)
    assert bpy.ops.proteinblender.capture_library_conformation(molecule_id=mol.identifier,
                                                             name='Authored pose') == {'FINISHED'}
    assert len(library.states) == 11 and library.states[-1].name == 'Authored pose'
    assert len(scene.molecule_list_items) == count
    assert not np.allclose(L.read_mesh(library.states[0].mesh), L.read_mesh(library.states[-1].mesh))
    library.fit = 'NONE'
    assert bpy.ops.proteinblender.switch_conformation(molecule_id=mol.identifier, index=10) == {'FINISHED'}
    # Capturing a pose must not apply the same domain transform a second time.
    np.testing.assert_allclose(H.evaluated_atom_positions(domains), observed, atol=2e-5)


def test_extract_library_state_and_delete_source_preserves_copy(scene, sm):
    mol, library = ensemble()
    library.active_index = 5
    original_meshes = [s.mesh.name for s in library.states]
    before = set(sm.molecules)
    expected = L.read_mesh(mol.object.data).copy()
    assert bpy.ops.proteinblender.extract_library_conformation(molecule_id=mol.identifier) == {'FINISHED'}
    copied_id = (set(sm.molecules) - before).pop()
    copied = sm.molecules[copied_id]
    assert len(copied.object.pb_conformations.states) == 1
    np.testing.assert_allclose(L.read_mesh(copied.object.data), expected, atol=1e-7)
    assert len(library.states) == 10
    assert all(not d.object.pb_conformations.states for d in copied.domains.values())
    assert bpy.ops.molecule.delete(molecule_id=mol.identifier) == {'FINISHED'}
    remaining = [bpy.data.meshes[name] for name in original_meshes if name in bpy.data.meshes]
    assert not remaining, {m.name: (m.users, [o.name for o in bpy.data.user_map(subset={m})[m]]) for m in remaining}
    assert bpy.ops.proteinblender.browse_conformations(molecule_id=copied_id) == {'FINISHED'}
    np.testing.assert_allclose(L.read_mesh(copied.object.data), expected, atol=1e-7)


def test_domain_deletion_removes_comparison_children(scene, sm):
    mid = H.import_local('4hhb.pdb', 'comparison_domains')
    assert bpy.ops.proteinblender.browse_conformations(molecule_id=mid) == {'FINISHED'}
    mol = sm.molecules[mid]
    mol.object.pb_conformations.show_comparison = True
    domain = next(iter(mol.domains.values())).object
    names = [o.name for o in domain.children if o.get('pb_state_preview_owner') == mol.object]
    assert names
    assert bpy.ops.molecule.delete_chain(molecule_id=mid, chain_id=next(iter(mol.domains.values())).chain_id) == {'FINISHED'}
    assert all(name not in bpy.data.objects for name in names)


@pytest.mark.network
def test_add_pdb_entry_to_library():
    mol, library = ensemble()
    assert bpy.ops.proteinblender.add_conformation_pdb(molecule_id=mol.identifier, pdb_id='1D3Z') == {'FINISHED'}
    assert len(library.states) == 20


def test_partial_morph_context_uses_chosen_start_state(scene):
    from proteinblender.core.domain_space import get_pivot
    mol, library = ensemble()
    library.fit = 'NONE'
    library.active_index = 8
    assert bpy.ops.proteinblender.create_conformation(source_id=mol.identifier, target_id=mol.identifier,
        source_state=library.states[0].uid, target_state=library.states[1].uid,
        source_chain='A', target_chain='A', source_region='1-20', target_region='1-20', fit='NONE') == {'FINISHED'}
    obj = C.transitions(scene)[0]
    identity = A.read_identity(mol)
    keep = (np.asarray(identity.residue) > 20) & np.isin(identity.residue_name, list(A.AA))
    expected = L.read_mesh(library.states[0].mesh)[keep] - np.asarray(get_pivot(mol.object))
    np.testing.assert_allclose(L.read_mesh(obj['pb_context_object'].data), expected, atol=1e-6)
