"""Puppet components and parenting, shared by create and edit dialogs."""
import bpy
from mathutils import Matrix


def is_component(item):
    # A Morphset owns its source chains and generated geometry as one unit.
    return (item.item_type in {'CHAIN', 'DOMAIN', 'MORPHSET'}
            and not item.reference_target_id and '_ref_' not in item.item_id)


def component_objects(item):
    if item.item_type == 'MORPHSET':
        obj = bpy.data.objects.get(item.object_name)
        return [obj] if obj else []
    from .outliner_targets import resolve_target
    return resolve_target(item.item_id)[1]


def components(scene):
    return [item for item in scene.outliner_items if is_component(item)]


def validate_members(scene, ids, puppet_id=''):
    """Resolve and validate the entire edit before mutating the scene."""
    by_id = {item.item_id: item for item in components(scene)}
    rows = []
    for uid in dict.fromkeys(ids):
        item = by_id.get(uid)
        if item is None:
            raise ValueError('Choose chains, domains, or whole Morphsets as puppet members.')
        objects = component_objects(item)
        if not objects:
            raise ValueError(f'{item.name}: no objects available.')
        if item.item_type != 'MORPHSET' and any(o.get('pb_morphset_owner') for o in objects):
            raise ValueError(f'{item.name} contains Morphset members. Choose the whole Morphset '
                             'or the remaining individual domains.')
        for puppet in scene.outliner_items:
            if puppet.item_type != 'PUPPET' or puppet.item_id in {puppet_id, 'puppets_separator'}:
                continue
            if (uid in puppet.puppet_memberships.split(',') or
                    any(o.parent and o.parent.name == puppet.controller_object_name for o in objects)):
                raise ValueError(f'{item.name} is already in puppet "{puppet.name}".')
        rows.append(item)
    return rows


def attach(obj, controller):
    from .model_morphsets import world_matrix
    world = world_matrix(obj)
    basis = obj.matrix_basis.copy()
    if obj.get('pb_morphset') and obj.parent != controller:
        if obj.parent:
            obj['pb_puppet_previous_parent'] = obj.parent
        obj['pb_puppet_previous_inverse'] = [v for r in obj.matrix_parent_inverse for v in r]
    obj.parent = controller
    if obj.get('pb_morphset'):
        # Keep pose F-curves in their existing local coordinates. Put the
        # change of parent in the parent inverse, not the animated channels.
        obj.matrix_parent_inverse = world_matrix(controller).inverted() @ world @ basis.inverted()
        obj.matrix_basis = basis
    else:
        obj.matrix_parent_inverse = world_matrix(controller).inverted()
        obj.matrix_world = world


def detach(obj):
    from .model_morphsets import world_matrix
    world = world_matrix(obj)
    basis = obj.matrix_basis.copy()
    obj.parent = obj.get('pb_puppet_previous_parent') if obj.get('pb_morphset') else None
    inverse = obj.get('pb_puppet_previous_inverse')
    obj.matrix_parent_inverse = (Matrix([inverse[i:i + 4] for i in range(0, 16, 4)])
                                 if inverse is not None else Matrix.Identity(4))
    if obj.get('pb_morphset') and obj.parent:
        obj.matrix_parent_inverse = world_matrix(obj.parent).inverted() @ world @ basis.inverted()
        obj.matrix_basis = basis
    else:
        obj.matrix_world = world
    for key in ('pb_puppet_previous_parent', 'pb_puppet_previous_inverse'):
        if key in obj:
            del obj[key]


def set_members(scene, puppet, rows):
    controller = bpy.data.objects.get(puppet.controller_object_name)
    objects = {o for row in rows for o in component_objects(row)}
    for child in list(controller.children):
        if child not in objects:
            detach(child)
    for obj in objects:
        if obj.parent != controller:
            attach(obj, controller)
    puppet.puppet_memberships = ','.join(row.item_id for row in rows)
    bpy.context.view_layer.update()
