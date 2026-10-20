"""Exercise Janet's assembly and cycling workflows across real UI event loops."""
import runpy
import site
import sys
from pathlib import Path

import bpy
import numpy as np

repo = sys.argv[sys.argv.index('--') + 1]
sys.path.insert(0, repo)
sys.path.append(site.getusersitepackages())
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import assembly as A, morphsets as C, model_morphsets as M
from proteinblender.operators.symmetry_dialog import MOLECULE_PB_OT_symmetry_dialog as S
from proteinblender.operators.morphset_operators import PROTEINBLENDER_OT_cycle_conformations as Cycle
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as K

H = g['H']
data = {}


def event(kind='RET'):
    window = g['active_window']()
    window.event_simulate(type=kind, value='PRESS')
    window.event_simulate(type=kind, value='RELEASE')


def redraw():
    if data.get('popup'):
        data['popup'].tag_redraw()
    for area in g['active_window']().screen.areas:
        area.tag_redraw()


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('items', []))


def prepare():
    H.reset_scene()
    with g['ui_override']('VIEW_3D'):
        data['mid'] = H.import_local('1stm.cif.gz', '1STM')
        data['other_mid'] = H.import_local('1stm.cif.gz', '1STM_001')
        for mid in (data['mid'], data['other_mid']):
            bpy.ops.molecule.symmetry_dialog(target_id=mid, source='GENERATED')
    bpy.context.view_layer.update()
    other = H.sm().molecules[data['other_mid']]
    data['other_atoms'] = H.evaluated_atom_positions(A._target_objects(other))
    assert len(data['other_atoms']) > 0
    bpy.ops.proteinblender.outliner_item_info(item_id=data['mid'])
    def observe(cls):
        original = cls.draw
        def draw(self, context):
            original(self, context)
            data[cls.__name__] = self
            data[cls.__name__ + '_layout'] = self.layout.introspect()
            data['popup'] = getattr(context, 'region_popup', None) or context.region
        cls.draw = draw
    for cls in (S, Cycle, K):
        observe(cls)
    with g['ui_override']():
        bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT', molecule_id_to_update=data['mid'])


def seek(where, wanted):
    """Walk the cursor down the dialog until Ctrl+C reports ``wanted``.

    Blender copies what is under the cursor, and for a dropdown that is the
    identifier it is showing. That finds a control wherever the dialog has
    put it, which a fixed coordinate stops doing the day a row is added.
    """
    def run():
        wm = bpy.context.window_manager
        popup = data['popup']
        window = g['active_window']()
        step = 6 * bpy.context.preferences.system.ui_scale
        text = wanted() if callable(wanted) else wanted
        at = data.get('seek')
        if at is None:
            at = (round(popup.x + popup.width * .75), round(popup.y + popup.height - step))
        elif wm.clipboard == text:
            data.pop('seek')
            # One step further in than the edge the probe has just crossed.
            data[where] = (at[0], round(at[1] - step))
            return f'{text} at {data[where]}'
        else:
            at = (at[0], round(at[1] - step))
        assert at[1] > popup.y, f'No control showing {text} in the dialog'
        data['seek'] = at
        wm.clipboard = ''
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=at[0], y=at[1])
        def copy():
            for value in ('PRESS', 'RELEASE'):
                window.event_simulate(type='C', value=value, ctrl=True, x=at[0], y=at[1])
        g['steps'][:0] = [('hover', lambda: None), ('copy hovered control', copy),
                          ('settle', lambda: None), (f'seek {text}', run)]
    return run


def click(where):
    x, y = data[where]
    window = g['active_window']()
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    for value in ('PRESS', 'RELEASE'):
        window.event_simulate(type='LEFTMOUSE', value=value, x=x, y=y)


def switch_to_deposited():
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / 'generated-dialog.png'))
    assert data[S.__name__].source == 'GENERATED'
    click('source_xy')


def choose_pdb_source():
    event('HOME')
    event()


def choose_assembly(aid):
    dialog = data[S.__name__]
    assert dialog.source == 'BIOLOGICAL'
    from proteinblender.operators.symmetry_dialog import biological_enum_items
    assert [item[0] for item in biological_enum_items(dialog, bpy.context)] == ['1','2','3','4','5','6']
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / 'assembly-dialog.png'))
    click('assembly_xy')
    data['desired_assembly'] = aid
    return f"Assembly dropdown click {data['assembly_xy']}"


def select_menu():
    path = str(Path(g['report_path']).parent / 'assembly-menu.png')
    bpy.ops.screen.screenshot(filepath=path)
    event('HOME')
    for _ in range(int(data['desired_assembly']) - 1):
        event('DOWN_ARROW')
    event()
    return f'Select assembly {data["desired_assembly"]} with keyboard navigation'


def shown_on_choosing(aid):
    """Choosing an assembly in the menu shows it: there is no button to press."""
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / 'assembly-selected.png'))
    assert data[S.__name__].assembly_id == aid, (data[S.__name__].assembly_id, aid)
    layout = data[S.__name__ + '_layout']
    assert not any(item.get('draw_string') == 'Apply' for item in flatten(layout)), (
        'The dialog still has an Apply button')
    assert A.built_assembly_id(H.sm().molecules[data['mid']]) == aid, (
        'Choosing an assembly did not show it', A.built_assembly_id(H.sm().molecules[data['mid']]), aid)
    verify_other_assembly()
    redraw()


