"""Create two membranes of different shapes from the Builders panel.

The Create New Membrane dialog describes a membrane that does not exist yet,
so nothing chosen in it may reach a membrane that does. The dialog shares its
fields with Edit Membrane, where a change is meant to land at once, which is
how picking a shape for a second membrane came to reshape the first.
"""
import runpy
import sys
from pathlib import Path

import bpy

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
H = g['H']
from proteinblender.membrane_builder.membrane_operators import (
    PROTEINBLENDER_OT_build_membrane as Dialog,
)

data = {}
folder = Path(g['report_path']).parent

#: Both in nm. A hemisphere of this radius is a bowl as deep as it is wide
#: across half its rim; a sheet has no depth at all.
RADIUS = 15.0
SIDE = 20.0
WIDER_RADIUS = 20.0
#: The scene is drawn at ten nanometres to the Blender unit.
NM_PER_UNIT = 10.0


def idle():
    return None


def scale():
    return bpy.context.preferences.system.ui_scale


def move(x, y):
    data['mouse'] = (int(x), int(y))
    g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def key(kind):
    # A key event carries the cursor too, and a dialog opens where it says.
    x, y = data['mouse']
    for value in ('PRESS', 'RELEASE'):
        g['active_window']().event_simulate(type=kind, value=value, x=x, y=y)


def capture(name):
    bpy.ops.screen.screenshot(filepath=str(folder / name))


def observe(cls):
    original = cls.draw
    def draw(self, context):
        original(self, context)
        data['popup'] = getattr(context, 'region_popup', None) or context.region
        data['open'] = True
    cls.draw = draw


def title_xy():
    popup = data['popup']
    return popup.x + popup.width / 2, popup.y + popup.height - 14 * scale()


def close_with(label, kind):
    # Enter over a button presses that button, so it is sent from the title.
    def press():
        assert data.pop('open', None), 'The membrane dialog is not open'
        key(kind)
    return [(f'hover the title before {label}', lambda: move(*title_xy())), ('settle', idle),
            (label, press), ('settle', idle)]


def props():
    return bpy.context.scene.membrane_builder_props


def choose(**settings):
    """Set dialog fields the way a click on them does, then redraw it."""
    with g['ui_override']('VIEW_3D'):
        for name, value in settings.items():
            setattr(props(), name, value)
    data['popup'].tag_refresh_ui()
    move(*title_xy())


def membranes():
    return sorted((o for o in bpy.data.objects if o.get('pb_is_membrane', False)),
                  key=lambda o: o.name)


def depth_over_width(root):
    """How deep the membrane's surface is next to how wide, off its vertices.

    Read from the base mesh the lipids are scattered on, not from the shape
    the membrane says it is: a sheet is flat, so 0, and a hemisphere is as
    deep as its radius and twice that across, so 0.5.
    """
    xs = [v.co.x for v in root.data.vertices]
    zs = [v.co.z for v in root.data.vertices]
    return (max(zs) - min(zs)) / (max(xs) - min(xs))


def width(root):
    xs = [v.co.x for v in root.data.vertices]
    return max(xs) - min(xs)


def is_sheet(root):
    return depth_over_width(root) < 0.05


def is_hemisphere(root):
    return 0.4 < depth_over_width(root) < 0.6


def shapes():
    return {o.name: round(depth_over_width(o), 3) for o in membranes()}


def prepare():
    H.reset_scene()
    observe(Dialog)
    window = g['active_window']()
    move(window.width * .45, window.height * .8)
    assert not membranes()
    with g['ui_override']('VIEW_3D'):
        props().shape = 'HEMISPHERE'
        props().radius = RADIUS
        props().width = props().height = SIDE


