"""Flat molecular colors in Eevee and Cycles.

The original surface remains connected to a bypass, so changing presets restores
the original shader, including its links and animated values. Pixel silhouettes
are applied separately by the compositor, using visible depth rather than normals.
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
        shader = output.inputs['Surface'].links[0].from_node
        # Only wrap a directly connected Principled material; arbitrary artist
        # shader graphs are left intact rather than guessing their base color.
        if shader.type != 'BSDF_PRINCIPLED':
            return
        shader_name, output_name = shader.name, output.name

        def new(kind, name):
            nodes.new(kind).name = name
            nodes[name][TAG] = True

        def link(source, output, target, input):
            links.new(nodes[source].outputs[output], nodes[target].inputs[input])

        new('ShaderNodeMixRGB', 'PB Illustration Color')
        new('ShaderNodeEmission', 'PB Illustration Emission')
        new('ShaderNodeBsdfTransparent', 'PB Illustration Transparent')
        new('ShaderNodeMixShader', 'PB Illustration Alpha')
        new('ShaderNodeMixShader', 'PB Illustration Bypass')
        nodes['PB Illustration Bypass'][TAG] = 'bypass'
        link('PB Illustration Color', 0, 'PB Illustration Emission', 'Color')
        link('PB Illustration Transparent', 0, 'PB Illustration Alpha', 1)
        link('PB Illustration Emission', 0, 'PB Illustration Alpha', 2)
        link(shader_name, 'BSDF', 'PB Illustration Bypass', 1)
        link('PB Illustration Alpha', 0, 'PB Illustration Bypass', 2)
        link('PB Illustration Bypass', 0, output_name, 'Surface')
        source_color = nodes[shader_name].inputs['Base Color']
        if source_color.is_linked:
            links.new(source_color.links[0].from_socket, nodes['PB Illustration Color'].inputs[1])
        original_alpha = nodes[shader_name].inputs['Alpha']
        if original_alpha.is_linked:
            links.new(original_alpha.links[0].from_socket, nodes['PB Illustration Alpha'].inputs[0])
    bypass = nodes['PB Illustration Bypass']
    bypass.inputs[0].default_value = 1
    # Upgrade existing files by disconnecting the old surface-angle mask.
    color_factor = nodes['PB Illustration Color'].inputs[0]
    for link in list(color_factor.links):
        links.remove(link)
    color_factor.default_value = 0
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
