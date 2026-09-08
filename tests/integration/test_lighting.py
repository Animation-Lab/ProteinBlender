"""Lighting must fit rendered geometry and illuminate real molecular materials."""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def restore_lighting_state(scene):
    world = scene.world
    engine = scene.render.engine
    yield
    scene.world = world
    scene.render.engine = engine
    for key in list(scene.keys()):
        if key.startswith('pb_lighting_') or key == 'pb_scene_lighting':
            del scene[key]
    for obj in list(bpy.data.objects):
        if obj.get('pb_scene_lighting'):
            bpy.data.objects.remove(obj, do_unlink=True)
    for light in list(bpy.data.lights):
        if light.users == 0:
            bpy.data.lights.remove(light)
    for item in list(bpy.data.worlds):
        if item.get('pb_scene_lighting') and item.users == 0:
            bpy.data.worlds.remove(item)


def _apply(**kwargs):
    assert bpy.ops.proteinblender.setup_lighting('EXEC_DEFAULT', preview=False, **kwargs) == {'FINISHED'}
    return bpy.context.scene['pb_scene_lighting']


def _cube(location=(0, 0, 0), scale=1):
    bpy.ops.mesh.primitive_cube_add(size=2, location=location)
    obj = bpy.context.object
    obj.scale = (scale,) * 3
    return obj


def test_empty_scene_refuses_without_side_effects(scene):
    world = scene.world
    assert bpy.ops.proteinblender.setup_lighting(preview=False) == {'CANCELLED'}
    assert not list(scene.objects)
    assert scene.world == world


def test_workbench_switches_to_a_renderer_that_uses_scene_lights(scene):
    _cube()
    scene.render.engine = 'BLENDER_WORKBENCH'
    _apply()
    assert scene.render.engine == 'BLENDER_EEVEE'


@pytest.mark.parametrize('preset', ['STUDIO', 'SURFACE', 'ILLUSTRATION'])
def test_fit_scale_neutrality_and_reapply(scene, preset):
    obj = _cube((10, -4, 3))
    original_matrix = obj.matrix_world.copy()
    rig = _apply(preset=preset)
    np.testing.assert_allclose(rig['center'], (10, -4, 3), atol=1e-5)
    assert rig['radius'] == pytest.approx(math.sqrt(3))
    lights = list(rig.objects)
    assert len(lights) == 4
    powers = {o.name: o.data.energy for o in lights}
    sizes = {o.name: o.data.size for o in lights}
    for light in lights:
        assert light.type == 'LIGHT' and light.data.type == 'AREA'
        assert tuple(light.data.color) == (1, 1, 1)
        direction = light.rotation_euler.to_quaternion() @ Vector((0, 0, -1))
        target = (Vector(rig['center']) - light.location).normalized()
        assert direction.dot(target) > .9999
    assert obj.matrix_world == original_matrix
    obj.scale = (3, 3, 3)
    _apply(preset=preset)
    assert {o.name for o in rig.objects} == set(powers)
    for light in rig.objects:
        assert light.data.energy == pytest.approx(powers[light.name] * 9, rel=1e-5)
        assert light.data.size == pytest.approx(sizes[light.name] * 3, rel=1e-5)


def test_hidden_objects_and_empty_controllers_do_not_affect_fit():
    _cube((7, 8, 9))
    hidden = _cube((1000, 1000, 1000))
    hidden.hide_set(True)
    render_hidden = _cube((-1000, -1000, -1000))
    render_hidden.hide_render = True
    empty_mesh = bpy.data.meshes.new('Empty controller')
    controller = bpy.data.objects.new('Empty controller', empty_mesh)
    bpy.context.scene.collection.objects.link(controller)
    rig = _apply()
    np.testing.assert_allclose(rig['center'], (7, 8, 9), atol=1e-5)
    assert rig['radius'] == pytest.approx(math.sqrt(3))


def test_molecular_assembly_bounds_include_pointcloud_copies(scene, sm):
    mid = H.import_local('5im3.pdb')
    assert bpy.ops.molecule.symmetry_dialog(source='BIOLOGICAL', target_id=mid, assembly_id='1') == {'FINISHED'}
    molecule = sm.molecules[mid]
    molecule.object.location = (5, -3, 2)
    bpy.context.view_layer.update()
    atoms = H.evaluated_atom_positions([molecule.object] + [d.object for d in molecule.domains.values()])
    assert len(atoms) > 1000
    rig = _apply()
    center = np.asarray(rig['center'])
    radius = rig['radius']
    assert np.linalg.norm(atoms - center, axis=1).max() <= radius
    # A fit to raw atoms or an empty protein controller misses the drawn copies.
    np.testing.assert_allclose(center, (atoms.min(axis=0) + atoms.max(axis=0)) / 2, atol=.05)
    assert radius < np.linalg.norm(atoms.max(axis=0) - atoms.min(axis=0)) * .65


