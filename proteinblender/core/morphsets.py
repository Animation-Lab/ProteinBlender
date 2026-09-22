"""Reusable morph definitions, with independently keyed states and visibility.

A Morphset groups morphs. Morphs can share members and contribute named states
to one animation per member. No coordinates are fitted or aligned here.
"""
import json
import uuid

import bmesh
import bpy
import numpy as np
from mathutils import Matrix

from . import structural_alignment as identity
from .domain_space import get_pivot
from ..utils.animation import get_fcurves_from_action, remove_fcurve_from_action

TAG = 'pb_morphset'
MORPH = 'pb_morph'
TRACK = 'pb_morphset_track'
OUTPUT = 'pb_morphset_output'


def sets(scene):
    return sorted((o for o in scene.objects if o.get(TAG)), key=lambda o: o.get('pb_order', 0))


def morphs(scene, root=None):
    return sorted((o for o in scene.objects if o.get(MORPH) and
                   (root is None or o.parent == root)), key=lambda o: o.get('pb_order', 0))


def find(scene, uid):
    return next((o for o in scene.objects if o.get(TAG) == uid or o.get(MORPH) == uid), None)


def states(morph):
    return list(morph.get('pb_states', ()))


def state(morph, uid):
    return next((s for s in states(morph) if s['uid'] == uid), None)


def records(obj):
    if obj.get(MORPH):
        return list(obj.get('pb_members', ()))
    return [m for child in obj.children if child.get(MORPH) for m in records(child)]


def track(scene, create=False):
    obj = next((o for o in scene.objects if o.get(TRACK)), None)
    if obj is None and create:
        obj = bpy.data.objects.new('Morphset keyframes', None)
        scene.collection.objects.link(obj)
        obj[TRACK] = True
    return obj


def outputs(scene, uid=None):
    return sorted((o for o in scene.objects if o.get(OUTPUT) and
                   (uid is None or output_slot(o, uid) is not None)),
                  key=lambda o: (o.get('pb_morph_order', 0), o['pb_slot']))


def output_slot(obj, uid):
    """An animated member can be referenced by several morph definitions."""
    if 'pb_morph_bindings' in obj:
        return next((b['slot'] for b in obj['pb_morph_bindings'] if b['uid'] == uid), None)
    return obj.get('pb_slot') if obj.get('pb_morph_uid') == uid else None


def _member_bindings(scene, obj, exclude=None):
    return [(morph, member) for morph in morphs(scene) if morph != exclude
            for member in records(morph) if member.get('object') == obj]


def _refresh_owners(scene):
    """Keep a representative owner for hierarchy bookkeeping, without exclusivity."""
    references = {}
    for morph in morphs(scene):
        objects = {m.get('object') for m in records(morph)}
        objects.update(m.get('original') for s in states(morph) for m in s['members'])
        for obj in objects - {None}:
            references.setdefault(obj, []).append(morph)
    for obj in scene.objects:
        candidates = references.get(obj, [])
        if candidates:
            if obj.get('pb_morphset_owner') not in candidates:
                obj['pb_morphset_owner'] = candidates[0]
        elif 'pb_morphset_owner' in obj:
            del obj['pb_morphset_owner']


def keyframes(scene):
    obj = track(scene)
    return json.loads(obj.get('pb_morph_keys', '{}')) if obj else {}


def morph_keys(scene, uid, keys=None):
    return {f: rows[uid] for f, rows in (keyframes(scene) if keys is None else keys).items() if uid in rows}


def rebuild(context):
    from ..utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(context)
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def create(context, name):
    root = bpy.data.objects.new(name.strip() or 'Morphset', None)
    context.scene.collection.objects.link(root)
    root[TAG] = uuid.uuid4().hex
    root['pb_schema'] = 2
    root['pb_order'] = len(sets(context.scene))
    rebuild(context)
    return root


