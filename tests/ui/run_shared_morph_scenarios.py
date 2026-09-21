"""Add two morph rows for one 1D3Z protein through the actual editor buttons."""
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo, report = sys.argv[sys.argv.index('--') + 1:][:2]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import morphsets
from proteinblender.operators import morphset_operators as M
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe
from proteinblender.dna_builder.dna_panel import PROTEINBLENDER_PT_builders
from proteinblender.panels.animation_panel import PROTEINBLENDER_PT_animation

data = {}


def enter():
    window = g['active_window']()
    window.event_simulate(type='RET', value='PRESS')
    window.event_simulate(type='RET', value='RELEASE')


def screenshot(name):
    bpy.ops.screen.screenshot(filepath=str(Path(report).parent / name))


def prepare():
    g['H'].reset_scene()
    mid = g['H'].import_local('1d3z.pdb.gz', '1D3Z')
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon') == {'FINISHED'}
    data['mid'] = mid
    library = g['H'].sm().molecules[mid].object.pb_conformations.states
    data['models'] = [library[i].uid for i in (0, 3, 7)]
    for row in bpy.context.scene.outliner_items:
        row.is_selected = False
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    g['state']['morph_draws'], g['state']['morph_draw_originals'] = {}, []
    def observe(cls):
        original = cls.draw
        def draw(self, context):
            original(self, context)
            g['state']['morph_draws'][cls.__name__] = self.layout.introspect()
        g['state']['morph_draw_originals'].append((cls, original))
        cls.draw = draw
    for cls in [PROTEINBLENDER_PT_builders, PROTEINBLENDER_PT_animation,
                M.PROTEINBLENDER_OT_create_morphset, M.PROTEINBLENDER_OT_edit_morphset]:
        observe(cls)
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=0, y=0)
    for area in g['active_window']().screen.areas:
        area.tag_redraw()
    return 'Only one 1D3Z protein is imported'


def choose_models(second=False):
    dialog = M.PROTEINBLENDER_OT_add_morph._active_instance
    assert dialog is not None, 'The actual Add Morph click did not open a form'
    assert dialog.source == data['mid'], 'The same protein should remain available'
    if second:
        assert dialog.model == data['models'][1], 'Second row should start at the previous End model'
    dialog.name = 'Model 4 to 8' if second else 'Model 1 to 4'
    dialog.model = data['models'][1 if second else 0]
    dialog.end_model = data['models'][2 if second else 1]
    return 'Selected Model 4 → 8 on the same 1D3Z protein' if second else 'Selected Model 1 → 4'


def verify_rows():
    a, b = morphsets.morphs(bpy.context.scene)
    data['uids'] = [a[morphsets.MORPH], b[morphsets.MORPH]]
    assert morphsets.records(a)[0]['object'] == morphsets.records(b)[0]['object']
    assert morphsets.records(a)[0]['name'] == morphsets.records(b)[0]['name'] == 'Chain A'
    layout = str(g['state']['morph_draws']['PROTEINBLENDER_OT_edit_morphset'])
    assert 'Model 1 to 4' in layout and 'Model 4 to 8' in layout
    assert layout.count('proteinblender.remove_morph(') == 2
    data['points'] = [morphsets._coordinates(s['members'][0]['mesh']) for s in
                      [morphsets.states(a)[0], morphsets.states(a)[-1], morphsets.states(b)[-1]]]
    screenshot('two-morphs-one-protein.png')
    for cls, original in g['state']['morph_draw_originals']:
        cls.draw = original
    enter()
    return 'Two separately editable morph rows reference the same original chain'


def open_keyframe(frame):
    bpy.context.scene.frame_set(frame)
    with g['ui_override']():
        assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def fill_keyframe(frame):
    dialog = PROTEINBLENDER_OT_create_keyframe._active_instance
    assert dialog is not None and len(dialog.morph_items) == 2
    for row in dialog.morph_items:
        morph = morphsets.find(bpy.context.scene, row.morph_id)
        first = row.morph_id == data['uids'][0]
        row.use_morph = (first and frame in (1, 45)) or (not first and frame in (45, 90))
        row.state = morphsets.states(morph)[-1 if (first and frame == 45) or frame == 90 else 0]['uid']
    for area in g['active_window']().screen.areas:
        area.tag_redraw()
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=0, y=0)
    return f'Frame {frame}: choose the appropriate transition endpoint; both rows agree on Model 4 at 45'