def test_existing_lights_can_be_muted_and_restored_and_world_is_preserved(scene):
    _cube()
    old_world = scene.world
    data = bpy.data.lights.new('Artist light', 'POINT')
    light = bpy.data.objects.new('Artist light', data)
    scene.collection.objects.link(light)
    data.energy = 123
    _apply()
    assert light.hide_get() and light.hide_render
    assert data.energy == 123
    assert scene['pb_lighting_previous_world'] == old_world
    light.name = 'Renamed artist light'
    _apply(mute_existing=False)
    assert not light.hide_get() and not light.hide_render
    assert data.energy == 123


def test_camera_orientation_and_materials_are_preserved(scene):
    obj = _cube()
    material = bpy.data.materials.new('Scientific color')
    material.diffuse_color = (.1, .4, .8, .6)
    obj.data.materials.append(material)
    cam = bpy.data.objects.new('Render camera', bpy.data.cameras.new('Render camera'))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.rotation_euler = (0, 0, 0)
    first = _apply()
    key = next(o for o in first.objects if o.get('pb_scene_lighting') == 'Key')
    before = key.location.copy()
    cam.rotation_euler.z = math.pi / 2
    _apply()
    np.testing.assert_allclose(key.location, (-before.y, before.x, before.z), atol=1e-5)
    assert tuple(material.diffuse_color) == pytest.approx((.1, .4, .8, .6))


@pytest.mark.parametrize('kind', ['dna', 'membrane'])
def test_builders_are_included_in_lighting_fit(kind):
    if kind == 'dna':
        H.build_dna()
    else:
        H.build_membrane(width=12, height=12)
    first = _apply()
    center, radius = Vector(first['center']), first['radius']
    # Move all roots of the generated scene. Bounds must follow evaluated
    # geometry by the same translation, independent of the builder's units.
    offset = Vector((7, -5, 3))
    for obj in bpy.context.scene.objects:
        if not obj.parent and obj.type != 'LIGHT':
            obj.location += offset
    second = _apply()
    np.testing.assert_allclose(second['center'], center + offset, atol=1e-4)
    assert second['radius'] == pytest.approx(radius, rel=1e-4)


@pytest.mark.visual
@pytest.mark.parametrize('preset, engine', [
    ('STUDIO', 'CYCLES'), ('SURFACE', 'CYCLES'), ('ILLUSTRATION', 'CYCLES'),
    ('STUDIO', 'BLENDER_EEVEE'),
])
def test_molecule_render_is_lit_and_keeps_color(scene, sm, single_chain, tmp_path, preset, engine):
    molecule = sm.molecules[single_chain]
    row = next(r for r in scene.outliner_items if r.item_id == single_chain)
    row.row_color = (.04, .25, .8, 1)
    scene.render.engine = engine
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.filepath = str(tmp_path / (preset + '.png'))
    camera = bpy.data.objects.new('Lighting test camera', bpy.data.cameras.new('Lighting test camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = 'ORTHO'
    camera.location = (0, -4, 0)
    camera.rotation_euler = (math.pi / 2, 0, 0)
    rig = _apply(preset=preset)
    camera.location = Vector(rig['center']) + Vector((0, -4, 0))
    camera.data.ortho_scale = rig['radius'] * 2.2
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    try:
        pixels = np.array(image.pixels[:]).reshape(-1, 4)
        rgb = pixels[pixels[:, 3] > .95, :3]
        assert len(rgb) > 500, 'Molecule disappeared from the lit render'
        assert rgb.mean() > .08, 'Molecule is effectively unlit'
        assert np.mean(np.min(rgb, axis=1) > .95) < .05, 'Lighting washed out the colors'
        assert rgb[:, 2].mean() > rgb[:, 0].mean() * 1.2, 'Blue molecular color was lost'
        assert np.std(rgb.mean(axis=1)) > .015, 'Surface shape has no visible shading'
        lit_mean = rgb.mean()
    finally:
        bpy.data.images.remove(image)
    # Observe actual light contribution, not only nonzero light properties.
    # This catches a rig that exists in RNA but is excluded from the render.
    if preset == 'STUDIO':
        for light in rig.objects:
            light.data.energy = 0
        scene.world.node_tree.nodes['PB Ambient'].inputs['Strength'].default_value = 0
        scene.render.filepath = str(tmp_path / 'unlit.png')
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        try:
            pixels = np.array(image.pixels[:]).reshape(-1, 4)
            unlit = pixels[pixels[:, 3] > .95, :3]
            assert len(unlit) > 500
            assert lit_mean > unlit.mean() + .08
        finally:
            bpy.data.images.remove(image)
