"""Build a microtubule with Create New Cytoskeleton, undo it, and edit its length."""
import json
import runpy
import sys
from pathlib import Path

import bpy
import numpy as np

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
H = g['H']
from proteinblender.core import assembly as A
from proteinblender.core import symmetry_bend
from proteinblender.dna_builder.dna_panel import PROTEINBLENDER_PT_builders as Builders
from proteinblender.operators.filament_operators import MOLECULE_PB_OT_build_filament as Builder
from proteinblender.operators.symmetry_dialog import MOLECULE_PB_OT_symmetry_dialog as Dialog
from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as Keyframe
from proteinblender.panels.subunit_panel import PROTEINBLENDER_PT_subunits as Subunits
from proteinblender.core import subunit_colors as SC

data = {}
folder = Path(g['report_path']).parent
STALE_HINT = 'OK the new settings first'

#: A 13-protofilament microtubule: 50 nm at 81.5 A a dimer is six dimers up
#: each strand, and 100 nm is twelve.
STRANDS = 13


def idle():
    return None


def scale():
    return bpy.context.preferences.system.ui_scale


def move(x, y):
    data['mouse'] = (int(x), int(y))
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def key(kind, **modifiers):
    # A key event carries the cursor too, and a dialog opens where it says.
    x, y = data['mouse']
    for value in ('PRESS', 'RELEASE'):
        g['active_window']().event_simulate(type=kind, value=value, x=x, y=y, **modifiers)


def capture(name):
    path = str(folder / name)
    bpy.ops.screen.screenshot(filepath=path)
    return path


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('items', []))


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data[cls.__name__ + '_layout'] = self.layout.introspect()
        if cls in (Dialog, Builder, Keyframe):
            data['popup'] = getattr(context, 'region_popup', None) or context.region
            data['open'] = cls.__name__
    cls.draw = draw


def labels(cls):
    assert data.get('open') == cls.__name__, f'{cls.__name__} is not open'
    return str(data[cls.__name__ + '_layout'])


def title_xy():
    popup = data['popup']
    return popup.x + popup.width / 2, popup.y + popup.height - 14 * scale()


def poke():
    """Make an open dialog draw again after a scripted change."""
    data['popup'].tag_refresh_ui()
    move(*title_xy())


def confirm(label):
    # Enter over a button presses that button, so it is sent from the title.
    return [(f'hover the title before {label}', lambda: move(*title_xy())), ('settle', idle),
            (label, press_ok),
            ('settle', idle)]


def press_ok():
    data.pop('open', None)
    key('RET')


def fits_the_window():
    popup, window = data['popup'], g['active_window']()
    assert popup.y >= 0 and popup.y + popup.height <= window.height, (
        'The dialog does not fit the window', popup.y, popup.height, window.height)
    return str((popup.x, popup.y, popup.width, popup.height, window.width, window.height))


def filament():
    molecules = H.sm().molecules
    assert len(molecules) == 1, sorted(molecules)
    return next(iter(molecules.values()))


