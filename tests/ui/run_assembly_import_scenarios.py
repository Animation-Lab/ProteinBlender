"""Create New Assembly on an empty scene: type a PDB ID, press OK.

Reported: with nothing imported, typing 1atn into the dialog's own Protein
block and pressing OK answered "Import a protein first - a symmetry repeats
one". The id was right there in the form. This drives the real dialog: its
invoke, the typed id (the very property write the Info log recorded) and the
RET that confirms it, with the download answered offline from the bundled
1ATN mmCIF so that everything after the HTTP call is the real import.
"""
import gzip
import runpy
import sys
from pathlib import Path

import bpy

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from proteinblender.core import assembly as A
from proteinblender.operators.symmetry_dialog import MOLECULE_PB_OT_symmetry_dialog as S
from proteinblender.utils.molecularnodes import download

H = g['H']
data = {}


def redraw():
    popup = data.get('popup')
    if popup:
        popup.tag_refresh_ui()
    for area in g['active_window']().screen.areas:
        area.tag_redraw()


def shot(name):
    bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / name))


def prepare():
    H.reset_scene()
    assert not H.sm().molecules, 'the scenario starts from an empty scene'
    served = gzip.open(H.data_path('1atn.cif.gz'), 'rt', encoding='utf-8').read()
    data['requested'] = []

    class Response:
        status_code = 200

        def __init__(self):
            self.text = served
            self.content = served.encode('utf-8')

    def answer(url, *args, **kwargs):
        data['requested'].append(url)
        return True, Response()

    data['real_download'] = download._download_with_retry
    download._download_with_retry = answer

    data['original_draw'] = S.draw

    def draw(self, context):
        data['original_draw'](self, context)
        data['dialog'] = self
        data['layout'] = self.layout.introspect()
        data['popup'] = getattr(context, 'region_popup', None)

    S.draw = draw
    with g['ui_override']('PROPERTIES'):
        assert bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
    return 'Create New Assembly opened on an empty scene'


def type_the_id():
    layout = str(data['layout'])
    assert 'Import one above to build a symmetry from it' in layout, layout
    assert data['dialog'].source == 'BIOLOGICAL', data['dialog'].source
    props = bpy.context.scene.protein_props
    assert (props.import_method, props.remote_format) == ('PDB', 'cif'), (
        props.import_method, props.remote_format)
    props.pdb_id = '1atn'  # what the Info log recorded
    redraw()
    return 'typed 1atn into the dialog\'s PDB ID field'


def press_ok():
    shot('assembly-from-id-dialog.png')
    window = g['active_window']()
    for value in ('PRESS', 'RELEASE'):
        window.event_simulate(type='RET', value=value)


def verify():
    S.draw = data['original_draw']
    download._download_with_retry = data['real_download']
    assert data['requested'] and '1atn' in data['requested'][0].lower(), data['requested']
    molecules = H.sm().molecules
    assert list(molecules) == ['1atn_001'], (
        f'OK must import the typed structure; molecules={list(molecules)}')
    molecule = molecules['1atn_001']
    assert A.built_assembly_id(molecule) == '1', A.built_assembly_id(molecule)
    rows = [(r.item_type, r.name) for r in bpy.context.scene.outliner_items]
    assert any(kind == 'SYMMETRY' for kind, _ in rows), rows
    shot('assembly-from-id-built.png')
    return 'OK imported 1atn and built its deposited assembly 1'


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', lambda: None),
    ('open Create New Assembly on an empty scene', prepare), ('settle', lambda: None),
    ('type the PDB ID', type_the_id), ('settle', lambda: None),
    ('press OK', press_ok), ('settle', lambda: None),
    ('verify the import and the build', verify),
]
