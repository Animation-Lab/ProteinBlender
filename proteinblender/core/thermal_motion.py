"""Deterministic B-factor-weighted illustrative motion before molecular styling.

B = 8*pi^2*Uiso (wwPDB atom_site.B_iso_or_equiv). A sinusoid per axis
has RMS 1/sqrt(2); its amplitude is sqrt(2*Uiso), in Blender units.
This is a visual effect, not a molecular-dynamics trajectory.
"""
import math

import bpy
import numpy as np

NAME = 'PB Temperature Motion'
AMPLITUDE = 'pb_thermal_amplitude'
REFERENCE_POSITION = 'pb_thermal_reference_position'
INTENSITY = 'pb_bfactor_intensity'


def prepare(mesh):
    values = np.zeros(len(mesh.vertices), dtype=np.float32)
    source = mesh.attributes.get('b_factor')
    if source:
        source.data.foreach_get('value', values)
    values = np.maximum(np.nan_to_num(values, nan=0, posinf=0, neginf=0), 0)
    values = np.sqrt(values / (4 * math.pi ** 2)) * .01
    attr = mesh.attributes.get(AMPLITUDE) or mesh.attributes.new(AMPLITUDE, 'FLOAT', 'POINT')
    attr.data.foreach_set('value', values)
    mesh.update()
    return bool(np.any(values))


def node_group():
    tree = bpy.data.node_groups.get(NAME)
    if tree:
        _upgrade(tree)
        return tree
    tree = bpy.data.node_groups.new(NAME, 'GeometryNodeTree')
    tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    specs = [('Input', 'NodeGroupInput'), ('Output', 'NodeGroupOutput'),
             ('Move', 'GeometryNodeSetPosition'), ('Time', 'GeometryNodeInputSceneTime'),
             ('Amplitude', 'GeometryNodeInputNamedAttribute'),
             ('Residue', 'GeometryNodeInputNamedAttribute'),
             ('Vector', 'ShaderNodeCombineXYZ'), ('Scale', 'ShaderNodeVectorMath')]
    for axis in 'XYZ':
        specs += [(axis + ' phase', 'FunctionNodeRandomValue'),
                  (axis + ' time', 'ShaderNodeMath'),
                  (axis + ' sum', 'ShaderNodeMath'),
                  (axis + ' sine', 'ShaderNodeMath')]
    for name, kind in specs:
        tree.nodes.new(kind).name = name
    n, links = tree.nodes, tree.links
    n['Amplitude'].data_type = 'FLOAT'
    n['Amplitude'].inputs['Name'].default_value = AMPLITUDE
    n['Residue'].data_type = 'INT'
    n['Residue'].inputs['Name'].default_value = 'res_id'
    for i, axis in enumerate('XYZ'):
        random = n[axis + ' phase']
        random.data_type = 'FLOAT'
        random.inputs['Min'].default_value = 0
        random.inputs['Max'].default_value = 2 * math.pi
        random.inputs['Seed'].default_value = i + 37
        links.new(n['Residue'].outputs['Attribute'], random.inputs['ID'])
        speed, add, sine = n[axis + ' time'], n[axis + ' sum'], n[axis + ' sine']
        speed.operation, add.operation, sine.operation = 'MULTIPLY', 'ADD', 'SINE'
        speed.inputs[1].default_value = (2.1, 2.7, 3.3)[i] * 2 * math.pi
        links.new(n['Time'].outputs['Seconds'], speed.inputs[0])
        links.new(speed.outputs[0], add.inputs[0])
        links.new(random.outputs['Value'], add.inputs[1])
        links.new(add.outputs[0], sine.inputs[0])
        links.new(sine.outputs[0], n['Vector'].inputs[axis])
    n['Scale'].operation = 'SCALE'
    links.new(n['Vector'].outputs[0], n['Scale'].inputs[0])
    links.new(n['Amplitude'].outputs['Attribute'], n['Scale'].inputs['Scale'])
    links.new(n['Scale'].outputs[0], n['Move'].inputs['Offset'])
    links.new(n['Input'].outputs[0], n['Move'].inputs['Geometry'])
    links.new(n['Move'].outputs[0], n['Output'].inputs[0])
    _upgrade(tree)
    return tree


