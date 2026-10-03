"""Click the outliner icon/menu and edit the installed Assembly Controls popup."""
import ast
import json
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
H = g['H']
from proteinblender.core import assembly as A
from proteinblender.operators.assembly_controls import MOLECULE_PB_OT_assembly_controls as Controls
from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_PT_outliner as Outliner

data = {}
folder = Path(g['report_path']).parent


def event(kind, x=None, y=None):
    window = g['active_window']()
    xy = {} if x is None else dict(x=int(x), y=int(y))
    if xy:
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', **xy)
    for value in ('PRESS', 'RELEASE'):
        window.event_simulate(type=kind, value=value, **xy)


def redraw():
    for area in g['active_window']().screen.areas:
        area.tag_redraw()
    if data.get('popup'):
        data['popup'].tag_redraw()


def capture(name):
    path = str(folder / name)
    bpy.ops.screen.screenshot(filepath=path)
    return path


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('items', []))


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data[cls.__name__] = self
        data[cls.__name__ + '_layout'] = self.layout.introspect()
        if cls == Controls:
            data['popup'] = getattr(context, 'region_popup', None) or context.region
    cls.draw = draw


def prepare():
    H.reset_scene()
    observe(Controls)
    observe(Outliner)
    observe(bpy.types.UI_MT_list_item_context_menu)
    with g['ui_override']('VIEW_3D'):
        data['mid'] = H.import_local('5im3.pdb', 'First')
        bpy.ops.molecule.symmetry_dialog(target_id=data['mid'], source='BIOLOGICAL', assembly_id='1')
        data['other_mid'] = H.import_local('1ubq.pdb', 'Other')
        bpy.ops.molecule.symmetry_dialog(target_id=data['other_mid'], source='GENERATED')
    scene = bpy.context.scene
    data['child_index'] = next(i for i, r in enumerate(scene.outliner_items)
                              if r.item_type == 'SYMMETRY' and r.parent_id == data['mid'])
    data['other_index'] = next(i for i, r in enumerate(scene.outliner_items) if r.item_id == data['other_mid'])
    for row in scene.outliner_items:
        row.is_expanded = row.item_id == data['mid']
    scene.outliner_index = data['child_index']
    assert not hasattr(bpy.types, 'PROTEINBLENDER_PT_symmetry')
    redraw()


def locate_row():
    path = capture('locate-row.png')
    picture = bpy.data.images.load(path, check_existing=False)
    width, height = picture.size
    pixels = np.array(picture.pixels[:]).reshape(height, width, 4)
    bpy.data.images.remove(picture)
    area = g['protein_workspace_panel_area']()
    left, right = area.x + 60, area.x + area.width - 100
    rgb = pixels[:, left:right, :3]
    blue = (rgb[:, :, 2] > .25) & (rgb[:, :, 2] > rgb[:, :, 0] * 1.6) & (rgb[:, :, 1] > rgb[:, :, 0] * 1.2)
    rows = np.where(np.sum(blue, axis=1) > (right - left) * .7)[0]
    assert len(rows), 'Assembly row not visible'
    y = int(np.median(rows[rows > rows.max() - 15]))
    data['row_y'] = y
    data['row_x'] = int(area.x + area.width * .47)
    data['icon_x'] = area.x + area.width - 110 * bpy.context.preferences.system.ui_scale
    bpy.context.scene.outliner_index = data['other_index']
    redraw()
    (folder / 'outliner-layout.json').write_text(json.dumps(data[Outliner.__name__ + '_layout'], indent=2))
    return str((data['icon_x'], y))


def click_icon():
    capture('before-icon.png')
    event('LEFTMOUSE', data['icon_x'], data['row_y'])


