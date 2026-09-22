"""Shared real-dialog scenarios for the imported-model Morphset workflow."""
from pathlib import Path

import bpy
import numpy as np


def build_steps(g):
    from proteinblender.core import morphsets as C, model_morphsets as Models
    from proteinblender.operators import morphset_operators as M
    from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as K
    from proteinblender.dna_builder.dna_panel import PROTEINBLENDER_PT_builders
    from proteinblender.panels.animation_panel import PROTEINBLENDER_PT_animation
    H, state = g['H'], g['state']
    data = {}

    def key_event(kind='RET'):
        window = g['active_window']()
        window.event_simulate(type=kind, value='PRESS')
        window.event_simulate(type=kind, value='RELEASE')

    def redraw():
        popup = data.get('popup')
        if popup:
            popup.tag_redraw()
        for area in g['active_window']().screen.areas:
            area.tag_redraw()
        data['mouse_tick'] = data.get('mouse_tick', 0) + 1
        scale = bpy.context.preferences.system.ui_scale
        g['active_window']().event_simulate(type='MOUSEMOVE', value='NOTHING',
            x=round((35 + data['mouse_tick'] % 2 * 10) * scale), y=round(100 * scale))

    def capture(name):
        bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / name))

    def prepare():
        H.reset_scene()
        mid = H.import_local('1d3z.pdb.gz', '1D3Z')
        state['morphset_mid'] = mid
        data['complex'] = H.import_local('2bbn.pdb.gz', 'Complex')
        data['single'] = H.import_local('1ubq.pdb', 'Single model')
        assert bpy.ops.proteinblender.edit_protein_visuals(item_id=mid, vs_style='cartoon') == {'FINISHED'}
        for row in bpy.context.scene.outliner_items:
            row.is_selected = row.item_type == 'CHAIN' and row.parent_id == mid
        data['draws'], data['originals'] = {}, []
        def observe(cls):
            original = cls.draw
            def draw(self, context):
                original(self, context)
                data['draws'][cls.__name__] = self.layout.introspect()
                if cls in (K, M.PROTEINBLENDER_OT_create_morphset, M.PROTEINBLENDER_OT_edit_morphset):
                    data['popup'] = getattr(context, 'region_popup', None)
            data['originals'].append((cls, original))
            cls.draw = draw
        for cls in [M.PROTEINBLENDER_OT_create_morphset, M.PROTEINBLENDER_OT_edit_morphset,
                    K, PROTEINBLENDER_PT_builders, PROTEINBLENDER_PT_animation]:
            observe(cls)
        redraw()
        return 'Imported 1D3Z; selected its chain in the PB Outliner'

    def create():
        builders = str(data['draws']['PROTEINBLENDER_PT_builders'])
        assert builders.index('Create New Assembly') < builders.index('Create Morphset')
        animation = str(data['draws']['PROTEINBLENDER_PT_animation'])
        assert 'proteinblender.create_morphset' not in animation
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_morphset('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def inspect_create():
        dialog = M.PROTEINBLENDER_OT_create_morphset._active_instance
        assert dialog and dialog.source == state['morphset_mid']
        assert len(dialog.members) == 1 and dialog.members[0].selected
        layout = str(data['draws']['PROTEINBLENDER_OT_create_morphset'])
        assert '10 imported models available' in layout
        assert all(label not in layout for label in ['Add Morph', 'Start', 'End'])
        dialog.source = data['complex']
        assert len(dialog.members) == 2, 'Changing protein must update the member list'
        assert all(m.selected for m in dialog.members)

    def single_model():
        dialog = M.PROTEINBLENDER_OT_create_morphset._active_instance
        dialog.source = data['single']
        assert len(dialog.members) == 1
        assert dialog.members[0].member_id in H.sm().molecules[data['single']].domains
        from proteinblender.core.model_morphsets import selection
        try:
            selection(bpy.context, dialog.source, [m.member_id for m in dialog.members])
        except ValueError as exc:
            assert 'Only one conformation' in str(exc)
        else:
            raise AssertionError('Single model should explain why animation is unavailable')
        dialog.source = state['morphset_mid']
        assert len(dialog.members) == 1 and dialog.members[0].selected
        assert dialog.members[0].member_id in H.sm().molecules[state['morphset_mid']].domains
        dialog.name = 'Ubiquitin conformations'
        capture('create-morphset.png')
        data.pop('popup', None)
        key_event()

    def verify_created():
        for mid in (data['complex'], data['single']):
            assert bpy.ops.molecule.delete(molecule_id=mid) == {'FINISHED'}
        root = C.sets(bpy.context.scene)[0]
        morph = Models.subject(root)
        data['root'], data['uid'] = root[C.TAG], morph[C.MORPH]
        state['morph_ids'] = [data['uid']]
        assert len(C.states(morph)) == 10 and len(C.morphs(bpy.context.scene)) == 1
        row = next(r for r in bpy.context.scene.outliner_items if r.item_id == root[C.TAG])
        assert row.parent_id == state['morphset_mid'] and row.indent_level == 1
        child = next(r for r in bpy.context.scene.outliner_items if r.item_type == 'MORPH_MEMBER')
        assert child.parent_id == root[C.TAG] and child.name == 'Chain A'
        data['points'] = [C._coordinates(s['members'][0]['mesh']) for s in C.states(morph)]
        return 'One Morphset under 1D3Z, one chain child, all ten models, no predefined transitions'

    def open_key(frame):
        bpy.context.scene.frame_set(frame)
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def choose(frame, model):
        dialog = K._active_instance
        assert dialog and dialog.frame_number == frame and len(dialog.morph_items) == 1
        row = dialog.morph_items[0]
        assert not row.use_morph
        row.state = C.states(C.find(bpy.context.scene, data['uid']))[model-1]['uid']
        popup = data['popup']
        scale = bpy.context.preferences.system.ui_scale
        x, y = round(popup.x + 32*scale), round(popup.y + 75*scale)
        window = g['active_window']()
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
        window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)

    def confirm_key(frame):
        assert K._active_instance.morph_items[0].use_morph, 'Actual checkbox click must enable the Morphset'
        layout = str(data['draws'][K.__name__])
        assert 'Ubiquitin conformations' in layout
        capture(f'keyframe-{frame}.png')
        if frame == 75:
            assert 'Previous key: Model 3 at frame 50' in layout, (layout, C.keyframes(bpy.context.scene))
            assert 'Next key: Model 9 at frame 100' in layout
        data.pop('popup', None)
        key_event()

    def verify_geometry():
        scene = bpy.context.scene
        assert sorted(map(int, C.keyframes(scene))) == [1, 50, 75, 100]
        assert len(C.outputs(scene)) == 1
        obj = C.outputs(scene)[0]
        p = data['points']
        for frame, expected in [(1,p[0]),(50,p[2]),(60,p[2]*.6+p[7]*.4),
                                (75,p[7]),(100,p[8]),(120,p[8])]:
            scene.frame_set(frame)
            assert len(H.eval_positions(obj)) > 0
            enabled = [m.show_viewport for m in obj.modifiers]
            for m in obj.modifiers:
                m.show_viewport = False
            bpy.context.view_layer.update()
            np.testing.assert_allclose(H.eval_positions(obj), expected, atol=1e-6)
            for m, value in zip(obj.modifiers, enabled):
                m.show_viewport = value
        scene.frame_set(1)
        return 'One visible chain: Models 1/3/8/9 at 1/50/75/100; Model 3 → 8 bridge verified atom by atom'

    def open_edit():
        with g['ui_override']():
            assert bpy.ops.proteinblender.edit_morphset('INVOKE_DEFAULT', morphset_id=data['root']) == {'RUNNING_MODAL'}

    def inspect_edit():
        dialog = M.PROTEINBLENDER_OT_edit_morphset._active_instance
        assert len(dialog.members) == 1 and dialog.members[0].selected
        layout = str(data['draws'][M.PROTEINBLENDER_OT_edit_morphset.__name__])
        assert 'Add Morph' not in layout and '10 imported models available' in layout
        dialog.name = 'Ubiquitin models'
        capture('edit-morphset.png')
        data.pop('popup', None)
        key_event()

    def remove():
        with g['ui_override']('VIEW_3D'):
            bpy.ops.ed.undo_push(message='Animated model Morphset')
        assert bpy.ops.proteinblender.delete_morphset(morphset_id=data['root']) == {'FINISHED'}
        assert not C.sets(bpy.context.scene) and not C.outputs(bpy.context.scene)
        assert any(r.item_type == 'CHAIN' and r.parent_id == state['morphset_mid'] for r in bpy.context.scene.outliner_items)
        with g['ui_override']('VIEW_3D'):
            bpy.ops.ed.undo_push(message='Removed model Morphset')

    def undo():
        with g['ui_override']('VIEW_3D'):
            assert bpy.ops.ed.undo() == {'FINISHED'}

    def frame_example():
        verify_geometry()
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 100
        obj = C.outputs(scene)[0]
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        scene.pb_keyframe_filter_by_selection = False
        with g['ui_override']('VIEW_3D'):
            bpy.ops.view3d.view_selected(use_all_regions=False)

    def save():
        capture('morphset-keyframes.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(g['report_path']).parent/'1d3z-model-keyframes.blend'))
        for cls, original in data['originals']:
            cls.draw = original
        return 'Saved 1D3Z example after removal/Undo and geometry revalidation'

    steps = [('prepare Morphset builder', prepare), ('redraw builder', redraw),
             ('Create Morphset', create), ('settle create', redraw),
             ('inspect and switch to two-chain protein', inspect_create), ('settle switched protein', redraw),
             ('verify single-model eligibility and restore 1D3Z', single_model), ('settle create confirmation', redraw),
             ('verify hierarchy and imported models', verify_created)]
    # Deliberately insert the middle key last to expose neighbor context.
    for frame, model in [(1,1),(50,3),(100,9),(75,8)]:
        steps += [(f'open keyframe {frame}', lambda frame=frame: open_key(frame)),
                  ('settle keyframe', redraw),
                  (f'choose Model {model}', lambda frame=frame, model=model: choose(frame,model)),
                  ('redraw model selection', redraw),
                  (f'confirm keyframe {frame}', lambda frame=frame: confirm_key(frame)),
                  ('settle keyframe confirmation', redraw)]
    steps += [('verify interpolation', verify_geometry), ('open membership editor', open_edit),
              ('redraw membership editor', redraw), ('inspect and rename Morphset', inspect_edit),
              ('settle membership editor', redraw), ('remove Morphset', remove),
              ('settle removal', redraw), ('Undo removal', undo), ('settle Undo', redraw),
              ('verify Undo and frame example', frame_example), ('settle viewport', redraw),
              ('save model keyframes example', save)]
    return steps
