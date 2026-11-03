"""B-factor motion can be set on one chain or one domain, not only a protein.

Janet (2026-10-30): she wanted the temperature motion on a flexible chain of
her complex without the rest of it shaking. The toggle lived on the protein
dialog alone and switched every chain at once. It is now in the Visual Set-up
block of the protein, Edit Chain and Edit Domain dialogs, and each sets only
the objects its row draws.

Ground truth is the atoms Blender draws (``H.evaluated_atom_positions``),
read at several frames: a part with motion moves between frames, a part
without it stays exactly where it is at rest.
"""
import json

import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration

FRAMES = (1, 7, 13, 19)


def _import_actin():
    mid = H.import_local('1atn.pdb', 'Actin')
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    return mid, H.sm().molecules[mid]


def _chain_row(mid, letter):
    (obj,) = _chain_objects(H.sm().molecules[mid], letter)
    return next(r for r in bpy.context.scene.outliner_items
                if r.item_type == 'CHAIN' and r.parent_id == mid
                and r.object_name == obj.name)


def _chain_objects(molecule, letter):
    return [d.object for d in molecule.domains.values()
            if d.object and str(d.chain_id) == letter]


def _movement(scene, objects):
    """Largest distance any drawn atom of ``objects`` strays from frame 1."""
    scene.frame_set(FRAMES[0])
    bpy.context.view_layer.update()
    rest = H.evaluated_atom_positions(objects)
    assert len(rest), "these objects draw no atoms"
    furthest = 0.0
    for frame in FRAMES[1:]:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        now = H.evaluated_atom_positions(objects)
        assert now.shape == rest.shape
        furthest = max(furthest, float(np.abs(now - rest).max()))
    return furthest


def _edit_chain(mid, letter, **fields):
    row = _chain_row(mid, letter)
    molecule = H.sm().molecules[mid]
    (domain_id, domain), = [(i, d) for i, d in molecule.domains.items()
                            if str(d.chain_id) == letter]
    layout = json.dumps([{"name": domain.name, "start": domain.start,
                          "end": domain.end, "domain_id": domain_id}])
    return bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=row.item_id, layout_json=layout,
        chain_name=row.name, **fields)


def test_edit_chain_moves_only_that_chain(scene):
    mid, molecule = _import_actin()
    assert _edit_chain(mid, 'A', bfactor_motion=True) == {'FINISHED'}
    assert _movement(scene, _chain_objects(molecule, 'A')) > 1e-4
    assert _movement(scene, _chain_objects(molecule, 'D')) == 0.0
    # The molecule reports that some part of it moves.
    assert molecule.object.get('pb_bfactor_enabled') is True


def test_a_chain_can_be_stilled_inside_a_moving_protein(scene):
    mid, molecule = _import_actin()
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, bfactor_motion=True) == {'FINISHED'}
    assert _movement(scene, _chain_objects(molecule, 'D')) > 1e-4
    assert _edit_chain(mid, 'D', bfactor_motion=False) == {'FINISHED'}
    assert _movement(scene, _chain_objects(molecule, 'D')) == 0.0
    assert _movement(scene, _chain_objects(molecule, 'A')) > 1e-4
    assert molecule.object.get('pb_bfactor_enabled') is True

    # Stilling every chain one by one stills the protein.
    for letter in sorted({str(d.chain_id) for d in molecule.domains.values()} - {'D'}):
        assert _edit_chain(mid, letter, bfactor_motion=False) == {'FINISHED'}
    assert molecule.object.get('pb_bfactor_enabled') is False


def test_each_chain_keeps_its_own_intensity(scene):
    """Tripling one chain's intensity triples its motion and leaves the other."""
    mid, molecule = _import_actin()
    a, d = _chain_objects(molecule, 'A'), _chain_objects(molecule, 'D')
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, bfactor_motion=True, bfactor_intensity=1.0) == {'FINISHED'}
    a_once, d_once = _movement(scene, a), _movement(scene, d)

    assert _edit_chain(mid, 'D', bfactor_intensity=3.0) == {'FINISHED'}
    assert _movement(scene, d) == pytest.approx(3 * d_once, rel=1e-3)
    assert _movement(scene, a) == pytest.approx(a_once, rel=1e-6)

    # A protein-wide intensity alone changes how strong, not what moves.
    assert _edit_chain(mid, 'D', bfactor_motion=False) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, bfactor_intensity=2.0) == {'FINISHED'}
    assert _movement(scene, d) == 0.0
    assert _movement(scene, a) == pytest.approx(2 * a_once, rel=1e-3)


def test_edit_domain_moves_only_that_domain(scene):
    mid, molecule = _import_actin()
    assert H.split_domain_from_outliner(mid, 'A', 1, 180) == {'FINISHED'}
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    pieces = [(i, d) for i, d in molecule.domains.items()
              if str(d.chain_id) == 'A' and d.object]
    assert len(pieces) == 2
    (moving_id, moving), (still_id, still) = sorted(pieces, key=lambda p: p[1].start)
    assert bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=moving_id, item_type='DOMAIN',
        new_name=moving.name, bfactor_motion=True) == {'FINISHED'}
    assert _movement(scene, [moving.object]) > 1e-4
    assert _movement(scene, [still.object]) == 0.0
    assert _movement(scene, _chain_objects(molecule, 'D')) == 0.0


def test_splitting_a_moving_chain_keeps_both_pieces_moving(scene):
    mid, molecule = _import_actin()
    assert _edit_chain(mid, 'A', bfactor_motion=True,
                       bfactor_intensity=2.0) == {'FINISHED'}
    before = _movement(scene, _chain_objects(molecule, 'A'))
    assert H.split_domain_from_outliner(mid, 'A', 1, 180) == {'FINISHED'}
    pieces = _chain_objects(molecule, 'A')
    assert len(pieces) == 2
    for piece in pieces:
        assert _movement(scene, [piece]) > 1e-4, f"{piece.name} stopped moving"
    assert _movement(scene, pieces) == pytest.approx(before, rel=1e-3)
    assert _movement(scene, _chain_objects(molecule, 'D')) == 0.0


def test_a_copy_moves_like_its_original_not_like_an_earlier_split(scene):
    """A copy takes its original's motion; a split before it hands it nothing.

    Splitting remembers what each deleted piece carried so its new pieces
    keep it. That memory must end with the split: a domain copied afterwards
    has no part in it.
    """
    mid, molecule = _import_actin()
    assert _edit_chain(mid, 'A', bfactor_motion=True) == {'FINISHED'}
    assert H.split_domain_from_outliner(mid, 'A', 1, 180) == {'FINISHED'}
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    (low_id, low), (high_id, high) = sorted(
        [(i, d) for i, d in molecule.domains.items() if str(d.chain_id) == 'A'],
        key=lambda p: p[1].start)
    assert bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=low_id, item_type='DOMAIN',
        new_name=low.name, bfactor_motion=False) == {'FINISHED'}

    before = set(molecule.domains)
    assert bpy.ops.molecule.copy_domain(domain_id=low_id) == {'FINISHED'}
    (copy_id,) = set(molecule.domains) - before
    assert _movement(scene, [molecule.domains[copy_id].object]) == 0.0

    before = set(molecule.domains)
    assert bpy.ops.molecule.copy_domain(domain_id=high_id) == {'FINISHED'}
    (copy_id,) = set(molecule.domains) - before
    assert _movement(scene, [molecule.domains[copy_id].object]) > 1e-4