def _upgrade(tree):
    """Upgrade saved motion nodes in place, preserving their existing users."""
    if tree.get('pb_thermal_version') == 2:
        return
    socket = tree.interface.new_socket(name='Intensity', in_out='INPUT', socket_type='NodeSocketFloat')
    socket.default_value, socket.min_value, socket.max_value = 1.0, 0.0, 5.0
    for name, kind in [('Intensity', 'ShaderNodeMath'),
                       ('Rest Position', 'GeometryNodeInputPosition'),
                       ('Store Rest Position', 'GeometryNodeStoreNamedAttribute')]:
        tree.nodes.new(kind).name = name
    n, links = tree.nodes, tree.links
    n['Intensity'].operation = 'MULTIPLY'
    links.new(n['Amplitude'].outputs['Attribute'], n['Intensity'].inputs[0])
    links.new(n['Input'].outputs['Intensity'], n['Intensity'].inputs[1])
    links.new(n['Intensity'].outputs[0], n['Scale'].inputs['Scale'])
    n['Store Rest Position'].data_type = 'FLOAT_VECTOR'
    n['Store Rest Position'].domain = 'POINT'
    n['Store Rest Position'].inputs['Name'].default_value = REFERENCE_POSITION
    links.new(n['Input'].outputs['Geometry'], n['Store Rest Position'].inputs['Geometry'])
    links.new(n['Rest Position'].outputs['Position'], n['Store Rest Position'].inputs['Value'])
    links.new(n['Store Rest Position'].outputs['Geometry'], n['Move'].inputs['Geometry'])
    tree['pb_thermal_version'] = 2
    # Adding an interface socket to an existing modifier can leave Blender's
    # stored value at zero even though the interface default is one. Older
    # scenes had no dial, so explicitly retain their original 1x motion.
    from ..utils.gn_compat import set_modifier_input
    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group == tree:
                set_modifier_input(mod, 'Intensity', 1.0)
                obj.update_tag()


def install(obj, intensity=None):
    # A domain can inherit this modifier when copied from its protein.
    matches = [m for m in obj.modifiers if m.name.startswith(NAME)]
    for extra in matches[1:]:
        obj.modifiers.remove(extra)
    mod = matches[0] if matches else obj.modifiers.new(NAME, 'NODES')
    mod.node_group = node_group()
    obj.modifiers.move(list(obj.modifiers).index(mod), 0)
    if intensity is not None:
        from ..utils.gn_compat import set_modifier_input
        set_modifier_input(mod, 'Intensity', intensity)
    from .cartoon_motion import stabilize
    stabilize(obj)
    obj.update_tag()
    return mod


def set_enabled(molecule, enabled, intensity=None):
    intensity = float(molecule.object.get(INTENSITY, 1.0) if intensity is None else intensity)
    if not math.isfinite(intensity) or not 0 <= intensity <= 5:
        raise ValueError('Motion intensity must be between 0 and 5.')
    objects = [molecule.object] + [d.object for d in molecule.domains.values() if d.object]
    # Update existing morph outputs in place: dragging intensity must not
    # rebuild shape keys, visibility keys, pivots, or puppet pose animation.
    from . import morphsets
    objects += [obj for obj in morphsets.outputs(bpy.context.scene)
                if obj.get('pb_morph_member_object') in objects]
    for obj in objects:
        if enabled:
            prepare(obj.data)
            install(obj, intensity)
        else:
            for mod in list(obj.modifiers):
                if mod.name.startswith(NAME):
                    obj.modifiers.remove(mod)
    molecule.object['pb_bfactor_enabled'] = bool(enabled)
    molecule.object[INTENSITY] = intensity


def restore_saved_motion():
    """Bring already-enabled motion in older .blend files onto the stable cartoon."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and any(m.name.startswith(NAME) for m in obj.modifiers):
            if AMPLITUDE not in obj.data.attributes:
                prepare(obj.data)
            install(obj)
