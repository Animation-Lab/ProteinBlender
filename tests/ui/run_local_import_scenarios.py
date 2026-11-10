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
    if bpy.app.version[:2] == (5, 1) and browser()[1] is not None:
        # Blender 5.1.0 crashes in the NVIDIA OpenGL driver (nvoglv64.dll)
        # when a file browser window that screen.screenshot has drawn is then
        # closed by Import. Its own OBJ importer crashes the same way, so it
        # is Blender's, and no user takes a scripted screenshot there.
        return None
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
    # A ChimeraX morph (Janet's morph.pdb, 2026-11-10): models and atoms, no
    # experiment record, so Detect from file cannot tell what the models are.
    # Kept apart so the multi-select below does not pick it up.
    morphs = folder.parent / 'local-import-morph'
    shutil.rmtree(morphs, ignore_errors=True)
    morphs.mkdir()
    H.chimera_like_ensemble(morphs / 'morph.pdb')
    data['morphs'] = morphs
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


def point_browser_at_folder(where='folder'):
    window, area = browser()
    assert area is not None, 'Import Local File did not open a file browser'
    area.spaces.active.params.directory = str(data[where]).encode()
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


def observe_import_options():
    """Watch the importer's options draw in the file browser's side panel.

    Reported 2026-11-03: the panel showed "Multiple mod..." squeezed beside
    "Detect from file", and nothing said what the choices were.
    """
    from proteinblender.operators.operator_import_local import MOLECULE_OT_import_local as Op
    original = Op.__dict__.get('draw')
    assert original is not None, (
        'the import dialog draws no options of its own, so Blender squeezes '
        '"Multiple models" beside its value in the narrow side panel')

    def draw(self, context):
        original(self, context)
        data['options'] = str(self.layout.introspect())
        data['options_width'] = context.region.width
    Op.draw = draw
    data['options_class'], data['options_draw'] = Op, original
    window, area = browser()
    for region in area.regions:
        region.tag_redraw()


def check_import_options():
    import blf
    data['options_class'].draw = data['options_draw']
    assert 'options' in data, 'the side panel never drew the import options'
    rna = bpy.ops.molecule.import_local.get_rna_type().properties['model_interpretation']
    labels = [item.name for item in rna.enum_items]
    texts = ['Multiple models in the file', *labels]
    for text in texts:
        assert text in data['options'], (text, data['options'][:400])
    # Each is drawn on a line of its own, the panel's full width; Blender's
    # own font says whether the words fit in it, margins and all.
    scale = bpy.context.preferences.system.ui_scale
    blf.size(0, 11 * scale)
    room = data['options_width'] - 40 * scale
    for text in texts:
        width = blf.dimensions(0, text)[0]
        assert width < room, f'"{text}" is {width:.0f}px in a {room:.0f}px line'
    # The file browser is a window of its own; shoot that one.
    window, area = browser()
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.screen.screenshot(
            filepath=str(Path(g['report_path']).parent / 'local-import-options.png'))
    return f'{len(texts)} lines fit {room:.0f}px'


def check_confirm_label():
    """The browser's confirm button reads the importer's name, whole.

    Reported 2026-11-03: it read "Import Local Structure File", clipped to
    "Import Local Structu..." in the narrow button.
    """
    name = bpy.ops.molecule.import_local.get_rna_type().name
    assert name == 'Import Structure', f'the importer is registered as {name!r}'
    window, area = browser()
    params = area.spaces.active.params
    assert params.title == name, f'the browser button reads {params.title!r}, not {name!r}'
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.screen.screenshot(
            filepath=str(Path(g['report_path']).parent / 'local-import-confirm.png'))
    return f'the browser confirm button reads "{params.title}"'


def change_the_option_and_cancel():
    """Pick an option, then Cancel: nothing imports, the browser goes."""
    data['before_cancel'] = molecules()
    window, area = browser()
    assert area is not None, 'file browser is not open'
    area.spaces.active.params.filename = 'ensemble.pdb'
    area.spaces.active.active_operator.model_interpretation = 'ASSEMBLY'
    region = next(r for r in area.regions if r.type == 'EXECUTE')
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.file.cancel() == {'FINISHED'}


