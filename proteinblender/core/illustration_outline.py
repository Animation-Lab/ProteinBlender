"""Pixel-width silhouettes from visible depth discontinuities.

Like ChimeraX's silhouette pass, compare each pixel with the nearest surface in
a circular pixel neighborhood and ink the farther side of a depth step. Linear
depth is compared against 1% of the fitted scene depth, as in ChimeraX Flat.
A bounded encoding lets the circular min filter handle background depth safely.
The compositor works in Eevee Material Preview and in Eevee/Cycles final renders.
"""
import bpy


OWNED = 'pb_lighting_illustration_compositor'
PREVIOUS = 'pb_lighting_previous_compositor'


def _new(tree, kind, name):
    node = tree.nodes.new(kind)
    node.name = name
    return node.name  # Blender may suffix names already used by an artist.


def _link(tree, source, output, target, input):
    tree.links.new(tree.nodes[source].outputs[output], tree.nodes[target].inputs[input])


def _math(tree, name, operation, a=None, b=None):
    name = _new(tree, 'ShaderNodeMath', name)
    tree.nodes[name].operation = operation
    for index, value in enumerate((a, b)):
        if isinstance(value, tuple):
            _link(tree, *value, name, index)
        elif value is not None:
            tree.nodes[name].inputs[index].default_value = value
    return name, 0


def _silhouette(tree, source, width, scene_depth, image_source=None):
    """Insert after a render layer, before any artist image transforms."""
    image_source = image_source or (source, 'Image')
    prefix = 'PB Silhouette ' + image_source[0] + ' '
    targets = [(link.to_node.name, list(link.to_node.inputs).index(link.to_socket))
               for link in tree.nodes[image_source[0]].outputs[image_source[1]].links]
    depth = (source, 'Depth')
    # f = d/(d+K) fits finite/background depth into [0,1], the domain of
    # Blender's morphology filter. Undo that compression in the comparison:
    # d0-ds > .01*K iff f0-fs > .01*(1-f0)*(1-fs).
    denominator = _math(tree, prefix + 'Range', 'ADD', depth, scene_depth)
    bounded = _math(tree, prefix + 'Depth', 'DIVIDE', depth, denominator)
    nearest = _new(tree, 'CompositorNodeDilateErode', prefix + 'Nearest')
    tree.nodes[nearest].inputs['Type'].default_value = 'Distance'
    tree.nodes[nearest].inputs['Size'].default_value = -width
    _link(tree, *bounded, nearest, 'Mask')
    difference = _math(tree, prefix + 'Difference', 'SUBTRACT', bounded, (nearest, 0))
    current_scale = _math(tree, prefix + 'Current Scale', 'SUBTRACT', 1, bounded)
    nearest_scale = _math(tree, prefix + 'Nearest Scale', 'SUBTRACT', 1, (nearest, 0))
    scale = _math(tree, prefix + 'Correction', 'MULTIPLY', current_scale, nearest_scale)
    threshold = _math(tree, prefix + 'Depth Jump', 'MULTIPLY', scale, .01)
    mask = _math(tree, prefix + 'Ink', 'GREATER_THAN', difference, threshold)

    # Carry the neighboring surface's opacity onto the exterior line, including
    # transparent-film exports and partially faded molecular regions.
    alpha = _new(tree, 'CompositorNodeDilateErode', prefix + 'Coverage')
    tree.nodes[alpha].inputs['Type'].default_value = 'Distance'
    tree.nodes[alpha].inputs['Size'].default_value = width
    _link(tree, source, 'Alpha', alpha, 'Mask')
    coverage = _math(tree, prefix + 'Ink Alpha', 'MULTIPLY', mask, (alpha, 0))
    final_alpha = _math(tree, prefix + 'Alpha', 'MAXIMUM', (source, 'Alpha'), coverage)
    mix = _new(tree, 'ShaderNodeMix', prefix + 'Color')
    tree.nodes[mix].data_type = 'RGBA'
    tree.nodes[mix].inputs[7].default_value = (0, 0, 0, 1)
    _link(tree, *mask, mix, 0)
    _link(tree, *image_source, mix, 6)
    result = _new(tree, 'CompositorNodeSetAlpha', prefix + 'Result')
    tree.nodes[result].inputs['Type'].default_value = 'Replace Alpha'
    _link(tree, mix, 2, result, 'Image')
    _link(tree, *final_alpha, result, 'Alpha')
    for name, index in targets:
        _link(tree, result, 0, name, index)


def restore(scene):
    """Restore only state owned by this effect; never replace a user edit."""
    owned = scene.get(OWNED)
    if not owned:
        return
    if scene.compositing_node_group == owned:
        scene.compositing_node_group = scene.get(PREVIOUS)
    for record in scene.get('pb_lighting_depth_passes', ()):
        layer = scene.view_layers.get(record['layer'])
        if layer:
            layer.use_pass_z = record['enabled']
    scene.render.use_compositing = scene.get('pb_lighting_use_compositing', True)
    for key in (OWNED, PREVIOUS, 'pb_lighting_depth_passes', 'pb_lighting_use_compositing'):
        if key in scene:
            del scene[key]
    if owned.users == 0:
        bpy.data.node_groups.remove(owned)


def configure(scene, enabled, width=1, radius=1):
    restore(scene)
    if not enabled:
        return
    previous = scene.compositing_node_group
    if previous:
        scene[PREVIOUS] = previous
        tree = previous.copy()
    else:
        tree = bpy.data.node_groups.new('PB Illustration', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        _new(tree, 'NodeGroupOutput', 'Output')
        _new(tree, 'CompositorNodeRLayers', 'Render Layers')
        _link(tree, 'Render Layers', 'Image', 'Output', 0)
    tree.name = 'PB Illustration'
    tree[OWNED] = True
    scene[OWNED] = tree
    scene['pb_lighting_use_compositing'] = scene.render.use_compositing
    scene['pb_lighting_depth_passes'] = [
        {'layer': layer.name, 'enabled': layer.use_pass_z} for layer in scene.view_layers]
    for layer in scene.view_layers:
        layer.use_pass_z = True
    # Updating the layer sockets is necessary after enabling a previously absent
    # Depth pass; retain node names across node allocations, never RNA pointers.
    sources = [node.name for node in tree.nodes if node.type == 'R_LAYERS'
               and (node.scene is None or node.scene == scene)]
    for name in sources:
        tree.nodes[name].update()
        _silhouette(tree, name, width, 2 * 1.01 * radius)
    # Blender 5 also supplies Combined implicitly to the first color input of
    # a root compositor. Keep that artist graph, with a matching depth source.
    inputs = [(node.name, 0) for node in tree.nodes if node.type == 'GROUP_INPUT'
              and node.outputs and node.outputs[0].type == 'RGBA' and node.outputs[0].is_linked]
    if inputs:
        layer_source = _new(tree, 'CompositorNodeRLayers', 'PB Silhouette Input Depth')
        for image_source in inputs:
            _silhouette(tree, layer_source, width, 2 * 1.01 * radius, image_source)
    scene.compositing_node_group = tree
    scene.render.use_compositing = True
