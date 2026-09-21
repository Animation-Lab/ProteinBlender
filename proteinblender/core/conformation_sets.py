"""Conformation libraries: one animated subject, reusable structures, movie keys.

The existing morph controller/coordinate engine remains the storage backend, so
older files retain atom correspondence, visibility, and stable action bindings.
"""
import uuid

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import morphsets as C

PREVIEW = 'pb_conformation_preview_object'
HIDDEN = 'pb_conformation_preview_hidden'


def subject(root, scene=None):
    values = C.morphs(scene or bpy.context.scene, root) if root else []
    return values[0] if values else None


def member_ids(morph):
    """Resolve actual domains, even when the original selection was a protein."""
    from ..utils.scene_manager import ProteinBlenderScene
    objects = {r.get('object') for r in C.records(morph)}
    return [did for mol in ProteinBlenderScene.get_instance().molecules.values()
            for did, domain in mol.domains.items() if domain.object in objects]


def provenance(value):
    sources = list(dict.fromkeys(m.get('source').name for m in value['members'] if m.get('source')))
    return value.get('source_name', '') or ' + '.join(sources) or 'Saved structure'


def create(context, name, row_ids):
    """Capture all imported models atomically, without choosing endpoint pairs."""
    from .outliner_targets import resolve_target
    molecules = [resolve_target(uid)[0] for uid in row_ids]
    if not molecules or any(m is None for m in molecules):
        raise ValueError('Choose a protein or select chains/domains in the PB Outliner.')
    models = list(molecules[0].object.pb_conformations.states) if all(m == molecules[0] for m in molecules) else []
    definitions, captured, origin = [], [], None
    try:
        for model in models or [None]:
            members, origin = C._capture(context, row_ids, model.uid if model else '', origin)
            captured.extend(members)
            if definitions:
                C._validate_members(definitions[0]['members'], members)
            value = C._state_definition(uuid.uuid4().hex, model.name if model else 'Current structure',
                                        members, model.uid if model else '')
            value['source_name'] = ' + '.join(dict.fromkeys(m.object.name for m in molecules))
            definitions.append(value)
        objects = {m['original'] for m in definitions[0]['members']}
        existing = next((m for m in C.morphs(context.scene)
                         if {r.get('object') for r in C.records(m)} == objects
                         and m.parent.get('pb_schema') == 3), None)
        if existing:
            C._discard_snapshots(captured)
            return existing.parent
        # Partial overlap needs an explicit independent subject: do not silently
        # fork one chain's state choices into two competing UI rows.
        if any(C._member_bindings(context.scene, obj) for obj in objects):
            raise ValueError('Some members already have a state library. Edit that Morphset, or choose separate members.')
    except Exception:
        C._discard_snapshots(captured)
        raise
    root = C.create(context, name.strip() or ' + '.join(dict.fromkeys(m.object.name for m in molecules)) + ' states')
    root['pb_schema'] = 3
    try:
        C._install_morph(context, root, root.name, definitions, origin)
    except Exception:
        if not C.morphs(context.scene, root):
            bpy.data.objects.remove(root, do_unlink=True)
        C._discard_snapshots(captured)
        raise
    return root


def _same_subject(a, b):
    return ([r.get('object') for r in C.records(a)] == [r.get('object') for r in C.records(b)]
            and np.allclose(a['pb_origin'], b['pb_origin'], atol=1e-8, rtol=0)
            and np.allclose(a.matrix_world, b.matrix_world, atol=1e-8, rtol=0))


def _equivalent(a, b):
    # Do not erase custom scientific names when two saved states happen to match.
    if C.state_label(a) != C.state_label(b) or len(a['members']) != len(b['members']):
        return False
    try:
        return all(np.allclose(C._coordinates(x['mesh']), C._match(x['mesh'], y['mesh']),
                               atol=1e-8, rtol=0) for x, y in zip(a['members'], b['members']))
    except ValueError:
        return False


