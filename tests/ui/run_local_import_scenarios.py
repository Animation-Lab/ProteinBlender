"""Opening local structure files through the real window, file browser and menus.

GitHub #19: "I can import PDB files from the internet, but I cannot open local
files." Headless tests call ``molecule.import_local`` with a filepath, which
skips everything a user actually touches. This scenario goes through it:

* the Import Local File button drawn in the Protein Import panel;
* the file browser it opens, including which files it lists;
* choosing a file and pressing Import, then choosing the same file again;
* selecting several files at once;
* the File > Import menu;
* dragging a file onto the 3D viewport and onto the Properties editor.
"""
import gzip
import runpy
import shutil
import sys
from pathlib import Path

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
import bpy

H = g['H']
data = {}

STRUCTURES = {'4hhb.pdb': '4hhb.pdb', '4ins.cif': '4ins.cif',
              'Upper.PDB': '1ubq.pdb', 'assembly.mmCIF': '5im3.cif',
              'ensemble.pdb': '1d3z.pdb.gz'}  # a 10-model NMR ensemble
HIDDEN = ('notes.txt', 'ligand.sdf')


def settle(count=1, label='event loop'):
    return [(f'settle {label} {i + 1}', lambda: None) for i in range(count)]


def capture(name):
    path = str(Path(g['report_path']).parent / name)
    bpy.ops.screen.screenshot(filepath=path)
    return path


def molecules():
    return sorted(H.sm().molecules)


def pdb_chains(path):
    """Chain letters straight from the file text, independent of the add-on."""
    return {line[21] for line in Path(path).read_text().splitlines()
            if line.startswith('ATOM')}


def browser():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'FILE_BROWSER':
                return window, area
    return None, None


def prepare():
    H.reset_scene()
    folder = Path(g['report_path']).parent / 'local-import-files'
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for name, fixture in STRUCTURES.items():
        if fixture.endswith('.gz') and not name.endswith('.gz'):
            (folder / name).write_bytes(gzip.open(H.data_path(fixture)).read())
        else:
            shutil.copy(H.data_path(fixture), folder / name)
    for name in HIDDEN:
        (folder / name).write_text('not a structure\n')
    data['folder'] = folder
    assert not molecules()
    return str(folder)


def observe_panel():
    from proteinblender.panels.panel_import_protein import PROTEIN_PB_PT_import_protein as Panel
    original = Panel.draw

    def draw(self, context):
        original(self, context)
        data['panel'] = str(self.layout.introspect())
    Panel.draw = draw
    data['panel_class'], data['panel_draw'] = Panel, original
    g['protein_workspace_panel_area']().tag_redraw()


def check_panel_button():
    layout = data.get('panel', '')
    assert 'Import Local File' in layout, 'the Protein Import panel does not offer Import Local File'
    assert 'molecule.import_local' in layout, layout[:400]
    data['panel_class'].draw = data['panel_draw']
    capture('local-import-panel.png')
    return 'Protein Import panel draws Import Local File'