def placed_copies(mol):
    """How many copies of one chain Blender instanced, read off the depsgraph."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    domain = next(iter(mol.domains.values())).object
    return sum(1 for i in depsgraph.object_instances
               if i.is_instance and i.parent is not None
               and i.parent.original.name == domain.name)


def rig_objects():
    """Bend curves and control nodes in the file, whoever they belong to."""
    return sorted(o.name for o in bpy.data.objects
                  if symmetry_bend.CURVE_SUFFIX in o.name or 'Filament Node' in o.name)


def prepare():
    H.reset_scene()
    for cls in (Builder, Dialog, Builders, Keyframe, Subunits):
        observe(cls)
    window = g['active_window']()
    move(window.width * .45, window.height * .8)
    for area in window.screen.areas:
        area.tag_redraw()
    assert not H.sm().molecules and not rig_objects()
    # Scripted calls leave no undo steps, so without one here the first undo
    # would go back past the empty scene.
    with g['ui_override']():
        bpy.ops.ed.undo_push(message='Empty scene')


def inspect_builders_panel():
    capture('builders-panel.png')
    layout = data.get(Builders.__name__ + '_layout')
    assert layout, 'The Builders panel was not drawn'
    (folder / 'builders-layout.json').write_text(json.dumps(layout, indent=2))
    buttons = [i for i in flatten(layout) if i.get('operator')]
    offered = [i for i in buttons if 'molecule.build_filament' in i['operator']]
    assert len(offered) == 1, [i['operator'] for i in buttons]
    assert offered[0]['draw_string'] == 'Create New Cytoskeleton'
    return offered[0]['operator']


def open_builder():
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.molecule.build_filament(
            'INVOKE_DEFAULT', preset='MICROTUBULE',
            length=50.0) == {'RUNNING_MODAL'}


def inspect_builder():
    capture('filament-dialog.png')
    shown = labels(Builder)
    (folder / 'filament-dialog-layout.json').write_text(
        json.dumps(data[Builder.__name__ + '_layout'], indent=2))
    assert all(label in shown for label in ('Cytoskeleton', 'Length (nm)'))
    # A filament starts straight; its nodes make any other shape.
    assert 'Start As' not in shown, shown
    # 500 A at 81.5 A a dimer is 6.1: six up each of thirteen strands.
    assert '13 strands of 6 - 78 copies' in shown, shown
    return fits_the_window()


def verify_built():
    assert 'open' not in data, 'OK did not close the builder'
    mol = filament()
    assert placed_copies(mol) == 6 * STRANDS, placed_copies(mol)
    assert A.built_assembly_id(mol) == 'generated:H'
    assert len(symmetry_bend.get_bend_nodes(mol)) >= 3
    rows = [r for r in bpy.context.scene.outliner_items if r.item_type == 'SYMMETRY']
    assert len(rows) == 1 and '13 x 6' in rows[0].name, [r.name for r in rows]
    chains = sorted(r.name for r in bpy.context.scene.outliner_items if r.item_type == 'CHAIN')
    assert chains == ['Alpha Tubulin', 'Beta Tubulin'], chains
    data['rig'] = rig_objects()
    assert data['rig'], 'The filament has no path'
    for area in g['active_window']().screen.areas:
        if area.type == 'VIEW_3D':
            with bpy.context.temp_override(
                    window=g['active_window'](), area=area,
                    region=next(r for r in area.regions if r.type == 'WINDOW')):
                bpy.ops.view3d.view_all()
    return rows[0].name


def undo_the_build():
    capture('microtubule.png')
    with g['ui_override']():
        assert bpy.ops.ed.undo() == {'FINISHED'}


def verify_undone():
    # One step back is the whole build: the subunit, its copies and its path.
    assert not H.sm().molecules, sorted(H.sm().molecules)
    assert not rig_objects(), rig_objects()
    assert not [r for r in bpy.context.scene.outliner_items], (
        [r.name for r in bpy.context.scene.outliner_items])
    with g['ui_override']():
        assert bpy.ops.ed.redo() == {'FINISHED'}


def verify_redone_and_edit():
    mol = filament()
    assert placed_copies(mol) == 6 * STRANDS, placed_copies(mol)
    assert rig_objects() == data['rig'], (rig_objects(), data['rig'])
    assert symmetry_bend.has_bend(mol)
    data.pop('open', None)
    with g['ui_override']():
        assert bpy.ops.molecule.symmetry_dialog(
            'INVOKE_DEFAULT', molecule_id_to_update=mol.identifier) == {'RUNNING_MODAL'}


def inspect_edit_dialog():
    capture('edit-microtubule.png')
    shown = labels(Dialog)
    (folder / 'edit-microtubule-layout.json').write_text(
        json.dumps(data[Dialog.__name__ + '_layout'], indent=2))
    scene = bpy.context.scene
    # The dialog opens on what the builder made, strands and all.
    assert scene.pb_symmetry_kind == 'H' and scene.pb_symmetry_count == 6
    assert scene.pb_symmetry_strands == STRANDS
    assert abs(scene.pb_symmetry_length - 48.9) < 1e-3, scene.pb_symmetry_length
    assert all(label in shown for label in (
        'Subunits per Strand', 'Length (nm)', 'Strands', 'Stagger', 'Strand Twist'))
    assert 'Tube - 13 strands of 6' in shown, shown
    # Either end can shrink, by the names a microtubule's ends go by.
    assert all(label in shown for label in ('Shrink', 'Plus (+) End', 'Minus (-) End')), shown
    assert scene.pb_symmetry_shrink_plus == 0 and scene.pb_symmetry_shrink_minus == 0
    # A filament that is already bent opens on its bend, with no shapes to pick.
    assert all(label in shown for label in ('Nodes', 'Edit Bend'))
    assert not any(label in shown for label in ("'Arc'", 'S-curve', 'Coil')), shown
    assert STALE_HINT not in shown
    fits = fits_the_window()
    scene.pb_symmetry_length = 100.0
    poke()
    return fits


def inspect_longer():
    capture('edit-microtubule-longer.png')
    shown = labels(Dialog)
    # 1000 A at 81.5 A a dimer is 12.3: twelve.
    assert bpy.context.scene.pb_symmetry_count == 12
    assert 'Tube - 13 strands of 12' in shown, shown
    assert STALE_HINT in shown, 'A new length left the assembly tools live'
    # The longer tube is on screen before OK is pressed.
    assert placed_copies(filament()) == 12 * STRANDS, placed_copies(filament())
    bpy.context.scene.pb_symmetry_shrink_minus = 1
    poke()


def inspect_shrunk():
    capture('edit-microtubule-shrunk.png')
    shown = labels(Dialog)
    # A dimer off the minus end of each of the thirteen protofilaments.
    assert '143 left' in shown, shown
    assert placed_copies(filament()) == 11 * STRANDS, placed_copies(filament())


def verify_rebuilt_longer():
    assert 'open' not in data, 'OK did not close the dialog'
    mol = filament()
    assert placed_copies(mol) == 11 * STRANDS, placed_copies(mol)
    assert symmetry_bend.has_bend(mol), 'Changing the length threw the path away'
    rows = [r for r in bpy.context.scene.outliner_items if r.item_type == 'SYMMETRY']
    assert len(rows) == 1 and '13 x 12' in rows[0].name, [r.name for r in rows]
    capture('microtubule-longer.png')
    return rows[0].name


def open_keyframe_dialog():
    data.pop('open', None)
    with g['ui_override']():
        assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def inspect_keyframe_dialog():
    capture('create-keyframe.png')
    shown = labels(Keyframe)
    mol = filament()
    dialog = Keyframe._active_instance
    assert dialog is not None, 'Create Keyframe is not open'
    rows = [item for item in dialog.puppet_items if item.item_kind == 'FILAMENT']
    assert len(rows) == 1 and rows[0].puppet_id == mol.identifier, (
        [(r.item_kind, r.puppet_id) for r in dialog.puppet_items])
    assert rows[0].puppet_name in shown, shown
    assert 'Nothing to keyframe' not in shown
    # The row's checkbox, as a click on it sets it.
    rows[0].use_puppet = True
    poke()
    return rows[0].puppet_name


def verify_keyed():
    assert 'open' not in data, 'OK did not close Create Keyframe'
    from proteinblender.core import filament_animation
    mol = filament()
    keyed = filament_animation.parameter_fcurves(mol.object)
    assert set(keyed) == set(filament_animation.PARAMETERS), sorted(keyed)
    assert keyed['count'].keyframe_points[0].co[1] == 12, keyed['count'].keyframe_points[0].co
    nodes = symmetry_bend.get_bend_nodes(mol)
    assert all(n.animation_data and n.animation_data.action for n in nodes)
    return 'keyed: ' + ', '.join(sorted(keyed))


# --------------------------------------------------------------------------
# The Cytoskeleton Subunits panel, and picking subunits in the viewport
# --------------------------------------------------------------------------

def viewport():
    window = g['active_window']()
    area = max((a for a in window.screen.areas if a.type == 'VIEW_3D'),
               key=lambda a: a.width * a.height)
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def tick_in_outliner(molecule_id):
    """Click a top-level row's checkbox in the PB Outliner."""
    with g['ui_override']():
        assert bpy.ops.proteinblender.outliner_select(
            'EXEC_DEFAULT', item_id=molecule_id) == {'FINISHED'}


