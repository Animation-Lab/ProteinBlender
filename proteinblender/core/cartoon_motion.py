"""Keep cartoon ribbons continuous during morphing and B-factor motion.

MolecularNodes corrects alternating peptide normals with a thresholded dot
product. Repeating that decision on interpolated coordinates can flip a ribbon
by 180 degrees in one frame. Evaluate those choices once on the start structure;
the actual normals, backbone and arrow/helix geometry still follow the moving atoms.
Distance-based gap tests use unjiggled positions when thermal motion is active.
"""
import bpy
import bmesh
import numpy as np

TURN = 'pb_cartoon_reference_turn'
HELIX_TURN = 'pb_cartoon_helix_turn'
INDEX = 'pb_cartoon_reference_index'
VERSION = 'pb_cartoon_motion_version'
REVISION = 3


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


def _reference_positions(tree):
    from .thermal_motion import REFERENCE_POSITION
    _node(tree, 'GeometryNodeInputNamedAttribute', 'Unjiggled Positions', data_type='FLOAT_VECTOR')
    tree.nodes['Unjiggled Positions'].inputs['Name'].default_value = REFERENCE_POSITION
    _node(tree, 'GeometryNodeSwitch', 'Gap Positions', input_type='VECTOR')
    _link(tree, 'Unjiggled Positions', 'Exists', 'Gap Positions', 'Switch')
    _link(tree, 'Unjiggled Positions', 'Attribute', 'Gap Positions', 'True')
    _link(tree, 'Position', 'Position', 'Gap Positions', 'False')


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
        if obj.data.shape_keys:
            obj.data.shape_keys.key_blocks[0].data.foreach_get('co', points)
        else:
            obj.data.vertices.foreach_get('co', points)
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
            # Nucleic-only PDBs (or a member with no peptide backbone) have no
            # CA curve. There are no orientation decisions to bake for them.
            indices = np.array([v.value for v in result.attributes[INDEX].data]
                               if len(result.vertices) else [], dtype=np.int32)
            turns = {name: np.array([v.value for v in result.attributes[name].data]
                                   if len(result.vertices) else [], dtype=np.int32)
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
    # Detect genuine backbone gaps on the unjiggled atoms. The original
    # distance cutoff otherwise repeatedly severs neighboring residues as
    # thermal motion moves them across the threshold. Only the gap decision
    # uses these positions; the spline still follows the animated atoms.
    backbone = bpy.data.node_groups['.Atoms to CA Splines'].copy()
    backbone.name = '.PB continuous backbone'
    curves = bpy.data.node_groups['Atoms to Curves'].copy()
    curves.name = '.PB continuous curves'
    chains = bpy.data.node_groups['Chain Group ID'].copy()
    chains.name = '.PB continuous chain groups'
    _group(cartoon, '.Atoms to CA Splines').node_tree = backbone
    _group(backbone, 'Atoms to Curves').node_tree = curves
    _group(curves, 'Chain Group ID').node_tree = chains
    destinations = [(l.to_node.name, l.to_socket.identifier) for l in chains.links
                    if l.from_node.bl_idname == 'GeometryNodeInputPosition']
    _reference_positions(chains)
    for name, identifier in destinations:
        socket = next(s for s in chains.nodes[name].inputs if s.identifier == identifier)
        chains.links.new(chains.nodes['Gap Positions'].outputs['Output'], socket)
    _group(cartoon, '.CA to sheet').node_tree = sheet
    helix = bpy.data.node_groups['.CA to helix'].copy()
    helix.name = '.PB continuous helix'
    _group(cartoon, '.CA to helix').node_tree = helix
    loops = bpy.data.node_groups['.CA to loops'].copy()
    loops.name = '.PB continuous loops'
    _group(cartoon, '.CA to loops').node_tree = loops
    split = bpy.data.node_groups['Curve Split Splines'].copy()
    split.name = '.PB continuous spline split'
    # The sheet/helix/loop splitters have another distance test after selecting
    # their residues. Keep both ends of that test in the same reference space.
    _reference_positions(split)
    for link in list(split.links):
        if link.from_node.name == 'Position' and link.to_node.name == 'Vector Math':
            split.links.new(split.nodes['Gap Positions'].outputs['Output'], link.to_socket)
    _link(split, 'Gap Positions', 'Output', _group(split, 'Offset Vector').name, 'Vector')
    for branch in (sheet, helix, loops):
        for node in branch.nodes:
            if node.type == 'GROUP' and node.node_tree.name == 'Curve Split Splines':
                node.node_tree = split
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
    from .visual_style import find_style_node
    style = find_style_node(obj)
    if style is None or 'Style Cartoon' not in style.node_tree.name:
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