def click_import_local_file():
    # Exactly what the panel button runs: an invoke from the Properties editor.
    with g['ui_override']('PROPERTIES'):
        assert bpy.ops.molecule.import_local('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def point_browser_at_folder():
    window, area = browser()
    assert area is not None, 'Import Local File did not open a file browser'
    area.spaces.active.params.directory = str(data['folder']).encode()
    return f'file browser filter: {area.spaces.active.params.filter_glob}'


def check_browser_listing():
    window, area = browser()
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.file.select_all(action='SELECT')
        listed = sorted(item.name for item in bpy.context.selected_files)
        bpy.ops.file.select_all(action='DESELECT')
    assert listed == sorted(STRUCTURES), (
        f'file browser listed {listed}; expected exactly {sorted(STRUCTURES)} '
        f'(not {list(HIDDEN)})')
    capture('local-import-browser.png')
    return 'lists ' + ', '.join(listed)


def choose(name, interpretation=None):
    def step():
        window, area = browser()
        assert area is not None, 'file browser is not open'
        area.spaces.active.params.filename = name
        if interpretation:
            # The "Multiple models" option in the browser's side panel.
            area.spaces.active.active_operator.model_interpretation = interpretation
        region = next(r for r in area.regions if r.type == 'EXECUTE')
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.file.execute() == {'FINISHED'}
    return step


def execute_selection():
    window, area = browser()
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.file.select_all(action='SELECT')
    region = next(r for r in area.regions if r.type == 'EXECUTE')
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.file.execute() == {'FINISHED'}


def expect_browser_closed():
    window, area = browser()
    assert area is None, 'the file browser stayed open after Import'


def expect_first_import():
    assert molecules() == ['4hhb'], molecules()
    molecule = H.sm().molecules['4hhb']
    chains = pdb_chains(data['folder'] / '4hhb.pdb')
    assert len(molecule.domains) == len(chains) == 4
    assert [i.identifier for i in bpy.context.scene.molecule_list_items] == ['4hhb']
    drawn = H.evaluated_atom_positions(
        [molecule.object, *(d.object for d in molecule.domains.values())])
    assert len(drawn) > 4000
    return f'{len(drawn)} atoms drawn in {len(chains)} chains'


def expect_ensemble_read_as_assembly():
    """The browser option is honoured: ten NMR models become ten copies."""
    molecule = H.sm().molecules['ensemble']
    assert len(molecule.domains) == 10, len(molecule.domains)
    return 'Assembly copies -> 10 chain copies'


def expect_second_copy():
    assert molecules() == ['4hhb', '4hhb_002'], molecules()
    rows = {i.identifier: i.object_ptr.name for i in bpy.context.scene.molecule_list_items}
    assert sorted(rows) == molecules()
    assert len(set(rows.values())) == 2, rows
    first, second = (H.sm().molecules[m] for m in molecules())
    assert first.object != second.object
    return 'same file twice -> two independent proteins'


def observe_import_menu():
    def observe(self, context):
        data['menu'] = str(self.layout.introspect())
    bpy.types.TOPBAR_MT_file_import.append(observe)
    data['menu_observer'] = observe
    with g['ui_override']('VIEW_3D'):
        bpy.ops.wm.call_menu(name='TOPBAR_MT_file_import')


def check_import_menu():
    bpy.types.TOPBAR_MT_file_import.remove(data['menu_observer'])
    g['active_window']().event_simulate(type='ESC', value='PRESS')
    g['active_window']().event_simulate(type='ESC', value='RELEASE')
    menu = data.get('menu', '')
    assert 'molecule.import_local' in menu, 'File > Import has no ProteinBlender entry: ' + menu[:300]
    assert 'Protein Structure' in menu, menu[:300]
    return 'File > Import offers Protein Structure'


def drop(area_type, name):
    def step():
        before = set(molecules())
        with g['ui_override'](area_type):
            result = bpy.ops.wm.drop_import_file(
                'EXEC_DEFAULT', directory=str(data['folder']), files=[{'name': name}])
        assert result == {'FINISHED'}, f'dropping {name} on {area_type} returned {result}'
        added = sorted(set(molecules()) - before)
        assert len(added) == 1 and added[0].startswith(Path(name).stem), added
        return f'{name} dropped on {area_type} -> {added[0]}'
    return step


def expect_drop_detects_models_itself():
    """A drop has no options, so an earlier "Assembly copies" must not carry over."""
    molecule = H.sm().molecules['ensemble_002']
    assert len(molecule.domains) == 1, (
        f'dropped NMR ensemble read as {len(molecule.domains)} copies; the '
        'previous import\'s Multiple models choice leaked into the drop')
    return 'dropped ensemble detected as conformations (1 chain)'


def expect_everything():
    # 4hhb: button, button again, multi-select. 4ins and assembly: dropped, then
    # multi-select. ensemble: button (Assembly copies), dropped, multi-select.
    # Upper: multi-select only.
    ids = molecules()
    assert ids == sorted(['4hhb', '4hhb_002', '4hhb_003', '4ins', '4ins_002',
                          'Upper', 'assembly', 'assembly_002',
                          'ensemble', 'ensemble_002', 'ensemble_003']), ids
    rows = [i.identifier for i in bpy.context.scene.molecule_list_items]
    assert sorted(rows) == ids, (rows, ids)
    capture('local-import-final.png')
    return ', '.join(ids)


def save():
    bpy.ops.wm.save_as_mainfile(
        filepath=str(Path(g['report_path']).parent / 'local-import.blend'))
    return 'saved'


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), *settle(2, 'workspace'),
    ('prepare structure files', prepare),
    ('watch the Protein Import panel draw', observe_panel), *settle(3, 'panel redraw'),
    ('Protein Import panel offers Import Local File', check_panel_button),
    ('click Import Local File', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder', point_browser_at_folder), *settle(20, 'file list'),
    ('file browser lists exactly the structure files', check_browser_listing),
    ('choose 4hhb.pdb and press Import', choose('4hhb.pdb')), *settle(8, 'import'),
    ('file browser closed', expect_browser_closed),
    ('4hhb imported with every chain', expect_first_import),
    ('click Import Local File again', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder again', point_browser_at_folder), *settle(20, 'file list'),
    ('choose the same 4hhb.pdb and press Import', choose('4hhb.pdb')), *settle(8, 'import'),
    ('same file twice gives two independent proteins', expect_second_copy),
    ('click Import Local File for an ensemble', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder for the ensemble', point_browser_at_folder),
    *settle(20, 'file list'),
    ('choose ensemble.pdb, set Multiple models to Assembly copies, Import',
     choose('ensemble.pdb', 'ASSEMBLY')), *settle(8, 'import'),
    ('Assembly copies option is honoured', expect_ensemble_read_as_assembly),
    ('open File > Import', observe_import_menu), *settle(4, 'menu'),
    ('File > Import offers structure files', check_import_menu), *settle(2, 'menu close'),
    ('drop 4ins.cif on the 3D viewport', drop('VIEW_3D', '4ins.cif')), *settle(4, 'drop'),
    ('drop assembly.mmCIF on the Properties editor', drop('PROPERTIES', 'assembly.mmCIF')),
    *settle(4, 'drop'),
    ('drop ensemble.pdb on the 3D viewport', drop('VIEW_3D', 'ensemble.pdb')), *settle(4, 'drop'),
    ('a drop does not inherit the earlier Multiple models choice', expect_drop_detects_models_itself),
    ('click Import Local File for a multi-select', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder for multi-select', point_browser_at_folder),
    *settle(20, 'file list'),
    ('select every listed file and press Import', execute_selection), *settle(12, 'import'),
    ('every selected file imported once', expect_everything),
    ('save', save),
]
