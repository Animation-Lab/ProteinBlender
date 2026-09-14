"""Viewport-only reference cartoons and displacement markers.

Helpers follow the same chain/domain transforms as the displayed protein. They
never change its materials, visibility, topology, or animation.
"""
import bpy
import bmesh
import numpy as np

from . import structural_alignment as alignment
from .domain_space import get_pivot


def clear(molecule):
    for obj in list(bpy.data.objects):
        if obj.get('pb_state_preview_owner') != molecule.object:
            continue
        _remove(obj)


def clear_for_parent(parent):
    for obj in list(parent.children):
        if 'pb_state_preview_owner' in obj:
            _remove(obj)


def _remove(obj):
    mesh = obj.data
    materials = set(mesh.materials)
    material = obj.get('pb_state_preview_material')
    if material:
        materials.add(material)
    trees = [m.node_group for m in obj.modifiers if m.type == 'NODES']
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    for tree in trees:
        if tree and tree.users == 0:
            bpy.data.node_groups.remove(tree)
    for material in materials:
        if material and material.users == 0:
            bpy.data.materials.remove(material)


def _helper(molecule, parent, coords, indices, *, reference, opacity):
    from ..utils.molecularnodes.blender.nodes import create_starting_node_tree
    from .visual_style import apply_color_to_object
    mesh = molecule.object.data.copy()
    mesh.name = 'Conformation reference' if reference else 'Conformation motion markers'
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        keep = set(indices.tolist())
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in keep], context='VERTS')
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.vertices.foreach_set('co', (coords[indices] - np.asarray(get_pivot(parent))).ravel())
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj['pb_state_preview_owner'] = molecule.object
    obj['pb_state_preview_kind'] = 'REFERENCE' if reference else 'MOTION'
    obj.parent = parent
    obj.hide_render = True
    obj.hide_select = True
    create_starting_node_tree(object=obj, style='cartoon' if reference else 'spheres', color='common')
    apply_color_to_object(obj, (.55, .55, .55, opacity) if reference else (1.0, .35, .04, 1.0))
    for node in obj.modifiers[0].node_group.nodes:
        if node.type == 'GROUP' and node.inputs.get('Material'):
            obj['pb_state_preview_material'] = node.inputs['Material'].default_value
            if not reference:
                mesh_socket = node.inputs.get('As Mesh') or node.inputs.get('Sphere As Mesh')
                if mesh_socket:
                    mesh_socket.default_value = True
    if not reference:
        for node in obj.modifiers[0].node_group.nodes:
            if node.type == 'GROUP' and node.inputs.get('Radii'):
                node.inputs['Radii'].default_value = 2.0
    tree = obj.modifiers[0].node_group
    output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT')
    previous = output.inputs[0].links[0].from_socket
    realize = tree.nodes.new('GeometryNodeRealizeInstances')
    tree.links.new(previous, realize.inputs[0])
    tree.links.new(realize.outputs[0], output.inputs[0])
    return obj


def update(molecule, active_coords):
    from .conformation_library import read_mesh, state, compensate_pose
    library = molecule.object.pb_conformations
    clear(molecule)
    if not library.show_comparison and not library.highlight_motion:
        return
    ref = read_mesh(state(molecule, library.reference_uid).mesh)
    identity = alignment.read_identity(molecule)
    protein = np.isin(identity.residue_name, list(alignment.AA))
    ca = (np.asarray(identity.atom_name) == 'CA') & protein
    displacement = np.linalg.norm(active_coords - ref, axis=1) / alignment.SCALE
    moving = ca & (displacement >= library.motion_threshold)
    ref = compensate_pose(molecule, ref, state(molecule, library.reference_uid))
    active_coords = compensate_pose(molecule, active_coords, library.states[library.active_index])
    assigned = np.zeros(len(ref), dtype=bool)
    targets = []
    for domain in molecule.domains.values():
        if domain.object is None:
            continue
        chain = molecule._resolve_chain_socket_name(domain.chain_id)
        mask = ((np.asarray(identity.chain) == chain) &
                (np.asarray(identity.residue) >= domain.start) &
                (np.asarray(identity.residue) <= domain.end))
        assigned |= mask
        if not domain.object.hide_get():
            targets.append((domain.object, mask))
    if not molecule.object.hide_get():
        targets.append((molecule.object, ~assigned))
    for parent, mask in targets:
        if library.show_comparison and np.any(mask & protein):
            _helper(molecule, parent, ref, np.flatnonzero(mask & protein),
                    reference=True, opacity=library.opacity)
        if library.highlight_motion and np.any(mask & moving):
            _helper(molecule, parent, active_coords, np.flatnonzero(mask & moving),
                    reference=False, opacity=1)
