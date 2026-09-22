"""Verify a UI-authored Morphset after a fresh installed-profile file load."""
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo, report = sys.argv[sys.argv.index('--')+1:][:2]
g = runpy.run_path(str(Path(repo)/'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import morphsets as C, model_morphsets as M
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as K

data = {}


def check_file():
    root = C.sets(bpy.context.scene)[0]
    morph = M.subject(root)
    assert len(C.sets(bpy.context.scene)) == len(C.morphs(bpy.context.scene)) == len(C.outputs(bpy.context.scene)) == 1
    assert len(C.states(morph)) == 10
    assert root.parent == root['pb_model_source']
    assert sorted(map(int, C.keyframes(bpy.context.scene))) == [1,50,75,100]
    row = next(r for r in bpy.context.scene.outliner_items if r.item_id == root[C.TAG])
    assert row.parent_id == M.source_id(root) and row.indent_level == 1
    assert any(r.parent_id == root[C.TAG] and r.name == 'Chain A' for r in bpy.context.scene.outliner_items)
    data['uid'] = morph[C.MORPH]
    data['points'] = [C._coordinates(s['members'][0]['mesh']) for s in C.states(morph)]
    for frame, model in [(1,0),(50,2),(75,7),(100,8)]:
        atoms(frame, data['points'][model])
    atoms(60, data['points'][2]*.6 + data['points'][7]*.4)
    bpy.context.scene.frame_set(1)
    bpy.ops.screen.screenshot(filepath=str(Path(report).parent/'reopened-model-morphset.png'))
    return 'Reopened hierarchy, all ten models, four exact keys, and direct Model 3 → 8 interpolation verified'


def atoms(frame, expected):
    bpy.context.scene.frame_set(frame)
    obj = C.outputs(bpy.context.scene)[0]
    assert len(g['H'].eval_positions(obj)) > 0
    enabled = [m.show_viewport for m in obj.modifiers]
    for m in obj.modifiers:
        m.show_viewport = False
    bpy.context.view_layer.update()
    np.testing.assert_allclose(g['H'].eval_positions(obj), expected, atol=1e-6)
    for m, enabled in zip(obj.modifiers, enabled):
        m.show_viewport = enabled


def open_edit():
    with g['ui_override']():
        assert bpy.ops.proteinblender.edit_keyframe(frame=75) == {'RUNNING_MODAL'}


def change_model():
    dialog = K._active_instance
    assert dialog and dialog.frame_number == 75
    row = dialog.morph_items[0]
    assert row.use_morph
    values = C.states(C.find(bpy.context.scene, data['uid']))
    assert row.state == values[7]['uid']
    row.state = values[6]['uid']
    window = g['active_window']()
    window.event_simulate(type='RET',value='PRESS')
    window.event_simulate(type='RET',value='RELEASE')


def verify_edit_and_delete():
    atoms(75,data['points'][6])
    assert bpy.ops.proteinblender.delete_keyframe(frame=75) == {'FINISHED'}
    assert sorted(map(int, C.keyframes(bpy.context.scene))) == [1,50,100]
    atoms(60,data['points'][2]*.8+data['points'][8]*.2)
    return 'The saved file remains editable through the keyframe-list pencil; deleting a key reconnects its neighbors'


g['steps'][:] = [('workspace', g['setup_morphset_workspace']), ('settle load', lambda: None),
    ('verify saved Morphset', check_file), ('edit saved keyframe', open_edit),
    ('settle editor', lambda: None), ('change saved model', change_model),
    ('settle edit', lambda: None), ('verify edit and delete', verify_edit_and_delete)]
