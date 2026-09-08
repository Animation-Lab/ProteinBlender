"""Native alignment popup, outliner child, playback and undo in installed Blender."""
import time

import pytest


@pytest.mark.live
@pytest.mark.parametrize('chain', ['A', 'ALL'])
def test_existing_cartoon_popup_upgrades_and_scrubs_smoothly(blender, chain):
    blender.call('''
import importlib
import numpy as np
with R.view3d_override():
    first = H.import_local('1ake.pdb', 'closed')
    second = H.import_local('4ake.pdb', 'open')
    bpy.ops.proteinblender.create_conformation(source_id=first, target_id=second,
        source_chain=chain, target_chain=chain, duration=3, smooth=False)
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
# Reproduce an older saved transition that still uses the ordinary MN cartoon.
tree = obj.modifiers[0].node_group
style = next(n for n in tree.nodes if n.type == 'GROUP' and 'Style Cartoon' in n.node_tree.name)
importlib.import_module(H.PKG + '.utils.molecularnodes.blender.nodes').swap(style, 'Style Cartoon')
for attribute in list(obj.data.attributes):
    if attribute.name.startswith('pb_cartoon_'):
        obj.data.attributes.remove(attribute)
for key in list(obj.data.keys()):
    if key.startswith('pb_cartoon_'):
        del obj.data[key]
bpy.context.scene.frame_set(50)
cls = importlib.import_module(H.PKG + '.operators.conformation_operators').PROTEINBLENDER_OT_edit_conformation
original = cls.draw
def draw(self, context):
    original(self, context)
    bpy.app.driver_namespace['pb_cartoon_popup'] = self
cls.draw = draw
bpy.app.driver_namespace['pb_cartoon_draw'] = (cls, original)
with R.view3d_override():
    bpy.ops.proteinblender.edit_conformation('INVOKE_DEFAULT', transition_id=obj['pb_conformation'])
''', chain=chain)
    try:
        time.sleep(.4)
        blender.call('''
import numpy as np
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
op = bpy.app.driver_namespace['pb_cartoon_popup']
assert op.style == 'cartoon' and bpy.context.scene.frame_current == 50
keys = obj.data.shape_keys.key_blocks
start = np.array([v.co[:] for v in keys[0].data])
end = np.array([v.co[:] for v in keys[1].data])
frames = obj['pb_end_frame'] - obj['pb_start_frame']
atom_step = np.linalg.norm(end - start, axis=1).max() / frames
op.progress = 0
previous = H.eval_positions(obj)
assert len(previous) > 1000
for frame in range(1, frames + 1):
    op.progress = frame / frames
    current = H.eval_positions(obj)
    assert current.shape == previous.shape
    assert np.linalg.norm(current - previous, axis=1).max() < 2 * atom_step
    previous = current
op.progress = .5
bpy.ops.proteinblender.conformation_preview(transition_id=obj['pb_conformation'], action='PLAY')
bpy.app.driver_namespace['pb_cartoon_frame'] = bpy.context.scene.frame_current
''')
        time.sleep(.35)
        blender.call('''
assert bpy.context.scene.frame_current != bpy.app.driver_namespace['pb_cartoon_frame']
''')
    finally:
        blender.call('''
import importlib
importlib.import_module(H.PKG + '.operators.conformation_operators').stop_playback()
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
cls, original = bpy.app.driver_namespace.pop('pb_cartoon_draw')
cls.draw = original
bpy.app.driver_namespace.pop('pb_cartoon_popup', None)
bpy.app.driver_namespace.pop('pb_cartoon_frame', None)
''')


