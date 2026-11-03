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


#: Per object: whether its motion is on. Motion is set per chain or domain,
#: so each object carries its own; a molecule object's flag says whether any
#: part of it moves.
ENABLED = 'pb_bfactor_enabled'


def is_enabled(obj):
    """Whether ``obj`` has temperature motion installed."""
    return any(m.name.startswith(NAME) for m in obj.modifiers)


def intensity_of(obj, default=1.0):
    """The motion intensity ``obj`` is drawn with, read off its modifier."""
    from ..utils.gn_compat import read_modifier_socket
    for mod in obj.modifiers:
        if mod.name.startswith(NAME) and mod.node_group is not None:
            for item in mod.node_group.interface.items_tree:
                if getattr(item, 'in_out', '') == 'INPUT' and item.name == 'Intensity':
                    value = read_modifier_socket(mod, item.identifier, default)
                    return float(default if value is None else value)
    return float(default)


def _molecules_drawing(objects):
    from ..utils.scene_manager import ProteinBlenderScene
    names = {obj.name for obj in objects}
    found = []
    for molecule in ProteinBlenderScene.get_instance().molecules.values():
        drawn = [molecule.object] + [d.object for d in molecule.domains.values() if d.object]
        if any(obj is not None and obj.name in names for obj in drawn):
            found.append((molecule, drawn))
    return found


def set_objects(objects, enabled=None, intensity=None):
    """Turn motion on or off for these objects, or change how strong it is.

    ``enabled=None`` keeps each object as it is and only sets the intensity
    of those that move. An object being turned on with no ``intensity`` keeps
    its own, or takes its molecule's last one.
    """
    if intensity is not None:
        intensity = float(intensity)
        if not math.isfinite(intensity) or not 0 <= intensity <= 5:
            raise ValueError('Motion intensity must be between 0 and 5.')
    unique = {}
    for obj in objects:
        if obj is not None:
            unique.setdefault(obj.name, obj)
    objects = list(unique.values())
    molecules = _molecules_drawing(objects)
    fallback = {}
    for molecule, drawn in molecules:
        for obj in drawn:
            if obj is not None:
                fallback[obj.name] = float(molecule.object.get(INTENSITY, 1.0))
    # Update existing morph outputs in place: dragging intensity must not
    # rebuild shape keys, visibility keys, pivots, or puppet pose animation.
    from . import morphsets
    for output in morphsets.outputs(bpy.context.scene):
        member = output.get('pb_morph_member_object')
        if member is not None and member.name in unique:
            fallback[output.name] = fallback.get(member.name, 1.0)
            objects.append(output)
    for obj in objects:
        on = is_enabled(obj) if enabled is None else bool(enabled)
        if on:
            level = intensity
            if level is None:
                level = intensity_of(obj, fallback.get(obj.name, 1.0)) if is_enabled(obj) \
                    else fallback.get(obj.name, 1.0)
            prepare(obj.data)
            install(obj, level)
        else:
            for mod in list(obj.modifiers):
                if mod.name.startswith(NAME):
                    obj.modifiers.remove(mod)
        obj[ENABLED] = on
    for molecule, drawn in molecules:
        # The atoms are drawn by the domains; the molecule object only draws
        # them itself when it has none.
        parts = [obj for obj in drawn[1:] if obj is not None] or drawn[:1]
        molecule.object[ENABLED] = any(is_enabled(obj) for obj in parts)
        molecule.object[INTENSITY] = (intensity if intensity is not None
                                      else float(molecule.object.get(INTENSITY, 1.0)))


def set_enabled(molecule, enabled, intensity=None):
    """Motion for a whole molecule: its object and every domain."""
    objects = [molecule.object] + [d.object for d in molecule.domains.values() if d.object]
    set_objects(objects, enabled, intensity)


def restore_saved_motion():
    """Bring already-enabled motion in older .blend files onto the stable cartoon."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and any(m.name.startswith(NAME) for m in obj.modifiers):
            if AMPLITUDE not in obj.data.attributes:
                prepare(obj.data)
            install(obj)