def verify_other_assembly():
    other = H.sm().molecules[data['other_mid']]
    bpy.context.view_layer.update()
    atoms = H.evaluated_atom_positions(A._target_objects(other))
    np.testing.assert_allclose(np.sort(atoms, axis=0), np.sort(data['other_atoms'], axis=0), atol=1e-6)


def confirm():
    data.pop('popup', None)
    event()


def verify_and_edit(aid):
    assert A.built_assembly_id(H.sm().molecules[data['mid']]) == aid
    with g['ui_override']():
        bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT', molecule_id_to_update=data['mid'])


def verify_reopened(aid):
    assert data[S.__name__].assembly_choice == aid


def verify_cancel():
    assert A.built_assembly_id(H.sm().molecules[data['mid']]) == '5'
    verify_other_assembly()


def prepare_cycle():
    with g['ui_override']('VIEW_3D'):
        mid = H.import_local('1d3z.pdb.gz', 'Models')
        bpy.ops.proteinblender.create_morphset(name='Cycle models', source=mid)
    morph = M.subject(C.sets(bpy.context.scene)[0]); data['uid'] = morph[C.MORPH]
    with g['ui_override']():
        bpy.ops.proteinblender.cycle_conformations('INVOKE_DEFAULT', morph_id=data['uid'],
                                                 start_frame=1, end_frame=51, frame_step=5)


def configure_cycle():
    dialog = data[Cycle.__name__]
    assert (dialog.start_frame, dialog.end_frame, dialog.frame_step) == (1, 51, 5)
    assert dialog.existing == 'KEEP'
    redraw()


def inspect_cycle():
    layout = str(data[Cycle.__name__ + '_layout'])
    assert '11 positions' in layout and 'In order, repeating' in layout
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / 'cycle-conformations.png'))
    confirm()


def verify_cycle_and_undo():
    keys = C.morph_keys(bpy.context.scene, data['uid'])
    assert set(map(int, keys)) == set(range(1, 52, 5))
    assert keys['1']['state'] == keys['51']['state']
    with g['ui_override']():
        assert bpy.ops.ed.undo() == {'FINISHED'}


def verify_undo_and_redo():
    assert not C.morph_keys(bpy.context.scene, data['uid'])
    with g['ui_override']():
        assert bpy.ops.ed.redo() == {'FINISHED'}


def verify_redo_and_key_dialog():
    assert len(C.morph_keys(bpy.context.scene, data['uid'])) == 11
    with g['ui_override']():
        bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT')


def inspect_key_dialog():
    row = next(r for r in data[K.__name__].morph_items if r.morph_id == data['uid'])
    row.use_morph = True
    redraw()


def verify_cycle_entry_and_cancel():
    layout = str(data[K.__name__ + '_layout'])
    assert 'Cycle through Conformations' in layout
    event('ESC')


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('open assembly dialog', prepare), ('settle', lambda: None),
    ('find the source dropdown', seek('source_xy', 'GENERATED')), ('settle', lambda: None),
    ('switch generated to PDB-defined', switch_to_deposited), ('settle', choose_pdb_source),
    ('settle', lambda: None),
    ('choose assembly 4', lambda: choose_assembly('4')), ('settle', lambda: None),
    ('assembly 4 shown on choosing', lambda: shown_on_choosing('4')), ('settle', lambda: None),
    ('confirm assembly', confirm), ('settle', lambda: None),
    ('reopen assembly 4', lambda: verify_and_edit('4')), ('settle', lambda: None),
    ('verify reopened choice', lambda: verify_reopened('4')),
    ('choose assembly 5', lambda: choose_assembly('5')), ('settle', lambda: None),
    ('assembly 5 shown on choosing', lambda: shown_on_choosing('5')), ('settle', lambda: None),
    ('confirm assembly 5', confirm), ('settle', lambda: None),
    ('reopen assembly 5', lambda: verify_and_edit('5')), ('settle', lambda: None),
    ('choose assembly 1 preview', lambda: choose_assembly('1')), ('settle', lambda: None),
    ('assembly 1 shown on choosing', lambda: shown_on_choosing('1')), ('settle', lambda: None),
    ('cancel preview', lambda: event('ESC')), ('settle', lambda: None),
    ('verify cancel restores 5', verify_cancel),
    ('open cycling dialog', prepare_cycle), ('settle', lambda: None),
    ('configure cycling', configure_cycle), ('settle', lambda: None),
    ('inspect and confirm cycling', inspect_cycle), ('settle', lambda: None),
    ('verify keys and undo', verify_cycle_and_undo), ('settle', lambda: None),
    ('verify undo and redo', verify_undo_and_redo), ('settle', lambda: None),
    ('verify redo and key dialog', verify_redo_and_key_dialog), ('settle', lambda: None),
    ('enable Morphset keyframe row', inspect_key_dialog), ('settle', lambda: None),
    ('verify cycling entry', verify_cycle_entry_and_cancel), ('settle', lambda: None),
]
for index, (name, function) in reversed(list(enumerate(g['steps']))):
    if name.startswith('choose assembly'):
        g['steps'].insert(index + 1, ('select dropdown entry', select_menu))
        # The dropdown shows the assembly currently chosen, whichever that is.
        g['steps'][index:index] = [
            ('find the assembly dropdown',
             seek('assembly_xy', lambda: data[S.__name__].assembly_choice)),
            ('settle', lambda: None)]
