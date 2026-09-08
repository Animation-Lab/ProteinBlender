"""The deployed lighting button, native popup, viewport preview and undo stack."""

import time

import pytest


@pytest.mark.live
@pytest.mark.parametrize('preset', ['STUDIO', 'SURFACE', 'ILLUSTRATION'])
def test_lighting_dialog_cancel_apply_and_undo(blender, preset):
    blender.call('''
import importlib
with R.view3d_override():
    H.import_local('4hhb.pdb')
bpy.context.window.workspace = bpy.data.workspaces['Protein Blender']
R.frame_all(zoom=.8)
previous_engine = bpy.context.scene.render.engine
if preset == 'STUDIO':
    bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'
records, originals = {}, []
classes = [
    importlib.import_module(H.PKG + '.panels.animation_panel').PROTEINBLENDER_PT_animation,
    importlib.import_module(H.PKG + '.operators.lighting_operators').PROTEINBLENDER_OT_setup_lighting,
]
def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        records[cls.__name__] = self.layout.introspect()
    originals.append((cls, original))
    cls.draw = draw
for cls in classes:
    observe(cls)
bpy.app.driver_namespace['pb_lighting_ui'] = (records, originals)
bpy.app.driver_namespace['pb_lighting_ui_engine'] = previous_engine
for area in bpy.context.screen.areas:
    area.tag_redraw()
''', preset=preset)
    try:
        time.sleep(.5)
        blender.call('''
records, _ = bpy.app.driver_namespace['pb_lighting_ui']
layout = str(records['PROTEINBLENDER_PT_animation'])
assert 'Create Keyframe' in layout and 'Set Up Lighting' in layout, layout
assert 'proteinblender.setup_lighting' in layout
with R.view3d_override():
    assert bpy.ops.proteinblender.setup_lighting('INVOKE_DEFAULT', preset=preset) == {'RUNNING_MODAL'}
''', preset=preset)
        time.sleep(.5)
        blender.call('''
records, _ = bpy.app.driver_namespace['pb_lighting_ui']
layout = str(records['PROTEINBLENDER_OT_setup_lighting'])
for label in ('Set Up Lighting', 'Brightness', 'Orient From', 'Mute Other Lights', 'Show Lighting in Viewport'):
    assert label in layout, layout
assert not any(o.get('pb_scene_lighting') for o in bpy.context.scene.objects)
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''')
        time.sleep(.4)
        blender.call('''
assert not any(o.get('pb_scene_lighting') for o in bpy.context.scene.objects)
bpy.ops.ed.undo_push(message='Before lighting')
with R.view3d_override():
    bpy.ops.proteinblender.setup_lighting('INVOKE_DEFAULT', preset=preset)
''', preset=preset)
        time.sleep(.4)
        blender.call('''
win = bpy.context.window
win.event_simulate(type='RET', value='PRESS')
win.event_simulate(type='RET', value='RELEASE')
''')
        time.sleep(.8)
        blender.call('''
scene = bpy.context.scene
rig = scene['pb_scene_lighting']
assert rig['preset'] == preset
assert len(rig.objects) == 4
assert scene.render.engine in {'CYCLES', 'BLENDER_EEVEE'}
assert all(o.type == 'LIGHT' and o.data.energy > 0 for o in rig.objects)
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        shading = area.spaces.active.shading
        assert shading.type == 'MATERIAL'
        assert shading.use_scene_lights and shading.use_scene_world
with R.view3d_override():
    assert bpy.ops.ed.undo() == {'FINISHED'}
''', preset=preset)
        time.sleep(.4)
        blender.call('''
assert not any(o.get('pb_scene_lighting') for o in bpy.context.scene.objects)
with R.view3d_override():
    assert bpy.ops.ed.redo() == {'FINISHED'}
''')
        time.sleep(.4)
        blender.call('''
assert len(bpy.context.scene['pb_scene_lighting'].objects) == 4
with R.view3d_override():
    assert bpy.ops.proteinblender.setup_lighting('EXEC_DEFAULT', True, preset=preset) == {'FINISHED'}
assert len([o for o in bpy.context.scene.objects if o.get('pb_scene_lighting')]) == 4
''', preset=preset)
    finally:
        blender.call('''
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
_, originals = bpy.app.driver_namespace.pop('pb_lighting_ui', ({}, []))
for cls, original in originals:
    cls.draw = original
bpy.context.scene.render.engine = bpy.app.driver_namespace.pop('pb_lighting_ui_engine')
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.shading.type = 'SOLID'
        area.spaces.active.shading.use_scene_lights = False
        area.spaces.active.shading.use_scene_world = False
''')