def _capture(context, row_ids, model='', origin=None, world_matrix=None):
    from .outliner_targets import resolve_target
    from .visual_style import get_object_style, get_object_color
    context.view_layer.update()
    members, seen = [], set()
    try:
        for row_id in row_ids:
            mol, objects = resolve_target(row_id, include_protein_domains=True)
            if mol is None or mol.object.get('pb_is_nucleic_acid'):
                raise ValueError('Choose protein chains or domains for this morph.')
            if row_id == mol.identifier:
                objects = [d.object for d in mol.domains.values() if d.object]
            if origin is None:
                origin = list(get_pivot(mol.object))
            for obj in objects:
                if obj.name in seen:
                    continue
                seen.add(obj.name)
                if obj.parent and any(r.item_type == 'PUPPET' and
                        r.controller_object_name == obj.parent.name for r in context.scene.outliner_items):
                    raise ValueError('Remove this member from its puppet before adding a morph.')
                shared = _member_bindings(context.scene, obj)
                label = shared[0][1]['name'] if shared else next((r.name for r in context.scene.outliner_items
                    if r.object_name == obj.name and r.item_type in {'CHAIN', 'DOMAIN'}), obj.name)
                mesh = _snapshot(mol, obj, model, origin,
                                 world_matrix(obj) if world_matrix else None)
                members.append(dict(mesh=mesh, source=mol.object, original=obj,
                                    row_id=row_id, name=label, style=get_object_style(obj) or 'cartoon',
                                    color=list(get_object_color(obj))))
        if not members:
            raise ValueError('Select at least one protein, chain or domain.')
        return members, origin
    except Exception:
        _discard_snapshots(members)
        raise


def _discard_snapshots(members):
    for member in members:
        mesh = member.get('mesh')
        if mesh and not mesh.users:
            bpy.data.meshes.remove(mesh)


def _validate_members(base, members):
    if len(base) != len(members):
        raise ValueError('States in a morph must contain the same number of chains/domains, in matching order.')
    for a, b in zip(base, members):
        _match(a['mesh'], b['mesh'])


def _state_definition(uid, name, members, model):
    source = members[0].get('source') if members else None
    library = source.pb_conformations.states if source else []
    label = next((s.name for s in library if s.uid == model), 'Current structure')
    return dict(uid=uid, name=name, members=members, model_uid=model, model_name=label)


def state_label(value):
    """Human-readable names include the captured PDB model, never internal IDs."""
    name, model = value['name'], value.get('model_name', '')
    if model and model != 'Current structure':
        if name in {'Start', 'End', 'Intermediate', model}:
            return model
        return f'{name} ({model})'
    return name


def add_morph(context, root, name, start_ids, end_ids, start_model='', end_model='',
              start_name='Start', end_name='End'):
    if root is None or not root.get(TAG):
        raise ValueError('Choose a Morphset first.')
    first, origin = _capture(context, start_ids, start_model)
    last = []
    try:
        last, _ = _capture(context, end_ids, end_model, origin)
        _validate_members(first, last)
    except Exception:
        _discard_snapshots(first + last)
        raise
    definitions = [
        _state_definition(uuid.uuid4().hex, start_name.strip() or 'Start', first, start_model),
        _state_definition(uuid.uuid4().hex, end_name.strip() or 'End', last, end_model)]
    return _install_morph(context, root, name, definitions, origin)


def _install_morph(context, root, name, definitions, origin):
    """Install validated snapshots; also used by automatic imported-model sets."""
    morph = bpy.data.objects.new(name.strip() or 'Morph', None)
    context.scene.collection.objects.link(morph)
    morph.parent = root
    morph[MORPH] = uuid.uuid4().hex
    morph['pb_origin'] = origin
    morph['pb_order'] = max((m.get('pb_order', 0) for m in morphs(context.scene)), default=0) + 1
    morph['pb_states'] = definitions
    members = []
    for source in definitions[0]['members']:
        obj = source['original']
        existing = _member_bindings(context.scene, obj)
        member = dict(source, object=obj, generated=False, render=obj.hide_render,
                      viewport=obj.hide_viewport, hidden=obj.hide_get(),
                      parent_inverse=[v for row in obj.matrix_parent_inverse for v in row])
        if existing:
            # Every row needs the original restoration data, not the parent
            # or hidden state applied by another morph currently using it.
            previous = existing[0][1]
            for key in ('generated', 'render', 'viewport', 'hidden', 'parent_inverse', 'parent',
                        'display_pivot', 'display_matrix'):
                if key in previous:
                    member[key] = previous[key]
        else:
            if obj.parent:
                member['parent'] = obj.parent
            matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = matrix
        members.append(member)
    morph['pb_members'] = members
    _refresh_owners(context.scene)
    # New definitions must resolve to an existing shared output immediately,
    # even before the new row receives its first keyframe.
    if keyframes(context.scene):
        compile_animation(context, keyframes(context.scene))
    rebuild(context)
    return morph


