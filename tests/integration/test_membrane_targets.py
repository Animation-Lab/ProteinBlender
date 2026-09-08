"""Membrane-owned force fields, driven through the membrane's picker."""

import json

import bpy
import pytest

import helpers as H


def _slots(root):
    from proteinblender.utils import gn_compat
    mod = next(m for m in root.modifiers if m.type == 'NODES')
    result = []
    for socket in mod.node_group.interface.items_tree:
        if (socket.item_type == 'SOCKET' and socket.in_out == 'INPUT'
                and socket.name.startswith('Protein FF ')
                and socket.socket_type == 'NodeSocketObject'):
            obj = gn_compat.read_modifier_socket(mod, socket.identifier)
            if obj is not None:
                result.append(obj)
    return result


def _assign(root, ids):
    return bpy.ops.proteinblender.membrane_force_fields(
        membrane_name=root.name, targets_json=json.dumps(ids), spacing=1.75)


@pytest.mark.integration
def test_targets_affect_only_the_chosen_membrane(scene, sm, multi_chain):
    names = H.build_membrane(width=10, height=10)
    first = bpy.data.objects[names[0]]
    second = bpy.data.objects[H.build_membrane(width=10, height=10)[0]]
    assert _assign(first, [multi_chain]) == {'FINISHED'}
    assert _slots(first) == [sm.molecules[multi_chain].object]
    assert _slots(second) == []
    assert _assign(first, []) == {'FINISHED'}
    assert _slots(first) == []


@pytest.mark.integration
def test_split_chain_resolves_all_domains_and_deduplicates(scene, sm, multi_chain):
    chain_id = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN')
    assert bpy.ops.proteinblender.edit_chain_domains(
        item_id=chain_id, layout_json=_split_payload(chain_id, 2)) == {'FINISHED'}
    chain = next(r for r in scene.outliner_items if r.item_id == chain_id)
    from proteinblender.utils.chain_utils import get_chain_domains
    members = get_chain_domains(sm.molecules[multi_chain], chain)
    assert len(members) == 2
    root = bpy.data.objects[H.build_membrane(width=10, height=10)[0]]
    assert _assign(root, [chain_id, members[0][0]]) == {'FINISHED'}
    assert {o.name for o in _slots(root)} == {d.object.name for _, d in members}
    # Membership follows stable rows when the chain is repartitioned.
    assert bpy.ops.proteinblender.edit_chain_domains(
        item_id=chain_id, layout_json=_split_payload(chain_id, 3)) == {'FINISHED'}
    from proteinblender.membrane_builder import force_fields
    force_fields.apply_to_all_membranes(scene)
    assert len(_slots(root)) == 3


@pytest.mark.integration
def test_domain_target_survives_rename_and_other_membrane_edit(scene, sm, multi_chain):
    chain_id = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN')
    bpy.ops.proteinblender.edit_chain_domains(item_id=chain_id, layout_json=_split_payload(chain_id, 2))
    domain_id = next(r.item_id for r in scene.outliner_items if r.item_type == 'DOMAIN')
    obj = sm.molecules[multi_chain].domains[domain_id].object
    first = bpy.data.objects[H.build_membrane(width=10, height=10)[0]]
    second = bpy.data.objects[H.build_membrane(width=10, height=10)[0]]
    assert _assign(first, [domain_id]) == {'FINISHED'}
    assert _assign(second, [multi_chain]) == {'FINISHED'}
    bpy.ops.proteinblender.rename_domain(
        target_item_id=domain_id, item_type='DOMAIN', new_name='Selected domain')
    assert _slots(first) == [obj]
    assert _slots(second) == [sm.molecules[multi_chain].object]


def _split_payload(chain_id, count):
    row = next(r for r in bpy.context.scene.outliner_items if r.item_id == chain_id)
    low, high = row.chain_start, row.chain_end
    size = high - low + 1
    return json.dumps([dict(name=f"Piece {i+1}",
        start=low + size*i//count, end=low + size*(i+1)//count - 1)
        for i in range(count)])
