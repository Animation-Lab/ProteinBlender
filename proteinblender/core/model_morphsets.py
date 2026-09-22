"""Morphsets whose members share the models already imported with one protein.

The snapshot engine also retains support for existing pair-based project files.
New sets expose only membership and model-at-frame controls.
"""
import uuid

import bpy
import numpy as np
from mathutils import Matrix

from . import morphsets as C

MANAGED = 'pb_model_morphset'


def molecule(source):
    from ..utils.scene_manager import ProteinBlenderScene
    return ProteinBlenderScene.get_instance().molecules.get(source)


def subject(root, scene=None):
    values = C.morphs(scene or bpy.context.scene, root) if root else []
    return values[0] if values else None


def source_id(root):
    from ..utils.scene_manager import ProteinBlenderScene
    source = root.get('pb_model_source') if root else None
    return next((mid for mid, mol in ProteinBlenderScene.get_instance().molecules.items()
                 if mol.object == source), '')


def _overlap(a, b):
    # Copied chains are distinct objects/subjects, even with the same residues.
    return (a.object == b.object or
            (not getattr(a, 'is_copy', False) and not getattr(b, 'is_copy', False)
             and a.chain_id == b.chain_id and max(a.start, b.start) <= min(a.end, b.end)))


def member_issue(context, mol, domain, root=None):
    obj = domain.object
    if not obj or obj.type != 'MESH':
        return 'No atom coordinates available.'
    if obj.data.shape_keys:
        return 'This member already has shape animation.'
    puppets = {r.controller_object_name for r in context.scene.outliner_items if r.item_type == 'PUPPET'}
    if obj.parent and obj.parent.name in puppets:
        return 'Remove this member from its puppet first.'
    for morph in C.morphs(context.scene):
        if root and morph.parent == root:
            continue
        for member in C.records(morph):
            other = next((d for d in mol.domains.values() if d.object == member.get('object')), None)
            if other and _overlap(domain, other):
                return f'Controlled by {morph.parent.name}.'
    return ''


def selection(context, source, ids, root=None):
    mol = molecule(source)
    if mol is None or mol.object.get('pb_is_nucleic_acid'):
        raise ValueError('Choose a protein with imported models.')
    models = list(mol.object.pb_conformations.states)
    if len(models) < 2:
        raise ValueError('Only one conformation is available. Choose a protein imported with multiple models.')
    if not ids:
        raise ValueError('Select at least one chain or domain.')
    domains = []
    for uid in dict.fromkeys(ids):
        domain = mol.domains.get(uid)
        if domain is None:
            raise ValueError('Choose chains/domains belonging to this protein.')
        issue = member_issue(context, mol, domain, root)
        if issue:
            raise ValueError(f'{domain.object.name}: {issue}')
        if any(_overlap(domain, other) for other in domains):
            raise ValueError('Selected members overlap. Select the chain or its domains, not both.')
        domains.append(domain)
    return mol, models


def _capture(context, source, ids, root=None):
    mol, models = selection(context, source, ids, root)
    morph = subject(root, context.scene)
    previous = {s.get('model_uid'): s['uid'] for s in C.states(morph)} if morph else {}
    origin, definitions, snapshots = None, [], []
    try:
        for model in models:
            members, origin = C._capture(context, ids, model.uid, origin, world_matrix)
            snapshots.extend(members)
            if morph:
                # Captures are in world space. Editing after a protein move must
                # keep the snapshots in the existing controller's local space.
                inverse = np.asarray(world_matrix(morph).inverted())
                for member in members:
                    points = C._coordinates(member['mesh'])
                    points = points @ inverse[:3, :3].T + inverse[:3, 3]
                    member['mesh'].vertices.foreach_set('co', points.ravel())
            if definitions:
                C._validate_members(definitions[0]['members'], members)
            definitions.append(C._state_definition(previous.get(model.uid, uuid.uuid4().hex),
                                                    model.name, members, model.uid))
    except Exception:
        C._discard_snapshots(snapshots)
        raise
    return mol, definitions, origin