def add_state(context, morph, name, row_ids, model=''):
    if morph is None or not morph.get(MORPH):
        raise ValueError('Choose a morph first.')
    members, _ = _capture(context, row_ids, model, morph['pb_origin'])
    try:
        _validate_members(records(morph), members)
    except Exception:
        _discard_snapshots(members)
        raise
    value = _state_definition(uuid.uuid4().hex, name.strip() or 'Intermediate', members, model)
    values = [s.to_dict() for s in states(morph)]
    values.insert(len(values) - 1, value)
    morph['pb_states'] = values
    _refresh_owners(context.scene)
    _hide_members(context.scene, keyframes(context.scene))
    rebuild(context)
    return value['uid']


def edit_state(context, morph, uid, name, row_ids=None, model=''):
    """Replace a state's snapshot without changing its identity or keyed times."""
    if morph is None or not morph.get(MORPH) or state(morph, uid) is None:
        raise ValueError('Choose an available morph state.')
    current = state(morph, uid)
    if row_ids is None:
        current['name'] = name.strip() or current['name']
        rebuild(context)
        return
    members, _ = _capture(context, row_ids, model, morph['pb_origin'])
    try:
        _validate_members(records(morph), members)
        replacement = _state_definition(uid, name.strip() or current['name'], members, model)
        # A model edit can conflict with another row's key at the same frame.
        # Validate the proposed snapshot before changing any saved definition.
        validate(context.scene, keyframes(context.scene), {(morph[MORPH], uid): replacement})
    except Exception:
        _discard_snapshots(members)
        raise
    previous = current.to_dict()
    # Copy all nested records before replacing the owning IDProperty array.
    morph['pb_states'] = [replacement if s['uid'] == uid else s.to_dict() for s in states(morph)]
    _refresh_owners(context.scene)
    keys = keyframes(context.scene)
    if morph_keys(context.scene, morph[MORPH], keys):
        compile_animation(context, keys)
    else:
        _hide_members(context.scene, keys)
    _discard_snapshots(previous['members'])
    rebuild(context)


def remove_state(context, morph, uid):
    values = states(morph)
    index = next((i for i, s in enumerate(values) if s['uid'] == uid), -1)
    if index <= 0 or index == len(values) - 1:
        raise ValueError('Keep the Start and End states; use their pencils to change the models or names.')
    if any(v['state'] == uid for v in morph_keys(context.scene, morph[MORPH]).values()):
        raise ValueError('Remove or change the keyframes using this state before removing it.')
    members = [dict(m) for m in values[index]['members']]
    morph['pb_states'] = [s.to_dict() for s in values if s['uid'] != uid]
    _release_unused_sources(context.scene, morph)
    _discard_snapshots(members)
    rebuild(context)


def _release_unused_sources(scene, morph):
    _refresh_owners(scene)


def _hide_members(scene, keys):
    targets = set()
    owned = {m.get('object') for morph in morphs(scene) for m in records(morph)}
    for morph in morphs(scene):
        if not morph_keys(scene, morph[MORPH], keys):
            continue
        targets.update(m.get('object') for m in records(morph))
        targets.update(m.get('original') for s in states(morph) for m in s['members'])
    backup = 'pb_morphset_visibility'
    for obj in scene.objects:
        if obj in targets:
            if backup not in obj:
                obj[backup] = dict(viewport=obj.hide_viewport, render=obj.hide_render,
                                   hidden=obj.hide_get() if obj.name in bpy.context.view_layer.objects else False)
            obj.hide_viewport = obj.hide_render = True
            if obj.name in bpy.context.view_layer.objects:
                obj.hide_set(True)
        elif backup in obj:
            saved = obj[backup]
            obj.hide_viewport, obj.hide_render = saved['viewport'], saved['render']
            if obj.name in bpy.context.view_layer.objects:
                obj.hide_set(saved['hidden'])
            del obj[backup]
        if obj not in targets and 'pb_morphset_hidden' in obj:
            obj.hide_viewport = obj.hide_render = bool(obj['pb_morphset_hidden'])
            if obj.name in bpy.context.view_layer.objects:
                obj.hide_set(bool(obj['pb_morphset_hidden']))
            if obj not in owned:
                # Once detached, the ordinary chain controls own visibility.
                # They use hide_set, so don't leave the object globally disabled.
                obj.hide_viewport = False
                del obj['pb_morphset_hidden']


def row_member(scene, item_id):
    """Resolve a member row without retaining rebuildable Outliner RNA data."""
    uid, separator, slot = item_id.rpartition(':')
    morph = find(scene, uid) if separator else None
    if morph and slot.isdigit() and int(slot) < len(records(morph)):
        return records(morph)[int(slot)]
    return None


