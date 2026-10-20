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
        if cls in (Dialog, Builder):
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
    for cls in (Builder, Dialog, Builders):
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


def verify_rebuilt_longer():
    assert 'open' not in data, 'OK did not close the dialog'
    mol = filament()
    assert placed_copies(mol) == 12 * STRANDS, placed_copies(mol)
    assert symmetry_bend.has_bend(mol), 'Changing the length threw the path away'
    rows = [r for r in bpy.context.scene.outliner_items if r.item_type == 'SYMMETRY']
    assert len(rows) == 1 and '13 x 12' in rows[0].name, [r.name for r in rows]
    capture('microtubule-longer.png')
    return rows[0].name


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
    ('inspect the longer setting', inspect_longer), ('settle', idle),
    *confirm('OK the longer filament'),
    ('verify the longer microtubule', verify_rebuilt_longer), ('settle', idle),
]
