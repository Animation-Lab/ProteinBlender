"""A linker between Morphset chains through Ctrl+Z and Ctrl+Shift+Z, in a window,
and through Cycle through Conformations.

Janet, 2026-11-03: a linker between the two morphing chains of a ChimeraX
morph. Removing the Morphset gives its chains back to the puppet and moves
the linker onto them (``tests/integration/test_morph_linker_lifecycle.py``);
undo and redo only run in a real window, so they are checked here: one Ctrl+Z
brings the Morphset and the linker on its chains back, one Ctrl+Shift+Z takes
them away again. Every check reads the alpha carbons Blender draws.

Dillon, 2026-11-24: "Linker animation (on morphset) transposes the pieces":
import a morph, make a puppet of its Morphset, link its chains, then Cycle
through Conformations over frames 1-250, and the chains split far apart.
That is taken here through the dialog, with the chains in Cartoon, then
played; the gap between the linked alpha carbons Blender draws must be the
file's at every keyed frame (``test_morph_linkers.py`` has it headless).
"""
import runpy, sys
from pathlib import Path
repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
import bpy
sys.path.insert(0, str(Path(repo) / 'tests' / 'integration'))
H = g['H']
import test_morph_linkers as ML
import test_morph_linker_lifecycle as LC
from test_morphsets import _key
from proteinblender.core import morphsets as C
from proteinblender.operators.morphset_operators import PROTEINBLENDER_OT_cycle_conformations as Cycle
import numpy as np
data = {}
out = Path(g['report_path']).parent
def settle(n, label='e'):
    return [(f'settle {label} {i}', lambda: None) for i in range(n)]
def push(msg):
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.ed.undo_push(message=msg) == {'FINISHED'}
def build():
    scene = bpy.context.scene
    H.reset_scene()
    path = H.chimera_like_ensemble(out / 'morph_ab.pdb', models=3)
    mid = ML._import_states(path)
    (root,) = C.sets(scene); (morph,) = C.morphs(scene, root)
    assert _key(morph, 1, 0) == {'FINISHED'}
    assert _key(morph, 50, 2) == {'FINISHED'}
    scene.frame_set(1)
    members = [r.item_id for r in scene.outliner_items
               if r.item_type == 'MORPH_MEMBER' and r.parent_id == root[C.TAG]]
    names = {r.item_id: r.name for r in scene.outliner_items}
    for row in scene.outliner_items:
        row.is_selected = row.item_id == root[C.TAG]
    assert bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name='Morph Puppet') == {'FINISHED'}
    puppet = next(r for r in scene.outliner_items if r.item_type == 'PUPPET' and r.name == 'Morph Puppet')
    for m in members:
        assert bpy.ops.proteinblender.edit_morph_member(item_id=m, vs_style='spheres') == {'FINISHED'}
    case = dict(path=path, mid=mid, members=members, chain_of={m: names[m].split()[-1] for m in members},
                puppet_id=puppet.item_id)
    linker, *_ = ML._add_morph_linker(case)
    data['ends'] = (linker.endpoint_a_item_id, linker.endpoint_b_item_id)
    push('PB probe morph linker made')
    return f'linker {linker.name} {data["ends"]}'
def delete():
    scene = bpy.context.scene
    (root,) = C.sets(scene)
    assert bpy.ops.proteinblender.delete_morphset(morphset_id=root[C.TAG]) == {'FINISHED'}
    push('PB probe morphset deleted')
    l = scene.pb2_linkers[0]
    return f'after delete: sets={len(C.sets(scene))} ends={(l.endpoint_a_item_id, l.endpoint_b_item_id)}'
def key(k, shift=False):
    def step():
        w = g['active_window'](); a = next(x for x in w.screen.areas if x.type == 'VIEW_3D')
        x, y = a.x + a.width // 2, a.y + a.height // 2
        w.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        w.event_simulate(type=k, value='PRESS', ctrl=True, shift=shift, x=x, y=y)
        w.event_simulate(type=k, value='RELEASE', ctrl=True, shift=shift, x=x, y=y)
    return step
def check_undone():
    scene = bpy.context.scene
    assert len(C.sets(scene)) == 1, 'Morphset not back after Ctrl+Z'
    assert len(scene.pb2_linkers) == 1, f'{len(scene.pb2_linkers)} linkers'
    l = scene.pb2_linkers[0]
    ends = (l.endpoint_a_item_id, l.endpoint_b_item_id)
    assert ends == data['ends'], f'ends {ends} != {data["ends"]}'
    for f in (10, 40):
        scene.frame_set(f)
        assert l.is_valid, 'linker invalid after undo'
        LC._assert_on_visible_alpha_carbons(l, f'after undo, frame {f}')
    return 'Morphset and linker back, ends on drawn alpha carbons'
def check_redone():
    scene = bpy.context.scene
    assert len(C.sets(scene)) == 0, 'Morphset back after redo'
    assert len(scene.pb2_linkers) == 1
    l = scene.pb2_linkers[0]
    rows = [LC._row(l.endpoint_a_item_id), LC._row(l.endpoint_b_item_id)]
    assert all(r is not None and r.item_type == 'CHAIN' for r in rows), rows
    scene.frame_set(20)
    assert l.is_valid
    LC._assert_on_visible_alpha_carbons(l, 'after redo')
    return 'redo: linker on the chains'
def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data['popup'] = getattr(context, 'region_popup', None) or context.region
    cls.draw = draw