def member_visible(scene, item_id):
    member = row_member(scene, item_id)
    obj = member.get('object') if member is not None else None
    if obj is None:
        return True
    if 'pb_morphset_hidden' in obj:
        return not obj['pb_morphset_hidden']
    if 'pb_morphset_visibility' in obj:
        return True  # The source is hidden because an animated output replaces it.
    return not obj.hide_get()


def set_member_visible(context, item_id, visible):
    """Manual eye override; retain the visibility chosen at each keyframe."""
    scene = context.scene
    member = row_member(scene, item_id)
    source = member.get('object') if member is not None else None
    if source is None:
        return
    source['pb_morphset_hidden'] = not visible
    bindings = _member_bindings(scene, source)
    for obj in outputs(scene):
        samples = {}
        for morph, bound in bindings:
            slot = output_slot(obj, morph[MORPH])
            if slot is None or records(morph)[slot].get('object') != source:
                continue
            for frame, value in morph_keys(scene, morph[MORPH]).items():
                samples[int(frame)] = value['visible'][slot]
        for frame, keyed_visible in sorted(samples.items()):
            obj.hide_viewport = obj.hide_render = not (visible and keyed_visible)
            obj.keyframe_insert('hide_viewport', frame=frame)
            obj.keyframe_insert('hide_render', frame=frame)
        if samples:
            _interpolation(obj, 'CONSTANT')
    _hide_members(scene, keyframes(scene))
    scene.frame_set(scene.frame_current)
    context.view_layer.update()


def _snapshot(molecule, obj, state_uid='', origin=(0, 0, 0), matrix=None):
    from .conformation_library import state, read_mesh
    ident = identity.read_identity(molecule)
    domain = next((d for d in molecule.domains.values() if d.object == obj), None)
    mask = np.ones(len(ident.chain), dtype=bool)
    if domain:
        chain = molecule._resolve_chain_socket_name(domain.chain_id)
        mask = ((np.asarray(ident.chain) == chain) &
                (np.asarray(ident.residue) >= domain.start) &
                (np.asarray(ident.residue) <= domain.end))
    indices = np.flatnonzero(mask)
    if not len(indices):
        raise ValueError('This member contains no atoms.')
    coords = read_mesh(state(molecule, state_uid).mesh if state_uid else molecule.object.data)
    matrix = np.asarray(obj.matrix_world if matrix is None else matrix)
    coords = (coords[mask] - np.asarray(get_pivot(obj))) @ matrix[:3, :3].T + matrix[:3, 3]
    # Undo import-only centering using one common origin for every state.
    coords += np.asarray(get_pivot(molecule.object)) - np.asarray(origin)
    if not np.isfinite(coords).all():
        raise ValueError('A Morphset member contains invalid coordinates.')
    chains = list(dict.fromkeys(np.asarray(ident.chain)[mask]))
    keys = [(chains.index(ident.chain[i]), ident.residue[i], ident.insertion[i],
             ident.residue_name[i], ident.atom_name[i], ident.element[i]) for i in indices]
    if len(set(keys)) != len(keys):
        raise ValueError('Resolve duplicate atom identities before making a Morphset.')
    mesh = molecule.object.data.copy()
    # Snapshots never carry source animation or another mesh's shape keys.
    if mesh.shape_keys:
        bpy.data.meshes.remove(mesh)
        raise ValueError('Import an unanimated structure before creating this Morphset.')
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not mask[v.index]], context='VERTS')
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.vertices.foreach_set('co', coords.ravel())
    mesh['pb_morph_atom_keys'] = json.dumps(keys)
    mesh.update()
    return mesh


def _display(context, mesh, name, style, color):
    from ..utils.molecularnodes.blender.nodes import create_starting_node_tree
    from .visual_style import apply_color_to_object
    obj = bpy.data.objects.new(name, mesh)
    context.scene.collection.objects.link(obj)
    create_starting_node_tree(object=obj, style=style or 'cartoon', color='common')
    apply_color_to_object(obj, color)
    return obj


def _coordinates(mesh):
    coords = np.empty((len(mesh.vertices), 3), dtype=float)
    mesh.vertices.foreach_get('co', coords.ravel())
    return coords