def inspect_popup():
    capture('controls-popup.png')
    assert Controls.__name__ in data, 'Assembly Controls icon did not open the popup'
    dialog = data[Controls.__name__]
    assert dialog.molecule_id == data['mid']
    layout = data[Controls.__name__ + '_layout']
    (folder / 'controls-layout.json').write_text(json.dumps(layout, indent=2))
    labels = str(layout)
    assert all(label in labels for label in ('Assembly progress', 'Copy delay', 'Keyframe', 'Cut Away', 'Realize Copies'))
    assert 'Add Bend' not in labels
    assert dialog.progress == 1 and dialog.copy_delay == 0
    assert not hasattr(bpy.types, 'PROTEINBLENDER_PT_symmetry')
    popup = data['popup']
    return str((popup.x, popup.y, popup.width, popup.height))


def enter_number(x, y, value):
    window = g['active_window']()
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
    for state in ('PRESS', 'RELEASE'):
        window.event_simulate(type='LEFTMOUSE', value=state, ctrl=True, x=int(x), y=int(y))
    window.event_simulate(type='A', value='PRESS', ctrl=True)
    window.event_simulate(type='A', value='RELEASE', ctrl=True)
    keys = {'0': 'ZERO', '4': 'FOUR', '5': 'FIVE', '.': 'PERIOD'}
    for char in value:
        window.event_simulate(type=keys[char], value='PRESS', unicode=char)
        window.event_simulate(type=keys[char], value='RELEASE')
    event('RET')


def edit_progress():
    path = capture('before-slider.png')
    picture = bpy.data.images.load(path, check_existing=False)
    w, h = picture.size
    pixels = np.array(picture.pixels[:]).reshape(h, w, 4)
    bpy.data.images.remove(picture)
    popup = data['popup']
    left, right = popup.x, popup.x + popup.width
    rgb = pixels[:, left:right, :3]
    blue = (rgb[:, :, 2] > .25) & (rgb[:, :, 2] > rgb[:, :, 0] * 1.6) & (rgb[:, :, 1] > rgb[:, :, 0] * 1.2)
    rows = np.where(np.sum(blue, axis=1) > (right - left) * .65)[0]
    assert len(rows), 'Progress slider not visible'
    y = int(np.median(rows[rows > rows.max() - 16]))
    x = round(left + (right - left) * .4)
    data['slider_xy'] = x, y
    enter_number(x, y, '0.4')
    return str((x, y))


def verify_progress():
    mol = H.sm().molecules[data['mid']]
    value = A.get_assembly_factor(mol)
    assert .1 < value < .9, value
    assert A.get_assembly_factor(H.sm().molecules[data['other_mid']]) == 1
    data['progress'] = value
    x, y = data['slider_xy']
    enter_number(x, y - 20 * bpy.context.preferences.system.ui_scale, '0.5')


def verify_delay_and_close():
    mol = H.sm().molecules[data['mid']]
    value = A.get_assembly_stagger(mol)
    assert .1 < value < .9, value
    assert A.get_assembly_stagger(H.sm().molecules[data['other_mid']]) == 0
    data['delay'] = value
    capture('edited-controls.png')
    data.pop('popup', None)
    event('ESC')


def verify_close_and_undo():
    mol = H.sm().molecules[data['mid']]
    assert abs(A.get_assembly_factor(mol) - data['progress']) < 1e-5
    assert abs(A.get_assembly_stagger(mol) - data['delay']) < 1e-5
    with g['ui_override']():
        assert bpy.ops.ed.undo() == {'FINISHED'}


def verify_undo_and_redo():
    mol = H.sm().molecules[data['mid']]
    assert A.get_assembly_stagger(mol) == 0
    with g['ui_override']():
        assert bpy.ops.ed.redo() == {'FINISHED'}


def verify_redo_and_menu():
    mol = H.sm().molecules[data['mid']]
    assert abs(A.get_assembly_stagger(mol) - data['delay']) < 1e-5
    event('RIGHTMOUSE', data['row_x'], data['row_y'])


