"""Real UI: create once, browse ten models, preview, key states, edit, Undo, save."""
import json
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo, report, *options = sys.argv[sys.argv.index('--') + 1:]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import morphsets as C, conformation_sets as S
from proteinblender.operators import conformation_browser as B, morphset_operators as M
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as K
from proteinblender.panels.animation_panel import PROTEINBLENDER_PT_animation

state = {}


def event(kind):
    w = g['active_window']()
    w.event_simulate(type=kind, value='PRESS')
    w.event_simulate(type=kind, value='RELEASE')


def shot(name):
    bpy.ops.screen.screenshot(filepath=str(Path(report).parent / (name + '.png')))


def prepare():
    g['H'].reset_scene()
    mid = g['H'].import_local('1d3z.pdb.gz', '1D3Z')
    state['mid'] = mid
    assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon') == {'FINISHED'}
    for row in bpy.context.scene.outliner_items:
        row.is_selected = row.item_type == 'PROTEIN' and row.item_id == mid
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=0, y=0)
    with g['ui_override']():
        assert bpy.ops.proteinblender.create_morphset('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def inspect_create():
    op = M.PROTEINBLENDER_OT_create_morphset._active_instance
    assert op and op.source == 'SELECTED'
    assert len(M._source_models(bpy.context, op.source)) == 11
    op.name = 'Ubiquitin'
    shot('create-library')
    return 'Creation asks for members once and makes all ten PDB models available'


def inspect_library():
    scene = bpy.context.scene
    assert len(C.sets(scene)) == len(C.morphs(scene)) == 1
    morph = C.morphs(scene)[0]
    state['uid'] = morph[C.MORPH]
    g['state']['morphset_mid'] = state['mid']
    g['state']['morph_ids'] = [state['uid']]
    assert len(C.states(morph)) == 10
    assert len(scene.pb_morph_browser.items) == 10
    assert [s['name'] for s in C.states(morph)] == [f'Model {i}' for i in range(1,11)]
    assert len([r for r in scene.outliner_items if r.item_type == 'MORPH_MEMBER']) == 1
    scene.pb_morph_browser.index = 7
    obj = C.records(morph)[0]['object']
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with g['ui_override']('VIEW_3D'):
        bpy.ops.view3d.view_selected(use_all_regions=False)
    with g['ui_override']():
        assert bpy.ops.proteinblender.open_conformation_library('INVOKE_DEFAULT', morphset_id=morph.parent[C.TAG]) == {'RUNNING_MODAL'}
    return 'One subject, ten states, one outliner member; no endpoint-pair setup'


def preview():
    # The popup is clamped to the lower-left by our cursor placement. Click
    # its real Preview button, rather than substituting a direct operator call.
    window = g['active_window']()
    scale = bpy.context.preferences.system.ui_scale
    x, y = round(150 * scale), round(74 * scale)
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)


def verify_preview():
    assert not C.keyframes(bpy.context.scene)
    assert bpy.context.scene.get('pb_conformation_preview')
    shot('preview-model-8')
    event('ESC')


def from_browser():
    morph = C.find(bpy.context.scene, state['uid'])
    bpy.context.scene.frame_set(1)
    with g['ui_override']():
        assert bpy.ops.proteinblender.keyframe_conformation(morph_id=state['uid'], state_id=C.states(morph)[0]['uid']) == {'RUNNING_MODAL'}


def inspect_seed():
    dialog = K._active_instance
    assert dialog and len(dialog.morph_items) == 1
    row = dialog.morph_items[0]
    assert row.use_morph and row.transition == 'MORPH'
    assert C.state(C.find(bpy.context.scene, state['uid']), row.state)['name'] == 'Model 1'
    assert not bpy.context.scene.get('pb_conformation_preview')
    labels = [x[1] for x in M.morph_state_items(row, bpy.context)]
    assert labels == [f'Model {i}' for i in range(1, 11)]
    shot('keyframe-1')