def _match(base, target):
    a = [tuple(k) for k in json.loads(base['pb_morph_atom_keys'])]
    b = [tuple(k) for k in json.loads(target['pb_morph_atom_keys'])]
    if len(a) != len(b) or set(a) != set(b):
        raise ValueError('Morphset members must have matching residues and atoms in the same member order. Prepare matching, aligned PDBs first.')
    lookup = {key: i for i, key in enumerate(b)}
    return _coordinates(target)[[lookup[key] for key in a]]


def _remove_outputs(scene, uid=None):
    for obj in outputs(scene, uid):
        mesh = obj.data
        trees = [m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group]
        object_action = obj.animation_data.action if obj.animation_data else None
        action = mesh.shape_keys.animation_data.action if mesh.shape_keys and mesh.shape_keys.animation_data else None
        action_names = {a.name for a in (action, object_action) if a}
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        for tree in trees:
            if not tree.users:
                bpy.data.node_groups.remove(tree)
        # Blender can share one action between object and shape-key slots.
        # Deduplicate names and resolve again after each datablock removal.
        for name in action_names:
            owned_action = bpy.data.actions.get(name)
            if owned_action and not owned_action.users:
                bpy.data.actions.remove(owned_action)


def _interpolation(data, kind):
    ad = data.animation_data
    if ad and ad.action:
        for curve in get_fcurves_from_action(ad.action, ad):
            for point in curve.keyframe_points:
                point.interpolation = kind


def _clear_curves(obj):
    """Keep surviving controllers' action/slot bindings stable across key edits."""
    ad = obj.animation_data
    if ad and ad.action:
        action = ad.action
        for curve in list(get_fcurves_from_action(action, ad)):
            remove_fcurve_from_action(action, curve, ad)
        action.update_tag()
        obj.update_tag(refresh={'OBJECT'})


def _animation_groups(scene, keys, replacements):
    groups = {}
    for morph in morphs(scene):
        uid = morph[MORPH]
        for slot, member in enumerate(records(morph)):
            body = member.get('object') or (uid, slot)
            groups.setdefault(body, []).append(dict(morph=morph, uid=uid, slot=slot, member=member))
    result = []
    for bindings in groups.values():
        active = [b for b in bindings if morph_keys(scene, b['uid'], keys)]
        if not active:
            continue
        base = active[0]
        samples, shapes = {}, {}
        for binding in active:
            morph, uid, slot = binding['morph'], binding['uid'], binding['slot']
            offset = np.asarray(morph['pb_origin']) - np.asarray(base['morph']['pb_origin'])
            for frame, value in morph_keys(scene, uid, keys).items():
                target = replacements.get((uid, value['state'])) or state(morph, value['state'])
                shape = value['state']
                if shape not in shapes:
                    shapes[shape] = _match(base['member']['mesh'], target['members'][slot]['mesh']) + offset
                visible = bool(value['visible'][slot])
                previous = samples.get(int(frame))
                if previous and (previous['visible'] != visible or not np.allclose(
                        shapes[previous['state']], shapes[shape], atol=1e-6, rtol=0)):
                    raise ValueError(
                        f"Frame {frame}: {previous['name']} and {morph.name} assign different states or "
                        f"visibility to {base['member']['name']}. Edit or remove one of those keys.")
                if previous is None:
                    samples[int(frame)] = dict(state=shape, visible=visible, name=morph.name)
        result.append(dict(base=base, bindings=bindings, samples=samples, shapes=shapes))
    return result


def validate(scene, keys, replacements=None):
    replacements = replacements or {}
    for frame, rows in keys.items():
        if int(frame) < 1:
            raise ValueError('Frames must be positive.')
        for uid, value in rows.items():
            morph = find(scene, uid)
            if morph is None or not morph.get(MORPH):
                raise ValueError('A keyframe refers to a deleted morph.')
            target = replacements.get((uid, value['state'])) or state(morph, value['state'])
            if target is None:
                raise ValueError('Choose an available state for each checked morph.')
            _validate_members(records(morph), target['members'])
            if len(value.get('visible', [])) != len(records(morph)):
                raise ValueError('Choose visibility for every member of the morph.')
    return _animation_groups(scene, keys, replacements)