def untick_the_filament():
    area, region = viewport()
    area.spaces.active.shading.type = 'MATERIAL'
    with bpy.context.temp_override(window=g['active_window'](), area=area, region=region):
        bpy.ops.view3d.view_all()
    mol = filament()
    row = next(r for r in bpy.context.scene.outliner_items if r.item_id == mol.identifier)
    if row.is_selected:
        tick_in_outliner(mol.identifier)
    assert not row.is_selected
    # Forget what was drawn, to see what the next redraw draws.
    for cls in (Builders, Subunits):
        data.pop(cls.__name__ + '_layout', None)
    g['protein_workspace_panel_area']().tag_redraw()
    return 'unticked'


def verify_hidden_and_tick():
    assert Builders.__name__ + '_layout' in data, 'the Properties editor did not redraw'
    assert Subunits.__name__ + '_layout' not in data, (
        'the Subunits panel was drawn with its filament unticked')
    capture('subunits-hidden.png')
    tick_in_outliner(filament().identifier)
    g['protein_workspace_panel_area']().tag_redraw()
    return 'hidden until ticked'


def inspect_subunits_panel():
    text = str(data.get('PROTEINBLENDER_PT_subunits_layout', ''))
    assert 'Cytoskeleton Subunits' in text, 'the Subunits panel was not drawn'
    for label in ('Pick in Viewport', 'Strength', 'Clear', 'Nothing selected'):
        assert label in text, (label, text[:400])
    # The select buttons sit above the list, a microtubule's tubulins below Select All.
    order = [text.find(label) for label in (
        'Select All', 'All Alpha Tubulin', 'All Beta Tubulin', 'Pick in Viewport')]
    assert -1 not in order and order == sorted(order), (order, text[:600])
    mol = filament()
    rows = mol.object.pb_filament.subunits
    # 12 dimers up each of 13 protofilaments, two monomers a dimer.
    assert len(rows) == 12 * STRANDS * 2, len(rows)
    capture('subunits-panel.png')
    return f'{len(rows)} rows'


