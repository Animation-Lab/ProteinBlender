"""Pixel observations of depth silhouettes, independent of shader/node internals."""
import bpy
import numpy as np
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.visual]


@pytest.fixture(autouse=True)
def restore_scene(scene):
    previous = scene.compositing_node_group
    engine, world = scene.render.engine, scene.world
    film = scene.render.film_transparent
    display = {name: getattr(scene.view_settings, name) for name in
               ('view_transform', 'look', 'exposure', 'gamma')}
    compositing = scene.render.use_compositing
    passes = {v.name: v.use_pass_z for v in scene.view_layers}
    yield
    from proteinblender.core.illustration_outline import restore
    from proteinblender.core.lighting import _illustration_display
    restore(scene)
    _illustration_display(bpy.context, False, False, False)
    scene.compositing_node_group = previous
    scene.render.engine, scene.world = engine, world
    scene.render.film_transparent = film
    for name, value in display.items():
        setattr(scene.view_settings, name, value)
    scene.render.use_compositing = compositing
    for layer in scene.view_layers:
        layer.use_pass_z = passes.get(layer.name, False)
    for key in list(scene.keys()):
        if key.startswith('pb_lighting_') or key == 'pb_scene_lighting':
            del scene[key]


def camera(scene, size=4, resolution=128):
    obj = bpy.data.objects.new('Silhouette camera', bpy.data.cameras.new('Silhouette camera'))
    scene.collection.objects.link(obj)
    obj.location = (0, 0, 5)
    obj.data.type = 'ORTHO'
    obj.data.ortho_scale = size
    scene.camera = obj
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 8
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    return obj


def color(obj, rgba):
    material = bpy.data.materials.new('Silhouette color')
    material.use_nodes = True
    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = rgba
    obj.data.materials.append(material)


def render(scene, tmp_path, name):
    scene.render.filepath = str(tmp_path / (name + '.png'))
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    try:
        return np.asarray(image.pixels[:]).reshape(image.size[1], image.size[0], 4).copy()
    finally:
        bpy.data.images.remove(image)


def apply(**kwargs):
    assert bpy.ops.proteinblender.setup_lighting(
        preset='ILLUSTRATION', preview=False, **kwargs) == {'FINISHED'}


@pytest.mark.parametrize('engine', ['CYCLES', 'BLENDER_EEVEE'])
@pytest.mark.parametrize('perspective', [False, True])
@pytest.mark.parametrize('width', [1, 3])
@pytest.mark.parametrize('implicit_input', [False, True])
def test_outlines_mark_depth_steps_on_front_facing_surfaces(scene, tmp_path, engine, perspective, width, implicit_input):
    cam = camera(scene)
    scene.render.engine = engine
    if perspective:
        cam.data.type = 'PERSP'
        cam.data.lens = 45
    if implicit_input:
        # Blender 5's default compositor receives Combined through a group
        # input, rather than necessarily having a Render Layers node.
        tree = bpy.data.node_groups.new('Artist input graph', 'CompositorNodeTree')
        for direction in ('INPUT', 'OUTPUT'):
            tree.interface.new_socket(name='Image', in_out=direction, socket_type='NodeSocketColor')
        tree.nodes.new('NodeGroupInput').name = 'Input'
        tree.nodes.new('NodeGroupOutput').name = 'Output'
        tree.links.new(tree.nodes['Input'].outputs[0], tree.nodes['Output'].inputs[0])
        scene.compositing_node_group = tree
    # Neither plane has a grazing normal. Their visible depth step still needs
    # a silhouette on the farther (blue) side, as in ChimeraX's depth rule.
    for name, vertices, rgba in [
        ('Back', [(-2,-2,0),(2,-2,0),(2,2,0),(-2,2,0)], (.05,.3,.8,1)),
        ('Front', [(-1,-1,1),(0,-1,1),(0,1,1),(-1,1,1)], (.8,.1,.05,1)),
    ]:
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], [(0,1,2,3)])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        color(obj, rgba)
    apply(outlines=True, outline_width=width)
    pixels = render(scene, tmp_path, 'depth-step')
    band = pixels[45:83, 63:67, :3].max(axis=2) < .03
    assert np.all(band.any(axis=1)), 'No outline at the visible depth discontinuity'
    assert pixels[64, 80, 2] > .5, 'Outline blackened the flat blue face'
    assert pixels[64, 45, 0] > .5, 'Outline blackened the flat red face'
    black = pixels[64, 61:70, :3].max(axis=1) < .03
    assert abs(np.count_nonzero(black) - width) <= 1, 'Width did not control the visible depth boundary'