def verify_geometry():
    scene = bpy.context.scene
    assert sorted(map(int, morphsets.keyframes(scene))) == [1, 45, 90]
    assert len(morphsets.outputs(scene)) == 1, 'Two morph rows duplicated the visible protein'
    a, b = data['uids']
    assert morphsets.outputs(scene, a) == morphsets.outputs(scene, b)
    obj = morphsets.outputs(scene)[0]
    start, middle, end = data['points']
    for frame, expected in [(1, start), (45, middle), (90, end),
                            (23, (start + middle) / 2), (67, middle + (end - middle) * 22 / 45)]:
        scene.frame_set(frame)
        assert len(g['H'].eval_positions(obj)) > 0
        enabled = [m.show_viewport for m in obj.modifiers]
        for modifier in obj.modifiers:
            modifier.show_viewport = False
        bpy.context.view_layer.update()
        actual = g['H'].eval_positions(obj)
        np.testing.assert_allclose(actual, expected, atol=1e-6)
        for modifier, value in zip(obj.modifiers, enabled):
            modifier.show_viewport = value
        bpy.context.view_layer.update()
    scene.frame_set(1)
    return 'Exactly one visible protein follows Models 1/4/8 at 1/45/90 and interpolates correctly'


def remove_first():
    with g['ui_override']('VIEW_3D'):
        bpy.ops.ed.undo_push(message='Both transitions on one protein')
    assert bpy.ops.proteinblender.remove_morph(morph_id=data['uids'][0]) == {'FINISHED'}
    assert len(morphsets.morphs(bpy.context.scene)) == len(morphsets.outputs(bpy.context.scene)) == 1
    with g['ui_override']('VIEW_3D'):
        bpy.ops.ed.undo_push(message='Removed first shared transition')


def undo():
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.ed.undo() == {'FINISHED'}


def prepare_save():
    assert len(morphsets.morphs(bpy.context.scene)) == 2
    verify_geometry()
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 90
    obj = morphsets.outputs(scene)[0]
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    scene.pb_keyframe_filter_by_selection = False
    with g['ui_override']('VIEW_3D'):
        bpy.ops.view3d.view_selected(use_all_regions=False)


def save():
    screenshot('shared-protein-keyframes.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(report).parent/'1d3z-two-morphs.blend'))
    return 'Saved two transitions on one protein, with all three keyframes and restored Undo state'


steps = [('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('prepare single protein', prepare), ('redraw', lambda: None),
    ('Create Morphset', g['invoke_morphset_dialog']), ('settle create form', lambda: None),
    ('confirm Create', enter), ('settle editor', lambda: None)]
for second in (False, True):
    steps += [('click Add Morph', g['click_add_morph_button']), ('settle Add Morph', lambda: None),
        ('choose endpoints', lambda second=second: choose_models(second)),
        ('confirm Add Morph', enter), ('redraw parent editor', lambda: None)]
steps += [('verify both rows', verify_rows), ('settle editor close', lambda: None)]
for frame in (1, 45, 90):
    steps += [(f'open keyframe {frame}', lambda frame=frame: open_keyframe(frame)),
        ('settle keyframe', lambda: None),
        (f'choose state at {frame}', lambda frame=frame: fill_keyframe(frame)),
        ('redraw keyframe', lambda: None),
        (f'capture frame {frame}', lambda frame=frame: screenshot(f'keyframe-{frame}.png')),
        ('confirm keyframe', enter), ('settle confirm', lambda: None)]
steps += [('verify one animated protein', verify_geometry), ('remove first transition', remove_first),
    ('settle removal', lambda: None), ('Undo removal', undo), ('settle Undo', lambda: None),
    ('verify restored transitions and frame example', prepare_save), ('settle viewport', lambda: None),
    ('save example', save)]
g['steps'][:] = steps
