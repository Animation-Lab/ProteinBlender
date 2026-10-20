"""Raise a built filament's bend node count from Edit Assembly, as a user does.

The Nodes field is typed into and stepped with its arrow, with a real cursor,
and nothing else is pressed: the path has to have that many control nodes the
moment the field does. Run for each shipped filament.
"""
import runpy
import sys
from pathlib import Path

import bpy

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
H = g['H']
from proteinblender.core import symmetry_bend
from proteinblender.operators.symmetry_dialog import MOLECULE_PB_OT_symmetry_dialog as Dialog

data = {}
folder = Path(g['report_path']).parent


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
    x, y = data['mouse']
    for value in ('PRESS', 'RELEASE'):
        g['active_window']().event_simulate(type=kind, value=value, x=x, y=y, **modifiers)


def capture(name):
    path = str(folder / name)
    bpy.ops.screen.screenshot(filepath=path)
    return path


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data['layout'] = self.layout.introspect()
        data['popup'] = getattr(context, 'region_popup', None) or context.region
        data['open'] = True
    cls.draw = draw


def title_xy():
    popup = data['popup']
    return popup.x + popup.width / 2, popup.y + popup.height - 14 * scale()


def click(label, where):
    return [(f'hover {label}', lambda: move(*data[where])), ('settle', idle),
            (f'press {label}', lambda: button('PRESS', *data[where])),
            (f'release {label}', lambda: button('RELEASE', *data[where])),
            ('settle', idle)]


def confirm(label):
    return [(f'hover the title before {label}', lambda: move(*title_xy())), ('settle', idle),
            (label, press_ok), ('settle', idle)]


def press_ok():
    data.pop('open', None)
    key('RET')


def seek(where, wanted):
    """Walk the cursor up the dialog until Ctrl+C reports ``wanted``."""
    def run():
        wm = bpy.context.window_manager
        popup = data['popup']
        step = 6 * scale()
        at = data.get('seek')
        if at is None:
            x, y = popup.x + popup.width * .4, popup.y + 8 * scale()
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


def rig():
    """The path as the file has it: control nodes, their hooks, curve points.

    Counted off Blender's own data rather than asked of the bend code, and
    all three have to agree for a node to be one the user can drag.
    """
    curves = [o for o in bpy.context.scene.objects if symmetry_bend.CURVE_SUFFIX in o.name]
    assert len(curves) == 1, [o.name for o in curves]
    nodes = [o for o in bpy.context.scene.objects if 'Filament Node' in o.name]
    hooked = {m.object.name for m in curves[0].modifiers
              if m.type == 'HOOK' and m.object is not None}
    return (len(nodes), len(hooked & {o.name for o in nodes}),
            len(curves[0].data.splines[0].bezier_points))


def has(nodes, label):
    found = rig()
    assert found == (nodes, nodes, nodes), (
        f'{label}: the path has {found} nodes, hooks and points, not {nodes}')
    copies = placed_copies(filament())
    assert copies == data['copies'], (label, copies, data['copies'])


def prepare(preset, copies):
    def run():
        H.reset_scene()
        if 'observed' not in data:
            observe(Dialog)
            data['observed'] = True
        window = g['active_window']()
        move(window.width * .45, window.height * .8)
        with g['ui_override']('VIEW_3D'):
            assert bpy.ops.molecule.build_filament(
                preset=preset, length=50.0) == {'FINISHED'}
            # Scripted calls leave no undo steps of their own.
            bpy.ops.ed.undo_push(message='Built filament')
        for area in window.screen.areas:
            area.tag_redraw()
        data['copies'] = copies
        has(3, 'as built')
    return run


def open_dialog():
    data.pop('open', None)
    with g['ui_override']():
        assert bpy.ops.molecule.symmetry_dialog(
            'INVOKE_DEFAULT', molecule_id_to_update=filament().identifier) == {'RUNNING_MODAL'}


def note_field(rows_up=1):
    # Nodes is the row above Edit Bend. A probe stops 6 to 12 px above the
    # bottom of the button it finds, so 25 px higher is inside the next row.
    def run():
        x, y = data['edit_xy']
        popup = data['popup']
        data['field_xy'] = (x, round(y + rows_up * 25 * scale()))
        # The field's own arrow, at its right-hand end: one more node a click.
        data['more_xy'] = (round(popup.x + popup.width - 28 * scale()), data['field_xy'][1])
        move(*data['field_xy'])
    return run


def copy_field():
    bpy.context.window_manager.clipboard = ''
    key('C', ctrl=True)


def field_reads(wanted):
    def run():
        shown = bpy.context.window_manager.clipboard
        assert shown == str(wanted), f'The Nodes field reads {shown!r}, not {wanted}'
    return run


def read_field(wanted):
    return [('hover Nodes', lambda: move(*data['field_xy'])), ('settle', idle),
            ('copy Nodes', copy_field), ('settle', idle),
            (f'Nodes reads {wanted}', field_reads(wanted)), ('settle', idle)]


def open_field():
    # Ctrl+click types into a number field.
    for value in ('PRESS', 'RELEASE'):
        button(value, *data['field_xy'], ctrl=True)


