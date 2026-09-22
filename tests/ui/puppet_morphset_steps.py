"""Real puppet dialogs, nested Morphset controls, keys and undo/redo."""
from pathlib import Path
import bpy
import numpy as np


def build_steps(g):
    from proteinblender.core import morphsets as C, model_morphsets as M
    from proteinblender.panels.group_maker_panel import (
        PROTEINBLENDER_OT_create_puppet as Create, PROTEINBLENDER_OT_edit_puppet as Edit)
    from proteinblender.panels.protein_outliner_panel import PROTEINBLENDER_UL_outliner as List
    from proteinblender.operators.keyframe_operators import PROTEINBLENDER_OT_create_keyframe as Key
    from proteinblender.operators.morphset_operators import PROTEINBLENDER_OT_edit_morphset as MorphEdit
    from proteinblender.panels.pose_library_panel import PROTEINBLENDER_OT_create_pose as Pose
    H, data = g['H'], {}

    def event(kind='RET'):
        for value in ('PRESS', 'RELEASE'):
            g['active_window']().event_simulate(type=kind, value=value)

    def root():
        return C.find(bpy.context.scene, data['root'])

    def morph():
        return M.subject(root())

    def row(uid):
        return next(r for r in bpy.context.scene.outliner_items if r.item_id == uid)

    def controller():
        return bpy.data.objects[row(data['pid']).controller_object_name]

    def capture(name):
        bpy.ops.screen.screenshot(filepath=str(Path(g['report_path']).parent / name))

    def prepare():
        H.reset_scene()
        mid = H.import_local('1d3z.pdb.gz', '1D3Z')
        companion = H.import_local('1ubq.pdb', 'Companion')
        data['chain'] = next(r.item_id for r in bpy.context.scene.outliner_items
                             if r.item_type == 'CHAIN' and r.parent_id == companion)
        assert bpy.ops.proteinblender.create_morphset(source=mid, name='Ubiquitin models') == {'FINISHED'}
        data['root'] = C.sets(bpy.context.scene)[0][C.TAG]
        data['originals'] = []
        def observe(cls):
            original = cls.draw
            def draw(self, context):
                original(self, context)
                data[cls.__name__] = self
                data[cls.__name__ + '_layout'] = self.layout.introspect()
            data['originals'].append((cls, original))
            cls.draw = draw
        for cls in (Create, Edit, Key, MorphEdit, Pose):
            observe(cls)
        for item in bpy.context.scene.outliner_items:
            item.is_selected = item.item_id == data['root']
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_puppet('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def create():
        dialog = data[Create.__name__]
        assert 'Creating puppet from 1 items' in str(data[Create.__name__ + '_layout'])
        dialog.puppet_name = 'Animated complex'
        capture('create-puppet-morphset.png')
        event()

    def created():
        data['pid'] = next(r.item_id for r in bpy.context.scene.outliner_items
                           if r.item_type == 'PUPPET' and r.name == 'Animated complex')
        assert root().parent == controller()
        bpy.context.scene.frame_set(1)
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def first_key():
        dialog = data[Key.__name__]
        assert len(dialog.morph_items) == 1 and len(dialog.puppet_items) == 1
        dialog.frame_number = 1
        dialog.puppet_items[0].use_puppet = True
        dialog.puppet_items[0].keyframe_color = False
        dialog.morph_items[0].use_morph = True
        dialog.morph_items[0].state = C.states(morph())[0]['uid']
        capture('puppet-and-model-keyframe.png')
        event()

    def next_key():
        assert '1' in C.keyframes(bpy.context.scene)
        bpy.context.scene.frame_set(45)
        controller().location.x += 2
        bpy.context.view_layer.update()
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def second_key():
        dialog = data[Key.__name__]
        dialog.frame_number = 45
        dialog.puppet_items[0].use_puppet = True
        dialog.puppet_items[0].keyframe_color = False
        dialog.morph_items[0].use_morph = True
        dialog.morph_items[0].state = C.states(morph())[3]['uid']
        event()

    def edit():
        bpy.context.scene.frame_set(23)
        data['atoms'] = H.evaluated_atom_positions(C.outputs(bpy.context.scene))
        assert len(data['atoms']) > 500
        with g['ui_override']():
            assert bpy.ops.proteinblender.edit_puppet('INVOKE_DEFAULT',
                action='EDIT', puppet_id=data['pid']) == {'RUNNING_MODAL'}

    def inspect_edit():
        dialog = data[Edit.__name__]
        choices = {s['item_id']: s for s in dialog.item_selections}
        assert set(choices) == {data['root'], data['chain']}
        assert choices[data['root']]['is_selected'] and not choices[data['root']]['reason']
        choices[data['chain']]['is_selected'] = True
        capture('edit-puppet-members.png')
        event()

    def added():
        assert set(row(data['pid']).puppet_memberships.split(',')) == {data['root'], data['chain']}
        assert bpy.data.objects[row(data['chain']).object_name].parent == controller()
        np.testing.assert_allclose(H.evaluated_atom_positions(C.outputs(bpy.context.scene)), data['atoms'], atol=1e-6)
        with g['ui_override']():
            assert bpy.ops.ed.undo() == {'FINISHED'}

    def undo():
        assert row(data['pid']).puppet_memberships == data['root']
        assert root().parent == controller()
        with g['ui_override']():
            assert bpy.ops.ed.redo() == {'FINISHED'}

    def redo():
        assert data['chain'] in row(data['pid']).puppet_memberships
        assert root().parent == controller()
        ref = row(data['pid'] + '_ref_' + data['root'])
        ref.is_expanded = True
        data['controls'] = {}
        original = List.draw_item
        def draw(self, context, layout, source, item, icon, active, prop):
            original(self, context, layout, source, item, icon, active, prop)
            if item.reference_target_id:
                data['controls'][item.item_id] = layout.introspect()
        data['list_draw'] = original
        List.draw_item = draw
        g['redraw_all_panels']()

    def reference_controls():
        ref_id = data['pid'] + '_ref_' + data['root']
        layout = str(data['controls'][ref_id])
        assert 'proteinblender.edit_morphset' in layout and data['root'] in layout
        member = next(r for r in bpy.context.scene.outliner_items if r.parent_id == ref_id)
        controls = str(data['controls'][member.item_id])
        for name in ('edit_morph_member', 'set_pivot_custom', 'outliner_select', 'toggle_visibility'):
            assert 'proteinblender.' + name in controls
        assert member.reference_target_id in controls
        capture('puppet-morphset-outliner.png')
        with g['ui_override']():
            assert bpy.ops.proteinblender.edit_morphset('INVOKE_DEFAULT', morphset_id=data['root']) == {'RUNNING_MODAL'}

    def inspect_morph():
        dialog = data[MorphEdit.__name__]
        assert dialog.name == 'Ubiquitin models'
        assert len(dialog.members) == 1 and dialog.members[0].selected and not dialog.members[0].reason
        event('ESC')

    def visibility():
        assert bpy.ops.proteinblender.toggle_visibility(item_id=data['pid']) == {'FINISHED'}
        bpy.context.scene.frame_set(30)
        assert all(o.hide_render for o in C.outputs(bpy.context.scene))
        assert bpy.ops.proteinblender.toggle_visibility(item_id=data['pid']) == {'FINISHED'}
        assert all(not o.hide_render for o in C.outputs(bpy.context.scene))
        data['pose_atoms'] = H.evaluated_atom_positions(C.outputs(bpy.context.scene))
        with g['ui_override']():
            assert bpy.ops.proteinblender.create_pose('INVOKE_DEFAULT') == {'RUNNING_MODAL'}

    def capture_pose():
        dialog = data[Pose.__name__]
        assert dialog.selected_puppets[data['pid']]
        dialog.pose_name = 'Morphset arrangement'
        event()

    def apply_pose():
        pose = bpy.context.scene.pose_library[-1]
        assert root().name in {t.object_name for t in pose.transforms}
        assert all(not t.object_name.startswith(morph().name + ' · ') for t in pose.transforms)
        # Rebuilding model output must not invalidate the saved component pose.
        C.insert_keys(bpy.context, 90, {morph()[C.MORPH]: {
            'state': C.states(morph())[7]['uid'], 'visible': [True]}})
        controller().location.y += 1
        root().location.x += .4
        bpy.context.view_layer.update()
        assert bpy.ops.proteinblender.apply_pose(pose_index=len(bpy.context.scene.pose_library) - 1) == {'FINISHED'}
        np.testing.assert_allclose(H.evaluated_atom_positions(C.outputs(bpy.context.scene)), data['pose_atoms'], atol=1e-6)
        path = Path(g['report_path']).parent / 'puppet-model-animation.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        for cls, draw in data['originals']:
            cls.draw = draw
        List.draw_item = data['list_draw']

    return [(f.__name__, f) for f in (prepare, create, created, first_key, next_key,
        second_key, edit, inspect_edit, added, undo, redo, reference_controls,
        inspect_morph, visibility, capture_pose, apply_pose)]
