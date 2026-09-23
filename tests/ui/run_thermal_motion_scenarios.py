"""Live B-factor slider, cartoon playback, and lighting wording."""
import runpy
import sys
from pathlib import Path

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
import bpy
import numpy as np
from proteinblender.operators.visual_edit import PROTEINBLENDER_OT_edit_protein_visuals as Edit
from proteinblender.operators.lighting_operators import PROTEINBLENDER_OT_setup_lighting as Lighting

data = {}
H = g['H']


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data[cls.__name__] = self
        data[cls.__name__ + '_layout'] = str(self.layout.introspect())
        data[cls.__name__ + '_region'] = (context.region.x, context.region.y,
                                         context.region.width, context.region.height)
    cls.draw = draw


def event(kind='RET'):
    for value in ('PRESS', 'RELEASE'):
        g['active_window']().event_simulate(type=kind, value=value)


def capture(name):
    path = str(Path(g['report_path']).parent / name)
    bpy.ops.screen.screenshot(filepath=path)
    return path


def prepare():
    H.reset_scene()
    data['mid'] = H.import_local('1ubq.pdb', 'Ubiquitin')
    bpy.ops.proteinblender.edit_protein_visuals(item_id=data['mid'], vs_style='cartoon')
    obj = next(iter(H.sm().molecules[data['mid']].domains.values())).object
    data['object'] = obj.name
    for item in bpy.context.view_layer.objects:
        item.select_set(item == obj)
    bpy.context.view_layer.objects.active = obj
    with g['ui_override']('VIEW_3D'):
        bpy.ops.view3d.view_selected(use_all_regions=False)
    data['rest'] = H.eval_positions(obj)
    assert len(data['rest']) > 100
    observe(Edit)
    observe(Lighting)
    with g['ui_override']():
        assert bpy.ops.proteinblender.edit_protein_visuals(
            'INVOKE_DEFAULT', item_id=data['mid']) == {'RUNNING_MODAL'}


def enable():
    dialog = data[Edit.__name__]
    screenshot = capture('thermal-before-enable.png')
    assert not dialog.bfactor_motion
    assert dialog.bfactor_intensity == 1
    scale = bpy.context.preferences.system.ui_scale
    # Blender exposes the underlying Properties region in draw(), not the
    # popup rectangle. Locate its pink swatch in the screenshot, then click
    # the checkbox immediately below it. Pixel coordinates have a bottom origin.
    image = bpy.data.images.load(screenshot, check_existing=False)
    width, height = image.size
    pixels = np.array(image.pixels[:]).reshape(height, width, 4)
    bpy.data.images.remove(image)
    pixels = pixels[:round(400*scale), :round(600*scale), :3]
    ys, xs = np.where((pixels[:,:,0] > .6) & (pixels[:,:,1] < .6)
                      & (pixels[:,:,2] < .6) & (pixels[:,:,0] > pixels[:,:,1] + .2))
    assert len(xs) > 100, 'Dialog color swatch was not visible'
    x, y = round(float(xs.min()) + 6*scale), round(float(np.median(ys)) - 38*scale)
    window = g['active_window']()
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    for value in ('PRESS', 'RELEASE'):
        window.event_simulate(type='LEFTMOUSE', value=value, x=x, y=y)
    return f'Checkbox click ({x}, {y}), region={data[Edit.__name__ + "_region"]}, scale={scale}'


def verify_slider():
    layout = data[Edit.__name__ + '_layout']
    assert 'Motion Intensity' in layout, layout
    set_slider('0.25')