def create(context, name, source, ids):
    mol, definitions, origin = _capture(context, source, ids)
    root = C.create(context, name)
    root[MANAGED] = True
    root['pb_model_source'] = mol.object
    # The coordinates were captured in world space. An identity world matrix
    # avoids applying the import transform twice and follows later protein moves.
    root.parent = mol.object
    root.matrix_parent_inverse = world_matrix(mol.object).inverted()
    C._install_morph(context, root, root.name, definitions, origin)
    return root


def world_matrix(obj):
    """Hidden source members do not always get a refreshed matrix_world.

    PB's ordinary object parenting can be evaluated from the live transform
    channels without making those hidden originals visible for a redraw.
    """
    if obj.constraints or obj.parent_type != 'OBJECT':
        return obj.matrix_world.copy()
    if obj.parent:
        return world_matrix(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis
    return obj.matrix_basis.copy()


def _restore(member):
    obj = member.get('object')
    if obj:
        world = world_matrix(obj)
        obj.parent = member.get('parent')
        obj.matrix_parent_inverse = Matrix(np.asarray(member['parent_inverse']).reshape(4, 4))
        obj.matrix_world = world


def edit(context, root, name, ids):
    if not root or not root.get(MANAGED):
        raise ValueError('Choose a model Morphset.')
    morph = subject(root, context.scene)
    old = [m.to_dict() for m in C.records(morph)]
    old_ids = [m['row_id'] for m in old]
    if ids == old_ids:
        root.name = name.strip() or root.name
        morph.name = root.name
        C.rebuild(context)
        return
    mol, definitions, origin = _capture(context, source_id(root), ids, root)
    old_by_object = {m.get('object'): m for m in old}
    meshes = {m['mesh'] for s in C.states(morph) for m in s['members']}
    meshes.update(m['mesh'] for m in old)
    members = []
    for snapshot in definitions[0]['members']:
        obj = snapshot['original']
        previous = old_by_object.get(obj)
        member = dict(snapshot, object=obj, generated=False)
        if previous:
            for key in ('render', 'viewport', 'hidden', 'parent_inverse', 'parent',
                        'display_pivot', 'display_matrix'):
                if key in previous:
                    member[key] = previous[key]
        else:
            member.update(render=obj.hide_render, viewport=obj.hide_viewport, hidden=obj.hide_get(),
                          parent_inverse=[v for row in obj.matrix_parent_inverse for v in row])
            if obj.parent:
                member['parent'] = obj.parent
            world = world_matrix(obj)
            obj.parent = root
            obj.matrix_world = world
        members.append(member)
    remaining = {m['object'] for m in members}
    for member in old:
        if member.get('object') not in remaining:
            _restore(member)
    keys = C.keyframes(context.scene)
    for rows in keys.values():
        value = rows.get(morph[C.MORPH])
        if value:
            visibility = {m['object']: visible for m, visible in zip(old, value['visible'])}
            value['visible'] = [visibility.get(m['object'], any(value['visible'])) for m in members]
    morph['pb_states'], morph['pb_members'], morph['pb_origin'] = definitions, members, origin
    root.name = name.strip() or root.name
    morph.name = root.name
    C._refresh_owners(context.scene)
    C.compile_animation(context, keys)
    for mesh in meshes:
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
    C.rebuild(context)


def neighbors(scene, morph, frame):
    keys = C.morph_keys(scene, morph[C.MORPH])
    def label(f):
        return f"{C.state_label(C.state(morph, keys[str(f)]['state']))} at frame {f}"
    before = max((int(f) for f in keys if int(f) < frame), default=None)
    after = min((int(f) for f in keys if int(f) > frame), default=None)
    return label(before) if before is not None else '', label(after) if after is not None else ''
