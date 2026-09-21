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
    return tree


def install(obj):
    # A domain can inherit this modifier when copied from its protein.
    matches = [m for m in obj.modifiers if m.name.startswith(NAME)]
    for extra in matches[1:]:
        obj.modifiers.remove(extra)
    mod = matches[0] if matches else obj.modifiers.new(NAME, 'NODES')
    mod.node_group = node_group()
    obj.modifiers.move(list(obj.modifiers).index(mod), 0)
    return mod


def set_enabled(molecule, enabled):
    if bool(molecule.object.get('pb_bfactor_enabled')) == enabled:
        return
    objects = [molecule.object] + [d.object for d in molecule.domains.values() if d.object]
    if enabled:
        prepare(molecule.object.data)
    for obj in objects:
        if enabled:
            install(obj)
        else:
            for mod in list(obj.modifiers):
                if mod.name.startswith(NAME):
                    obj.modifiers.remove(mod)
    molecule.object['pb_bfactor_enabled'] = bool(enabled)
    from . import morphsets
    if morphsets.keyframes(bpy.context.scene):
        morphsets.compile_animation(bpy.context, morphsets.keyframes(bpy.context.scene))