def colour_three():
    mol = filament()
    present = SC.present_sites(mol)
    rows = [row for row in mol.object.pb_filament.subunits if row.site in present]
    for row in rows[:3]:
        row.select = True
    data['coloured'] = [row.name for row in rows[:3]]
    # Changing the colour field paints them; there is no button to press.
    bpy.context.scene.pb_subunit_color = (0.1, 0.9, 0.2)
    return ', '.join(data['coloured'])


def verify_coloured():
    mol = filament()
    assert sorted(mol.object.pb_filament.colors.keys()) == sorted(data['coloured'])
    text = str(data.get('PROTEINBLENDER_PT_subunits_layout', ''))
    assert '3 selected' in text, text[:400]
    capture('subunits-coloured.png')
    return '3 coloured'


def select_all_alpha():
    mol = filament()
    alpha = next(row.chain for row in mol.object.pb_filament.subunits
                 if row.label.startswith('Alpha Tubulin'))
    data['alpha'] = alpha
    with g['protein_workspace_override']():
        assert bpy.ops.molecule.select_subunits(
            'EXEC_DEFAULT', molecule_id=mol.identifier, action='CHAIN',
            chain=alpha) == {'FINISHED'}
    return alpha


def verify_all_alpha():
    mol = filament()
    present = SC.present_sites(mol)
    rows = [row for row in mol.object.pb_filament.subunits if row.site in present]
    chosen = [row for row in rows if row.select]
    assert chosen and all(row.chain == data['alpha'] for row in chosen)
    assert len(chosen) == sum(1 for row in rows if row.chain == data['alpha'])
    text = str(data.get('PROTEINBLENDER_PT_subunits_layout', ''))
    assert f'{len(chosen)} selected' in text, text[:400]
    capture('subunits-all-alpha.png')
    return f'{len(chosen)} alpha'


