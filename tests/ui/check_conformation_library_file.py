"""Fresh-process installed-addon check for old and new conformation .blend files."""
import json
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo, report = sys.argv[sys.argv.index('--') + 1:][:2]
g = runpy.run_path(str(Path(repo)/'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import morphsets as C, conformation_sets as S
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as K

baseline = {}


def atoms(obj):
    enabled = [m.show_viewport for m in obj.modifiers]
    hidden = obj.hide_viewport
    obj.hide_viewport = False
    for mod in obj.modifiers:
        mod.show_viewport = False
    bpy.context.view_layer.update()
    points = g['H'].eval_positions(obj)
    for mod,value in zip(obj.modifiers,enabled):
        mod.show_viewport = value
    obj.hide_viewport = hidden
    bpy.context.view_layer.update()
    return points


def verify():
    scene = bpy.context.scene
    assert g['active_window']().screen.get('pb_layout_revision') == 3
    roots = C.sets(scene)
    assert roots and all(r.get('pb_schema') == 3 for r in roots)
    assert all(len(C.morphs(scene,r)) == 1 for r in roots)
    assert not scene.get('pb_conformation_preview')
    assert not any(o.get(S.PREVIEW) or S.HIDDEN in o for o in scene.objects)
    path = Path(bpy.data.filepath).name.lower()
    if 'two-morphs' in path:
        assert len(roots) == len(C.morphs(scene)) == len(C.outputs(scene)) == 1
        assert [C.state_label(s) for s in C.states(C.morphs(scene)[0])] == ['Model 1','Model 4','Model 8']
    for morph in C.morphs(scene):
        keys = sorted((int(f),v) for f,v in C.morph_keys(scene,morph[C.MORPH]).items())
        for output in C.outputs(scene,morph[C.MORPH]):
            slot = C.output_slot(output,morph[C.MORPH])
            for frame,value in keys:
                scene.frame_set(frame)
                assert output.hide_render == (not value['visible'][slot])
                shape = C.state(morph,value['state'])
                np.testing.assert_allclose(atoms(output),C._coordinates(shape['members'][slot]['mesh']),atol=1e-6)
            for (f,a),(t,b) in zip(keys,keys[1:]):
                at = (f+t)//2
                scene.frame_set(at)
                amount = 0 if a.get('transition','MORPH') == 'HOLD' else (at-f)/(t-f)
                start,end = [C._coordinates(C.state(morph,v['state'])['members'][slot]['mesh']) for v in (a,b)]
                np.testing.assert_allclose(atoms(output),start*(1-amount)+end*amount,atol=1e-6)
    baseline['keys'] = C.keyframes(scene)
    baseline['frame'] = sorted(map(int,baseline['keys']))[1]
    return f'{len(roots)} libraries; {len(C.outputs(scene))} animated members; all keyed and midpoint coordinates verified'


def open_key():
    bpy.context.scene.frame_set(baseline['frame'])
    g['active_window']().event_simulate(type='MOUSEMOVE',value='NOTHING',x=0,y=0)
    with g['ui_override']():
        assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def inspect():
    dialog = K._active_instance
    assert dialog and len(dialog.morph_items) == len(C.sets(bpy.context.scene))
    for row in dialog.morph_items:
        expected = baseline['keys'][str(baseline['frame'])].get(row.morph_id)
        assert row.use_morph == bool(expected)
        if expected:
            assert row.state == expected['state']
            assert row.transition == expected.get('transition','MORPH')
    bpy.ops.screen.screenshot(filepath=str(Path(report).parent/'reopened-state-keyframes.png'))
    return 'The installed keyframe editor reopens the saved state and transition choices'


def edit():
    dialog = K._active_instance
    for row in dialog.morph_items:
        row.use_morph = False
    row = dialog.morph_items[0]
    row.use_morph = True
    row.state = C.states(C.find(bpy.context.scene,row.morph_id))[0]['uid']
    baseline['edited_uid'] = row.morph_id
    w = g['active_window']()
    w.event_simulate(type='RET',value='PRESS')
    w.event_simulate(type='RET',value='RELEASE')


def restore():
    keys = C.keyframes(bpy.context.scene)
    frame,uid = str(baseline['frame']),baseline['edited_uid']
    assert keys[frame][uid]['state'] == C.states(C.find(bpy.context.scene,uid))[0]['uid']
    for f,rows in baseline['keys'].items():
        for other,value in rows.items():
            if f != frame or other != uid:
                assert keys[f][other] == value
    C.compile_animation(bpy.context,baseline['keys'])
    verify()
    return 'Edited one state through the live keyframe form; other keys were preserved; restored original animation'


g['steps'][:]=[('workspace',g['setup_morphset_workspace']),('settle load',lambda:None),
    ('verify migrated or new file',verify),('open saved key',open_key),('settle dialog',lambda:None),
    ('inspect saved keyframe form',inspect),('edit one state',edit),('settle edit',lambda:None),('restore animation',restore)]