def upgrade(context):
    """Flatten old pair libraries without changing the union of keyed samples.

    Exact shared subjects merge. Independent subjects get separate roots.
    Exceptional overlapping/transformed subjects remain separate so their
    original correspondence and animation are preserved rather than guessed.
    """
    C._migrate_v1(context)
    legacy = [r for r in C.sets(context.scene) if r.get('pb_schema', 2) < 3]
    if not legacy:
        return
    keys = C.keyframes(context.scene)
    C.validate(context.scene, keys)
    discarded = []
    for root in legacy:
        groups = []
        for morph in C.morphs(context.scene, root):
            group = next((g for g in groups if _same_subject(g[0], morph)), None)
            if group is None:
                groups.append([morph])
            else:
                group.append(morph)
        root['pb_schema'] = 3
        root_name = root.name
        for i, group in enumerate(groups):
            keeper = group[0]
            owner = root if i == 0 else C.create(context, root_name + ' · ' + keeper.name)
            owner['pb_schema'] = 3
            if len(groups) > 1 and i == 0:
                root.name += ' · ' + keeper.name
            world = keeper.matrix_world.copy()
            keeper.parent = owner
            keeper.matrix_world = world
            values, remap = [], {}
            for morph in group:
                for value in C.states(morph):
                    duplicate = next((s for s in values if _equivalent(s, value)), None)
                    if duplicate:
                        remap[value['uid']] = duplicate['uid']
                        discarded.extend(dict(m) for m in value['members'])
                    else:
                        remap[value['uid']] = value['uid']
                        copied = value.to_dict()
                        if value['name'] in {'Start', 'End', 'Intermediate'}:
                            copied['name'] = C.state_label(value)
                        copied['source_name'] = provenance(value)
                        values.append(copied)
            ids = {m[C.MORPH] for m in group}
            for rows in keys.values():
                old = [rows.pop(uid) for uid in list(rows) if uid in ids]
                if old:
                    rows[keeper[C.MORPH]] = dict(old[-1], state=remap[old[-1]['state']])
            keeper['pb_states'] = values
            keeper.name = owner.name
            for morph in group[1:]:
                # The survivor retains the source restoration data. Do not call
                # remove_morph, which would delete the keys we just transferred.
                discarded.extend(dict(r) for r in C.records(morph))
                bpy.data.objects.remove(morph, do_unlink=True)
            for member in C.records(keeper):
                obj = member.get('object')
                if obj:
                    matrix = obj.matrix_world.copy()
                    obj.parent = owner
                    obj.matrix_world = matrix
    C._refresh_owners(context.scene)
    C.compile_animation(context, keys)
    C._discard_snapshots(discarded)
    C.rebuild(context)


def timeline_context(scene, morph, frame, keys=None):
    """Read neighboring keys from the actual shared member animation."""
    uid = morph[C.MORPH]
    relevant = {uid}
    objects = {m.get('object') for m in C.records(morph)} - {None}
    for other in C.morphs(scene):
        if objects.intersection(r.get('object') for r in C.records(other)):
            relevant.add(other[C.MORPH])
    samples = {}
    for f, rows in (C.keyframes(scene) if keys is None else keys).items():
        for key, value in rows.items():
            if key in relevant:
                owner = C.find(scene, key)
                target = C.state(owner, value['state'])
                samples[int(f)] = (C.state_label(target), value.get('transition', 'MORPH'))
    before = max((f for f in samples if f < frame), default=None)
    after = min((f for f in samples if f > frame), default=None)
    return ((before, *samples[before]) if before is not None else None,
            (after, *samples[after]) if after is not None else None)


def clear_preview(scene, remove=False):
    """Restore viewport visibility. Frame handlers only hide preview objects."""
    for obj in list(scene.objects):
        if HIDDEN in obj:
            if obj.name in bpy.context.view_layer.objects:
                obj.hide_set(bool(obj[HIDDEN]))
            del obj[HIDDEN]
        if obj.get(PREVIEW):
            if remove:
                mesh = obj.data
                trees = [m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group]
                bpy.data.objects.remove(obj, do_unlink=True)
                if not mesh.users:
                    bpy.data.meshes.remove(mesh)
                for tree in trees:
                    if not tree.users:
                        bpy.data.node_groups.remove(tree)
            else:
                obj.hide_viewport = True
    if 'pb_conformation_preview' in scene:
        del scene['pb_conformation_preview']


def preview(context, morph, uid):
    value = C.state(morph, uid) if morph else None
    if value is None:
        raise ValueError('Choose an available state to preview.')
    # Check all members before changing any display.
    coords = [C._match(r['mesh'], m['mesh']) for r, m in zip(C.records(morph), value['members'])]
    clear_preview(context.scene, remove=True)
    hidden = {r.get('object') for r in C.records(morph)}
    hidden.update(m.get('original') for s in C.states(morph) for m in s['members'])
    hidden.update(C.outputs(context.scene, morph[C.MORPH]))
    for obj in hidden - {None}:
        if obj.name in context.view_layer.objects:
            obj[HIDDEN] = obj.hide_get()
            obj.hide_set(True)
    for member, positions in zip(C.records(morph), coords):
        mesh = member['mesh'].copy()
        mesh.vertices.foreach_set('co', positions.ravel())
        obj = C._display(context, mesh, 'Preview · ' + member['name'], member['style'], member['color'])
        obj[PREVIEW] = True
        obj.hide_render = True
        obj.matrix_world = morph.matrix_world.copy()
        obj.shape_key_add(name='Basis')
        from .cartoon_motion import stabilize
        stabilize(obj)
    context.scene['pb_conformation_preview'] = dict(morph=morph[C.MORPH], state=uid)
    context.view_layer.update()


@persistent
def end_preview_on_frame(scene, *_):
    if scene.get('pb_conformation_preview'):
        clear_preview(scene)


@persistent
def end_preview_on_save(*_):
    for scene in bpy.data.scenes:
        clear_preview(scene, remove=True)


def register():
    for collection, fn in ((bpy.app.handlers.frame_change_pre, end_preview_on_frame),
                           (bpy.app.handlers.save_pre, end_preview_on_save)):
        if fn not in collection:
            collection.append(fn)


def unregister():
    end_preview_on_save()
    for collection, fn in ((bpy.app.handlers.frame_change_pre, end_preview_on_frame),
                           (bpy.app.handlers.save_pre, end_preview_on_save)):
        if fn in collection:
            collection.remove(fn)