def inspect_menu():
    capture('assembly-menu.png')
    layout = data['UI_MT_list_item_context_menu_layout']
    (folder / 'row-menu-layout.json').write_text(json.dumps(layout, indent=2))
    assert 'Assembly Controls' in str(layout)
    event('HOME')
    # Blender adds Add to Quick Favorites and Online Manual for the row label.
    event('DOWN_ARROW')
    event('DOWN_ARROW')
    event('RET')


def inspect_reopened():
    dialog = data[Controls.__name__]
    assert dialog.molecule_id == data['mid']
    assert abs(dialog.progress - data['progress']) < 1e-5
    assert abs(dialog.copy_delay - data['delay']) < 1e-5
    capture('controls-from-menu.png')
    event('ESC')


def open_helix():
    data.pop('popup', None)
    scene = bpy.context.scene
    scene.pb_symmetry_kind = 'H'
    scene.pb_symmetry_count = 5
    scene.pb_symmetry_rise = 20
    scene.pb_symmetry_twist = 30
    with g['ui_override']():
        bpy.ops.molecule.symmetry_dialog(target_id=data['other_mid'], source='GENERATED')
        bpy.ops.molecule.assembly_controls('INVOKE_DEFAULT', molecule_id=data['other_mid'])


def inspect_helix():
    layout = data[Controls.__name__ + '_layout']
    assert 'Add Bend' in str(layout)
    button = next(i for i in flatten(layout) if i.get('draw_string') == 'Add Bend')
    call = ast.parse(button['operator'], mode='eval').body
    data['bend_args'] = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    assert data['bend_args']['molecule_id'] == data['other_mid']
    capture('helical-controls.png')
    data.pop('popup', None)
    event('ESC')


def add_bend_and_reopen():
    with g['ui_override']():
        assert bpy.ops.molecule.add_filament_bend(**data['bend_args']) == {'FINISHED'}
        bpy.ops.molecule.assembly_controls('INVOKE_DEFAULT', molecule_id=data['other_mid'])


def inspect_bend_and_clear():
    layout = str(data[Controls.__name__ + '_layout'])
    assert all(label in layout for label in ('Nodes', 'Arc', 'Edit Bend', 'Remove'))
    capture('bend-controls.png')
    with g['ui_override']():
        bpy.ops.molecule.clear_assembly(molecule_id=data['other_mid'])
    redraw()


def inspect_deleted_target():
    assert A.built_assembly_id(H.sm().molecules[data['other_mid']]) is None
    with g['ui_override']():
        assert bpy.ops.molecule.assembly_controls(molecule_id=data['other_mid'], progress=.5) == {'CANCELLED'}
    event('ESC')


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('prepare two assemblies', prepare), ('settle', lambda: None),
    ('locate assembly row', locate_row), ('settle', lambda: None),
    ('click sliders icon', click_icon), ('settle', lambda: None),
    ('inspect assembly popup', inspect_popup),
    ('edit progress with mouse', edit_progress), ('settle', lambda: None),
    ('verify progress and edit delay', verify_progress), ('settle', lambda: None),
    ('verify delay and dismiss popup', verify_delay_and_close), ('settle', lambda: None),
    ('verify edits persist and undo', verify_close_and_undo), ('settle', lambda: None),
    ('verify undo and redo', verify_undo_and_redo), ('settle', lambda: None),
    ('verify redo and open row menu', verify_redo_and_menu), ('settle', lambda: None),
    ('inspect menu and choose controls', inspect_menu), ('settle', lambda: None),
    ('verify reopened controls', inspect_reopened), ('settle', lambda: None),
    ('open helical assembly controls', open_helix), ('settle', lambda: None),
    ('inspect helical controls', inspect_helix), ('settle', lambda: None),
    ('add bend and reopen popup', add_bend_and_reopen), ('settle', lambda: None),
    ('inspect bend controls and delete target', inspect_bend_and_clear), ('settle', lambda: None),
    ('verify popup handles deleted assembly', inspect_deleted_target), ('settle', lambda: None),
]
