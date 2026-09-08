"""Keep the cartoon's discrete ribbon orientation choices fixed during a morph.

MolecularNodes corrects alternating peptide normals with a thresholded dot
product. Repeating that decision on interpolated coordinates can flip a ribbon
by 180 degrees in one frame. Evaluate those choices once on the start structure;
the actual normals, backbone and arrow/helix geometry still follow the moving atoms.
"""
import bpy
import bmesh
import numpy as np

TURN = 'pb_cartoon_reference_turn'
HELIX_TURN = 'pb_cartoon_helix_turn'
INDEX = 'pb_cartoon_reference_index'
VERSION = 'pb_cartoon_motion_version'
REVISION = 2


def _group(tree, name):
    return next(n for n in tree.nodes if n.type == 'GROUP' and n.node_tree.name == name)


def _node(tree, kind, name, **properties):
    node = tree.nodes.new(kind)
    node.name = name
    for key, value in properties.items():
        setattr(node, key, value)


def _link(tree, source, output, target, input):
    # Node collections can reallocate when a node is added; resolve at use.
    tree.links.new(tree.nodes[source].outputs[output], tree.nodes[target].inputs[input])


def _bake_turns(obj, style):
    """Read reference decisions from the actual MN curve, preserving atom indices."""
    from ..utils.molecularnodes.blender import nodes
    # Mesh.copy() also copies the Key datablock. Clearing that temporary key
    # leaves an invalid orphan in Blender 5.0; copy geometry/attributes only.
    mesh = bpy.data.meshes.new('Cartoon orientation reference')
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        for layer in list(bm.verts.layers.shape.values()):
            bm.verts.layers.shape.remove(layer)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    reference = bpy.data.objects.new('Cartoon orientation reference', mesh)
    bpy.context.scene.collection.objects.link(reference)
    tree = nodes.new_tree('Cartoon orientation reference', fallback=False)
    try:
        # Use the stored start conformation even when upgrading at a later frame.
        points = np.empty(len(mesh.vertices) * 3)
        obj.data.shape_keys.key_blocks[0].data.foreach_get('co', points)
        mesh.vertices.foreach_set('co', points)
        index = mesh.attributes.new(INDEX, 'INT', 'POINT')
        index.data.foreach_set('value', np.arange(len(mesh.vertices), dtype=np.int32))
        _node(tree, 'GeometryNodeGroup', 'Backbone', node_tree=bpy.data.node_groups['.Atoms to CA Splines'])
        tree.nodes['Backbone'].inputs['BS Smoothing'].default_value = style.inputs['Smoothing'].default_value
        _node(tree, 'GeometryNodeGroup', 'Turns', node_tree=bpy.data.node_groups['Curve Offset Dot'])
        original = _group(bpy.data.node_groups['.CA to sheet'], 'Curve Offset Dot')
        for name in ('Offset', 'Threshold Direction', 'Threshold Cutoff', 'Rotation Amount'):
            tree.nodes['Turns'].inputs[name].default_value = original.inputs[name].default_value
        _node(tree, 'GeometryNodeStoreNamedAttribute', 'Store', data_type='INT', domain='POINT')
        tree.nodes['Store'].inputs['Name'].default_value = TURN
        _node(tree, 'GeometryNodeGroup', 'Helix Turns', node_tree=bpy.data.node_groups['Curve Offset Dot'])
        original = _group(bpy.data.node_groups['.CA to helix'], 'Curve Offset Dot')
        for name in ('Offset', 'Threshold Direction', 'Threshold Cutoff', 'Rotation Amount'):
            tree.nodes['Helix Turns'].inputs[name].default_value = original.inputs[name].default_value
        _node(tree, 'GeometryNodeStoreNamedAttribute', 'Store Helix', data_type='INT', domain='POINT')
        tree.nodes['Store Helix'].inputs['Name'].default_value = HELIX_TURN
        _node(tree, 'GeometryNodeCurveSplineType', 'Control Points', spline_type='POLY')
        _node(tree, 'GeometryNodeCurveToMesh', 'Mesh')
        _link(tree, 'Group Input', 0, 'Backbone', 'Atoms')
        _link(tree, 'Backbone', 'CA Splines', 'Store', 'Geometry')
        _link(tree, 'Turns', 'Leading', 'Store', 'Value')
        _link(tree, 'Store', 'Geometry', 'Store Helix', 'Geometry')
        _link(tree, 'Helix Turns', 'Leading', 'Store Helix', 'Value')
        _link(tree, 'Store Helix', 'Geometry', 'Control Points', 'Curve')
        _link(tree, 'Control Points', 'Curve', 'Mesh', 'Curve')
        _link(tree, 'Mesh', 'Mesh', 'Group Output', 0)
        reference.modifiers.new('Reference', 'NODES').node_group = tree
        evaluated = reference.evaluated_get(bpy.context.evaluated_depsgraph_get())
        result = evaluated.to_mesh()
        try:
            indices = np.array([v.value for v in result.attributes[INDEX].data])
            turns = {name: np.array([v.value for v in result.attributes[name].data])
                     for name in (TURN, HELIX_TURN)}
        finally:
            evaluated.to_mesh_clear()
        for name, data in turns.items():
            values = np.zeros(len(obj.data.vertices), dtype=np.int32)
            values[indices] = data
            attribute = obj.data.attributes.get(name) or obj.data.attributes.new(name, 'INT', 'POINT')
            attribute.data.foreach_set('value', values)
        obj.data[VERSION] = REVISION
        obj.data.update()
    finally:
        bpy.data.objects.remove(reference, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.node_groups.remove(tree)


def _stable_style():
    """Copy only the affected groups; ordinary proteins keep their renderer."""
    existing = next((t for t in bpy.data.node_groups if t.get(VERSION) == REVISION), None)
    if existing:
        return existing
    root = bpy.data.node_groups['Style Cartoon'].copy()
    root.name = 'Style Cartoon (Continuous Motion)'
    cartoon = bpy.data.node_groups['.MN_utils_style_cartoon'].copy()
    cartoon.name = '.PB continuous cartoon'
    sheet = bpy.data.node_groups['.CA to sheet'].copy()
    sheet.name = '.PB continuous sheet'
    _group(root, '.MN_utils_style_cartoon').node_tree = cartoon
    _group(cartoon, '.CA to sheet').node_tree = sheet
    helix = bpy.data.node_groups['.CA to helix'].copy()
    helix.name = '.PB continuous helix'
    _group(cartoon, '.CA to helix').node_tree = helix
    correction_name = _group(sheet, 'Curve Offset Dot').name
    destinations = [(l.to_node.name, l.to_socket.identifier) for l in sheet.links
                    if l.from_node.name == correction_name and l.from_socket.name == 'Leading']
    _node(sheet, 'GeometryNodeInputNamedAttribute', 'Reference Turns', data_type='INT')
    sheet.nodes['Reference Turns'].inputs['Name'].default_value = TURN
    for name, identifier in destinations:
        socket = next(s for s in sheet.nodes[name].inputs if s.identifier == identifier)
        sheet.links.new(sheet.nodes['Reference Turns'].outputs['Attribute'], socket)
    correction = _group(helix, 'Curve Offset Dot')
    correction_name = correction.name
    axis = tuple(correction.inputs['Rotation Axis'].default_value)
    angle = correction.inputs['Rotation Amount'].default_value
    destinations = [(l.to_node.name, l.to_socket.identifier) for l in helix.links
                    if l.from_node.name == correction_name and l.from_socket.name == 'Rotation']
    _node(helix, 'GeometryNodeInputNamedAttribute', 'Reference Turns', data_type='INT')
    helix.nodes['Reference Turns'].inputs['Name'].default_value = HELIX_TURN
    _node(helix, 'ShaderNodeMath', 'Reference Angle', operation='MULTIPLY')
    helix.nodes['Reference Angle'].inputs[1].default_value = angle
    _node(helix, 'FunctionNodeAxisAngleToRotation', 'Reference Rotation')
    helix.nodes['Reference Rotation'].inputs['Axis'].default_value = axis
    _link(helix, 'Reference Turns', 'Attribute', 'Reference Angle', 0)
    _link(helix, 'Reference Angle', 'Value', 'Reference Rotation', 'Angle')
    for name, identifier in destinations:
        socket = next(s for s in helix.nodes[name].inputs if s.identifier == identifier)
        helix.links.new(helix.nodes['Reference Rotation'].outputs['Rotation'], socket)
    root[VERSION] = REVISION
    return root


def stabilize(obj):
    """Prepare new or saved transitions, and restore the renderer after style swaps."""
    tree = next(m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group)
    style = next((n for n in tree.nodes if n.type == 'GROUP' and 'Style Cartoon' in n.node_tree.name), None)
    if style is None:
        return
    needs_reference = obj.data.get(VERSION) != REVISION or any(
        name not in obj.data.attributes for name in (TURN, HELIX_TURN))
    needs_style = style.node_tree.get(VERSION) != REVISION
    if needs_reference or needs_style:
        # An old saved transition may retain only its copied renderer: unused
        # original templates are not necessarily present after reopening.
        from ..utils.molecularnodes.blender.nodes import append
        append('Style Cartoon')
    if needs_reference:
        _bake_turns(obj, style)
    if needs_style:
        from ..utils.molecularnodes.blender.nodes import swap
        swap(style, _stable_style())