def test_outline_width_stays_in_pixels_when_image_size_changes(scene, tmp_path):
    camera(scene, size=2.5)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48)
    obj = bpy.context.object
    for face in obj.data.polygons:
        face.use_smooth = True
    color(obj, (.05,.3,.8,1))
    widths = []
    # At thumbnail resolution even ChimeraX's finite depth threshold detects
    # the steep continuous curvature beside a silhouette. Use illustration
    # resolutions here; the analytic overlap test covers small-image edges.
    for resolution in (512, 1024):
        scene.render.resolution_x = scene.render.resolution_y = resolution
        apply(outlines=True)
        pixels = render(scene, tmp_path, 'width-' + str(resolution))
        row = pixels[resolution // 2]
        black = (row[:, :3].max(axis=1) < .03) & (row[:, 3] > .9)
        width = np.count_nonzero(black[:resolution // 2])
        widths.append(width)
    assert all(1 <= w <= 2 for w in widths), f'Contours expanded with curvature/resolution: {widths}'
    assert abs(widths[1] - widths[0]) <= 1


def test_flat_display_is_color_faithful_and_restores_artist_settings(scene):
    bpy.ops.mesh.primitive_cube_add()
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
    scene.view_settings.exposure = 1.25
    scene.view_settings.gamma = 1.1
    apply(outlines=True)
    assert scene.view_settings.view_transform == 'Standard'
    assert scene.view_settings.exposure == 0
    assert scene.view_settings.gamma == 1
    assert bpy.ops.proteinblender.setup_lighting(preset='STUDIO', preview=False) == {'FINISHED'}
    assert scene.view_settings.view_transform == 'AgX'
    assert scene.view_settings.look == 'AgX - Medium High Contrast'
    assert scene.view_settings.exposure == 1.25
    assert scene.view_settings.gamma == pytest.approx(1.1)


def test_existing_compositor_and_pass_settings_survive_repeated_apply(scene):
    bpy.ops.mesh.primitive_cube_add()
    tree = bpy.data.node_groups.new('Artist compositing', 'CompositorNodeTree')
    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    tree.nodes.new('NodeGroupOutput').name = 'Output'
    tree.nodes.new('CompositorNodeRLayers').name = 'Layers'
    tree.nodes.new('CompositorNodeExposure').name = 'Artist exposure'
    tree.nodes['Artist exposure'].inputs['Exposure'].default_value = .75
    tree.links.new(tree.nodes['Layers'].outputs['Image'], tree.nodes['Artist exposure'].inputs['Image'])
    tree.links.new(tree.nodes['Artist exposure'].outputs[0], tree.nodes['Output'].inputs[0])
    scene.compositing_node_group = tree
    scene.render.use_compositing = False
    bpy.context.view_layer.use_pass_z = False
    apply(outlines=True)
    assert scene.compositing_node_group != tree
    assert len(tree.nodes) == 3 and len(tree.links) == 2
    count = len(bpy.data.node_groups)
    apply(outlines=True)
    assert len(bpy.data.node_groups) == count
    apply(outlines=False)
    assert scene.compositing_node_group == tree
    assert not bpy.context.view_layer.use_pass_z
    assert not scene.render.use_compositing
    assert tree.nodes['Artist exposure'].inputs['Exposure'].default_value == .75