def set_slider(value):
    path = capture('thermal-slider-location.png')
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    pixels = np.array(image.pixels[:]).reshape(height, width, 4)
    bpy.data.images.remove(image)
    scale = bpy.context.preferences.system.ui_scale
    pixels = pixels[:round(400*scale), :round(600*scale), :3]
    ys, xs = np.where((pixels[:,:,0] > .6) & (pixels[:,:,1] < .6)
                      & (pixels[:,:,2] < .6) & (pixels[:,:,0] > pixels[:,:,1] + .2))
    assert len(xs) > 100
    x, y = round(float(xs.min()) + 110*scale), round(float(np.median(ys)) - 64*scale)
    window = g['active_window']()
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    for state in ('PRESS', 'RELEASE'):
        window.event_simulate(type='LEFTMOUSE', value=state, ctrl=True, x=x, y=y)
    window.event_simulate(type='A', value='PRESS', ctrl=True)
    window.event_simulate(type='A', value='RELEASE', ctrl=True)
    keys = {'0': 'ZERO', '2': 'TWO', '5': 'FIVE', '.': 'PERIOD'}
    for char in value:
        window.event_simulate(type=keys[char], value='PRESS', unicode=char)
        window.event_simulate(type=keys[char], value='RELEASE')
    event()


def verify_quarter():
    assert data[Edit.__name__].bfactor_intensity == .25
    assert H.sm().molecules[data['mid']].object['pb_bfactor_intensity'] == .25
    capture('thermal-edit.png')
    event()


def frame(number):
    bpy.context.scene.frame_set(number)
    points = H.eval_positions(bpy.data.objects[data['object']])
    assert points.shape == data['rest'].shape
    assert np.max(np.abs(points - data['rest'])) > 1e-4
    if 'previous' in data:
        assert np.max(np.abs(points - data['previous'])) > 1e-4
    data['previous'] = points
    return f'Frame {number}: {len(points)} cartoon vertices, ribbon preserved'


def reopen():
    with g['ui_override']():
        assert bpy.ops.proteinblender.edit_protein_visuals(
            'INVOKE_DEFAULT', item_id=data['mid']) == {'RUNNING_MODAL'}


def zero():
    dialog = data[Edit.__name__]
    assert dialog.bfactor_motion and dialog.bfactor_intensity == .25
    set_slider('0')


def verify_zero():
    assert data[Edit.__name__].bfactor_intensity == 0
    obj = bpy.data.objects[data['object']]
    bpy.context.scene.frame_set(1)
    first = H.eval_positions(obj)
    bpy.context.scene.frame_set(16)
    np.testing.assert_allclose(H.eval_positions(obj), first, atol=1e-7)
    data[Edit.__name__].vs_style = 'surface'


def style_back():
    assert len(H.eval_positions(bpy.data.objects[data['object']])) > 0
    dialog = data[Edit.__name__]
    dialog.vs_style = 'cartoon'
    set_slider('2')


def verify_strong():
    assert data[Edit.__name__].bfactor_intensity == 2
    assert H.eval_positions(bpy.data.objects[data['object']]).shape == data['rest'].shape
    capture('thermal-strong.png')
    event()


def lighting():
    with g['ui_override']():
        assert bpy.ops.proteinblender.setup_lighting('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def lighting_label():
    assert bpy.ops.proteinblender.setup_lighting.get_rna_type().properties[
        'mute_existing'].name == 'Turn Off Other Lights'
    assert 'Turn Off Other Lights' in data[Lighting.__name__ + '_layout']
    capture('lighting-label.png')
    event('ESC')


def save():
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(g['report_path']).parent / 'thermal-motion.blend'))
    return 'Saved cartoon at 2x intensity'


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('open protein edit', prepare), ('settle dialog', lambda: None),
    ('enable motion at quarter intensity', enable), ('settle slider', lambda: None),
    ('type quarter intensity into visible slider', verify_slider), ('settle intensity', lambda: None),
    ('verify quarter intensity', verify_quarter), ('settle confirm', lambda: None),
    ('cartoon frame 1', lambda: frame(1)), ('cartoon frame 8', lambda: frame(8)),
    ('cartoon frame 16', lambda: frame(16)),
    ('reopen edit', reopen), ('settle reopen', lambda: None),
    ('set zero intensity', zero), ('settle zero', lambda: None),
    ('verify stopped motion and change style', verify_zero), ('settle surface', lambda: None),
    ('restore cartoon at double intensity', style_back), ('settle cartoon', lambda: None),
    ('verify strong cartoon', verify_strong), ('settle confirm', lambda: None),
    ('open lighting', lighting), ('settle lighting', lambda: None),
    ('verify lighting label', lighting_label), ('settle close', lambda: None),
    ('save motion settings', save),
]