def open_key(frame):
    bpy.context.scene.frame_set(frame)
    with g['ui_override']():
        assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def fill(index, mode='MORPH'):
    dialog = K._active_instance
    assert len(dialog.morph_items) == 1
    row = dialog.morph_items[0]
    row.use_morph = True
    row.state = C.states(C.find(bpy.context.scene, state['uid']))[index]['uid']
    row.transition = mode
    for area in g['active_window']().screen.areas:
        area.tag_redraw()
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=0, y=0)


def atoms(obj):
    enabled = [m.show_viewport for m in obj.modifiers]
    for m in obj.modifiers:
        m.show_viewport = False
    bpy.context.view_layer.update()
    points = g['H'].eval_positions(obj)
    for m, visible in zip(obj.modifiers, enabled):
        m.show_viewport = visible
    bpy.context.view_layer.update()
    return points


def verify_geometry():
    scene = bpy.context.scene
    morph = C.find(scene, state['uid'])
    assert sorted(map(int, C.keyframes(scene))) == [1, 45, 90]
    assert len(C.outputs(scene)) == 1
    values = [C._coordinates(C.states(morph)[i]['members'][0]['mesh']) for i in (0,3,7)]
    obj = C.outputs(scene)[0]
    for frame, expected in [(1,values[0]),(23,(values[0]+values[1])/2),(45,values[1]),
                            (89,values[1]),(90,values[2])]:
        scene.frame_set(frame)
        assert len(g['H'].eval_positions(obj)) > 0
        np.testing.assert_allclose(atoms(obj), expected, atol=1e-6)
    return 'Model 1 -> 4 morphs over frames 1-45; Hold keeps Model 4 through 89, switches to 8 at 90'


def edit_model():
    morph = C.find(bpy.context.scene, state['uid'])
    with g['ui_override']():
        bpy.ops.proteinblender.edit_morph_state('INVOKE_DEFAULT', morph_id=state['uid'], state_id=C.states(morph)[3]['uid'])


def inspect_edit():
    op = M.PROTEINBLENDER_OT_edit_morph_state._active_instance
    assert op.name == 'Model 4'
    assert dict((uid,label) for uid,label,*_ in M.state_models(op,bpy.context))[op.model] == 'Model 4'
    op.name = 'Selected conformation'
    shot('edit-state')


def verify_edit():
    morph = C.find(bpy.context.scene, state['uid'])
    assert C.states(morph)[3]['name'] == 'Selected conformation'
    assert C.keyframes(bpy.context.scene)['45'][state['uid']]['state'] == C.states(morph)[3]['uid']
    # Rename back for the teaching file, preserving the same state ID.
    C.edit_state(bpy.context,morph,C.states(morph)[3]['uid'],'Model 4')


def open_add_state():
    with g['ui_override']():
        assert bpy.ops.proteinblender.add_morph_state('INVOKE_DEFAULT', morph_id=state['uid']) == {'RUNNING_MODAL'}


def fill_added_state(index):
    op = M.PROTEINBLENDER_OT_add_morph_state._active_instance
    assert op is not None
    op.source = state['mid']
    op.model = g['H'].sm().molecules[state['mid']].object.pb_conformations.states[index].uid
    op.name = f'Additional state {index}'


def verify_added_states():
    morph = C.find(bpy.context.scene, state['uid'])
    assert len(C.states(morph)) == 12
    assert [s['name'] for s in C.states(morph)[-2:]] == ['Additional state 2', 'Additional state 8']
    assert [s['model_name'] for s in C.states(morph)[-2:]] == ['Model 3', 'Model 9']
    assert len(C.sets(bpy.context.scene)) == len(C.outputs(bpy.context.scene)) == 1
    assert sorted(map(int, C.keyframes(bpy.context.scene))) == [1,45,90]
    for uid in [s['uid'] for s in C.states(morph)[-2:]]:
        assert bpy.ops.proteinblender.remove_morph_state(morph_id=state['uid'],state_id=uid) == {'FINISHED'}
    return 'Added two editable named states consecutively through modal forms; original keys and one animated subject preserved'


