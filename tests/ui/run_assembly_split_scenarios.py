"""Ann's 1STM assembly in a real window: split, re-cut, color, edit, realize.

Ann (2026-11-10, Alpha 1.2.5, Blender 5.2.3) split chain B of 1STM's complete
icosahedral assembly into two domains, moved the cut, colored the pieces,
pressed the protein row's pencil ("an error message popped up") and realized
the copies ("the domain split options are only available for the first set of
chains"). This walks the same path with the real dialogs opened by INVOKE in
the window: the lane fails on any Python or draw error Blender reports, which
is what her pop-up was. The headless geometry checks for the same workflow are
``tests/integration/test_assembly_chain_split.py``.
"""
import json
import runpy
import sys
from pathlib import Path

import bpy

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.operators import visual_edit

H = g['H']
data = {}
RED, BLUE = (1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)


def shot(name):
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / name))


def rows():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    return bpy.context.scene.outliner_items


def chain_row(molecule_id, name='Chain B'):
    return next(r for r in rows() if r.item_type == 'CHAIN'
                and r.parent_id == molecule_id and r.name == name)


def pieces(molecule_id):
    molecule = H.sm().molecules[molecule_id]
    return [key for key, d in sorted(molecule.domains.items(), key=lambda kv: kv[1].start)
            if str(d.chain_id) == 'B']


def splitter(molecule_id, ranges, ids=None):
    row = chain_row(molecule_id)
    ids = ids or [''] * len(ranges)
    layout = json.dumps([{'name': '', 'start': a, 'end': b, 'domain_id': i}
                         for (a, b), i in zip(ranges, ids)])
    with g['ui_override']('PROPERTIES'):
        return bpy.ops.proteinblender.edit_chain_domains(
            'EXEC_DEFAULT', item_id=row.item_id, layout_json=layout, chain_name=row.name)


def escape():
    window = g['active_window']()
    window.event_simulate(type='ESC', value='PRESS')
    window.event_simulate(type='ESC', value='RELEASE')


def prepare():
    H.reset_scene()
    with g['ui_override']('VIEW_3D'):
        mid = data['mid'] = H.import_local('1stm.cif.gz', '1STM')
        assert bpy.ops.molecule.symmetry_dialog(
            target_id=mid, source='BIOLOGICAL', assembly_id='1') == {'FINISHED'}
    assert splitter(mid, [(17, 100), (101, 223)]) == {'FINISHED'}
    assert splitter(mid, [(17, 150), (151, 223)], pieces(mid)) == {'FINISHED'}
    first, second = pieces(mid)
    for domain_id, color in ((first, RED), (second, BLUE)):
        row = next(r for r in rows() if r.item_type == 'DOMAIN' and r.item_id == domain_id)
        row.row_color = color
    # Janet's half of the report: restyle a chain, then press the protein's pencil.
    other = next(key for key, d in H.sm().molecules[mid].domains.items()
                 if str(d.chain_id) == 'A')
    assert bpy.ops.proteinblender.rename_domain(
        target_item_id=other, item_type='DOMAIN',
        new_name=H.sm().molecules[mid].domains[other].name,
        vs_style='surface') == {'FINISHED'}
    bpy.context.view_layer.update()
    shot('assembly-split-prepared.png')
    return f'{mid}: chain B cut at 150 into {len(pieces(mid))} colored pieces'


def open_protein_pencil(key):
    def run():
        mid = data[key] if key in data else key
        with g['ui_override']('PROPERTIES'):
            result = bpy.ops.proteinblender.edit_protein_visuals('INVOKE_DEFAULT', item_id=mid)
        assert result == {'RUNNING_MODAL'}, result
        assert visual_edit.active_dialog() is not None, f'the pencil on {mid} opened no dialog'
        shot(f'assembly-split-pencil-{mid}.png')
        return f'{mid} pencil opened'
    return run


def close_dialog():
    escape()


def assert_closed():
    assert visual_edit.active_dialog() is None, 'Escape left the dialog open'
    return 'closed'


def realize():
    with g['ui_override']('PROPERTIES'):
        assert bpy.ops.molecule.realize_copies(
            'EXEC_DEFAULT', molecule_id=data['mid']) == {'FINISHED'}
    copies = [m for m in H.sm().molecules if m != data['mid']]
    assert len(copies) == 11, f'12 copies should make 11 new proteins, got {copies}'
    data['copy'] = copies[0]
    for molecule_id in H.sm().molecules:
        spans = [(H.sm().molecules[molecule_id].domains[k].start,
                  H.sm().molecules[molecule_id].domains[k].end) for k in pieces(molecule_id)]
        assert spans == [(17, 150), (151, 223)], (molecule_id, spans)
    shot('assembly-split-realized.png')
    return f'realized: {len(copies)} new proteins, each with both pieces of chain B'


def open_copy_splitter():
    """The copy's chain B offers the Domain Splitter, not only a rename."""
    from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_UL_outliner

    row = chain_row(data['copy'])

    class Recorder:
        def __init__(self):
            self.operators = []

        def operator(self, identifier, **kwargs):
            self.operators.append(identifier)
            return type('Props', (), {})()

        def __getattr__(self, name):
            return lambda *a, **k: self

    recorder = Recorder()
    PROTEINBLENDER_UL_outliner.draw_actions(bpy.context, recorder, row)
    assert 'proteinblender.edit_chain_domains' in recorder.operators, recorder.operators
    with g['ui_override']('PROPERTIES'):
        result = bpy.ops.proteinblender.edit_chain_domains('INVOKE_DEFAULT', item_id=row.item_id)
    assert result == {'RUNNING_MODAL'}, result
    shot('assembly-split-copy-splitter.png')
    return f"{data['copy']} chain B opened the Domain Splitter"


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('split, re-cut and color chain B of the capsid', prepare), ('settle', lambda: None),
    ('press the assembly protein pencil', open_protein_pencil('mid')), ('settle', lambda: None),
    ('close it', close_dialog), ('settle', lambda: None),
    ('assert it closed', assert_closed), ('settle', lambda: None),
    ('realize the copies', realize), ('settle', lambda: None),
    ('press a copy protein pencil', open_protein_pencil('copy')), ('settle', lambda: None),
    ('close the copy dialog', close_dialog), ('settle', lambda: None),
    ('assert the copy dialog closed', assert_closed), ('settle', lambda: None),
    ('open the Domain Splitter on a copy', open_copy_splitter), ('settle', lambda: None),
    ('close the Domain Splitter', close_dialog), ('settle', lambda: None),
]
