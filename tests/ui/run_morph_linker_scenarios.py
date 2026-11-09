"""A linker between Morphset chains through Ctrl+Z and Ctrl+Shift+Z, in a window.

Janet, 2026-11-03: a linker between the two morphing chains of a ChimeraX
morph. Removing the Morphset gives its chains back to the puppet and moves
the linker onto them (``tests/integration/test_morph_linker_lifecycle.py``);
undo and redo only run in a real window, so they are checked here: one Ctrl+Z
brings the Morphset and the linker on its chains back, one Ctrl+Shift+Z takes
them away again. Every check reads the alpha carbons Blender draws.
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
g['steps'][:] = [
    ('workspace', g['setup']), *settle(3, 'ws'),
    ('build morph, puppet, linker', build), *settle(6, 'b'),
    ('delete morphset', delete), *settle(4, 'd'),
    ('ctrl+z', key('Z')), *settle(8, 'u'),
    ('check undone', check_undone), *settle(2, 'c'),
    ('ctrl+shift+z', key('Z', True)), *settle(8, 'r'),
    ('check redone', check_redone),
]