def remove_and_undo():
    with g['ui_override']('VIEW_3D'):
        bpy.ops.ed.undo_push(message='Conformation library before state removal')
    morph = C.find(bpy.context.scene, state['uid'])
    assert bpy.ops.proteinblender.remove_morph_state(morph_id=state['uid'],state_id=C.states(morph)[-1]['uid']) == {'FINISHED'}
    assert len(C.states(morph)) == 9
    with g['ui_override']('VIEW_3D'):
        bpy.ops.ed.undo_push(message='Removed unkeyed state')
        assert bpy.ops.ed.undo() == {'FINISHED'}


def save():
    scene = bpy.context.scene
    morph = C.find(scene,state['uid'])
    assert len(C.states(morph)) == 10
    verify_geometry()
    scene.frame_end = 90
    scene.frame_set(45)
    obj = C.outputs(scene)[0]
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with g['ui_override']('VIEW_3D'):
        bpy.ops.view3d.view_selected(use_all_regions=False)
    scene.pb_morph_browser.index = 3
    S.preview(bpy.context, morph, C.states(morph)[0]['uid'])
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(report).parent/'1d3z-state-library.blend'))
    assert not scene.get('pb_conformation_preview')
    assert not any(o.get(S.PREVIEW) or S.HIDDEN in o for o in scene.objects)
    shot('state-library-and-keyframes')
    return 'Saved ten-state library after Undo; frame 45 explicitly holds until Model 8 at frame 90'


steps = [('workspace',g['setup_morphset_workspace']),('settle',lambda:None),
    ('import 1D3Z and Create Morphset',prepare),('settle',lambda:None),('inspect simple creation',inspect_create),
    ('confirm creation',lambda:event('RET')),('settle',lambda:None),('inspect ten-state library',inspect_library),
    ('settle library popup',lambda:None),('preview Model 8',preview),('settle preview',lambda:None),
    ('verify preview has no keys',verify_preview),('settle close',lambda:None),
    ('keyframe from library',from_browser),('settle',lambda:None),('inspect seeded keyframe',inspect_seed),
    ('confirm frame 1',lambda:event('RET')),('settle',lambda:None)]
for frame,index,mode in ((45,3,'HOLD'),(90,7,'MORPH')):
    steps += [(f'open frame {frame}',lambda f=frame:open_key(f)),('settle',lambda:None),
        ('choose state and transition',lambda i=index,m=mode:fill(i,m)),('redraw',lambda:None),
        (f'capture frame {frame}',lambda f=frame:shot(f'keyframe-{f}')),('confirm key',lambda:event('RET')),('settle',lambda:None)]
steps += [('verify endpoints, interpolation, hold and cut',verify_geometry),('open state editor',edit_model),
    ('settle',lambda:None),('inspect editable model',inspect_edit),('confirm edit',lambda:event('RET')),
    ('settle',lambda:None),('verify state edit preserves keys',verify_edit)]
for index in (2,8):
    steps += [('open Add State',open_add_state),('settle add form',lambda:None),
        ('choose added model',lambda i=index:fill_added_state(i)),('confirm added state',lambda:event('RET')),('settle addition',lambda:None)]
steps += [('verify consecutive state additions',verify_added_states),('remove state and Undo',remove_and_undo),
    ('settle Undo',lambda:None),('save example',save),('settle final layout',lambda:None),
    ('final screenshot',lambda:shot('final-layout'))]
for morphing in (False, True):
    label = 'Morphset' if morphing else 'Protein'
    steps += [(label + ' style dialog', lambda m=morphing:g['invoke_motion_style_dialog'](m)),
        ('settle style',lambda:None),
        ('B-factor on, Surface', lambda:g['edit_motion_style'](True,'surface')),
        ('verify live Surface',lambda:g['verify_motion_style'](True,'Surface')),
        ('B-factor off, Cartoon',lambda:g['edit_motion_style'](False,'cartoon')),
        ('verify live Cartoon',lambda:g['verify_motion_style'](False,'Cartoon')),
        ('settle style close',lambda:None)]

if '--full-ui' in options:
    steps = g['steps'] + steps

g['steps'][:] = steps
