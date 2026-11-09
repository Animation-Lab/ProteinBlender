"""Linkers between chains that are members of a Morphset.

Reported 2026-11-03 (Janet): a ChimeraX morph with chains A and B, both
changing shape, imported with "States for Morphsets" and made into a
Morphset. A linker between A and B worked before the Morphset existed and
could not be made once it did.

Janet's own file (morph.pdb, 15.4 MB) was not available to this suite. The
stand-in is the bundled two-chain NMR ensemble 2BBN with its header stripped,
which is what a ChimeraX morph looks like to the importer: MODEL records and
atoms, no experiment record, so the import has to be told "States".

Ground truth is the fixture itself, parsed with biotite: how far each chosen
alpha carbon moves between two models, at MolecularNodes' 0.01 Blender units
per angstrom. Displacements are frame-free, so they do not depend on the
import's centring or on any add-on coordinate helper.
"""

import numpy as np
import pytest
import bpy

import helpers as H
from proteinblender.core import morphsets as C
from test_morphsets import _key

pytestmark = pytest.mark.integration

SCALE = 0.01  # Blender units per angstrom
MODELS = 3


def _chimera_like_morph(tmp_path):
    return H.chimera_like_ensemble(tmp_path / 'morph_ab.pdb', models=MODELS)


def _ca_by_model(path, chain):
    """{residue: (models, 3) CA coordinates in angstroms} for ``chain``."""
    import biotite.structure.io.pdb as pdb
    stack = pdb.PDBFile.read(str(path)).get_structure()
    atoms = (stack.chain_id == chain) & (stack.atom_name == 'CA')
    residues = stack.res_id[atoms]
    return residues, stack.coord[:, atoms]


def _moving_residue(path, chain):
    """A chain's residue whose CA moves most between model 1 and 3."""
    residues, coords = _ca_by_model(path, chain)
    shift = np.linalg.norm(coords[2] - coords[0], axis=1)
    index = int(np.argmax(shift))
    assert shift[index] > 1.0, f"chain {chain} barely moves ({shift[index]:.2f} A)"
    return int(residues[index]), coords[:, index]


def _linker_ends(linker):
    obj = bpy.data.objects[linker.curve_object_name]
    points = obj.data.splines[0].bezier_points
    world = obj.matrix_world
    return (np.array(world @ points[0].co), np.array(world @ points[-1].co))


def _import_states(path):
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.import_local(
        filepath=str(path), model_interpretation='CONFORMATIONS',
        identifier_override='morph_ab') == {'FINISHED'}
    (mid,) = set(H.sm().molecules) - before
    return mid


@pytest.fixture
def morph_ab(scene, tmp_path):
    """Janet's scene: a two-chain morph made into a keyed Morphset, puppeted."""
    path = _chimera_like_morph(tmp_path)
    mid = _import_states(path)
    # "States for Morphsets" makes the Morphset of both chains on import.
    (root,) = C.sets(scene)
    (morph,) = C.morphs(scene, root)
    assert len(C.states(morph)) == MODELS
    assert _key(morph, 1, 0) == {'FINISHED'}
    assert _key(morph, 50, 2) == {'FINISHED'}
    scene.frame_set(1)

    members = [r.item_id for r in scene.outliner_items
               if r.item_type == 'MORPH_MEMBER' and r.parent_id == root[C.TAG]]
    names = {r.item_id: r.name for r in scene.outliner_items}
    assert len(members) == 2, f"expected chains A and B, got {[names[m] for m in members]}"

    for row in scene.outliner_items:
        row.is_selected = row.item_id == root[C.TAG]
    assert bpy.ops.proteinblender.create_puppet(
        'EXEC_DEFAULT', puppet_name='Morph Puppet') == {'FINISHED'}
    puppet = next(r for r in scene.outliner_items
                  if r.item_type == 'PUPPET' and r.name == 'Morph Puppet')
    chain_of = {m: names[m].split()[-1] for m in members}
    # Spheres, so Blender's evaluated output carries one point per atom and
    # the visible alpha carbon can be read off it directly.
    for member in members:
        assert bpy.ops.proteinblender.edit_morph_member(
            item_id=member, vs_style='spheres') == {'FINISHED'}
    return dict(path=path, mid=mid, morph=morph, members=members,
                chain_of=chain_of, puppet_id=puppet.item_id,
                controller=puppet.controller_object_name)


def _add_morph_linker(case):
    scene = bpy.context.scene
    a, b = case['members']
    res_a, ca_a = _moving_residue(case['path'], case['chain_of'][a])
    res_b, ca_b = _moving_residue(case['path'], case['chain_of'][b])
    before = len(scene.pb2_linkers)
    result = bpy.ops.pb2.add_linker(
        'EXEC_DEFAULT', puppet_selector=case['puppet_id'],
        endpoint_a_item=f"A_{a}", endpoint_a_residue=res_a,
        endpoint_b_item=f"B_{b}", endpoint_b_residue=res_b,
        length_residues=100, linker_name='A to B')
    assert result == {'FINISHED'}, result
    assert len(scene.pb2_linkers) == before + 1
    return scene.pb2_linkers[-1], ca_a, ca_b


