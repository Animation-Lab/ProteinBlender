"""Scene-sized, neutral lighting for molecular illustrations.

Broad key/fill lighting follows the approach described by ChimeraX's lighting
guide. Presets vary shadow softness and fill rather than recolouring materials.
See docs/lighting.md for sources and the intended use of each preset.
"""

import math

import bpy
import numpy as np
from mathutils import Euler, Vector


TAG = "pb_scene_lighting"
PRESETS = {
    # key, fill, rim, lower fill; powers are for a one-unit bounding radius.
    "STUDIO": ((220, 140, 200, 60), 2.0, 0.20, True),
    "SURFACE": ((280, 85, 210, 40), 1.2, 0.12, True),
    "ILLUSTRATION": ((0, 0, 0, 0), 2.8, 1.0, False),
}
OFFSETS = ((-2, 2.5, 3), (2.5, 0.8, 2), (0.5, 2, -3), (0, -2.5, 1.5))
ROLES = ("Key", "Fill", "Rim", "Lower Fill")


def scene_bounds(context):
    """Bounds of visible evaluated geometry, including GN/assembly instances.

    Read evaluated coordinates: raw molecular meshes have not had domain pivots,
    selection masks, bending, or assembly transforms applied yet. Empty controller
    meshes and hidden source geometry must not pull the rig toward the origin.
    """
    context.view_layer.update()
    low, high = Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
    cache = {}
    for instance in context.evaluated_depsgraph_get().object_instances:
        obj = instance.object
        if not instance.show_self or obj.type not in {
                'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME',
                'POINTCLOUD', 'CURVES'}:
            continue
        owner = instance.parent.original if instance.is_instance else obj.original
        if owner.hide_render or not owner.visible_get(view_layer=context.view_layer):
            continue
        if obj.original.hide_render:
            continue
        # Depsgraph reuses a temporary Object for GN components/instances.
        # Its pointer is not a geometry identity; the evaluated data is.
        key = (obj.type, obj.data.as_pointer())
        if key not in cache:
            if obj.type == 'POINTCLOUD':
                # Blender's object box for GN point-cloud instances can be
                # zero/stale. Read their evaluated positions and sphere radii.
                count = len(obj.data.points)
                if count:
                    positions = np.empty(count * 3, dtype=np.float32)
                    obj.data.attributes['position'].data.foreach_get('vector', positions)
                    positions = positions.reshape(-1, 3)
                    radii = np.zeros(count, dtype=np.float32)
                    attr = obj.data.attributes.get('radius')
                    if attr:
                        attr.data.foreach_get('value', radii)
                    lower = (positions - radii[:, None]).min(axis=0)
                    upper = (positions + radii[:, None]).max(axis=0)
                    cache[key] = [Vector((x, y, z)) for x in (lower[0], upper[0])
                                  for y in (lower[1], upper[1]) for z in (lower[2], upper[2])]
                else:
                    cache[key] = ()
            # An empty evaluated mesh can still have a misleading zero box.
            elif obj.type == 'MESH' and not len(obj.data.vertices):
                cache[key] = ()
            else:
                corners = [Vector(c) for c in obj.bound_box]
                cache[key] = (() if all(tuple(c) == (-1, -1, -1) for c in corners)
                              else corners)
        for corner in cache[key]:
            point = instance.matrix_world @ corner
            if all(math.isfinite(v) for v in point):
                for axis in range(3):
                    low[axis] = min(low[axis], point[axis])
                    high[axis] = max(high[axis], point[axis])
    if not math.isfinite(low.x):
        raise ValueError("Add or show some scene geometry before setting up lighting")
    return (low + high) * 0.5, max((high - low).length * 0.5, 0.001)


def view_rotation(context, alignment):
    camera = context.scene.camera
    if alignment == 'AUTO' and camera:
        return camera.evaluated_get(context.evaluated_depsgraph_get()).matrix_world.to_quaternion()
    if context.area and context.area.type == 'VIEW_3D':
        return context.space_data.region_3d.view_rotation.copy()
    if context.screen:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                return area.spaces.active.region_3d.view_rotation.copy()
    return Euler((math.pi / 2, 0, 0)).to_quaternion()


def _collection(scene):
    collection = scene.get(TAG)
    if not isinstance(collection, bpy.types.Collection) or collection.name not in scene.collection.children:
        collection = bpy.data.collections.new("PB Scene Lighting")
        collection[TAG] = True
        scene.collection.children.link(collection)
        scene[TAG] = collection
    collection.hide_render = False
    collection.hide_viewport = False
    return collection


