"""Click an assembly row's pencil and work on the assembly from its one dialog."""
import ast
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
from proteinblender.operators.symmetry_dialog import MOLECULE_PB_OT_symmetry_dialog as Dialog
from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_PT_outliner as Outliner

data = {}
folder = Path(g['report_path']).parent
STALE_HINT = 'OK the new settings first'


def idle():
    return None


def scale():
    return bpy.context.preferences.system.ui_scale


def move(x, y):
    data['mouse'] = (int(x), int(y))
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def button(value, x, y, kind='LEFTMOUSE', **modifiers):
    g['active_window']().event_simulate(type=kind, value=value, x=int(x), y=int(y), **modifiers)


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


def molecule(which='mid'):
    return H.sm().molecules[data[which]]


def placed_copies(mol):
    """How many copies Blender actually instanced, read off the depsgraph."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    domain = next(iter(mol.domains.values())).object
    return sum(1 for i in depsgraph.object_instances
               if i.is_instance and i.parent is not None
               and i.parent.original.name == domain.name)


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data[cls.__name__ + '_layout'] = self.layout.introspect()
        if cls == Dialog:
            data['popup'] = getattr(context, 'region_popup', None) or context.region
            data['dialog'] = {'source': self.source, 'opened_on': self.opened_on}
    cls.draw = draw


def dialog_labels():
    assert 'dialog' in data, 'The Edit Assembly dialog is not open'
    return str(data[Dialog.__name__ + '_layout'])


def title_xy():
    popup = data['popup']
    return popup.x + popup.width / 2, popup.y + popup.height - 14 * scale()


def poke():
    """Make an open dialog draw again after a scripted change.

    A popup lays itself out again when one of its own controls changes
    something, not when a timer does, so it has to be told.
    """
    data['popup'].tag_refresh_ui()
    move(*title_xy())


def click(label, where):
    # A UI button only takes a press that lands after the motion that made it
    # active, and a release after that, so each gets an event-loop tick.
    return [(f'hover {label}', lambda: move(*data[where])), ('settle', idle),
            (f'press {label}', lambda: button('PRESS', *data[where])),
            (f'release {label}', lambda: button('RELEASE', *data[where])),
            ('settle', idle)]


def confirm(label):
    # Enter over a button presses that button, so it is sent from the title.
    return [(f'hover the title before {label}', lambda: move(*title_xy())), ('settle', idle),
            (label, press_ok),
            ('settle', idle)]


def press_ok():
    data.pop('dialog', None)
    key('RET')


def seek(where, wanted):
    """Walk the cursor up the dialog until Ctrl+C reports ``wanted``.

    Blender copies what is under the cursor - an operator button's Python
    command, a field's value - which identifies a control without guessing at
    layout arithmetic. From the bottom, since what is sought sits below the
    build settings. A probe lands within one step of the edge it has just
    crossed, so the control is then used one step further in.
    """
    def run():
        wm = bpy.context.window_manager
        popup = data['popup']
        step = 6 * scale()
        at = data.get('seek')
        if at is None:
            x, y = popup.x + popup.width * .75, popup.y + 8 * scale()
        elif wanted in wm.clipboard:
            data.pop('seek')
            data[where] = (at[0], round(at[1] + step))
            return f'{wanted} at {data[where]}'
        else:
            x, y = at[0], at[1] + step
        assert y < popup.y + popup.height, f'No {wanted} button in the dialog'
        data['seek'] = (round(x), round(y))
        wm.clipboard = ''
        move(*data['seek'])
        g['steps'][:0] = [('hover', idle), ('copy hovered control', lambda: key('C', ctrl=True)),
                          ('settle', idle), (f'seek {wanted}', run)]
    return run


def prepare():
    H.reset_scene()
    for cls in (Dialog, Outliner, bpy.types.UI_MT_list_item_context_menu):
        observe(cls)
    scene = bpy.context.scene
    with g['ui_override']('VIEW_3D'):
        # A filament of five copies marching 20 A apart along -Y, which is the
        # direction a cutaway takes away by default.
        data['mid'] = H.import_local('1ubq.pdb', 'First')
        scene.pb_symmetry_kind = 'H'
        scene.pb_symmetry_count = 5
        scene.pb_symmetry_rise = 20
        scene.pb_symmetry_twist = 30
        scene.pb_symmetry_axis = (0, -1, 0)
        bpy.ops.molecule.symmetry_dialog(target_id=data['mid'], source='GENERATED')
        data['other_mid'] = H.import_local('5im3.pdb', 'Other')
        bpy.ops.molecule.symmetry_dialog(target_id=data['other_mid'], source='BIOLOGICAL', assembly_id='1')
    data['child_index'] = next(i for i, r in enumerate(scene.outliner_items)
                              if r.item_type == 'SYMMETRY' and r.parent_id == data['mid'])
    data['other_index'] = next(i for i, r in enumerate(scene.outliner_items) if r.item_id == data['other_mid'])
    for row in scene.outliner_items:
        row.is_expanded = row.item_id == data['mid']
    scene.outliner_index = data['child_index']
    assert placed_copies(molecule()) == 5
    # One way into an assembly: the popup the row's second button opened is gone.
    assert not hasattr(bpy.types, 'MOLECULE_OT_assembly_controls')
    assert not hasattr(bpy.types, 'PROTEINBLENDER_PT_assembly_controls')
    for area in g['active_window']().screen.areas:
        area.tag_redraw()
    # Scripted calls leave no undo steps, so without one here the first undo
    # would go back past the import.
    with g['ui_override']():
        bpy.ops.ed.undo_push(message='Two assemblies')


def locate_row():
    path = capture('locate-row.png')
    picture = bpy.data.images.load(path, check_existing=False)
    width, height = picture.size
    pixels = np.array(picture.pixels[:]).reshape(height, width, 4)
    bpy.data.images.remove(picture)
    area = g['protein_workspace_panel_area']()
    left, right = area.x + 60, area.x + area.width - 100
    rgb = pixels[:, left:right, :3]
    blue = (rgb[:, :, 2] > .25) & (rgb[:, :, 2] > rgb[:, :, 0] * 1.6) & (rgb[:, :, 1] > rgb[:, :, 0] * 1.2)
    rows = np.where(np.sum(blue, axis=1) > (right - left) * .7)[0]
    assert len(rows), 'Assembly row not visible'
    data['row_y'] = int(np.median(rows[rows > rows.max() - 15]))
    data['row_x'] = int(area.x + area.width * .47)
    # From the right: visibility, select, delete, then the pencil.
    data['pencil_xy'] = (round(area.x + area.width - 95 * scale()), data['row_y'])
    bpy.context.scene.outliner_index = data['other_index']
    for item in g['active_window']().screen.areas:
        item.tag_redraw()
    (folder / 'outliner-layout.json').write_text(json.dumps(data[Outliner.__name__ + '_layout'], indent=2))
    return str(data['pencil_xy'])


def inspect_dialog():
    capture('edit-dialog.png')
    labels = dialog_labels()
    (folder / 'edit-dialog-layout.json').write_text(
        json.dumps(data[Dialog.__name__ + '_layout'], indent=2))
    assert data['dialog']['source'] == 'GENERATED'
    assert data['dialog']['opened_on'], 'The pencil did not open the dialog on its assembly'
    # The build settings, and under them everything the popup used to hold,
    # with the cutaway and the bend folded away until they are asked for.
    assert all(label in labels for label in (
        'Show Symmetry Axes', 'Realize Copies', 'Cutaway', 'Bend'))
    # Changes show as they are made, so there is nothing to apply.
    assert 'Apply' not in labels and 'Changes show as you make them' in labels
    assert not any(folded in labels for folded in ('Cut Depth', 'Cut Away', 'Add Bend'))
    assert STALE_HINT not in labels
    # No way out to a second menu, and no assembly animation.
    assert not any(gone in labels for gone in (
        'Change Assembly', 'Assembly progress', 'Copy delay', 'Keyframe'))
    return fits_the_window()


def fits_the_window():
    popup, window = data['popup'], g['active_window']()
    assert popup.y >= 0 and popup.y + popup.height <= window.height, (
        'The dialog does not fit the window', popup.y, popup.height, window.height)
    return str((popup.x, popup.y, popup.width, popup.height, window.width, window.height))


def fold_below(where, above):
    """A step that notes the section header in the row under a found button.

    A header is not a control Ctrl+C can name. A probe stops 6 to 12 px above
    the bottom edge of the button it finds, so 28 px lower is inside the next
    row whatever the gap between the two.
    """
    def run():
        popup = data['popup']
        data[where] = (round(popup.x + 40 * scale()), round(data[above][1] - 28 * scale()))
        return str(data[where])
    return run


def inspect_cutaway_open():
    labels = dialog_labels()
    assert 'Cut Depth' in labels and 'Cut Away' in labels, 'The Cutaway section did not open'
    assert 'Add Bend' not in labels


def inspect_bend_open():
    capture('edit-dialog-open.png')
    layout = data[Dialog.__name__ + '_layout']
    shown = [i for i in flatten(layout) if i.get('draw_string') == 'Add Bend']
    assert shown, 'The Bend section did not open'
    call = ast.parse(shown[0]['operator'], mode='eval').body
    arguments = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    assert arguments['molecule_id'] == data['mid']
    # Everything open at once is the tallest the dialog gets.
    return fits_the_window()


def note_cut_depth():
    # Cut Depth shares the button's row, in its left half.
    x, y = data['cut_xy']
    popup = data['popup']
    data['depth_xy'] = (round(popup.x + popup.width * .25), y)
    assert bpy.context.scene.pb_cutaway_offset == 0
    move(*data['depth_xy'])


def open_cut_depth():
    # Ctrl+click types into a number field.
    for value in ('PRESS', 'RELEASE'):
        button(value, *data['depth_xy'], ctrl=True)


def type_cut_depth():
    key('A', ctrl=True)
    window = g['active_window']()
    x, y = data['mouse']
    for char, name in (('5', 'FIVE'), ('0', 'ZERO')):
        window.event_simulate(type=name, value='PRESS', unicode=char, x=x, y=y)
        window.event_simulate(type=name, value='RELEASE', x=x, y=y)


def verify_cut():
    """An operator button after a field edit once took Blender down with it."""
    capture('cut-away.png')
    # Blender's own record of what the click ran, not what the product says.
    history = bpy.context.window_manager.operators
    assert len(history), ('Clicking Cut Away ran nothing', bpy.context.scene.pb_cutaway_offset)
    ran = history[-1]
    assert ran.bl_idname == 'MOLECULE_OT_cutaway', ran.bl_idname
    assert ran.properties.molecule_id == data['mid']
    assert abs(ran.properties.offset - 50) < 1e-4, ran.properties.offset
    assert bpy.context.scene.pb_cutaway_offset == 50, bpy.context.scene.pb_cutaway_offset
    # Copies sit 0, 20, 40, 60 and 80 A along the cut direction. A plane 50 A
    # out takes the last two; the 0 the field opened on would have taken four.
    assert placed_copies(molecule()) == 3, placed_copies(molecule())
    assert STALE_HINT not in dialog_labels()
    return f'{ran.bl_idname} offset={ran.properties.offset:g}, 3 of 5 copies kept'


def verify_ok_kept_the_cut():
    assert 'dialog' not in data, 'OK did not close the dialog'
    mol = molecule()
    # OK builds what the settings say, and they said nothing new: rebuilding
    # here would hand back all five copies.
    assert placed_copies(mol) == 3, placed_copies(mol)
    assert A.built_assembly_id(mol) == 'generated:H'
    with g['ui_override']():
        assert bpy.ops.ed.undo() == {'FINISHED'}


def verify_undo():
    # One step back is the cut itself: closing with OK added none of its own.
    assert placed_copies(molecule()) == 5, placed_copies(molecule())
    with g['ui_override']():
        assert bpy.ops.ed.redo() == {'FINISHED'}


def verify_redo_and_open_menu():
    assert placed_copies(molecule()) == 3, placed_copies(molecule())
    move(data['row_x'], data['row_y'])
    for value in ('PRESS', 'RELEASE'):
        button(value, data['row_x'], data['row_y'], kind='RIGHTMOUSE')


def inspect_menu():
    capture('assembly-menu.png')
    layout = data['UI_MT_list_item_context_menu_layout']
    (folder / 'row-menu-layout.json').write_text(json.dumps(layout, indent=2))
    assert 'Edit Assembly' in str(layout)
    assert 'Assembly Controls' not in str(layout)
    data.pop('dialog', None)
    key('HOME')
    # Blender adds Add to Quick Favorites and Online Manual for the row label.
    key('DOWN_ARROW')
    key('DOWN_ARROW')
    key('RET')


def inspect_reopened():
    labels = dialog_labels()
    capture('reopened-after-cut.png')
    # A cut filament is still the filament it was built as: its dialog comes
    # back on its own settings rather than as a deposited assembly.
    assert data['dialog']['source'] == 'GENERATED', data['dialog']
    assert bpy.context.scene.pb_symmetry_count == 5
    assert 'Cutaway' in labels and STALE_HINT not in labels
    bpy.context.scene.pb_symmetry_count = 4
    poke()


def inspect_changed_settings():
    capture('changed-settings.png')
    assert STALE_HINT in dialog_labels(), 'Changed settings left the assembly tools live'
    # Shown at once, before OK.
    assert placed_copies(molecule()) == 4, placed_copies(molecule())


def verify_ok_rebuilt():
    assert 'dialog' not in data, 'OK did not close the dialog'
    mol = molecule()
    # Something new was asked for, so OK builds it - whole, not cut.
    assert placed_copies(mol) == 4, placed_copies(mol)
    assert A.built_build_params(mol)['count'] == 4
    with g['ui_override']():
        assert bpy.ops.molecule.add_filament_bend(molecule_id=data['mid']) == {'FINISHED'}
    reopen('mid')


def reopen(which):
    data.pop('dialog', None)
    with g['ui_override']():
        assert bpy.ops.molecule.symmetry_dialog(
            'INVOKE_DEFAULT', molecule_id_to_update=data[which]) == {'RUNNING_MODAL'}


def inspect_bend():
    capture('bend.png')
    labels = dialog_labels()
    # A filament that is already bent opens on its bend, and on nothing else:
    # the cutaway unfolded in the earlier dialog is folded again in this one.
    assert all(label in labels for label in ('Nodes', 'Edit Bend', 'Remove'))
    # No ready-made shapes: the nodes make the shape.
    assert not any(label in labels for label in ("'Arc'", 'S-curve', 'Coil'))
    assert 'Add Bend' not in labels and 'Cut Depth' not in labels
    assert STALE_HINT not in labels
    return fits_the_window()


def verify_ok_kept_the_bend():
    assert 'dialog' not in data, 'OK did not close the dialog'
    mol = molecule()
    assert symmetry_bend.has_bend(mol)
    assert placed_copies(mol) == 4
    with g['ui_override']():
        assert bpy.ops.molecule.remove_filament_bend(molecule_id=data['mid']) == {'FINISHED'}
    data['proteins'] = set(H.sm().molecules)
    reopen('mid')


def verify_realized():
    capture('realized.png')
    mol = molecule()
    assert A.built_assembly_id(mol) is None
    # Four copies, of which the first is the protein already there: the other
    # three are proteins of their own.
    data['realized'] = set(H.sm().molecules) - data['proteins']
    assert len(data['realized']) == 3, data['realized']
    # Nothing is left for the assembly's tools to work on.
    assert 'Cutaway' not in dialog_labels()


def verify_ok_left_the_realized_copies_alone():
    assert 'dialog' not in data, 'OK did not close the dialog'
    mol = molecule()
    # Building here would put a new assembly on top of the copies just made.
    assert A.built_assembly_id(mol) is None
    assert placed_copies(mol) <= 1, placed_copies(mol)
    assert set(H.sm().molecules) - data['proteins'] == data['realized']
    # The point of realizing: each copy is a protein row, with its chain
    # beneath it, that the outliner's own buttons work on.
    rows = bpy.context.scene.outliner_items
    listed = {r.item_id for r in rows if r.item_type == 'PROTEIN'}
    assert data['realized'] <= listed, (data['realized'], listed)
    for copy in data['realized']:
        assert any(r.item_type == 'CHAIN' and r.parent_id == copy for r in rows), copy
    assert not any(r.item_type == 'SYMMETRY' and r.parent_id == data['mid'] for r in rows)
    capture('realized-outliner.png')
    reopen('other_mid')


def inspect_deposited():
    capture('deposited.png')
    labels = dialog_labels()
    assert data['dialog']['source'] == 'BIOLOGICAL' and data['dialog']['opened_on']
    assert all(label in labels for label in ('Show Symmetry Axes', 'Realize Copies', 'Cutaway'))
    # A deposited assembly is not a filament, so it has no path to bend.
    assert 'Bend' not in labels
    data.pop('dialog', None)
    key('ESC')


def clear_and_reopen():
    with g['ui_override']():
        assert bpy.ops.molecule.clear_assembly(molecule_id=data['other_mid']) == {'FINISHED'}
    reopen('other_mid')


def inspect_cleared():
    # With nothing built the same dialog is only a builder.
    labels = dialog_labels()
    assert not data['dialog']['opened_on']
    assert 'Changes show as you make them' in labels
    assert 'Cutaway' not in labels and 'Realize Copies' not in labels
    key('ESC')


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', idle),
    ('prepare two assemblies', prepare), ('settle', idle),
    ('locate assembly row', locate_row), ('settle', idle),
    *click('the row pencil', 'pencil_xy'),
    ('inspect Edit Assembly', inspect_dialog), ('settle', idle),
    ('find Realize Copies', seek('realize_xy', 'molecule.realize_copies')), ('settle', idle),
    ('note the Cutaway header', fold_below('cut_fold_xy', 'realize_xy')),
    *click('the Cutaway header', 'cut_fold_xy'),
    ('inspect the open Cutaway section', inspect_cutaway_open), ('settle', idle),
    ('find Cut Away', seek('cut_xy', 'molecule.cutaway')), ('settle', idle),
    ('note the Bend header', fold_below('bend_fold_xy', 'cut_xy')),
    *click('the Bend header', 'bend_fold_xy'),
    ('inspect the open Bend section', inspect_bend_open), ('settle', idle),
    # Opening a section can move the rows above it.
    ('find Cut Away again', seek('cut_xy', 'molecule.cutaway')), ('settle', idle),
    ('hover Cut Depth', note_cut_depth), ('settle', idle),
    ('open Cut Depth for typing', open_cut_depth), ('settle', idle),
    ('type a cut depth', type_cut_depth), ('settle', idle),
    ('confirm the cut depth', lambda: key('RET')), ('settle', idle),
    *click('Cut Away', 'cut_xy'),
    ('verify Cut Away used the typed depth', verify_cut), ('settle', idle),
    *confirm('OK with nothing changed'),
    ('verify OK kept the cut and undo', verify_ok_kept_the_cut), ('settle', idle),
    ('verify undo and redo', verify_undo), ('settle', idle),
    ('verify redo and open row menu', verify_redo_and_open_menu), ('settle', idle),
    ('inspect menu and choose Edit Assembly', inspect_menu), ('settle', idle),
    ('inspect reopened dialog and change a setting', inspect_reopened), ('settle', idle),
    ('inspect changed settings', inspect_changed_settings), ('settle', idle),
    *confirm('OK with a changed setting'),
    ('verify OK rebuilt, bend and reopen', verify_ok_rebuilt), ('settle', idle),
    ('inspect bend tools', inspect_bend), ('settle', idle),
    *confirm('OK with a bend'),
    ('verify OK kept the bend and reopen', verify_ok_kept_the_bend), ('settle', idle),
    ('find Realize Copies', seek('realize_xy', 'molecule.realize_copies')), ('settle', idle),
    *click('Realize Copies', 'realize_xy'),
    ('verify realized copies', verify_realized), ('settle', idle),
    *confirm('OK after realizing'),
    ('verify OK left the copies alone and open deposited', verify_ok_left_the_realized_copies_alone),
    ('settle', idle),
    ('inspect deposited assembly', inspect_deposited), ('settle', idle),
    ('clear the assembly and reopen', clear_and_reopen), ('settle', idle),
    ('inspect dialog with nothing built', inspect_cleared), ('settle', idle),
]
