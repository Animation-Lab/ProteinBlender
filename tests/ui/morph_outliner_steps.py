"""Actual PB row menus and live member appearance dialogs."""
from pathlib import Path

import bpy
import numpy as np


def build_steps(g):
    from proteinblender.core import morphsets as C, model_morphsets as M
    from proteinblender.core.visual_style import get_object_style, get_object_color
    from proteinblender.operators import morphset_operators as O, visual_edit
    from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_UL_outliner as List
    data = {}
    scene = lambda: bpy.context.scene
    root = lambda: C.find(scene(), data['root'])
    morph = lambda: M.subject(root())
    output = lambda: C.outputs(scene(), morph()[C.MORPH])[0]

    def event(kind, value='PRESS', **kw):
        g['active_window']().event_simulate(type=kind, value=value, **kw)
        if value == 'PRESS':
            g['active_window']().event_simulate(type=kind, value='RELEASE', **kw)

    def screenshot(name):
        path = str(Path(g['report_path']).parent / name)
        bpy.ops.screen.screenshot(filepath=path)
        return path

    def observe(cls):
        original = cls.draw
        def draw(self, context):
            original(self, context)
            data[cls.__name__] = self.layout.introspect()
        data['draws'].append((cls, original))
        cls.draw = draw

    def prepare():
        g['H'].reset_scene()
        with g['ui_override']('VIEW_3D'):
            mid = g['H'].import_local('1d3z.pdb.gz', 'Outliner 1D3Z')
        data['mid'] = mid
        assert bpy.ops.proteinblender.create_morphset(source=mid, name='Outliner models') == {'FINISHED'}
        data['root'] = C.sets(scene())[0][C.TAG]
        data['member'] = morph()[C.MORPH] + ':0'
        for row in scene().outliner_items:
            row.is_expanded = True
            if row.item_type == 'PROTEIN':
                row.row_color = (1, 0, 0, 1)
        for frame, index in ((1,0), (50,3)):
            C.insert_keys(bpy.context, frame, {morph()[C.MORPH]: {
                'state': C.states(morph())[index]['uid'], 'visible': [True]}})
        scene().frame_set(1)
        scene().outliner_index = 0  # right-click must use the hovered row
        data['draws'] = []
        observe(O.PROTEINBLENDER_OT_edit_morphset)
        observe(O.PROTEINBLENDER_OT_edit_morph_member)
        def menu(menu, context):
            row = getattr(context, 'pb_outliner_item', None)
            data['menu_target'] = row.item_id if row else None
            data['menu_layout'] = menu.layout.introspect()
        data['menu_observer'] = menu
        bpy.types.UI_MT_list_item_context_menu.append(menu)
        original = List.draw_item
        def draw_item(self, context, layout, source, item, icon, active_data, active_propname):
            original(self, context, layout, source, item, icon, active_data, active_propname)
            if item.item_type == 'MORPH_MEMBER':
                data['member_controls'] = layout.introspect()
        data['original_item_draw'] = original
        List.draw_item = draw_item
        g['redraw_all_panels']()

    def right_click():
        image = bpy.data.images.load(screenshot('morph-outliner.png'), check_existing=False)
        w,h = image.size
        pixels = np.array(image.pixels[:]).reshape(h,w,4)
        bpy.data.images.remove(image)
        area = g['protein_workspace_panel_area']()
        mask = np.max(np.abs(pixels[:,area.x:area.x+area.width,:3]-(1,0,0)), axis=2) < .15
        ys = np.flatnonzero(mask.sum(axis=1) >= 10)
        assert len(ys), 'Protein row color marker was not drawn'
        ys = np.split(ys, np.flatnonzero(np.diff(ys) > 1)+1)[-1]
        x = area.x + area.width // 2
        y = round(float(np.median(ys)) - 20*bpy.context.preferences.system.ui_scale)
        event('MOUSEMOVE', 'NOTHING', x=x, y=y)
        event('RIGHTMOUSE', x=x, y=y)

    def inspect_menu():
        assert data['menu_target'] == data['root']
        layout = str(data['menu_layout'])
        assert 'Edit' in layout and 'proteinblender.edit_morphset' in layout
        assert all(op not in layout for op in ('delete_morphset', 'toggle_visibility', 'outliner_select'))
        # The backing list cursor is read-only, suppressing Blender's driver,
        # animation, reset and copy-property actions before our menu is drawn.
        assert scene().is_property_readonly('pb_outliner_menu_index')
        screenshot('morph-outliner-context-menu.png')
        event('ESC')

    def open_root():
        with g['ui_override']():
            assert bpy.ops.proteinblender.edit_morphset('INVOKE_DEFAULT',
                morphset_id=data['menu_target']) == {'RUNNING_MODAL'}

    def inspect_root():
        dialog = O.PROTEINBLENDER_OT_edit_morphset._active_instance
        assert dialog.name == 'Outliner models' and len(dialog.members) == 1
        screenshot('morph-outliner-edit-set.png')
        event('ESC')

    def open_member():
        layout = str(data['member_controls'])
        for op in ('edit_morph_member', 'outliner_select', 'toggle_visibility', 'set_pivot_custom'):
            assert 'proteinblender.' + op in layout
        assert 'row_color' in layout
        assert 'Keyframe visibility' not in layout
        with g['ui_override']():
            assert bpy.ops.proteinblender.edit_morph_member('INVOKE_DEFAULT',
                item_id=data['member']) == {'RUNNING_MODAL'}

    def edit_member():
        dialog = visual_edit.active_dialog()
        assert dialog.item_id == data['member'] and dialog.new_name == 'Chain A'
        assert dialog.vs_style == get_object_style(output())
        layout = str(data['PROTEINBLENDER_OT_edit_morph_member'])
        assert 'Representation' in layout and 'Color' in layout
        assert 'Add Morph' not in layout
        dialog.new_name = 'Animated chain'
        dialog.vs_style = 'spheres'
        dialog.vs_color = (.2,.6,.1,1)
        g['redraw_all_panels']()

    def verify_live():
        assert get_object_style(output()) == 'spheres'
        np.testing.assert_allclose(get_object_color(output()), (.2,.6,.1,1), atol=1e-6)
        screenshot('morph-outliner-edit-chain.png')
        event('RET')

    def select_and_hide():
        row = next(r for r in scene().outliner_items if r.item_id == data['member'])
        assert row.name == 'Animated chain'
        row.is_selected = False
        assert bpy.ops.proteinblender.outliner_select(item_id=data['member']) == {'FINISHED'}
        assert output().select_get() and bpy.context.view_layer.objects.active == output()
        data['keys'] = C.keyframes(scene())
        assert bpy.ops.proteinblender.toggle_visibility(item_id=data['member']) == {'FINISHED'}
        scene().frame_set(25)

    def prepare_swatch():
        next(r for r in scene().outliner_items if r.item_id == data['member']).row_color = (0,0,1,1)
        g['redraw_all_panels']()

    def click_swatch():
        image = bpy.data.images.load(screenshot('morph-chain-swatch.png'), check_existing=False)
        w,h = image.size
        pixels = np.array(image.pixels[:]).reshape(h,w,4)
        bpy.data.images.remove(image)
        area = g['protein_workspace_panel_area']()
        mask = np.max(np.abs(pixels[:,area.x:area.x+area.width,:3]-(0,0,1)), axis=2) < .15
        ys = np.flatnonzero(mask.sum(axis=1) >= 10)
        assert len(ys), 'The chain color swatch was not visible'
        band = np.split(ys, np.flatnonzero(np.diff(ys) > 1)+1)[0]
        y = round(float(np.median(band)))
        x = area.x + round(float(np.median(np.flatnonzero(mask[y]))))
        data['pivot_button'] = (round(x+20*bpy.context.preferences.system.ui_scale), y)
        event('MOUSEMOVE', 'NOTHING', x=x, y=y)
        event('LEFTMOUSE', x=x, y=y)

    def edit_swatch():
        screenshot('morph-chain-color-picker.png')
        color = (.1,.3,.8,1)
        next(r for r in scene().outliner_items if r.item_id == data['member']).row_color = color
        np.testing.assert_allclose(get_object_color(output()), color, atol=1e-6)
        event('ESC')

    def click_pivot():
        x,y = data['pivot_button']
        event('MOUSEMOVE', 'NOTHING', x=x, y=y)
        event('LEFTMOUSE', x=x, y=y)

    def move_pivot():
        from proteinblender.operators.pivot_operators import PIVOT_HELPER, pivot_edit_key
        assert pivot_edit_key(scene()) == data['member']
        helper = bpy.data.objects[PIVOT_HELPER]
        assert helper.select_get() and bpy.context.view_layer.objects.active == helper
        data['atoms'] = g['H'].evaluated_atom_positions([output()])
        assert len(data['atoms']) > 500
        helper.location.x += .12
        helper.location.y -= .08
        bpy.context.view_layer.update()
        data['pivot'] = tuple(helper.matrix_world.translation)
        screenshot('morph-chain-pivot.png')

    def verify_pivot():
        from proteinblender.operators.pivot_operators import pivot_edit_key
        assert not pivot_edit_key(scene())
        np.testing.assert_allclose(output().matrix_world.translation, data['pivot'], atol=1e-6)
        np.testing.assert_allclose(g['H'].evaluated_atom_positions([output()]), data['atoms'], atol=1e-6)
        C.insert_keys(bpy.context, 75, {morph()[C.MORPH]: {
            'state': C.states(morph())[7]['uid'], 'visible': [True]}})
        np.testing.assert_allclose(output().matrix_world.translation, data['pivot'], atol=1e-6)
        np.testing.assert_allclose(get_object_color(output()), (.1,.3,.8,1), atol=1e-6)

    def show_and_finish():
        assert output().hide_viewport and output().hide_render
        assert bpy.ops.proteinblender.toggle_visibility(item_id=data['member']) == {'FINISHED'}
        assert not output().hide_viewport and not output().hide_render
        assert C.records(morph())[0]['object'].hide_get(), 'The hidden source must not appear too'
        assert data['keys'] == C.keyframes(scene())
        for cls, original in data['draws']:
            cls.draw = original
        List.draw_item = data['original_item_draw']
        bpy.types.UI_MT_list_item_context_menu.remove(data['menu_observer'])
        return 'Morphset context menu, chain swatch, pivot placement, styling, selection and eye verified'

    steps = []
    for name, function in [('prepare',prepare), ('right click',right_click), ('inspect menu',inspect_menu),
            ('open root editor',open_root), ('inspect root editor',inspect_root),
            ('open chain editor',open_member), ('edit chain',edit_member), ('verify live appearance',verify_live),
            ('prepare swatch',prepare_swatch), ('click chain swatch',click_swatch), ('edit chain swatch',edit_swatch),
            ('click pivot button',click_pivot), ('move pivot',move_pivot), ('apply pivot button',click_pivot),
            ('verify pivot and new key',verify_pivot),
            ('select and hide',select_and_hide), ('show and finish',show_and_finish)]:
        steps += [('Morphset Outliner '+name, function), ('settle Morphset Outliner',lambda: None)]
    return steps
