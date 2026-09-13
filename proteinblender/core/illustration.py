"""Flat molecular colors with view-dependent contours in Eevee and Cycles.

The original surface remains connected to a bypass, so changing presets restores
the original shader, including its links and animated values. These contours
follow surface normals; unlike ChimeraX's depth-buffer silhouettes their width
depends on local curvature.
"""
import bpy

TAG = 'pb_flat_illustration'


def _materials(scene):
    found, visited = set(), set()

    def visit(tree):
        if tree is None or tree.as_pointer() in visited:
            return
        visited.add(tree.as_pointer())
        for node in tree.nodes:
            for socket in node.inputs:
                if socket.type == 'MATERIAL' and socket.default_value:
                    found.add(socket.default_value)
            if node.type == 'GROUP':
                visit(node.node_tree)

    for obj in scene.objects:
        for slot in obj.material_slots:
            if slot.material:
                found.add(slot.material)
        for mod in obj.modifiers:
            if mod.type == 'NODES':
                visit(mod.node_group)
    return found


def sync_alpha(material, alpha):
    if material and material.node_tree:
        node = material.node_tree.nodes.get('PB Illustration Alpha')
        if node and not node.inputs[0].is_linked:
            node.inputs[0].default_value = alpha


def sync_animated_alpha():
    """Follow evaluated alpha through the existing frame-change lifecycle.

    A driver between sockets in the same shader tree creates a dependency
    cycle in Blender, including after reopening. Keep the original material
    animation as the authority and synchronize the display wrapper instead.
    """
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        bypass = tree.nodes.get('PB Illustration Bypass')
        if bypass and bypass.inputs[0].default_value and bypass.inputs[1].is_linked:
            original = bypass.inputs[1].links[0].from_node
            sync_alpha(material, original.inputs['Alpha'].default_value)


def _setup(material, brightness, outlines):
    tree = material.node_tree
    if tree is None:
        return
    nodes, links = tree.nodes, tree.links
    bypass = next((n for n in nodes if n.get(TAG) == 'bypass'), None)
    if bypass is None:
        output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
        if output is None or not output.inputs['Surface'].is_linked:
            return
        original = output.inputs['Surface'].links[0].from_socket
        # Only wrap a directly connected Principled material; arbitrary artist
        # shader graphs are left intact rather than guessing their base color.
        shader = original.node
        if shader.type != 'BSDF_PRINCIPLED':
            return

        def new(kind, name):
            node = nodes.new(kind)
            node.name = name
            node[TAG] = True
            return node

        geometry = new('ShaderNodeNewGeometry', 'PB Illustration Geometry')
        dot = new('ShaderNodeVectorMath', 'PB Illustration Facing')
        dot.operation = 'DOT_PRODUCT'
        links.new(geometry.outputs['Normal'], dot.inputs[0])
        links.new(geometry.outputs['Incoming'], dot.inputs[1])
        absolute = new('ShaderNodeMath', 'PB Illustration Absolute')
        absolute.operation = 'ABSOLUTE'
        links.new(dot.outputs['Value'], absolute.inputs[0])
        edge = new('ShaderNodeMath', 'PB Illustration Edge')
        edge.operation = 'LESS_THAN'
        links.new(absolute.outputs[0], edge.inputs[0])
        color = new('ShaderNodeMixRGB', 'PB Illustration Color')
        links.new(edge.outputs[0], color.inputs[0])
        source_color = shader.inputs['Base Color']
        if source_color.is_linked:
            links.new(source_color.links[0].from_socket, color.inputs[1])
        else:
            color.inputs[1].default_value = source_color.default_value
        color.inputs[2].default_value = (0, 0, 0, 1)
        emission = new('ShaderNodeEmission', 'PB Illustration Emission')
        links.new(color.outputs[0], emission.inputs['Color'])
        transparent = new('ShaderNodeBsdfTransparent', 'PB Illustration Transparent')
        alpha = new('ShaderNodeMixShader', 'PB Illustration Alpha')
        links.new(transparent.outputs[0], alpha.inputs[1])
        links.new(emission.outputs[0], alpha.inputs[2])
        original_alpha = shader.inputs['Alpha']
        if original_alpha.is_linked:
            links.new(original_alpha.links[0].from_socket, alpha.inputs[0])
        else:
            alpha.inputs[0].default_value = original_alpha.default_value
        bypass = new('ShaderNodeMixShader', 'PB Illustration Bypass')
        bypass[TAG] = 'bypass'
        links.new(original, bypass.inputs[1])
        links.new(alpha.outputs[0], bypass.inputs[2])
        links.new(bypass.outputs[0], output.inputs['Surface'])
    bypass.inputs[0].default_value = 1
    nodes['PB Illustration Edge'].inputs[1].default_value = .4 if outlines else 0
    nodes['PB Illustration Emission'].inputs['Strength'].default_value = brightness
    original_shader = bypass.inputs[1].links[0].from_node
    color = nodes['PB Illustration Color'].inputs[1]
    if not color.is_linked:
        color.default_value = original_shader.inputs['Base Color'].default_value
    sync_alpha(material, original_shader.inputs['Alpha'].default_value)


def set_illustration(scene, enabled, brightness=1, outlines=True):
    materials = _materials(scene)
    # Include owned wrappers on previously-used materials so switching back
    # also restores materials whose objects have since changed representation.
    for material in bpy.data.materials:
        if material.node_tree:
            for node in material.node_tree.nodes:
                if node.get(TAG) == 'bypass':
                    node.inputs[0].default_value = 0
    if enabled:
        for material in materials:
            _setup(material, brightness, outlines)