def aim_at_a_subunit():
    """Park the mouse over the subunit nearest the viewer, then start picking."""
    from bpy_extras import view3d_utils
    mol = filament()
    area, region = viewport()
    view = area.spaces.active.region_3d
    eye = np.array(view.view_matrix.inverted().translation)
    best = None
    for name, centre, _radius in SC.subunit_spheres(mol):
        if name in data['coloured']:
            continue
        where = view3d_utils.location_3d_to_region_2d(region, view, centre.tolist())
        if where is None or not (40 < where.x < region.width - 40
                                 and 40 < where.y < region.height - 40):
            continue
        depth = float(np.linalg.norm(centre - eye))
        if best is None or depth < best[0]:
            best = (depth, name, where)
    assert best is not None, 'no subunit in view to pick'
    _depth, name, where = best
    data['target'] = name
    data['target_xy'] = (region.x + where.x, region.y + where.y)
    move(*data['target_xy'])
    with bpy.context.temp_override(window=g['active_window'](), area=area, region=region):
        assert bpy.ops.molecule.pick_subunits(
            'INVOKE_DEFAULT', molecule_id=mol.identifier) == {'RUNNING_MODAL'}
    return name


def hover():
    move(*data['target_xy'])


def verify_hover():
    mol = filament()
    tints = SC.overlay(mol)
    assert tints.get(data['target']) == SC.HOVER_TINT, (data['target'], sorted(tints)[:6])
    for name in data['coloured']:
        assert tints.get(name) == SC.SELECTED_TINT, name
    capture('pick-hover.png')
    return data['target']


def click(value):
    x, y = data['target_xy']
    g['active_window']().event_simulate(type='LEFTMOUSE', value=value, x=int(x), y=int(y))


def verify_picked_and_finish():
    mol = filament()
    row = mol.object.pb_filament.subunits[data['target']]
    assert row.select, f"the click did not select {data['target']}"
    key('ESC')


def verify_picking_finished():
    mol = filament()
    assert SC.overlay(mol) == {}, 'Esc left the pick highlight on the filament'
    assert sorted(SC.selected_keys(mol)) == sorted(data['coloured'] + [data['target']])
    capture('pick-finished.png')
    return 'four selected'


def properties_region():
    area = g['protein_workspace_panel_area']()
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def hovered_row():
    """The Subunits row under the mouse, as Blender's own hovered button says."""
    import re
    area, region = properties_region()
    with bpy.context.temp_override(window=g['active_window'](), area=area, region=region):
        found = bpy.context.property
    if not found:
        return None
    match = re.match(r'^pb_filament\.subunits\[(\d+)\]', found[1] or '')
    return int(match.group(1)) if match else None


def find_a_row():
    """Walk the mouse down the Properties editor until it is over a list row."""
    area, region = properties_region()
    x = region.x + region.width * 0.3
    spots = list(range(region.y + region.height - 20, region.y + 20, -8))
    data['row_spots'] = spots
    steps = []
    for y in spots:
        steps.append((f'point at y={y}', lambda y=y: move(x, y)))
        steps.append(('settle', idle))
        steps.append((f'check y={y}', lambda y=y: check_row(x, y)))
    g['steps'][:0] = steps
    return f'{len(spots)} spots'


