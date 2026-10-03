"""Changing assembly sources must preserve geometry in every other protein."""
import bpy
import numpy as np
import pytest
import helpers as H
from proteinblender.core import assembly as A

pytestmark = pytest.mark.integration


def placed_geometry(mol):
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get(); graph.update()
    result = {}
    names = {obj.name for obj in A._target_objects(mol)}
    for i in graph.object_instances:
        if not i.is_instance or not i.parent or i.parent.original.name not in names:
            continue
        mesh = i.object.to_mesh()
        result.setdefault(i.parent.original.name, []).append(len(mesh.vertices))
        i.object.to_mesh_clear()
    return result

@pytest.mark.parametrize('style', ['cartoon', 'surface', 'ball_and_stick'])
def test_switching_generated_to_deposited_keeps_visible_geometry(scene, style):
    mol = H.sm().molecules[H.import_local('1stm.cif.gz', '1stm_001')]
    bpy.ops.proteinblender.edit_protein_visuals(item_id=mol.identifier, vs_style=style)
    bpy.ops.molecule.symmetry_dialog(target_id=mol.identifier, source='GENERATED')
    generated = placed_geometry(mol)
    assert all(sum(generated[d.object.name]) > 0 for d in mol.domains.values())
    assert bpy.ops.molecule.symmetry_dialog(target_id=mol.identifier, source='BIOLOGICAL', assembly_id='1') == {'FINISHED'}
    after = placed_geometry(mol)
    for d in mol.domains.values():
        assert len(after.get(d.object.name, [])) == 12
        assert sum(after[d.object.name]) > 0


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('operation', ['switch', 'clear'])
def test_switching_first_import_preserves_second_import_geometry(scene, legacy, operation):
    first = H.sm().molecules[H.import_local('1stm.cif.gz', '1stm')]
    second = H.sm().molecules[H.import_local('1stm.cif.gz', '1stm_001')]
    for mol in (first, second):
        bpy.ops.proteinblender.edit_protein_visuals(item_id=mol.identifier, vs_style='cartoon')
        bpy.ops.molecule.symmetry_dialog(target_id=mol.identifier, source='GENERATED')
    if legacy:
        # Older saved builds had only Object Info references, without explicit
        # owner or point-cloud properties. They must be safe to edit too.
        for block in list(bpy.data.objects) + list(bpy.data.node_groups):
            for key in ('pb_assembly_owner', 'pb_assembly_points'):
                if key in block:
                    del block[key]
    before = placed_geometry(second)
    if operation == 'switch':
        bpy.ops.molecule.symmetry_dialog(target_id=first.identifier, source='BIOLOGICAL', assembly_id='1')
    else:
        A.clear_assembly(first)
    after = placed_geometry(second)
    for d in second.domains.values():
        assert after.get(d.object.name) == before.get(d.object.name)
        assert sum(after[d.object.name]) > 0


def test_updating_one_assembly_does_not_move_a_similarly_named_assembly(scene):
    first = H.sm().molecules[H.import_local('1stm.cif.gz', '1stm')]
    second = H.sm().molecules[H.import_local('1stm.cif.gz', '1stm_001')]
    for mol in (first, second):
        bpy.ops.molecule.symmetry_dialog(target_id=mol.identifier, source='GENERATED')
    bpy.context.view_layer.update()
    before = H.evaluated_atom_positions(A._target_objects(second))
    assert len(before) > 0
    operators = [(np.eye(3), np.array([10.0 * i, 0, 0])) for i in range(3)]
    assert A.update_operator_points(first, operators)
    bpy.context.view_layer.update()
    after = H.evaluated_atom_positions(A._target_objects(second))
    np.testing.assert_array_equal(before, after)