def expect_cancel_imported_nothing():
    window, area = browser()
    assert area is None, 'Cancel left the file browser open'
    assert molecules() == data['before_cancel'], (molecules(), data['before_cancel'])
    return 'Cancel closed the browser and imported nothing'


def expect_reopened_fresh():
    """A reopened browser starts from Detect from file, not the cancelled choice."""
    window, area = browser()
    assert area is not None, 'Import Local File did not open the browser again'
    chosen = area.spaces.active.active_operator.model_interpretation
    assert chosen == 'AUTO', f'the reopened browser kept the cancelled choice {chosen!r}'
    return 'reopened on Detect from file'


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


def morphset_names():
    from proteinblender.core import morphsets
    return sorted(root.name for root in morphsets.sets(bpy.context.scene))


def remember_before_states():
    data['before_states'] = (molecules(), morphset_names())
    # The drops above were scripted from a timer, which pushes no undo step;
    # mark this state as a user's last action would, so one Ctrl+Z after the
    # import has a known place to return to.
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.ed.undo_push(message='PB UI before states import') == {'FINISHED'}
    return f"{len(data['before_states'][0])} proteins, Morphsets {data['before_states'][1]}"


def expect_states_made_a_morphset():
    """Janet, 2026-11-03, and Dillon, 2026-11-10: a ChimeraX morph imported
    with nothing chosen (Detect from file) failed; it now comes in as states
    with its Morphset ready, not one more thing to make by hand."""
    proteins, sets = data['before_states']
    added = sorted(set(molecules()) - set(proteins))
    assert len(added) == 1, added
    made = sorted(set(morphset_names()) - set(sets))
    assert len(made) == 1, f'expected one new Morphset, got {made}'
    data['states_import'] = added[0]
    return f'{added[0]} -> Morphset {made[0]}'


def press_ctrl_z():
    """Ctrl+Z as a user presses it, over the 3D Viewport."""
    window = g['active_window']()
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    x, y = area.x + area.width // 2, area.y + area.height // 2
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window.event_simulate(type='Z', value='PRESS', ctrl=True, x=x, y=y)
    window.event_simulate(type='Z', value='RELEASE', ctrl=True, x=x, y=y)


def _over_a_setting(window, area, region):
    """Whether the cursor is on one of the importer's own settings.

    Resetting to the default is offered over any editable property, while
    ``context.property`` names only those an ID owns; together they mark an
    operator's settings on every Blender version.
    """
    with bpy.context.temp_override(window=window, area=area, region=region):
        return bpy.ops.ui.reset_default_button.poll() and bpy.context.property is None


def find_the_choices(locate, done):
    """Walk the cursor down a region, recording each stretch over a setting.

    ``locate()`` gives ``(window, area, region)``; ``done(window, x, spans)``
    runs at the bottom. Only the cursor moves, so nothing is clicked by mistake.
    """
    def run():
        window, area, region = locate()
        assert region is not None, 'the region to walk is not on screen'
        step = max(3, round(4 * bpy.context.preferences.system.ui_scale))
        walk = data.setdefault('walk', {'at': None, 'spans': [], 'inside': False})
        if walk['at'] is None:
            walk['x'] = region.x + region.width // 2
            at = region.y + region.height - step
        else:
            if _over_a_setting(window, area, region):
                if not walk['inside']:
                    walk['spans'].append([walk['at'], walk['at']])
                walk['spans'][-1][1] = walk['at']
                walk['inside'] = True
            else:
                walk['inside'] = False
            at = walk['at'] - step
        if at > region.y:
            walk['at'] = at
            def hover():
                window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=walk['x'], y=at)
            g['steps'][:0] = [('hover', hover), *settle(2, 'hover'), ('walk on', run)]
            return None
        data.pop('walk')
        return done(window, walk['x'], walk['spans'])
    return run