def open_create():
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.proteinblender.build_membrane('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def verify_hemisphere():
    assert 'open' not in data, 'OK did not close the dialog'
    assert len(membranes()) == 1, shapes()
    data['first'] = membranes()[0].name
    assert is_hemisphere(membranes()[0]), shapes()
    capture('one-hemisphere.png')
    return str(shapes())


def choose_sheet():
    choose(shape='FLAT')


def verify_first_untouched_while_choosing():
    capture('choosing-a-sheet.png')
    first = bpy.data.objects[data['first']]
    assert is_hemisphere(first), (
        'Choosing a shape for a new membrane reshaped the one already built',
        shapes())
    assert first['pb_mem_shape'] == 'HEMISPHERE', first['pb_mem_shape']


def verify_one_of_each():
    assert 'open' not in data, 'OK did not close the dialog'
    assert len(membranes()) == 2, shapes()
    first = bpy.data.objects[data['first']]
    second = next(o for o in membranes() if o.name != data['first'])
    data['second'] = second.name
    assert is_hemisphere(first), (
        'Building a sheet turned the hemisphere into a sheet as well', shapes())
    assert is_sheet(second), shapes()
    capture('one-of-each.png')
    return str(shapes())


def choose_sphere_and_denser():
    data['density'] = {o.name: o['pb_mem_density'] for o in membranes()}
    choose(shape='SPHERE', density=props().density + 1.0)


def verify_cancel_built_nothing():
    assert len(membranes()) == 2, shapes()
    assert is_hemisphere(bpy.data.objects[data['first']]), shapes()
    assert is_sheet(bpy.data.objects[data['second']]), shapes()
    assert {o.name: o['pb_mem_density'] for o in membranes()} == data['density'], (
        'A cancelled Create New Membrane changed a membrane that exists')
    # The fields go back to the membrane they described before the dialog, so
    # the abandoned sphere cannot ride along with the next one touched.
    assert props().shape == 'FLAT', (
        'Cancel left the abandoned draft in the fields', props().shape)
    assert props().density == data['density'][data['second']], props().density


def open_edit_first():
    with g['ui_override']('VIEW_3D'):
        assert bpy.ops.proteinblender.build_membrane(
            'INVOKE_DEFAULT', membrane_root_to_update=data['first']) == {'RUNNING_MODAL'}


def edit_first_denser_and_wider():
    # Edit Membrane is the other half of the bargain: there a change does land
    # at once, and on the membrane the dialog was opened for.
    assert props().shape == 'HEMISPHERE', props().shape
    data['target'] = round(data['density'][data['first']] + 0.5, 3)
    choose(density=data['target'], radius=WIDER_RADIUS)


def verify_edit_is_live():
    capture('editing-the-hemisphere.png')
    first, second = (bpy.data.objects[data[k]] for k in ('first', 'second'))
    assert round(first['pb_mem_density'], 3) == data['target'], (
        'Edit Membrane no longer previews on the membrane it is editing',
        first['pb_mem_density'], data['target'])
    assert second['pb_mem_density'] == data['density'][data['second']], (
        'Editing one membrane changed the other')


def verify_edit_resized_one():
    assert 'open' not in data, 'OK did not close the dialog'
    first, second = (bpy.data.objects[data[k]] for k in ('first', 'second'))
    assert is_hemisphere(first) and is_sheet(second), shapes()
    # A hemisphere is two radii across, a sheet as wide as it was built.
    assert abs(width(first) - 2 * WIDER_RADIUS / NM_PER_UNIT) < 0.01, (
        'OK did not resize the hemisphere to the radius typed', width(first))
    assert abs(width(second) - SIDE / NM_PER_UNIT) < 0.01, (
        'Resizing the hemisphere resized the sheet', width(second))
    capture('hemisphere-resized.png')
    return str({o.name: round(width(o), 3) for o in membranes()})


g['steps'][:] = [
    ('workspace', g['setup_morphset_workspace']), ('settle', idle),
    ('prepare an empty scene', prepare), ('settle', idle),
    ('open Create New Membrane', open_create), ('settle', idle),
    *close_with('OK the hemisphere', 'RET'),
    ('verify the hemisphere', verify_hemisphere), ('settle', idle),
    ('open Create New Membrane again', open_create), ('settle', idle),
    ('choose Sheet', choose_sheet), ('settle', idle),
    ('verify the hemisphere is untouched', verify_first_untouched_while_choosing),
    *close_with('OK the sheet', 'RET'),
    ('verify one of each', verify_one_of_each), ('settle', idle),
    ('open Create New Membrane a third time', open_create), ('settle', idle),
    ('choose Sphere and a higher density', choose_sphere_and_denser), ('settle', idle),
    *close_with('cancel the sphere', 'ESC'),
    ('verify cancelling built and changed nothing', verify_cancel_built_nothing),
    ('open Edit Membrane on the hemisphere', open_edit_first), ('settle', idle),
    ('raise its density and radius', edit_first_denser_and_wider), ('settle', idle),
    ('verify the edit previews on its own membrane', verify_edit_is_live),
    *close_with('OK the edit', 'RET'),
    ('verify only the hemisphere was resized', verify_edit_resized_one), ('settle', idle),
]