@pytest.mark.live
def test_alignment_popup_playback_cancel_and_undo(blender):
    blender.call('''
import importlib
with R.view3d_override():
    first = H.import_local('1ake.pdb', 'closed')
    second = H.import_local('4ake.pdb', 'open')
bpy.context.window.workspace = bpy.data.workspaces['Protein Blender']
R.frame_all(zoom=.8)
mod = importlib.import_module(H.PKG + '.operators.conformation_operators')
records, originals = {}, []
for cls in (mod.PROTEINBLENDER_OT_create_conformation, mod.PROTEINBLENDER_OT_edit_conformation):
    original = cls.draw
    def make_draw(cls, original):
        def draw(self, context):
            original(self, context)
            records[cls.__name__] = (self.layout.introspect(), self)
        return draw
    originals.append((cls, original))
    cls.draw = make_draw(cls, original)
bpy.app.driver_namespace['pb_conformation_ui'] = (records, originals, first, second)
with R.view3d_override():
    assert bpy.ops.proteinblender.create_conformation('INVOKE_DEFAULT', source_id=first,
        target_id=second, source_chain='A', target_chain='A') == {'RUNNING_MODAL'}
''')
    try:
        time.sleep(.6)
        blender.call('''
records, _, first, second = bpy.app.driver_namespace['pb_conformation_ui']
layout, op = records['PROTEINBLENDER_OT_create_conformation']
for text in ('Start structure', 'End structure', 'Residue match', '214 paired residues', 'Fit RMSD'):
    assert text in str(layout), str(layout)
assert not any(o.get('pb_conformation') for o in bpy.context.scene.objects)
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''')
        time.sleep(.4)
        blender.call('''
_, _, first, second = bpy.app.driver_namespace['pb_conformation_ui']
assert not any(o.get('pb_conformation') for o in bpy.context.scene.objects)
bpy.ops.ed.undo_push(message='Before transition')
with R.view3d_override():
    bpy.ops.proteinblender.create_conformation('INVOKE_DEFAULT', source_id=first,
        target_id=second, source_chain='A', target_chain='A', duration=1)
''')
        time.sleep(.4)
        blender.call('''
win = bpy.context.window
win.event_simulate(type='RET', value='PRESS')
win.event_simulate(type='RET', value='RELEASE')
''')
        time.sleep(.8)
        blender.call('''
records, _, first, second = bpy.app.driver_namespace['pb_conformation_ui']
layout, op = records['PROTEINBLENDER_OT_edit_conformation']
for text in ('Start', 'End', 'Play', 'Duration', 'Color', 'Match details'):
    assert text in str(layout), str(layout)
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
row = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'TRANSITION')
assert row.parent_id == first and row.object_name == obj.name
op.progress = .5
assert abs(obj.data.shape_keys.key_blocks[1].value - .5) < .05
bpy.ops.proteinblender.conformation_preview(transition_id=obj['pb_conformation'], action='END')
assert obj.data.shape_keys.key_blocks[1].value == 1
# The scrubber must reflect the endpoint button, not a stale earlier value.
assert op.progress == 1, f'Scrubber remains at {op.progress} after End; should be 1'
bpy.ops.proteinblender.conformation_preview(transition_id=obj['pb_conformation'], action='PLAY')
bpy.app.driver_namespace['pb_conformation_frame'] = bpy.context.scene.frame_current
''')
        time.sleep(.35)
        blender.call('''
assert bpy.context.scene.frame_current != bpy.app.driver_namespace['pb_conformation_frame']
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
''')
        time.sleep(.3)
        blender.call('''
import importlib
assert importlib.import_module(H.PKG + '.operators.conformation_operators')._playing is None
assert len([o for o in bpy.context.scene.objects if o.get('pb_conformation')]) == 1
with R.view3d_override():
    bpy.ops.ed.undo()
''')
        time.sleep(.4)
        blender.call('''
assert not any(o.get('pb_conformation') for o in bpy.context.scene.objects)
assert not any(o.get('pb_transition_visibility') for o in bpy.context.scene.objects)
with R.view3d_override():
    bpy.ops.ed.redo()
''')
        time.sleep(.4)
        blender.call('''
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
assert any(r.item_type == 'TRANSITION' for r in bpy.context.scene.outliner_items)
with R.view3d_override():
    bpy.ops.proteinblender.edit_conformation('INVOKE_DEFAULT', transition_id=obj['pb_conformation'])
''')
        time.sleep(.4)
        blender.call('''
win = bpy.context.window
win.event_simulate(type='RET', value='PRESS')
win.event_simulate(type='RET', value='RELEASE')
''')
    finally:
        blender.call('''
import importlib
importlib.import_module(H.PKG + '.operators.conformation_operators').stop_playback()
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
_, originals, _, _ = bpy.app.driver_namespace.pop('pb_conformation_ui', ({}, [], '', ''))
for cls, original in originals:
    cls.draw = original
''')


@pytest.mark.live
def test_surface_choice_applies_reopens_and_plays(blender):
    blender.call('''
import importlib
with R.view3d_override():
    first = H.import_local('1ake.pdb', 'closed')
    second = H.import_local('4ake.pdb', 'open')
    bpy.ops.proteinblender.create_conformation(source_id=first, target_id=second,
        source_chain='A', target_chain='A', duration=2)
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
cls = importlib.import_module(H.PKG + '.operators.conformation_operators').PROTEINBLENDER_OT_edit_conformation
original = cls.draw
def draw(self, context):
    original(self, context)
    bpy.app.driver_namespace['pb_surface_popup'] = self
cls.draw = draw
bpy.app.driver_namespace['pb_surface_draw'] = (cls, original)
with R.view3d_override():
    bpy.ops.proteinblender.edit_conformation('INVOKE_DEFAULT', transition_id=obj['pb_conformation'])
''')
    try:
        time.sleep(.4)
        blender.call('''
op = bpy.app.driver_namespace['pb_surface_popup']
properties = bpy.ops.proteinblender.edit_conformation.get_rna_type().properties
choices = {item.identifier: item.name for item in properties['style'].enum_items}
assert choices.get('surface') == 'Surface', choices
op.style = 'surface'
win = bpy.context.window
win.event_simulate(type='RET', value='PRESS')
win.event_simulate(type='RET', value='RELEASE')
''')
        time.sleep(.5)
        blender.call('''
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
assert obj['pb_transition_style'] == 'surface'
assert len(H.eval_positions(obj)) > 100
with R.view3d_override():
    bpy.ops.proteinblender.edit_conformation('INVOKE_DEFAULT', transition_id=obj['pb_conformation'])
''')
        time.sleep(.4)
        blender.call('''
op = bpy.app.driver_namespace['pb_surface_popup']
assert op.style == 'surface'
op.progress = .5
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
assert abs(obj.data.shape_keys.key_blocks[1].value - .5) < .05
bpy.ops.proteinblender.conformation_preview(transition_id=obj['pb_conformation'], action='PLAY')
bpy.app.driver_namespace['pb_surface_frame'] = bpy.context.scene.frame_current
''')
        time.sleep(.4)
        blender.call('''
assert bpy.context.scene.frame_current != bpy.app.driver_namespace['pb_surface_frame']
obj = next(o for o in bpy.context.scene.objects if o.get('pb_conformation'))
assert len(H.eval_positions(obj)) > 100
''')
    finally:
        blender.call('''
import importlib
importlib.import_module(H.PKG + '.operators.conformation_operators').stop_playback()
win = bpy.context.window
win.event_simulate(type='ESC', value='PRESS')
win.event_simulate(type='ESC', value='RELEASE')
cls, original = bpy.app.driver_namespace.pop('pb_surface_draw')
cls.draw = original
bpy.app.driver_namespace.pop('pb_surface_popup', None)
bpy.app.driver_namespace.pop('pb_surface_frame', None)
''')