def check_row(x, y):
    if 'row' in data:
        return 'found already'
    index = hovered_row()
    if index is None:
        return None
    data['row'] = index
    data['row_xy'] = (x, y)
    # Skip the rest of the walk.
    steps = g['steps']
    rest = next(i for i, (name, _f) in enumerate(steps) if name == 'point at the row again')
    del steps[:rest]
    return f'row {index}'


def wait_for_the_watch():
    assert 'row' in data, 'the mouse never found a Subunits row'
    move(*data['row_xy'])


def verify_row_lit():
    mol = filament()
    row = mol.object.pb_filament.subunits[data['row']]
    lit = SC.overlay(mol, SC.LIST_LAYER)
    assert lit == {row.name: SC.HOVER_TINT}, (row.name, lit)
    capture('subunits-hover.png')
    return row.label


def leave_the_list():
    area, region = viewport()
    move(region.x + region.width * 0.1, region.y + region.height * 0.1)


def verify_row_dark():
    mol = filament()
    assert SC.overlay(mol, SC.LIST_LAYER) == {}, 'the highlight stayed after the mouse left'
    return 'cleared'


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', idle),
    ('prepare an empty scene', prepare), ('settle', idle),
    ('inspect the Builders panel', inspect_builders_panel), ('settle', idle),
    ('open Create New Cytoskeleton', open_builder), ('settle', idle),
    ('inspect Create New Cytoskeleton', inspect_builder), ('settle', idle),
    *confirm('OK the filament'),
    ('verify the microtubule', verify_built), ('settle', idle),
    ('undo the build', undo_the_build), ('settle', idle),
    ('verify undo and redo', verify_undone), ('settle', idle),
    ('verify redo and open Edit Assembly', verify_redone_and_edit), ('settle', idle),
    ('inspect Edit Assembly and ask for more', inspect_edit_dialog), ('settle', idle),
    ('inspect the longer setting and shrink it', inspect_longer), ('settle', idle),
    ('inspect the shrunk setting', inspect_shrunk), ('settle', idle),
    *confirm('OK the longer filament'),
    ('verify the longer microtubule', verify_rebuilt_longer), ('settle', idle),
    ('open Create Keyframe', open_keyframe_dialog), ('settle', idle),
    ('inspect Create Keyframe and tick the filament', inspect_keyframe_dialog), ('settle', idle),
    *confirm('OK the keyframe'),
    ('verify the filament is keyed', verify_keyed), ('settle', idle),
    ('untick the filament in the PB Outliner', untick_the_filament), ('settle', idle), ('settle', idle),
    ('verify the Subunits panel is hidden, and tick the filament', verify_hidden_and_tick),
    ('settle', idle), ('settle', idle),
    ('inspect the Subunits panel', inspect_subunits_panel), ('settle', idle),
    ('colour three subunits', colour_three), ('settle', idle), ('settle', idle),
    ('verify the colours', verify_coloured), ('settle', idle),
    ('aim at a subunit and start picking', aim_at_a_subunit), ('settle', idle),
    ('hover the subunit', hover), ('settle', idle), ('settle', idle),
    ('verify the hover highlight', verify_hover), ('settle', idle),
    ('press', lambda: click('PRESS')), ('settle', idle),
    ('release', lambda: click('RELEASE')), ('settle', idle),
    ('verify the pick and press Esc', verify_picked_and_finish), ('settle', idle),
    ('verify picking finished', verify_picking_finished), ('settle', idle),
    ('find a Subunits row', find_a_row),
    ('point at the row again', wait_for_the_watch), ('settle', idle), ('settle', idle),
    ('verify the row is lit', verify_row_lit), ('settle', idle),
    ('leave the list', leave_the_list), ('settle', idle), ('settle', idle), ('settle', idle),
    ('verify the row is dark again', verify_row_dark), ('settle', idle),
    ('select all alpha tubulin', select_all_alpha), ('settle', idle), ('settle', idle),
    ('verify only alpha tubulin is selected', verify_all_alpha), ('settle', idle),
]
