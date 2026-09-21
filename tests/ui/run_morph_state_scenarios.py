"""Exercise the 1D3Z Model 1/4/8 workflow through live state/keyframe dialogs."""
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo, report = sys.argv[sys.argv.index('--') + 1:][:2]
driver = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import morphsets
from proteinblender.operators import morphset_operators as M
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe

data = {}


def redraw():
    for area in driver['active_window']().screen.areas:
        area.tag_redraw()


def key_event(key):
    window = driver['active_window']()
    window.event_simulate(type=key, value='PRESS')
    window.event_simulate(type=key, value='RELEASE')


def click(x, y):
    window = driver['active_window']()
    scale = bpy.context.preferences.system.ui_scale
    x, y = round(x * scale), round(y * scale)
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)


def screenshot(name):
    bpy.ops.screen.screenshot(filepath=str(Path(report).parent / name))


def prepare():
    driver['H'].reset_scene()
    mid = driver['H'].import_local('1d3z.pdb.gz', '1D3Z')
    # Cartoon gives the demo a visible ribbon and a mesh we can measure;
    # the default sphere style emits a point cloud, not mesh vertices.
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon') == {'FINISHED'}
    models = driver['H'].sm().molecules[mid].object.pb_conformations.states
    data['models'] = [models[i].uid for i in (0, 3, 7)]
    assert bpy.ops.proteinblender.create_morphset(name='1D3Z model sequence') == {'FINISHED'}
    root = morphsets.sets(bpy.context.scene)[0]
    assert bpy.ops.proteinblender.add_morph(morphset_id=root[morphsets.TAG], source=mid,
        name='1D3Z conformations', model=data['models'][0], end_model=data['models'][1]) == {'FINISHED'}
    morph = morphsets.morphs(bpy.context.scene)[0]
    data['morph'] = morph[morphsets.MORPH]
    data['end'] = morphsets.states(morph)[-1]['uid']
    data['end_mesh'] = morphsets.states(morph)[-1]['members'][0]['mesh']
    # Observe real Blender layouts, including the contents of nested popups.
    data['draws'], data['originals'] = {}, []
    def observe(cls):
        original = cls.draw
        def draw(self, context):
            original(self, context)
            data['draws'][cls.__name__] = self.layout.introspect()
        data['originals'].append((cls, original))
        cls.draw = draw
    for cls in [M.PROTEINBLENDER_OT_edit_morph, M.PROTEINBLENDER_OT_edit_morph_state,
                M.PROTEINBLENDER_OT_add_morph_state]:
        observe(cls)
    driver['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=0, y=0)
    with driver['ui_override']():
        assert bpy.ops.proteinblender.edit_morph('INVOKE_DEFAULT', morph_id=data['morph']) == {'RUNNING_MODAL'}
    return 'Imported 1D3Z and opened its existing Model 1 → Model 4 morph for editing'


def click_end_pencil():
    layout = str(data['draws']['PROTEINBLENDER_OT_edit_morph'])
    assert 'Model 1' in layout and 'Model 4' in layout
    assert 'proteinblender.edit_morph_state' in layout
    # Popup clamped above the bottom edge; End is above Add and two help lines.
    click(548, 132)


def choose_end():
    dialog = M.PROTEINBLENDER_OT_edit_morph_state._active_instance
    assert dialog is not None, 'The End pencil did not open Edit Model / State'
    assert dialog.model == data['models'][1], 'Editor did not load the saved model'
    assert dialog.source == 'MORPH_MEMBERS'
    form = str(data['draws']['PROTEINBLENDER_OT_edit_morph_state'])
    assert data['morph'] not in form and data['end'] not in form, 'Internal IDs exposed as editable fields'
    dialog.model = data['models'][2]
    redraw()
    return 'The pencil offers Model 4; changed it to Model 8 without touching an ID'


def verify_cancel():
    value = morphsets.state(morphsets.find(bpy.context.scene, data['morph']), data['end'])
    assert value['model_uid'] == data['models'][1]
    assert value['members'][0]['mesh'] == data['end_mesh']
    return 'Cancel preserved the original Model 4 snapshot'


def verify_end_and_click_add():
    value = morphsets.state(morphsets.find(bpy.context.scene, data['morph']), data['end'])
    assert value['model_uid'] == data['models'][2]
    assert 'Model 8' in str(data['draws']['PROTEINBLENDER_OT_edit_morph'])
    click(280, 106)


def choose_middle():
    dialog = M.PROTEINBLENDER_OT_add_morph_state._active_instance
    assert dialog is not None, 'Add Model / State did not open its form'
    assert dialog.source == 'MORPH_MEMBERS', 'Add State lost the morph’s protein'
    available = M.state_models(dialog, bpy.context)
    assert all(uid in {item[0] for item in available} for uid in data['models'])
    dialog.model = data['models'][1]
    redraw()
    return 'Add Model / State defaults to the same 1D3Z members; chose Model 4'


def verify_states():
    morph = morphsets.find(bpy.context.scene, data['morph'])
    values = morphsets.states(morph)
    assert [s['model_uid'] for s in values] == data['models']
    assert [morphsets.state_label(s) for s in values] == ['Model 1', 'Model 4', 'Model 8']
    data['states'] = [s['uid'] for s in values]
    data['coordinates'] = [morphsets._coordinates(s['members'][0]['mesh']) for s in values]
    layout = str(data['draws']['PROTEINBLENDER_OT_edit_morph'])
    assert all(f'Model {i}' in layout for i in (1, 4, 8))
    screenshot('three-models-editor.png')
    key_event('RET')
    return 'Start — Model 1, State — Model 4, End — Model 8 are visible in the editor'


def open_keyframe(frame):
    bpy.context.scene.frame_set(frame)
    with driver['ui_override']():
        assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def choose_keyframe(index):
    dialog = PROTEINBLENDER_OT_create_keyframe._active_instance
    assert dialog is not None and len(dialog.morph_items) == 1
    row = dialog.morph_items[0]
    assert row.morph_id == data['morph']
    labels = [item[1] for item in M.morph_state_items(row, bpy.context)]
    assert labels == ['Start — Model 1', 'State — Model 4', 'End — Model 8']
    row.use_morph, row.state = True, data['states'][index]
    redraw()
    return f'Checked the morph and selected {labels[index]}'


def verify_frame(frame, index):
    scene = bpy.context.scene
    keys = morphsets.keyframes(scene)
    assert keys[str(frame)][data['morph']]['state'] == data['states'][index]
    scene.frame_set(frame)
    obj = morphsets.outputs(scene, data['morph'])[0]
    enabled = [m.show_viewport for m in obj.modifiers]
    for modifier in obj.modifiers:
        modifier.show_viewport = False
    bpy.context.view_layer.update()
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    actual = np.empty((len(mesh.vertices), 3))
    mesh.vertices.foreach_get('co', actual.ravel())
    np.testing.assert_allclose(actual, data['coordinates'][index], atol=1e-6)
    for modifier, value in zip(obj.modifiers, enabled):
        modifier.show_viewport = value
    bpy.context.view_layer.update()
    assert len(driver['H'].eval_positions(obj)) > 0, 'The representation is empty'
    return f'Frame {frame} evaluates to Model {(1, 4, 8)[index]} and draws geometry'


def save_example():
    scene = bpy.context.scene
    assert sorted(map(int, morphsets.keyframes(scene))) == [1, 45, 90]
    scene.frame_start, scene.frame_end = 1, 90
    scene.frame_set(1)
    obj = morphsets.outputs(scene, data['morph'])[0]
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    scene.pb_keyframe_filter_by_selection = False
    with driver['ui_override']('VIEW_3D'):
        bpy.ops.view3d.view_selected(use_all_regions=False)
    for cls, original in data['originals']:
        cls.draw = original
    notes = bpy.data.texts.new('1D3Z Morphset — How to edit')
    notes.write('1D3Z: Model 1 at frame 1, Model 4 at frame 45, Model 8 at frame 90.\n'
                'Morphset pencil → morph pencil → state pencil edits its model/name.\n'
                'Add Model / State adds another conformation of the same protein.\n'
                'Create/Edit Keyframe chooses the state to reach at that frame.\n')
    redraw()


def save_file():
    screenshot('1d3z-model-sequence.png')
    filepath = str(Path(report).parent / '1d3z-model-sequence.blend')
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    return 'Saved a framed, editable 1D3Z example with keys at frames 1, 45, and 90'


steps = [('workspace', driver['setup_morphset_workspace']), ('settle', lambda: None),
    ('prepare 1D3Z', prepare), ('settle editor', lambda: None),
    ('click End pencil', click_end_pencil), ('settle state dialog', lambda: None),
    ('choose Model 8', choose_end), ('cancel edit', lambda: key_event('ESC')),
    ('settle cancellation', lambda: None), ('verify cancel', verify_cancel),
    ('click End pencil again', click_end_pencil), ('settle state dialog', lambda: None),
    ('choose Model 8 again', choose_end), ('redraw model choice', lambda: None),
    ('capture model editor', lambda: screenshot('edit-model-state.png')),
    ('confirm model edit', lambda: key_event('RET')), ('settle edit', lambda: None),
    ('verify End and click Add Model', verify_end_and_click_add), ('settle Add State', lambda: None),
    ('choose intermediate Model 4', choose_middle), ('redraw middle choice', lambda: None),
    ('capture Add Model', lambda: screenshot('add-model-state.png')),
    ('confirm intermediate', lambda: key_event('RET')), ('settle intermediate', lambda: None),
    ('verify three model rows', verify_states), ('settle editor close', lambda: None)]
for index, frame in enumerate((1, 45, 90)):
    steps += [(f'open frame {frame}', lambda f=frame: open_keyframe(f)),
        ('settle keyframe form', lambda: None),
        (f'choose model for {frame}', lambda i=index: choose_keyframe(i)),
        ('redraw keyframe form', lambda: None),
        (f'capture keyframe {frame}', lambda f=frame: screenshot(f'keyframe-{f}.png')),
        ('confirm keyframe', lambda: key_event('RET')), ('settle keyframe', lambda: None),
        (f'verify geometry at {frame}', lambda f=frame, i=index: verify_frame(f, i))]
steps += [('prepare example', save_example), ('settle viewport', lambda: None), ('save example', save_file)]
driver['steps'][:] = steps
