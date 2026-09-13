"""Membrane-owned force fields, driven through the membrane's picker."""

import json

import bpy
import numpy as np
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
    assert set(_slots(first)) == {d.object for d in sm.molecules[multi_chain].domains.values()}
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
    assert set(_slots(second)) == {d.object for d in sm.molecules[multi_chain].domains.values()}


def _split_payload(chain_id, count):
    row = next(r for r in bpy.context.scene.outliner_items if r.item_id == chain_id)
    low, high = row.chain_start, row.chain_end
    size = high - low + 1
    return json.dumps([dict(name=f"Piece {i+1}",
        start=low + size*i//count, end=low + size*(i+1)//count - 1)
        for i in range(count)])


def _clearance(root, center):
    bpy.context.view_layer.update()
    # Background Blender does not tick timers. Run the refresh scheduled by
    # the real depsgraph handler, as the foreground event loop would.
    from proteinblender.membrane_builder.force_fields import _deferred_membrane_refresh
    if bpy.app.timers.is_registered(_deferred_membrane_refresh):
        bpy.app.timers.unregister(_deferred_membrane_refresh)
        _deferred_membrane_refresh()
    positions = [tuple(i.matrix_world.translation) for i in
                 bpy.context.evaluated_depsgraph_get().object_instances
                 if i.is_instance and i.parent and i.parent.original == root]
    assert len(positions) > 100, 'No evaluated lipid instances'
    return np.linalg.norm((np.asarray(positions) - center)[:, :2], axis=1).min()


@pytest.mark.integration
def test_protein_target_parts_lipids_around_its_moved_chain(scene, sm, single_chain):
    molecule = sm.molecules[single_chain]
    domain = next(iter(molecule.domains.values())).object
    domain.location.x += 1.0
    scene.view_layers[0].update()
    atoms = H.evaluated_atom_positions([domain])
    assert len(atoms) > 100
    center = atoms.mean(axis=0)
    root = bpy.data.objects[H.build_membrane(width=40, height=40)[0]]
    before = _clearance(root, center)
    assert _assign(root, [single_chain]) == {'FINISHED'}
    after = _clearance(root, center)
    assert after > before + .15, (before, after, center)


@pytest.mark.integration
def test_force_field_uses_geometry_after_pivot_edit_and_tracks_height(scene, sm, single_chain):
    molecule = sm.molecules[single_chain]
    domain = next(iter(molecule.domains.values())).object
    chain_id = next(r.item_id for r in scene.outliner_items if r.item_type == 'CHAIN')
    atoms = H.evaluated_atom_positions([domain])
    center = atoms.mean(axis=0)
    root = bpy.data.objects[H.build_membrane(width=40, height=40)[0]]
    baseline = _clearance(root, center)
    assert _assign(root, [chain_id]) == {'FINISHED'}
    embedded = _clearance(root, center)
    assert embedded > baseline + .15
    assert bpy.ops.proteinblender.set_pivot_first(item_id=chain_id) == {'FINISHED'}
    # The molecular body is unchanged; moving its origin must not move the gap.
    shifted_pivot = _clearance(root, center)
    assert shifted_pivot == pytest.approx(embedded, abs=.01)
    domain.location.z += 5
    scene.view_layers[0].update()
    far = _clearance(root, center)
    assert far == pytest.approx(baseline, abs=.01), 'A remote protein still parts the bilayer'
    domain.location.z -= 5
    scene.view_layers[0].update()
    assert _clearance(root, center) == pytest.approx(embedded, abs=.01)
    assert _assign(root, []) == {'FINISHED'}
    assert _clearance(root, center) == pytest.approx(baseline, abs=.01)
