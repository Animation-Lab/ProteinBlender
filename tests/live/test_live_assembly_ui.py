"""Exercise the shared assembly UI, observing Blender's actual drawn widgets."""

import time

import pytest


def _settle():
    time.sleep(0.4)


@pytest.mark.live
@pytest.mark.parametrize('source, kind, copies', [
    ('BIOLOGICAL', 'C', 2),
    ('GENERATED', 'C', 5),
    ('GENERATED', 'H', 5),
])
def test_create_preview_cancel_and_edit_assembly_child(blender, source, kind, copies):
    mid = blender.call('''
import importlib
with R.view3d_override():
    H.import_local('1ubq.pdb', 'Earlier protein')
    mid = H.import_local('5im3.pdb', 'Assembly UI')
scene = bpy.context.scene
scene.pb_symmetry_kind = kind
scene.pb_symmetry_order = 5
scene.pb_symmetry_count = 5
scene.pb_symmetry_rise = 20
scene.pb_symmetry_twist = 30
win = bpy.context.window
win.workspace = bpy.data.workspaces['Protein Blender']
for row in scene.outliner_items:
    row.is_expanded = True
panel = importlib.import_module(H.PKG + '.panels.symmetry_panel').PROTEINBLENDER_PT_symmetry
assert not panel.poll(bpy.context), 'Plain import opened a separate assembly panel'
# Wrap the real draw functions and inspect Blender's resulting native layout.
# This is not a mock layout: missing controls or a draw exception stay visible.
classes = [
    importlib.import_module(H.PKG + '.operators.symmetry_dialog').MOLECULE_PB_OT_symmetry_dialog,
    importlib.import_module(H.PKG + '.dna_builder.dna_panel').PROTEINBLENDER_PT_builders,
    panel,
    importlib.import_module(H.PKG + '.panels.protein_outliner_panel').PROTEINBLENDER_PT_outliner,
]
records, originals = {}, []
def observe(cls):
    method = 'draw'
    original = cls.draw
    def draw(self, context, *args):
        original(self, context, *args)
        key = cls.__name__
        records[key] = self.layout.introspect()
    originals.append((cls, method, original))
    setattr(cls, method, draw)
for cls in classes:
    observe(cls)
bpy.app.driver_namespace['pb_assembly_ui_records'] = records
bpy.app.driver_namespace['pb_assembly_ui_originals'] = originals
for area in win.screen.areas:
    area.tag_redraw()
return mid
''', kind=kind)
    try:
        _settle()
        blender.call('''
records = bpy.app.driver_namespace['pb_assembly_ui_records']
builder = str(records['PROTEINBLENDER_PT_builders'])
assert 'Create New Assembly' in builder, builder
assert 'Create New Symmetry' not in builder
with R.view3d_override():
    assert bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT', source=source) == {'RUNNING_MODAL'}
''', source=source)
        _settle()
        blender.call('''
records = bpy.app.driver_namespace['pb_assembly_ui_records']
layout = records['MOLECULE_PB_OT_symmetry_dialog']
assert 'Create New Assembly' in str(layout)
assert ('Deposited Assembly (BMT)' if source == 'BIOLOGICAL' else 'Generated Symmetry') in str(layout)
# Drive the Apply operator and arguments Blender actually drew.
def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('items', []))
button = next(item for item in flatten(layout) if item.get('draw_string') == 'Apply')
import ast
call = ast.parse(button['operator'], mode='eval').body
args = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
assert args['molecule_id'] == mid
assert args['source'] == source
with R.view3d_override():
    assert bpy.ops.molecule.symmetry_preview(**args) == {'FINISHED'}
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''', source=source, mid=mid)
        _settle()
        blender.call('''
import importlib
dialog = importlib.import_module(H.PKG + '.operators.symmetry_dialog')
assert not dialog.pending_previews(), 'Cancel failed to restore the preview'
assert not any(r.item_type == 'SYMMETRY' for r in bpy.context.scene.outliner_items)
with R.view3d_override():
    assert bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT', source=source) == {'RUNNING_MODAL'}
''', source=source)
        _settle()
        blender.call('''
win = bpy.context.window
win.event_simulate(type='RET', value='PRESS')
win.event_simulate(type='RET', value='RELEASE')
''')
        _settle()
        child_id = blender.call('''
scene = bpy.context.scene
children = [r for r in scene.outliner_items if r.item_type == 'SYMMETRY']
assert len(children) == 1, 'OK did not create an assembly child'
child = children[0]
assert child.parent_id == mid and child.indent_level == 1
# Ground truth: inspect the evaluated instances visible for each source chain.
bpy.context.view_layer.update()
graph = bpy.context.evaluated_depsgraph_get()
for domain in H.sm().molecules[mid].domains.values():
    actual = sum(i.is_instance and i.parent is not None
                 and i.parent.original.name == domain.object.name for i in graph.object_instances)
    assert actual == copies, (actual, copies)
return child.item_id
''', mid=mid, copies=copies)
        _settle()
        blender.call('''
import ast
records = bpy.app.driver_namespace['pb_assembly_ui_records']
layout = records['PROTEINBLENDER_PT_outliner']
def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get('items', []))
button = next(item for item in flatten(layout)
              if item.get('operator', '').startswith('bpy.ops.molecule.symmetry_dialog('))
call = ast.parse(button['operator'], mode='eval').body
args = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
assert args['molecule_id_to_update'] == mid, 'The child pencil targets another protein'
with R.view3d_override():
    assert bpy.ops.molecule.symmetry_dialog('INVOKE_DEFAULT', **args) == {'RUNNING_MODAL'}
''', mid=mid, child_id=child_id)
        _settle()
        blender.call('''
layout = str(bpy.app.driver_namespace['pb_assembly_ui_records']['MOLECULE_PB_OT_symmetry_dialog'])
assert 'Edit Assembly' in layout
assert ('Deposited Assembly (BMT)' if source == 'BIOLOGICAL' else 'Generated Symmetry') in layout
if source == 'BIOLOGICAL':
    assert 'Assembly 1 - 2 copies' in layout
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''', source=source)
        _settle()
        blender.call('''
import importlib
panel = importlib.import_module(H.PKG + '.panels.symmetry_panel').PROTEINBLENDER_PT_symmetry
bpy.ops.proteinblender.outliner_item_info(item_id=mid)
assert not panel.poll(bpy.context)
bpy.ops.proteinblender.outliner_item_info(item_id=child_id)
assert panel.poll(bpy.context)
for area in bpy.context.window.screen.areas:
    area.tag_redraw()
''', mid=mid, child_id=child_id)
        _settle()
        blender.call('''
layout = str(bpy.app.driver_namespace['pb_assembly_ui_records']['PROTEINBLENDER_PT_symmetry'])
assert 'Assembled' in layout and 'Keyframe' in layout
assert 'molecule.build_assembly(' not in layout, 'A duplicate deposited builder remains in the panel'
assert ('Add Bend' in layout) == (source == 'GENERATED' and kind == 'H'), layout
with R.view3d_override():
    assert bpy.ops.molecule.clear_assembly('EXEC_DEFAULT', True, molecule_id=mid) == {'FINISHED'}
assert not any(r.item_type == 'SYMMETRY' for r in bpy.context.scene.outliner_items)
''', mid=mid, source=source, kind=kind)
        _settle()
        blender.call('''
with R.view3d_override():
    assert bpy.ops.ed.undo() == {'FINISHED'}
''')
        _settle()
        blender.call('''
children = [r for r in bpy.context.scene.outliner_items if r.item_type == 'SYMMETRY']
assert len(children) == 1 and children[0].parent_id == mid, 'Undo lost the assembly child'
with R.view3d_override():
    assert bpy.ops.ed.redo() == {'FINISHED'}
''', mid=mid)
        _settle()
        blender.call('''
assert not any(r.item_type == 'SYMMETRY' for r in bpy.context.scene.outliner_items), 'Redo left a stale child'
''')
    finally:
        blender.call('''
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
for cls, method, original in bpy.app.driver_namespace.pop('pb_assembly_ui_originals', []):
    setattr(cls, method, original)
bpy.app.driver_namespace.pop('pb_assembly_ui_records', None)
''')
        _settle()