def compile_animation(context, keys):
    scene = context.scene
    groups = validate(scene, keys)  # Validate all changes before replacing any animation.
    from .morph_member_pivots import preserve_outputs, restore_output
    preserve_outputs(scene)
    controller = track(scene, True)
    _remove_outputs(scene)
    _clear_curves(controller)
    controller['pb_morph_keys'] = json.dumps(keys)
    for morph in morphs(scene):
        uid = morph[MORPH]
        keyed = morph_keys(scene, uid, keys)
        _clear_curves(morph)
        for frame, value in keyed.items():
            morph['active_state'] = next(i for i, s in enumerate(states(morph)) if s['uid'] == value['state'])
            morph.keyframe_insert('["active_state"]', frame=int(frame))
        _interpolation(morph, 'CONSTANT')
    for group in groups:
        base = group['base']
        morph, member = base['morph'], base['member']
        obj = _display(context, member['mesh'].copy(), morph.name + ' · ' + member['name'],
                       member['style'], member['color'])
        obj[OUTPUT] = True
        obj['pb_morph_member_object'] = member['object']
        obj['pb_morph_uid'], obj['pb_slot'] = base['uid'], base['slot']
        obj['pb_morph_bindings'] = [dict(uid=b['uid'], slot=b['slot']) for b in group['bindings']]
        obj['pb_morph_order'] = morph['pb_order']
        obj.parent = morph
        obj.shape_key_add(name='Basis')
        for uid, coords in group['shapes'].items():
            key = obj.shape_key_add(name=uid)
            key.data.foreach_set('co', coords.ravel())
        from .cartoon_motion import stabilize
        stabilize(obj)
        restore_output(obj, member)
        if member.get('source') and member['source'].get('pb_bfactor_enabled'):
            from .thermal_motion import prepare, install
            prepare(obj.data)
            install(obj)
        for frame, value in sorted(group['samples'].items()):
            for uid in group['shapes']:
                key = obj.data.shape_keys.key_blocks[uid]
                key.value = float(value['state'] == uid)
                key.keyframe_insert('value', frame=frame)
            hidden = bool(member.get('object') and member['object'].get('pb_morphset_hidden'))
            obj.hide_viewport = obj.hide_render = hidden or not value['visible']
            obj.keyframe_insert('hide_viewport', frame=frame)
            obj.keyframe_insert('hide_render', frame=frame)
        _interpolation(obj.data.shape_keys, 'LINEAR')
        _interpolation(obj, 'CONSTANT')
    _hide_members(scene, keys)
    if keys:
        scene.frame_end = max(scene.frame_end, max(map(int, keys)))
    scene.frame_set(scene.frame_current)
    context.view_layer.update()


def insert_keys(context, frame, rows):
    keys = keyframes(context.scene)
    values = keys.setdefault(str(frame), {})
    values.update(rows)  # Unchecked morphs retain their existing keys.
    compile_animation(context, keys)


def delete_key(context, frame, uid=None):
    keys = keyframes(context.scene)
    if uid is None:
        keys.pop(str(frame), None)
    elif str(frame) in keys:
        keys[str(frame)].pop(uid, None)
        if not keys[str(frame)]:
            del keys[str(frame)]
    compile_animation(context, keys)


def sync_style(scene, source, style):
    from .visual_style import apply_style_to_object
    for morph in morphs(scene):
        slots = {slot for s in states(morph) for slot, m in enumerate(s['members'])
                 if source == m.get('original')}
        slots.update(slot for slot, m in enumerate(records(morph)) if source == m.get('object'))
        for slot in slots:
            records(morph)[slot]['style'] = style
            obj = records(morph)[slot].get('object')
            if obj and obj != source:
                apply_style_to_object(obj, style, sync_morphsets=False)
        for obj in outputs(scene, morph[MORPH]):
            if output_slot(obj, morph[MORPH]) in slots:
                apply_style_to_object(obj, style, sync_morphsets=False)


def sync_color(scene, source, color):
    from .visual_style import apply_color_to_object
    for morph, member in _member_bindings(scene, source):
        member['color'] = list(color)
        for obj in outputs(scene, morph[MORPH]):
            slot = output_slot(obj, morph[MORPH])
            if slot is not None and records(morph)[slot].get('object') == source:
                apply_color_to_object(obj, color, sync_morphsets=False)


