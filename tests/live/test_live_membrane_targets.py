"""The membrane's target picker parts only its own evaluated lipid bilayer."""

import pytest

from test_live_membrane import lipid_stats


@pytest.mark.live
def test_force_field_picker_affects_only_its_membrane(blender, single_chain):
    roots = blender.call('''
with R.view3d_override():
    first = H.build_membrane(width=20, height=20)[0]
    second = H.build_membrane(width=20, height=20)[0]
return [first, second]
''')
    before = [lipid_stats(blender, root) for root in roots]
    assert all(s['count'] > 100 for s in before)
    assert blender.call('''
import json
with R.view3d_override():
    result = bpy.ops.proteinblender.membrane_force_fields(
        membrane_name=root, targets_json=json.dumps([mid]), spacing=3.0)
return sorted(result)
''', root=roots[0], mid=single_chain) == ['FINISHED']
    after = [lipid_stats(blender, root) for root in roots]
    assert after[0]['clearance_nm'] > before[0]['clearance_nm'] + 1.0
    assert after[1]['clearance_nm'] == pytest.approx(before[1]['clearance_nm'], abs=0.001)


@pytest.mark.live
def test_bmt_and_scoped_symmetry_in_the_installed_addon(blender, multi_chain):
    result = blender.call('''
scene = bpy.context.scene
chain_id = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN')
scene.pb_symmetry_kind = 'C'
scene.pb_symmetry_order = 3
scene.pb_symmetry_range = 0
scene.pb_symmetry_contact = 0
with R.view3d_override():
    assert bpy.ops.molecule.symmetry_dialog(target_id=chain_id) == {'FINISHED'}
row = next(r for r in scene.outliner_items if r.item_type == 'SYMMETRY')
assert row.parent_id == chain_id
with R.view3d_override():
    assert bpy.ops.molecule.clear_assembly(molecule_id=mid) == {'FINISHED'}
    biological = H.import_local('5im3.cif', '5im3')
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=biological, source='BIOLOGICAL', assembly_id='1') == {'FINISHED'}
row = next(r for r in scene.outliner_items if r.item_type == 'SYMMETRY')
return {'parent': row.parent_id, 'protein': biological, 'label': row.name}
''', mid=multi_chain)
    assert result['parent'] == result['protein']
    assert result['label'] == 'Biological Assembly 1'
