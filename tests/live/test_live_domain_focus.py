"""The domain selector changes actual viewport opacity, including restoration."""

import pytest


@pytest.mark.live
@pytest.mark.visual
def test_selected_domain_is_opaque_and_its_neighbor_is_translucent(blender, single_chain):
    chain_id, first_name = blender.call('''
import json
chain = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'CHAIN')
chain_id = chain.item_id
payload = json.dumps([dict(name='First', start=1, end=38),
                      dict(name='Second', start=39, end=chain.chain_end)])
with R.view3d_override():
    assert bpy.ops.proteinblender.edit_chain_domains(
        item_id=chain_id, layout_json=payload) == {'FINISHED'}
first = next(d.object for d in H.sm().molecules[mid].domains.values() if d.start == 1)
R.set_shading(kind='MATERIAL')
R.frame_all(objects=[first.name], zoom=1.0)
with R.view3d_override():
    assert bpy.ops.proteinblender.edit_chain_domains(
        'INVOKE_DEFAULT', item_id=chain_id) == {'RUNNING_MODAL'}
return chain_id, first.name
''', mid=single_chain)

    def observe(index):
        return blender.call('''
with R.view3d_override():
    assert bpy.ops.proteinblender.domain_splitter_select(index=index) == {'FINISHED'}
# Observe the same object from the same view under each selector state.
# Hide other objects only while measuring; the public selector owns materials.
visibility = [(o, o.hide_get()) for o in bpy.context.scene.objects if o.type == 'MESH']
try:
    for obj, _ in visibility:
        obj.hide_set(obj.name != first_name)
    pixels = R._render_viewport(256, True, True)
    alpha = pixels[:, :, 3]
    return {'alpha_sum': float(alpha.sum()), 'max_alpha': float(alpha.max())}
finally:
    for obj, hidden in visibility:
        obj.hide_set(hidden)
''', index=index, first_name=first_name)

    try:
        solid = observe(0)
        ghost = observe(1)
        # A later redraw may use a different operator wrapper. Read what its
        # actual row drawing code asks Blender to display, after selecting the
        # neighbor and allowing a fresh event-loop turn.
        highlighted = blender.call('''
import importlib
from types import SimpleNamespace
ds = importlib.import_module(H.PKG + '.operators.domain_splitter')
class Layout:
    def __init__(self):
        self.buttons = []
    def row(self, **kwargs):
        return self
    def label(self, **kwargs):
        pass
    def prop(self, *args, **kwargs):
        pass
    def operator(self, operator_id, **kwargs):
        button = SimpleNamespace(operator_id=operator_id, **kwargs)
        self.buttons.append(button)
        return button
layout = Layout()
dialog = ds._active()
for index, row in enumerate(dialog.rows):
    dialog._draw_columns(layout, row=row, index=index)
return [b.index for b in layout.buttons
        if b.operator_id == 'proteinblender.domain_splitter_select'
        and b.icon == 'RADIOBUT_ON']
''')
        assert highlighted == [1], "the popup highlights a different domain from its opaque preview"
        solid_again = observe(0)
        assert solid['alpha_sum'] > 100
        assert solid['max_alpha'] > 0.95
        assert 0 < ghost['alpha_sum'] < solid['alpha_sum'] * 0.7
        assert solid_again['alpha_sum'] == pytest.approx(solid['alpha_sum'], rel=0.03)
    finally:
        blender.call('''
window = R.find_view3d()[0]
window.event_simulate(type='ESC', value='PRESS')
window.event_simulate(type='ESC', value='RELEASE')
return True
''')