def remove_morph(context, morph):
    uid = morph[MORPH]
    keys = {f: {k: v for k, v in rows.items() if k != uid}
            for f, rows in keyframes(context.scene).items()}
    keys = {f: rows for f, rows in keys.items() if rows}
    validate(context.scene, keys)
    for member in records(morph):
        obj = member.get('object')
        if not obj:
            continue
        shared = _member_bindings(context.scene, obj, exclude=morph)
        if shared:
            matrix = obj.matrix_world.copy()
            obj.parent = shared[0][0].parent
            obj.matrix_world = matrix
            continue
        if member.get('generated'):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if not data.users:
                bpy.data.meshes.remove(data)
        else:
            if morph.parent.get('pb_model_morphset'):
                from .model_morphsets import world_matrix
                matrix = world_matrix(obj)
            else:
                matrix = obj.matrix_world.copy()
            obj.parent = member.get('parent')
            obj.matrix_parent_inverse = Matrix(np.asarray(member['parent_inverse']).reshape(4, 4))
            obj.matrix_world = matrix
    meshes = {m['mesh'] for s in states(morph) for m in s['members']}
    meshes.update(m['mesh'] for m in records(morph))
    bpy.data.objects.remove(morph, do_unlink=True)
    _refresh_owners(context.scene)
    compile_animation(context, keys)
    for mesh in meshes:
        if not mesh.users:
            bpy.data.meshes.remove(mesh)
    rebuild(context)


def remove(context, root):
    for morph in morphs(context.scene, root):
        remove_morph(context, morph)
    bpy.data.objects.remove(root, do_unlink=True)
    if not sets(context.scene):
        controller = track(context.scene)
        if controller:
            bpy.data.objects.remove(controller, do_unlink=True)
    rebuild(context)


def add_outliner_rows(context, selection, expansion):
    _migrate_v1(context)
    scene = context.scene
    owned = {m['object'].name for morph in morphs(scene) for m in records(morph) if m.get('object')}
    for index in reversed(range(len(scene.outliner_items))):
        row = scene.outliner_items[index]
        if row.object_name in owned and row.item_type in {'CHAIN', 'DOMAIN'}:
            scene.outliner_items.remove(index)
    for index in reversed(range(len(scene.outliner_items))):
        row = scene.outliner_items[index]
        if row.item_type == 'CHAIN' and row.has_domains and not any(
                child.parent_id == row.item_id for child in scene.outliner_items):
            scene.outliner_items.remove(index)
    for root in sets(scene):
        source = root.get('pb_model_source')
        parent = next((r for r in scene.outliner_items if r.item_type == 'PROTEIN'
                       and source and r.object_name == source.name), None)
        parent_id = parent.item_id if parent else ''
        depth = parent.indent_level + 1 if parent else 0
        row = scene.outliner_items.add()
        row.item_type, row.item_id, row.name = 'MORPHSET', root[TAG], root.name
        row.object_name, row.icon = root.name, 'IPO_EASE_IN_OUT'
        row.parent_id, row.indent_level = parent_id, depth
        row.is_expanded = expansion.get(root[TAG], True)
        row.is_selected = selection.get(root[TAG], False)
        block_ids = [root[TAG]]
        for morph in morphs(scene, root):
            for slot, member in enumerate(records(morph)):
                obj = member.get('object')
                if not obj:
                    continue
                child = scene.outliner_items.add()
                child.item_type = 'MORPH_MEMBER'
                child.item_id = morph[MORPH] + ':' + str(slot)
                child.parent_id = root[TAG]
                child.object_name = obj.name
                child.name = member['name'] if root.get('pb_model_morphset') else morph.name + ' · ' + member['name']
                child.indent_level = depth + 1
                child.icon = 'GROUP_VERTEX'
                child.is_selected = selection.get(child.item_id, False)
                block_ids.append(child.item_id)
        if parent_id:
            # UIList displays collection order, not a sorted tree. Place the
            # entire block inside its protein, before the next top-level row.
            items = scene.outliner_items
            start = next(i for i, r in enumerate(items) if r.item_id == parent_id)
            insertion = next((i for i in range(start + 1, len(items))
                              if items[i].indent_level < depth or items[i].item_id == root[TAG]), len(items))
            for offset, uid in enumerate(block_ids):
                index = next(i for i, r in enumerate(items) if r.item_id == uid)
                items.move(index, insertion + offset)


def preserve_for_source(context, source):
    preserved = {}
    for morph in morphs(context.scene):
        members = [dict(m) for m in records(morph)]
        changed = False
        for member in members:
            if member.get('source') != source or member.get('generated'):
                continue
            original = member.get('object')
            if original:
                obj = preserved.get(original)
                if obj is None:
                    obj = _display(context, member['mesh'].copy(), member['name'], member['style'], member['color'])
                    obj.parent = morph.parent
                    obj['pb_morphset_owner'] = morph
                    obj.hide_viewport, obj.hide_render = original.hide_viewport, original.hide_render
                    if 'pb_morphset_visibility' in original:
                        obj['pb_morphset_visibility'] = dict(original['pb_morphset_visibility'])
                    if 'pb_morphset_hidden' in original:
                        obj['pb_morphset_hidden'] = original['pb_morphset_hidden']
                    preserved[original] = obj
                member['object'], member['generated'] = obj, True
                member.pop('parent', None)
                changed = True
        if changed:
            morph['pb_members'] = members