def _other_lights(context, rig, mute):
    scene = context.scene
    # Keep datablock references (rename-safe and saved with the .blend), and
    # restore only visibility that this tool previously changed.
    for record in scene.get("pb_lighting_muted", ()):
        obj = record.get("object")
        if obj and obj.name in scene.objects:
            obj.hide_render = record["render"]
            layer = scene.view_layers.get(record["layer"])
            if layer and obj.name in layer.objects:
                obj.hide_set(record["viewport"], view_layer=layer)
    if "pb_lighting_muted" in scene:
        del scene["pb_lighting_muted"]
    records = []
    if mute:
        for obj in scene.objects:
            if obj.type == 'LIGHT' and obj.name not in rig.objects:
                in_layer = obj.name in context.view_layer.objects
                records.append({"object": obj, "render": obj.hide_render,
                                "viewport": obj.hide_get() if in_layer else False,
                                "layer": context.view_layer.name})
                obj.hide_render = True
                if in_layer:
                    obj.hide_set(True)
    if records:
        scene["pb_lighting_muted"] = records


def _world(scene, strength, color=(1, 1, 1)):
    world = scene.get("pb_lighting_world")
    if not isinstance(world, bpy.types.World):
        world = bpy.data.worlds.new("PB Lighting World")
        world[TAG] = True
        scene["pb_lighting_world"] = world
    if scene.world and scene.world != world and 'pb_lighting_previous_world' not in scene:
        scene["pb_lighting_previous_world"] = scene.world
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    nodes.clear()
    nodes.new('ShaderNodeBackground').name = "PB Ambient"
    nodes.new('ShaderNodeOutputWorld').name = "PB Output"
    nodes['PB Ambient'].inputs['Color'].default_value = (*color, 1)
    nodes['PB Ambient'].inputs['Strength'].default_value = strength
    world.node_tree.links.new(nodes['PB Ambient'].outputs[0], nodes['PB Output'].inputs['Surface'])


def _illustration_display(context, enabled, preview, outlines):
    scene = context.scene
    settings = scene.view_settings
    key = 'pb_lighting_previous_display'
    if enabled:
        if key not in scene:
            scene[key] = {name: getattr(settings, name) for name in
                          ('view_transform', 'look', 'exposure', 'gamma')}
        settings.view_transform = 'Standard'
        settings.look = 'None'
        settings.exposure = 0
        settings.gamma = 1
    elif key in scene:
        for name in ('view_transform', 'look', 'exposure', 'gamma'):
            setattr(settings, name, scene[key][name])
        del scene[key]

    viewport_key = 'pb_lighting_previous_viewports'
    # Restore before reapplying so repeated Apply never overwrites the backup.
    for record in scene.get(viewport_key, ()):
        screen = record['screen']
        index = record['area']
        if index >= len(screen.areas) or screen.areas[index].type != 'VIEW_3D':
            continue
        space = screen.areas[index].spaces.active
        space.shading.use_compositor = record['compositor']
        for name, value in record['overlays'].items():
            setattr(space.overlay, name, value)
    if viewport_key in scene:
        del scene[viewport_key]
    if enabled and preview and context.screen:
        records = []
        for index, area in enumerate(context.screen.areas):
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            overlays = {name: getattr(space.overlay, name) for name in (
                'show_extras', 'show_floor', 'show_axis_x', 'show_axis_y',
                'show_axis_z', 'show_cursor', 'show_relationship_lines')}
            records.append({'screen': context.screen, 'area': index,
                            'compositor': space.shading.use_compositor, 'overlays': overlays})
            if outlines:
                space.shading.use_compositor = 'ALWAYS'
            for name in overlays:
                setattr(space.overlay, name, False)
        if records:
            scene[viewport_key] = records