def _choice_labels():
    rna = bpy.ops.molecule.import_local.get_rna_type().properties['model_interpretation']
    return [(item.identifier, item.name) for item in rna.enum_items]


def _side_panel():
    window, area = browser()
    if area is None:
        return None, None, None
    region = next((r for r in area.regions if r.type == 'TOOL_PROPS'), None)
    return window, area, region


def expect_the_side_panel():
    window, area, region = _side_panel()
    assert region is not None and region.width > 1, (
        'the file browser shows no side panel, so Multiple models cannot be chosen')
    area.spaces.active.params.filename = 'morph.pdb'
    chosen = area.spaces.active.active_operator.model_interpretation
    assert chosen == 'AUTO', f'the browser opened on {chosen!r}'
    return f'side panel {region.width}px wide, on Detect from file'


def found_side_panel_choices(window, x, spans):
    labels = _choice_labels()
    names = [name for _i, name in labels]
    # Expanded in an aligned column, the choices are one button each, in the
    # enum's order and touching, so the walk crosses them as one stretch.
    assert len(spans) == 1, (
        f'walking the side panel at x={x} crossed {len(spans)} settings {spans}; '
        f'expected the column of {names}')
    top, bottom = spans[0]
    step = max(3, round(4 * bpy.context.preferences.system.ui_scale))
    height = (top - bottom + step) / len(labels)
    unit = 20 * bpy.context.preferences.system.ui_scale
    assert abs(height - unit) <= step, (
        f'the column {spans[0]} is not {len(labels)} buttons of {unit:.0f}px')
    data['choice_xy'] = {identifier: (x, round(top + step / 2 - height * (slot + 0.5)))
                         for slot, (identifier, _n) in enumerate(labels)}
    return f'choices at {data["choice_xy"]}, buttons {height:.0f}px'


def click_choice(identifier):
    def step():
        window, _area, _region = _side_panel()
        x, y = data['choice_xy'][identifier]
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
        window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    return step


def expect_chosen(identifier):
    def step():
        window, area, _region = _side_panel()
        chosen = area.spaces.active.active_operator.model_interpretation
        assert chosen == identifier, (
            f'clicking {identifier} in the side panel left the importer on {chosen!r}')
        capture(f'local-import-{identifier.lower()}-chosen.png')
        return f'the click chose {identifier}'
    return step


def expect_morph_as_copies():
    """Assembly copies, clicked in the side panel, still draws a morph's models side by side."""
    proteins, sets = data['before_copies']
    added = sorted(set(molecules()) - set(proteins))
    assert len(added) == 1, added
    text = (data['morphs'] / 'morph.pdb').read_text().splitlines()
    models = sum(line.startswith('MODEL ') for line in text)
    chains = {line[21] for line in text if line.startswith('ATOM')}
    molecule = H.sm().molecules[added[0]]
    assert len(molecule.domains) == models * len(chains), (len(molecule.domains), models, chains)
    assert morphset_names() == sets, f'Assembly copies made a Morphset: {morphset_names()}'
    return f'{added[0]}: {models} models x {len(chains)} chains drawn as copies'


def remember_before_copies():
    data['before_copies'] = (molecules(), morphset_names())


def press_import():
    """Enter over the file list, as a user confirms a chosen file."""
    window, area = browser()
    region = next(r for r in area.regions if r.type == 'WINDOW')
    x, y = region.x + region.width // 2, region.y + region.height // 3
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window.event_simulate(type='RET', value='PRESS', x=x, y=y)
    window.event_simulate(type='RET', value='RELEASE', x=x, y=y)


def remember_before_the_drop():
    data['before_drop'] = (molecules(), morphset_names())


def drop_the_morph():
    """Drag the ChimeraX morph onto the 3D Viewport, as Blender delivers a drop."""
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.wm.drop_import_file(
            'EXEC_DEFAULT', directory=str(data['morphs']),
            files=[{'name': 'morph.pdb'}]) == {'FINISHED'}