def row_has_keys(scene, item):
    if item.item_type == 'MORPH_MEMBER':
        uid, slot = item.item_id.rsplit(':', 1)
        return any(output_slot(obj, uid) == int(slot) for obj in outputs(scene, uid))
    root = find(scene, item.item_id)
    return bool(root and any(outputs(scene, m[MORPH]) for m in morphs(scene, root)))


def row_object(scene, item):
    if item.item_type == 'MORPH_MEMBER':
        uid, slot = item.item_id.rsplit(':', 1)
        obj = next((o for o in outputs(scene, uid) if output_slot(o, uid) == int(slot)), None)
        if obj:
            return obj
    return bpy.data.objects.get(item.object_name)


def _migrate_v1(context):
    """Preserve the previous snapshot-per-set files as named morph states.

    Compatible old sets become one morph. Incompatible, unkeyed sets get
    separate definitions, so opening a file never discards captured geometry.
    Runs during hierarchy reconstruction, outside panel draw callbacks.
    """
    scene = context.scene
    legacy = [r for r in sets(scene) if 'pb_members' in r and not r.get('pb_schema')]
    if not legacy:
        return
    controller = track(scene)
    old_keys = keyframes(scene)
    groups = []
    for root in legacy:
        for group in groups:
            try:
                _validate_members(list(group[0]['pb_members']), list(root['pb_members']))
            except ValueError:
                continue
            group.append(root)
            break
        else:
            groups.append([root])
    mapping = {}
    for group in groups:
        root = group[0]
        morph = bpy.data.objects.new('Imported morph', None)
        scene.collection.objects.link(morph)
        morph.parent = root
        morph[MORPH] = uuid.uuid4().hex
        morph['pb_order'] = len(morphs(scene))
        morph['pb_origin'] = list(controller.get('pb_origin', (0, 0, 0))) if controller else [0, 0, 0]
        members = [dict(m) for m in root['pb_members']]
        if controller:
            overrides = controller.get('pb_morphset_styles', {})
            for slot, member in enumerate(members):
                member['style'] = overrides.get(str(slot), member['style'])
        morph['pb_members'] = members
        values = []
        for old in group:
            values.append(dict(uid=old[TAG], name=old.name, members=[
                {k: v for k, v in dict(m).items() if k in
                 {'mesh', 'source', 'original', 'row_id', 'name', 'style', 'color'}}
                for m in old['pb_members']]))
            mapping[old[TAG]] = (morph[MORPH], old[TAG])
            if old != root:
                for m in old['pb_members']:
                    obj = m.get('object')
                    if not obj:
                        continue
                    if m.get('generated'):
                        mesh = obj.data
                        bpy.data.objects.remove(obj, do_unlink=True)
                        if not mesh.users:
                            bpy.data.meshes.remove(mesh)
                    else:
                        matrix = obj.matrix_world.copy()
                        obj.parent = m.get('parent')
                        obj.matrix_parent_inverse = Matrix(np.asarray(m['parent_inverse']).reshape(4, 4))
                        obj.matrix_world = matrix
                bpy.data.objects.remove(old, do_unlink=True)
        if len(values) == 1:
            values.append(dict(values[0], uid=uuid.uuid4().hex, name='End'))
        morph['pb_states'] = values
        for value in states(morph):
            for member in value['members']:
                obj = member.get('original')
                if obj:
                    obj['pb_morphset_owner'] = morph
        for member in records(morph):
            if member.get('object'):
                member['object']['pb_morphset_owner'] = morph
        root['pb_schema'] = 2
        del root['pb_members']
        root.name = 'Imported Morphset' if len(group) > 1 else root.name
    converted = {}
    for frame, value in old_keys.items():
        if 'set' in value and value['set'] in mapping:
            uid, state_uid = mapping[value['set']]
            converted[frame] = {uid: dict(state=state_uid, visible=value['visible'])}
        elif 'set' not in value:
            converted[frame] = value
    compile_animation(context, converted)