def setup_lighting(context, preset='STUDIO', brightness=1.0, alignment='AUTO',
                   mute_existing=True, preview=True, outlines=True, outline_width=1, background_color=(1, 1, 1)):
    if preset == 'DEFAULT':
        return remove_lighting(context)
    center, radius = scene_bounds(context)  # Validate before changing the scene.
    rotation = view_rotation(context, alignment)
    powers, softness, ambient, shadows = PRESETS[preset]
    scene = context.scene
    if 'pb_lighting_original_engine' not in scene:
        scene['pb_lighting_original_engine'] = scene.render.engine
        scene['pb_lighting_had_world'] = scene.world is not None
    rig = _collection(scene)
    scene['pb_lighting_settings'] = dict(preset=preset, brightness=brightness,
        alignment=alignment, mute_existing=mute_existing, preview=preview,
        outlines=outlines, outline_width=outline_width, background_color=list(background_color))
    for role, offset, power in zip(ROLES, OFFSETS, powers):
        obj = next((o for o in rig.objects if o.get(TAG) == role and o.type == 'LIGHT'), None)
        if obj is None:
            data = bpy.data.lights.new("PB " + role, 'AREA')
            obj = bpy.data.objects.new("PB " + role, data)
            obj[TAG] = role
            rig.objects.link(obj)
        obj.parent = None
        obj.location = center + rotation @ (Vector(offset) * radius)
        obj.rotation_euler = (center - obj.location).to_track_quat('-Z', 'Y').to_euler()
        obj.scale = (1, 1, 1)
        obj.hide_render = obj.hide_viewport = False
        obj.hide_set(False)
        obj.hide_select = True
        light = obj.data
        light.type = 'AREA'
        light.shape = 'DISK'
        light.normalize = True
        light.use_nodes = False
        light.color = (1, 1, 1)
        light.energy = power * radius ** 2 * brightness
        light.size = softness * radius
        light.use_shadow = shadows
        light.specular_factor = 0.35
    rig["center"] = list(center)
    rig["radius"] = radius
    rig["preset"] = preset
    _other_lights(context, rig, mute_existing)
    _world(scene, 1 if preset == 'ILLUSTRATION' else ambient * brightness,
           background_color if preset == 'ILLUSTRATION' else (1, 1, 1))
    from .illustration import set_illustration
    set_illustration(scene, preset == 'ILLUSTRATION', brightness, outlines)
    from .illustration_outline import configure
    configure(scene, preset == 'ILLUSTRATION' and outlines, outline_width, radius)
    _illustration_display(context, preset == 'ILLUSTRATION', preview, outlines)
    if scene.render.engine == 'BLENDER_WORKBENCH':
        scene.render.engine = 'BLENDER_EEVEE'
    if preview and context.screen:
        _save_preview(context)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                shading = area.spaces.active.shading
                shading.use_scene_lights = True
                shading.use_scene_world = True
                shading.use_scene_lights_render = True
                shading.use_scene_world_render = True
                shading.type = 'MATERIAL'
    context.view_layer.update()
    return rig


PREVIEW_FIELDS = ('type', 'use_scene_lights', 'use_scene_world',
                  'use_scene_lights_render', 'use_scene_world_render')


def _save_preview(context):
    records = list(context.scene.get('pb_lighting_original_preview', ()))
    for index, area in enumerate(context.screen.areas):
        if area.type != 'VIEW_3D' or any(
                r['screen'] == context.screen and r['area'] == index for r in records):
            continue
        records.append(dict(screen=context.screen, area=index,
                            values={key: getattr(area.spaces.active.shading, key)
                                    for key in PREVIEW_FIELDS}))
    if records:
        context.scene['pb_lighting_original_preview'] = records


def remove_lighting(context):
    """Restore the saved scene and remove only the rig owned by this tool."""
    scene = context.scene
    from .illustration import set_illustration
    from .illustration_outline import restore
    set_illustration(scene, False)
    restore(scene)
    _illustration_display(context, False, False, False)
    _other_lights(context, None, False)
    world = scene.get('pb_lighting_world')
    if world and scene.world == world:
        scene.world = scene.get('pb_lighting_previous_world')
    if 'pb_lighting_original_engine' in scene:
        scene.render.engine = scene['pb_lighting_original_engine']
    for record in scene.get('pb_lighting_original_preview', ()):
        screen, index = record.get('screen'), record['area']
        if screen and index < len(screen.areas) and screen.areas[index].type == 'VIEW_3D':
            shading = screen.areas[index].spaces.active.shading
            for key, value in record['values'].items():
                setattr(shading, key, value)
    rig = scene.get(TAG)
    if rig:
        for obj in list(rig.objects):
            if obj.get(TAG):
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.lights.remove(data)
            else:
                if obj.name not in scene.collection.objects:
                    scene.collection.objects.link(obj)
        bpy.data.collections.remove(rig)
    for key in (TAG, 'pb_lighting_world', 'pb_lighting_previous_world',
                'pb_lighting_original_engine', 'pb_lighting_had_world',
                'pb_lighting_original_preview', 'pb_lighting_settings'):
        if key in scene:
            del scene[key]
    if world and world.users == 0:
        bpy.data.worlds.remove(world)
    context.view_layer.update()