def expect_the_drop_made_a_morphset():
    """Reported 2026-11-10: a dropped morph failed with "This file has several
    models and does not say what they are". It now imports as states."""
    proteins, sets = data['before_drop']
    added = sorted(set(molecules()) - set(proteins))
    assert len(added) == 1 and added[0].startswith('morph'), added
    made = sorted(set(morphset_names()) - set(sets))
    assert len(made) == 1, f'expected one new Morphset, got {made}'
    return f'{added[0]} -> Morphset {made[0]}'


def expect_one_undo_took_both_away():
    proteins, sets = data['before_states']
    H.scene_manager_module().sync_molecule_list_after_undo()
    assert molecules() == proteins, (
        f"after one Ctrl+Z: {molecules()}; before the import: {proteins}")
    assert morphset_names() == sets, (
        f"after one Ctrl+Z the Morphsets are {morphset_names()}; before: {sets}")
    return 'one Ctrl+Z removed the protein and its Morphset'


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
    ('click Import Local File to cancel', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder to cancel', point_browser_at_folder),
    *settle(20, 'file list'),
    ('the confirm button reads Import Structure', check_confirm_label),
    ('pick Assembly copies, then Cancel', change_the_option_and_cancel), *settle(4, 'cancel'),
    ('Cancel imported nothing', expect_cancel_imported_nothing),
    ('click Import Local File for an ensemble', click_import_local_file), *settle(3, 'browser open'),
    ('the reopened browser forgot the cancelled choice', expect_reopened_fresh),
    ('point the file browser at the folder for the ensemble', point_browser_at_folder),
    *settle(20, 'file list'),
    ('watch the import options draw', observe_import_options), *settle(4, 'options redraw'),
    ('the import options are readable in the side panel', check_import_options),
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
    ('note what is loaded before a states import', remember_before_states),
    ('click Import Local File for a morph', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the morph folder', lambda: point_browser_at_folder('morphs')),
    *settle(20, 'file list'),
    ('choose morph.pdb; the side panel is there, on Detect from file', expect_the_side_panel),
    *settle(3, 'side panel'),
    ('press Enter to import, choosing nothing', press_import), *settle(12, 'import'),
    ('Detect from file read the morph as states and made the Morphset',
     expect_states_made_a_morphset),
    ('press Ctrl+Z once', press_ctrl_z), *settle(8, 'undo'),
    ('one Ctrl+Z took the protein and its Morphset away', expect_one_undo_took_both_away),
    ('note what is loaded before importing as copies', remember_before_copies),
    ('click Import Local File for the morph as copies', click_import_local_file),
    *settle(3, 'browser open'),
    ('point the file browser at the morph folder again', lambda: point_browser_at_folder('morphs')),
    *settle(20, 'file list'),
    ('choose morph.pdb again', expect_the_side_panel), *settle(3, 'side panel'),
    ('find the Multiple models choices in the side panel',
     find_the_choices(_side_panel, found_side_panel_choices)),
    ('click Assembly copies', click_choice('ASSEMBLY')), *settle(4, 'click'),
    ('the click chose Assembly copies', expect_chosen('ASSEMBLY')),
    ('press Enter to import as copies', press_import), *settle(12, 'import'),
    ('the clicked Assembly copies drew the models as copies', expect_morph_as_copies),
    ('press Ctrl+Z to take the copies away', press_ctrl_z), *settle(8, 'undo'),
    ('click Import Local File for a multi-select', click_import_local_file), *settle(3, 'browser open'),
    ('point the file browser at the folder for multi-select', point_browser_at_folder),
    *settle(20, 'file list'),
    ('select every listed file and press Import', execute_selection), *settle(12, 'import'),
    ('every selected file imported once', expect_everything),
    ('note what is loaded before the drop', remember_before_the_drop),
    ('drop the ChimeraX morph on the 3D viewport', drop_the_morph), *settle(12, 'drop'),
    ('the dropped morph came in as states with its Morphset', expect_the_drop_made_a_morphset),
    ('save', save),
]
