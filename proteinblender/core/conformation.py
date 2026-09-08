"""Persistent conformational transitions, rendered through ordinary shape keys."""
import json
import uuid

import bpy
import bmesh
import numpy as np
from mathutils import Matrix

from . import structural_alignment as alignment
from .domain_space import get_pivot

TAG = 'pb_conformation'


def transitions(scene):
    return [obj for obj in scene.objects if obj.get(TAG)]


def find(scene, identifier):
    return next((obj for obj in transitions(scene) if obj[TAG] == identifier), None)


def rebuild_outliner(context):
    from ..utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(context)
    if context.screen:
        for area in context.screen.areas:
            area.tag_redraw()


def add_outliner_rows(context, selection):
    scene = context.scene
    for obj in transitions(scene):
        parent = obj.get('pb_start_object')
        parent_row = next((r for r in scene.outliner_items
                           if r.item_type == 'PROTEIN' and parent and r.object_name == parent.name), None)
        if parent_row is None:
            continue
        parent_id = parent_row.item_id
        index = next(i for i, r in enumerate(scene.outliner_items) if r.item_id == parent_id)
        row = scene.outliner_items.add()
        row.item_type = 'TRANSITION'
        row.item_id = obj[TAG]
        row.parent_id = parent_id
        row.name = obj.name
        row.object_name = obj.name
        row.indent_level = 1
        row.icon = 'IPO_EASE_IN_OUT'
        row.is_selected = selection.get(row.item_id, obj.select_get())
        row.tooltip = 'Conformational transition. Open the pencil to scrub, play, or change timing.'
        scene.outliner_items.move(len(scene.outliner_items) - 1, index + 1)


def source_visibility(obj, hide):
    """Reference-count visibility ownership; deleting one transition keeps others isolated."""
    identifier = obj[TAG]
    for record in obj.get('pb_original_objects', []):
        source = record.get('object')
        if source is None:
            continue
        saved = source.get('pb_transition_visibility')
        owners = json.loads(saved['owners']) if saved else []
        if hide and identifier not in owners:
            if not owners:
                source['pb_transition_visibility'] = {
                    'viewport': source.hide_get(), 'render': source.hide_render, 'owners': '[]'}
                saved = source['pb_transition_visibility']
            owners.append(identifier)
            saved['owners'] = json.dumps(owners)
            source.hide_set(True)
            source.hide_render = True
        elif not hide and identifier in owners:
            owners.remove(identifier)
            if owners:
                saved['owners'] = json.dumps(owners)
            else:
                source.hide_set(saved['viewport'])
                source.hide_render = saved['render']
                del source['pb_transition_visibility']
    obj['pb_hide_originals'] = hide


def set_timing(obj, start, duration, smooth=True):
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    end = start + max(1, round(duration * fps))
    keys = obj.data.shape_keys
    old_action = keys.animation_data.action if keys.animation_data else None
    keys.animation_data_clear()
    if old_action and old_action.users == 0:
        bpy.data.actions.remove(old_action)
    key = keys.key_blocks['End conformation']
    for frame, value in ((start, 0.0), (end, 1.0)):
        key.value = value
        key.keyframe_insert('value', frame=frame)
    from ..utils.animation import get_fcurves_from_action
    for curve in get_fcurves_from_action(keys.animation_data.action, keys.animation_data):
        for point in curve.keyframe_points:
            point.interpolation = 'SINE' if smooth else 'LINEAR'
            point.easing = 'EASE_IN_OUT'
    obj['pb_start_frame'], obj['pb_end_frame'] = start, end
    obj['pb_duration'], obj['pb_smooth'] = duration, smooth
    scene.frame_end = max(scene.frame_end, end)
    scene.frame_set(scene.frame_current)


def create(context, source, target, match, start=1, duration=3, smooth=True):
    from ..utils.molecularnodes.blender.nodes import create_starting_node_tree
    from .visual_style import apply_color_to_object
    source_name = getattr(source, 'name', source.identifier)
    target_name = getattr(target, 'name', target.identifier)
    mesh = source.object.data.copy()
    mesh.name = 'Conformational transition atoms'
    if alignment.IDENTITY_KEY in mesh:
        del mesh[alignment.IDENTITY_KEY]
    obj = bpy.data.objects.new(f'{source_name} → {target_name}', mesh)
    context.scene.collection.objects.link(obj)
    obj[TAG] = f'conformation_{uuid.uuid4().hex}'
    try:
        # Keep every named MN attribute and only bonds among retained atoms.
        keep = set(match.source_indices.tolist())
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in keep], context='VERTS')
            bm.to_mesh(mesh)
        finally:
            bm.free()
        pivot = np.asarray(get_pivot(source.object))
        mesh.vertices.foreach_set('co', (match.start - pivot).ravel())
        mesh.update()
        obj.parent = source.object
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        obj.shape_key_add(name='Start conformation')
        key = obj.shape_key_add(name='End conformation')
        key.data.foreach_set('co', (match.end - pivot).ravel())
        create_starting_node_tree(object=obj, style='cartoon', color='common')
        from .cartoon_motion import stabilize
        stabilize(obj)
        apply_color_to_object(obj, (.25, .65, .9, 1.0))
        obj['pb_start_object'], obj['pb_end_object'] = source.object, target.object
        obj['pb_match'] = json.dumps(match.summary, separators=(',', ':'))
        obj['pb_start_label'], obj['pb_end_label'] = source_name, target_name
        obj['pb_transition_style'] = 'cartoon'
        originals = []
        for molecule in (source, target):
            originals += [molecule.object] + [d.object for d in molecule.domains.values() if d.object]
        obj['pb_original_objects'] = [{'object': original} for original in dict.fromkeys(originals)]
        set_timing(obj, start, duration, smooth)
        source_visibility(obj, True)
        rebuild_outliner(context)
        return obj
    except Exception:
        remove(context, obj, rebuild=False)
        raise


def remove(context, obj, rebuild=True):
    source_visibility(obj, False)
    mesh = obj.data
    action = (mesh.shape_keys.animation_data.action
              if mesh.shape_keys and mesh.shape_keys.animation_data else None)
    trees = [m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group]
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    for tree in trees:
        if tree.users == 0:
            bpy.data.node_groups.remove(tree)
    if action and action.users == 0:
        bpy.data.actions.remove(action)
    if rebuild:
        rebuild_outliner(context)


def clear_for_source(context, source):
    for obj in transitions(context.scene):
        if obj.get('pb_start_object') == source:
            remove(context, obj, rebuild=False)
