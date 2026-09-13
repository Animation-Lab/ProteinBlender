"""Ghost unmatched source regions inside the morph's own geometry output."""
import bpy
import bmesh
import numpy as np

from . import structural_alignment as alignment
from .domain_space import get_pivot


def create(obj, source, matched_indices, visible=True, opacity=.18):
    identity = alignment.read_identity(source)
    matched = set(matched_indices.tolist())
    keep = [i for i, name in enumerate(identity.residue_name)
            if name in alignment.AA and i not in matched]
    if not keep:
        return
    mesh = source.object.data.copy()
    mesh.name = obj.name + ' context atoms'
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        selected = set(keep)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in selected], context='VERTS')
        bm.to_mesh(mesh)
    finally:
        bm.free()
    coords = alignment.positions(source.object)[keep] * alignment.SCALE - np.asarray(get_pivot(source.object))
    mesh.vertices.foreach_set('co', coords.ravel())
    mesh.update()
    helper = bpy.data.objects.new(obj.name + ' context data', mesh)
    bpy.context.scene.collection.objects.link(helper)
    helper.hide_set(True)
    helper.hide_render = True
    helper.hide_select = True
    helper['pb_morph_context'] = True
    obj['pb_context_object'] = helper
    from .visual_style import get_or_create_transparent_material
    material = get_or_create_transparent_material(helper.name)
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    for link in list(shader.inputs['Base Color'].links):
        material.node_tree.links.remove(link)
    shader.inputs['Base Color'].default_value = (.5, .5, .5, 1)
    shader.inputs['Alpha'].default_value = opacity
    mesh.materials.clear()
    mesh.materials.append(material)
    obj['pb_context_material'] = material
    tree = next(m.node_group for m in obj.modifiers if m.type == 'NODES')
    nodes, links = tree.nodes, tree.links
    info = nodes.new('GeometryNodeObjectInfo')
    info.name = 'PB Morph Context Source'
    info.transform_space = 'ORIGINAL'
    info.inputs['Object'].default_value = helper
    style = nodes.new('GeometryNodeGroup')
    style.name = 'PB Morph Context Style'
    style.node_tree = bpy.data.node_groups['Style Cartoon'].copy()
    style.node_tree.name = 'PB Morph Context Cartoon'
    obj['pb_context_style'] = style.node_tree
    style.inputs['Material'].default_value = material
    links.new(info.outputs['Geometry'], style.inputs['Atoms'])
    switch = nodes.new('GeometryNodeSwitch')
    switch.name = 'PB Morph Context Visibility'
    switch.input_type = 'GEOMETRY'
    switch.inputs[0].default_value = visible
    links.new(style.outputs['Geometry'], switch.inputs['True'])
    output = next(n for n in nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
    geometry = output.inputs['Geometry']
    original = geometry.links[0].from_socket
    join = nodes.new('GeometryNodeJoinGeometry')
    join.name = 'PB Morph and Context'
    links.new(original, join.inputs['Geometry'])
    links.new(switch.outputs[0], join.inputs['Geometry'])
    links.new(join.outputs[0], geometry)


def set_visible(obj, visible, opacity=.18):
    obj['pb_show_context'], obj['pb_context_opacity'] = visible, opacity
    for mod in obj.modifiers:
        if mod.type == 'NODES':
            switch = mod.node_group.nodes.get('PB Morph Context Visibility')
            if switch:
                switch.inputs[0].default_value = visible
    material = obj.get('pb_context_material')
    if material and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                node.inputs['Alpha'].default_value = opacity
        from .illustration import sync_alpha
        sync_alpha(material, opacity)


def remove(obj):
    helper = obj.get('pb_context_object')
    if helper:
        mesh = helper.data
        bpy.data.objects.remove(helper, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