def move(x, y):
    data['mouse'] = (int(x), int(y))
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
def cycle_build():
    scene = bpy.context.scene
    H.reset_scene()
    path = H.chimera_like_ensemble(out / 'morph_cycle.pdb', models=21)
    ML._import_states(path)
    (root,) = C.sets(scene); (morph,) = C.morphs(scene, root)
    rows = [(r.item_id, r.name) for r in scene.outliner_items
            if r.item_type == 'MORPH_MEMBER' and r.parent_id == root[C.TAG]]
    (a, name_a), (b, name_b) = rows
    for row in scene.outliner_items:
        row.is_selected = row.item_id == root[C.TAG]
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name='Morph Puppet') == {'FINISHED'}
    puppet = next(r for r in scene.outliner_items if r.item_type == 'PUPPET' and r.name == 'Morph Puppet')
    (res_a, ca_a), (res_b, ca_b) = ML._first_ca(path, 'A'), ML._first_ca(path, 'B')
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.pb2.add_linker(
            'EXEC_DEFAULT', puppet_selector=puppet.item_id,
            endpoint_a_item=f"A_{a}", endpoint_a_residue=res_a,
            endpoint_b_item=f"B_{b}", endpoint_b_residue=res_b,
            length_residues=10, linker_name='A to B') == {'FINISHED'}
    # The dialog starts at the current frame: frame 1, for frames 1-250.
    scene.frame_set(1)
    data.update(cycle_morph=morph[C.MORPH], members=(a, b), names=(name_a, name_b),
                residues=(res_a, res_b), cas=(ca_a, ca_b))
    push('PB probe morph cycle linker made')
    return f'linker on residues {res_a}, {res_b}'
def cycle_open():
    observe(Cycle)
    w = g['active_window'](); a = next(x for x in w.screen.areas if x.type == 'VIEW_3D')
    move(a.x + a.width // 2, a.y + a.height * 0.8)
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.proteinblender.cycle_conformations(
            'INVOKE_DEFAULT', morph_id=data['cycle_morph']) == {'RUNNING_MODAL'}
def cycle_title():
    popup = data['popup']
    move(popup.x + popup.width / 2, popup.y + popup.height - 14)
def cycle_ok():
    path = str(out / 'cycle-dialog.png')
    bpy.ops.screen.screenshot(filepath=path)
    x, y = data['mouse']
    for value in ('PRESS', 'RELEASE'):
        g['active_window']().event_simulate(type='RET', value=value, x=x, y=y)
def cycle_play():
    keys = C.morph_keys(bpy.context.scene, data['cycle_morph'])
    assert len(keys) == 50 and min(map(int, keys)) == 1 and max(map(int, keys)) == 246, sorted(keys, key=int)[:5]
    bpy.context.scene.frame_set(1)
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.screen.animation_play() == {'FINISHED'}
def cycle_stop():
    with g['ui_override']('VIEW_3D'):
        bpy.ops.screen.animation_cancel(restore_frame=False)
    frame = bpy.context.scene.frame_current
    bpy.ops.screen.screenshot(filepath=str(out / 'cycle-played.png'))
    return f'played to frame {frame}'
def cycle_check():
    scene = bpy.context.scene
    for member in data['members']:
        assert bpy.ops.proteinblender.edit_morph_member(item_id=member, vs_style='spheres') == {'FINISHED'}
    morph = C.find(scene, data['cycle_morph'])
    order = [s['uid'] for s in C.states(morph)]
    keys = C.morph_keys(scene, data['cycle_morph'])
    (name_a, name_b), (res_a, res_b), (ca_a, ca_b) = data['names'], data['residues'], data['cas']
    seen = []
    for frame in (1, 6, 51, 101, 246):
        model = order.index(keys[str(frame)]['state'])
        scene.frame_set(frame)
        drawn = np.linalg.norm(
            H.visible_alpha_carbon([H.morph_output_named(name_b)], res_b)
            - H.visible_alpha_carbon([H.morph_output_named(name_a)], res_a))
        truth = np.linalg.norm(ca_b[model] - ca_a[model]) * ML.SCALE
        assert abs(drawn - truth) < 2e-4, (
            f'frame {frame} (model {model + 1}): linked CAs drawn {drawn / ML.SCALE:.1f} A apart, '
            f'the file has {truth / ML.SCALE:.1f} A')
        seen.append(f'{frame}:{drawn / ML.SCALE:.1f}A')
    return ', '.join(seen)
g['steps'][:] = [
    ('workspace', g['setup']), *settle(3, 'ws'),
    ('build morph, puppet, linker', build), *settle(6, 'b'),
    ('delete morphset', delete), *settle(4, 'd'),
    ('ctrl+z', key('Z')), *settle(8, 'u'),
    ('check undone', check_undone), *settle(2, 'c'),
    ('ctrl+shift+z', key('Z', True)), *settle(8, 'r'),
    ('check redone', check_redone), *settle(2, 'cr'),
    ('cycle: morph, puppet and linker', cycle_build), *settle(6, 'cb'),
    ('cycle: open Cycle through Conformations', cycle_open), *settle(3, 'co'),
    ('cycle: hover the dialog title', cycle_title), *settle(2, 'ct'),
    ('cycle: OK', cycle_ok), *settle(10, 'ck'),
    ('cycle: play', cycle_play), *settle(20, 'cp'),
    ('cycle: stop', cycle_stop), *settle(2, 'cs'),
    ('cycle: chains where the file puts them', cycle_check),
]