def test_linker_endpoints_offer_each_morphset_chain(morph_ab):
    """The puppet's endpoint lists name chains A and B, not one Morphset."""
    from proteinblender.linkers.linker_operators import get_chain_items_a

    class _Op:
        puppet_selector = morph_ab['puppet_id']

    offered = {identifier[2:] for identifier, *_ in get_chain_items_a(_Op, bpy.context)}
    assert set(morph_ab['members']) <= offered, (
        f"chains {morph_ab['members']} not offered; got {sorted(offered)}")


def test_linker_between_morphing_chains_follows_the_morph(morph_ab):
    scene = bpy.context.scene
    linker, ca_a, ca_b = _add_morph_linker(morph_ab)

    scene.frame_set(1)
    start_1, end_1 = _linker_ends(linker)
    for frame, weight in ((50, 1.0), (25, 24 / 49)):
        scene.frame_set(frame)
        start, end = _linker_ends(linker)
        expected_a = (ca_a[2] - ca_a[0]) * SCALE * weight
        expected_b = (ca_b[2] - ca_b[0]) * SCALE * weight
        np.testing.assert_allclose(
            start - start_1, expected_a, atol=2e-4,
            err_msg=f"frame {frame}: end A did not follow chain A's morph")
        np.testing.assert_allclose(
            end - end_1, expected_b, atol=2e-4,
            err_msg=f"frame {frame}: end B did not follow chain B's morph")


def _visible_ca(member_name, residue):
    """The CA Blender draws for this member (evaluated Spheres output)."""
    return H.visible_alpha_carbon([H.morph_output_named(member_name)], residue)


def test_linker_ends_sit_on_the_visible_alpha_carbons(morph_ab):
    """Absolute, not only relative: each end is on the CA Blender draws, at a
    keyed frame, between keys, and after the puppet is moved and turned."""
    scene = bpy.context.scene
    names = {r.item_id: r.name for r in scene.outliner_items}
    a, b = morph_ab['members']
    linker, _ca_a, _ca_b = _add_morph_linker(morph_ab)
    res_a, res_b = linker.endpoint_a_residue, linker.endpoint_b_residue

    def check(label):
        start, end = _linker_ends(linker)
        np.testing.assert_allclose(start, _visible_ca(names[a], res_a), atol=1e-4,
                                   err_msg=f"{label}: end A is off chain A's CA")
        np.testing.assert_allclose(end, _visible_ca(names[b], res_b), atol=1e-4,
                                   err_msg=f"{label}: end B is off chain B's CA")

    for frame in (1, 50, 25):
        scene.frame_set(frame)
        check(f"frame {frame}")

    controller = bpy.data.objects[morph_ab['controller']]
    controller.location = (0.7, -0.4, 0.2)
    controller.rotation_euler = (0.5, -0.3, 1.2)
    bpy.context.view_layer.update()
    scene.frame_set(37)
    check("moved and turned puppet, frame 37")


def test_a_linker_made_before_the_morph_is_keyed_follows_it_once_keyed(scene, tmp_path):
    """The other order: Morphset, puppet and linker first, keys afterwards."""
    path = _chimera_like_morph(tmp_path)
    _import_states(path)
    (root,) = C.sets(scene)
    (morph,) = C.morphs(scene, root)
    names = {r.item_id: r.name for r in scene.outliner_items}
    members = [r.item_id for r in scene.outliner_items
               if r.item_type == 'MORPH_MEMBER' and r.parent_id == root[C.TAG]]
    for row in scene.outliner_items:
        row.is_selected = row.item_id == root[C.TAG]
    assert bpy.ops.proteinblender.create_puppet(
        'EXEC_DEFAULT', puppet_name='Morph Puppet') == {'FINISHED'}
    puppet = next(r for r in scene.outliner_items
                  if r.item_type == 'PUPPET' and r.name == 'Morph Puppet')
    case = dict(path=path, members=members, puppet_id=puppet.item_id,
                chain_of={m: names[m].split()[-1] for m in members})
    linker, _ca_a, _ca_b = _add_morph_linker(case)

    assert _key(morph, 1, 0) == {'FINISHED'}
    assert _key(morph, 50, 2) == {'FINISHED'}
    for member in members:
        assert bpy.ops.proteinblender.edit_morph_member(
            item_id=member, vs_style='spheres') == {'FINISHED'}
    a, b = members
    for frame in (50, 25):
        scene.frame_set(frame)
        start, end = _linker_ends(linker)
        np.testing.assert_allclose(
            start, _visible_ca(names[a], linker.endpoint_a_residue), atol=1e-4,
            err_msg=f"frame {frame}: end A is off chain A's CA")
        np.testing.assert_allclose(
            end, _visible_ca(names[b], linker.endpoint_b_residue), atol=1e-4,
            err_msg=f"frame {frame}: end B is off chain B's CA")


def test_morph_linker_moves_with_its_puppet(morph_ab):
    scene = bpy.context.scene
    linker, _ca_a, _ca_b = _add_morph_linker(morph_ab)
    scene.frame_set(25)
    start, end = _linker_ends(linker)

    controller = bpy.data.objects[morph_ab['controller']]
    controller.location.x += 0.5
    controller.location.z -= 0.25
    bpy.context.view_layer.update()
    scene.frame_set(25)
    moved_start, moved_end = _linker_ends(linker)
    np.testing.assert_allclose(moved_start - start, [0.5, 0, -0.25], atol=2e-4)
    np.testing.assert_allclose(moved_end - end, [0.5, 0, -0.25], atol=2e-4)