def type_six():
    key('A', ctrl=True)
    window = g['active_window']()
    x, y = data['mouse']
    window.event_simulate(type='SIX', value='PRESS', unicode='6', x=x, y=y)
    window.event_simulate(type='SIX', value='RELEASE', x=x, y=y)


def verify(nodes, label, shot=None):
    def run():
        if shot:
            capture(shot)
        assert data.get('open'), 'The dialog closed'
        has(nodes, label)
        assert 'molecule.set_filament_bend_nodes' not in str(data['layout']), (
            'Nodes still has a button of its own to press')
        return str(rig())
    return run


def verify_ok_kept(nodes):
    def run():
        assert 'open' not in data, 'OK did not close the dialog'
        has(nodes, 'after OK')
        with g['ui_override']():
            assert bpy.ops.ed.undo() == {'FINISHED'}
    return run


def verify_undo(nodes, then):
    def run():
        # One step back is one change of the field.
        has(nodes, 'after undo')
        with g['ui_override']():
            assert bpy.ops.ed.redo() == {'FINISHED'}
    return run


def verify_redo_and_reopen(nodes):
    def run():
        has(nodes, 'after redo')
        open_dialog()
    return run


def key_the_path():
    # Any key on a control node will do: the last one's place at frame 1.
    last = max((o for o in bpy.context.scene.objects if 'Filament Node' in o.name),
               key=lambda o: o.name)
    assert last.keyframe_insert('location', frame=1)
    data['keyed'] = last.name


def verify_locked(shot):
    def run():
        capture(shot)
        assert data.get('open'), 'The dialog closed'
        assert 'Keyframed - clear its keys' in str(data['layout']), (
            'Nothing says why Nodes cannot be changed')
        has(3, 'keyframed')
        kept = bpy.data.objects[data['keyed']]
        assert kept.animation_data is not None and kept.animation_data.action is not None
    return run


def close():
    data.pop('open', None)
    key('ESC')


def run_through(preset, copies):
    tag = preset.lower()
    return [
        (f'{tag}: build', prepare(preset, copies)), ('settle', idle),
        (f'{tag}: open Edit Assembly', open_dialog), ('settle', idle),
        (f'{tag}: find Edit Bend', seek('edit_xy', 'molecule.edit_filament_bend')),
        ('settle', idle),
        (f'{tag}: note Nodes', note_field()), ('settle', idle),
        *read_field(3),
        (f'{tag}: open Nodes for typing', open_field), ('settle', idle),
        (f'{tag}: type 6', type_six), ('settle', idle),
        (f'{tag}: confirm the field', lambda: key('RET')), ('settle', idle),
        (f'{tag}: typing 6 gave six nodes', verify(6, 'after typing 6', f'{tag}-typed.png')),
        ('settle', idle),
        *click('the Nodes arrow', 'more_xy'),
        (f'{tag}: the arrow gave a seventh', verify(7, 'after the arrow', f'{tag}-stepped.png')),
        ('settle', idle),
        *read_field(7),
        *confirm('OK'),
        (f'{tag}: OK kept seven and undo', verify_ok_kept(7)), ('settle', idle),
        (f'{tag}: undo gave six and redo', verify_undo(6, 7)), ('settle', idle),
        (f'{tag}: redo gave seven and reopen', verify_redo_and_reopen(7)), ('settle', idle),
        # Opening is not a change: the path it opens on is left as it was.
        (f'{tag}: reopened on seven', verify(7, 'reopened')), ('settle', idle),
        # A dialog opens where the cursor is, which is not where it was.
        (f'{tag}: find Edit Bend again', seek('edit_xy', 'molecule.edit_filament_bend')),
        ('settle', idle),
        (f'{tag}: note Nodes again', note_field()), ('settle', idle),
        *read_field(7),
        (f'{tag}: close', close), ('settle', idle),
    ]


def keyframed(preset, copies):
    """A keyed path keeps its nodes, and the dialog says so before it is tried."""
    tag = f'{preset.lower()} keyed'
    return [
        (f'{tag}: build', prepare(preset, copies)), ('settle', idle),
        (f'{tag}: key a node', key_the_path), ('settle', idle),
        (f'{tag}: open Edit Assembly', open_dialog), ('settle', idle),
        (f'{tag}: find Edit Bend', seek('edit_xy', 'molecule.edit_filament_bend')),
        ('settle', idle),
        # The line saying why sits between Nodes and Edit Bend.
        (f'{tag}: note Nodes', note_field(rows_up=2)), ('settle', idle),
        (f'{tag}: opened locked', verify_locked(f'{tag.replace(" ", "-")}.png')),
        ('settle', idle),
        *click('the locked Nodes arrow', 'more_xy'),
        (f'{tag}: the arrow changed nothing', verify_locked(f'{tag.replace(" ", "-")}-clicked.png')),
        ('settle', idle),
        (f'{tag}: close', close), ('settle', idle),
    ]


# 500 A of each: eighteen actin subunits, and six dimers up thirteen strands.
g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', idle),
    *run_through('ACTIN', 18),
    *run_through('MICROTUBULE', 78),
    *keyframed('ACTIN', 18),
]
