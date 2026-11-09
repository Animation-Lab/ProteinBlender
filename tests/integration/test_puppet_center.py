"""A new puppet's controller sits at the centre of what the puppet draws.

Reported 2026-11-03 (Janet): import 1STM, build its icosahedral biological
assembly, make a puppet from it to move the whole virus, and the controller
lands "a little off from the centre of the assembly" - above the particle in
the screenshot rather than in its middle.

Ground truth is Blender's own evaluated output: every atom position the
depsgraph draws for the puppet's members, assembly copies included, read by
``helpers.evaluated_atom_positions``. Nothing here goes through the add-on's
bounding-box or pivot helpers.
"""

import math
import time

import numpy as np
import pytest
import bpy
from mathutils import Euler

import helpers as H


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_ids(mid):
    return [it.item_id for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _make_puppet_from(item_ids, name):
    wanted = set(item_ids)
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in wanted
    assert bpy.ops.proteinblender.create_puppet(
        'EXEC_DEFAULT', puppet_name=name) == {'FINISHED'}
    puppet = next(it for it in bpy.context.scene.outliner_items
                  if it.item_type == "PUPPET" and it.name == name)
    return bpy.data.objects[puppet.controller_object_name]


def _drawn_atoms(molecule):
    objects = [molecule.object] + [d.object for d in molecule.domains.values()
                                   if d.object]
    bpy.context.view_layer.update()
    return H.evaluated_atom_positions(objects)


def _assert_controller_centred(controller, atoms, label):
    assert len(atoms), f"{label}: nothing was drawn to measure"
    lo, hi = atoms.min(axis=0), atoms.max(axis=0)
    centre = (lo + hi) / 2
    extent = float(np.linalg.norm(hi - lo))
    offset = float(np.linalg.norm(np.array(controller.matrix_world.translation)
                                  - centre))
    # 1% of the particle's diagonal: far tighter than the reported miss.
    assert offset <= 0.01 * extent, (
        f"{label}: controller is {offset:.3f} from the centre of the drawn "
        f"atoms ({centre.round(3)}), {100 * offset / extent:.1f}% of the "
        f"{extent:.2f} diagonal")


def _icosahedral_1stm(location=None, rotation=None):
    mid = H.import_local('1stm.cif.gz', '1stm')
    molecule = H.sm().molecules[mid]
    if location is not None:
        molecule.object.location = location
    if rotation is not None:
        molecule.object.rotation_euler = Euler(rotation)
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=mid, source='BIOLOGICAL', assembly_id='1') == {'FINISHED'}
    _build_outliner()
    return mid, molecule


@pytest.mark.integration
@pytest.mark.parametrize('placement', ['in place', 'moved and turned',
                                       'turned and stretched'])
def test_puppet_of_an_icosahedral_assembly_is_centred_on_it(scene, placement):
    kwargs = {}
    if placement == 'moved and turned':
        kwargs = dict(location=(3.0, -2.0, 1.5), rotation=(0.4, 0.0, 1.1))
    mid, molecule = _icosahedral_1stm(**kwargs)
    if placement == 'turned and stretched':
        molecule.object.rotation_euler = Euler((0.3, -0.7, 0.9))
        molecule.object.scale = (1.8, 0.6, 1.2)
    atoms = _drawn_atoms(molecule)

    # The assembly really is drawn: 1STM's deposited unit is a pentamer and
    # assembly 1 places 12 copies of it (60 subunits).
    deposited = len(molecule.object.data.vertices)
    assert len(atoms) == 12 * deposited, (
        f"expected the 12-copy assembly to be drawn, got {len(atoms)} atoms "
        f"for {deposited} deposited")

    started = time.perf_counter()
    controller = _make_puppet_from(_chain_ids(mid), 'Virus')
    print(f"[timing] create_puppet over {len(atoms)} drawn atoms: "
          f"{time.perf_counter() - started:.3f}s")
    _assert_controller_centred(controller, atoms, placement)

    # Making the puppet must not have moved anything it now controls.
    np.testing.assert_allclose(_drawn_atoms(molecule), atoms, atol=1e-4)


@pytest.mark.integration
def test_puppet_of_a_realized_icosahedral_assembly_is_centred_on_it(scene):
    """Realize Copies turns every copy into a protein of its own; a puppet of
    all of them must still sit in the middle of the particle."""
    mid, molecule = _icosahedral_1stm(location=(1.0, 0.5, -2.0),
                                      rotation=(0.2, 0.4, -0.3))
    before = _drawn_atoms(molecule)
    assert bpy.ops.molecule.realize_copies(molecule_id=mid) == {'FINISHED'}
    _build_outliner()
    molecules = list(H.sm().molecules.values())
    assert len(molecules) == 12, f"expected 12 proteins, got {len(molecules)}"

    atoms = np.concatenate([_drawn_atoms(m) for m in molecules])
    assert len(atoms) == len(before), (
        f"realizing changed the atom count: {len(before)} -> {len(atoms)}")
    chains = [cid for m in molecules for cid in _chain_ids(m.identifier)]
    controller = _make_puppet_from(chains, 'Realized Virus')
    _assert_controller_centred(controller, atoms, 'realized')


def _one_sphere(name, radius):
    """An object drawing a single point of ``radius`` at its origin."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    tree = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    tree.interface.new_socket('Geometry', in_out='INPUT',
                              socket_type='NodeSocketGeometry')
    tree.interface.new_socket('Geometry', in_out='OUTPUT',
                              socket_type='NodeSocketGeometry')
    group_in = tree.nodes.new('NodeGroupInput')
    group_out = tree.nodes.new('NodeGroupOutput')
    to_points = tree.nodes.new('GeometryNodeMeshToPoints')
    to_points.inputs['Radius'].default_value = radius
    tree.links.new(group_in.outputs[0], to_points.inputs['Mesh'])
    tree.links.new(to_points.outputs['Points'], group_out.inputs[0])
    obj.modifiers.new(name, 'NODES').node_group = tree
    return obj


@pytest.mark.integration
def test_drawn_bounds_of_a_sphere_under_rotation_and_stretch(scene):
    """A sphere's reach along each world axis follows that axis, not an average.

    One point of radius r, scaled (2, 1, 1) and then turned 90 degrees about Z,
    is an ellipsoid whose long axis now lies along world Y. Worked by hand:
    the linear part is [[0, -1, 0], [2, 0, 0], [0, 0, 1]], whose row norms are
    (1, 2, 1), so the half-extents are (r, 2r, r) around (1, 2, 3).
    """
    from proteinblender.core.evaluated_bounds import evaluated_bounds

    radius = 0.25
    obj = _one_sphere('pb_bounds_probe', radius)
    obj.location = (1.0, 2.0, 3.0)
    obj.scale = (2.0, 1.0, 1.0)
    obj.rotation_euler = Euler((0.0, 0.0, math.pi / 2))

    bounds = evaluated_bounds(bpy.context, {obj.name})
    assert bounds is not None, "the probe sphere drew nothing"
    low, high = (np.array(v) for v in bounds)
    np.testing.assert_allclose(low, [1 - radius, 2 - 2 * radius, 3 - radius],
                               atol=1e-5)
    np.testing.assert_allclose(high, [1 + radius, 2 + 2 * radius, 3 + radius],
                               atol=1e-5)
