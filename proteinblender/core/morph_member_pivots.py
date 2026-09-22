"""Keep a Morphset member's pivot when its animated display is rebuilt.

Snapshots and shape keys remain in canonical coordinates. The display's pivot
input and compensating local transform move its origin without moving atoms.
Source objects retain the same world pivot for editing before/after animation.
"""
import numpy as np
from mathutils import Matrix

from . import domain_space, morphsets as C
from .model_morphsets import world_matrix

def _bindings(scene, output):
    source = output.get('pb_morph_member_object')
    if source is not None:
        yield from C._member_bindings(scene, source)
        return
    for morph in C.morphs(scene):
        slot = C.output_slot(output, morph[C.MORPH])
        if slot is not None and slot < len(C.records(morph)):
            yield morph, C.records(morph)[slot]


def _remember(scene, output):
    for morph, member in _bindings(scene, output):
        output['pb_morph_member_object'] = member['object']
        member['display_pivot'] = list(domain_space.get_pivot(output))
        local = world_matrix(morph).inverted() @ world_matrix(output)
        member['display_matrix'] = [v for row in local for v in row]


def preserve_outputs(scene):
    """Capture later rotations/translations as well as the chosen origin."""
    for output in C.outputs(scene):
        if any('display_pivot' in member for _, member in _bindings(scene, output)):
            _remember(scene, output)


def restore_output(obj, member):
    if 'display_pivot' not in member:
        return
    domain_space.set_pivot_local(obj, member['display_pivot'])
    obj.matrix_basis = Matrix(np.asarray(member['display_matrix']).reshape(4, 4))
    obj['initial_matrix_local'] = [list(row) for row in obj.matrix_basis]


def sync_pivot(context, obj):
    """Called after the standard pivot tool moves an origin without moving atoms."""
    scene = context.scene
    position = world_matrix(obj).translation
    if obj.get(C.OUTPUT):
        _remember(scene, obj)
        sources = {member.get('object') for _, member in _bindings(scene, obj)} - {None}
        for source in sources:
            # Hidden originals can have an out-of-date matrix_world.
            source.matrix_world = world_matrix(source)
            domain_space.set_pivot_world(source, position)
            source['initial_matrix_local'] = [list(row) for row in source.matrix_local]
    else:
        bindings = C._member_bindings(scene, obj)
        displays = {output for morph, member in bindings
                    for output in C.outputs(scene, morph[C.MORPH])
                    if C.records(morph)[C.output_slot(output, morph[C.MORPH])].get('object') == obj}
        for output in displays:
            domain_space.set_pivot_world(output, position)
            _remember(scene, output)
        if not displays:
            # Before the first key there is only the original chain. Prepare
            # its future display using the same origin in snapshot space.
            for morph, member in bindings:
                pivot = world_matrix(morph).inverted() @ position
                member['display_pivot'] = list(pivot)
                member['display_matrix'] = [v for row in Matrix.Translation(pivot) for v in row]
    context.view_layer.update()
