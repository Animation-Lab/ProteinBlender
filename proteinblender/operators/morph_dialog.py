"""One contextual interface for protein states, morph preview, and editing."""
import json

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from . import conformation_operators as actions
from . import conformation_library as browsing
from ..core import conformation as core
from ..core import conformation_library as library_core
from ..utils.scene_manager import ProteinBlenderScene

MATCH_FIELDS = ('source_id', 'target_id', 'source_state', 'target_state',
                'source_chain', 'target_chain', 'source_region', 'target_region',
                'chain_pairs', 'fit', 'fit_region')
EDIT_FIELDS = ('start_frame', 'end_frame', 'return_to_start', 'return_frame', 'repeat',
               'smooth', 'show_context', 'context_opacity', 'hide_originals', 'style', 'color')


def _key(identifier, uid=''):
    return json.dumps([identifier, uid], separators=(',', ':'))


def _endpoints(self, context):
    items = []
    for mid, label, _ in actions._molecules(self, context):
        mol = ProteinBlenderScene.get_instance().molecules[mid]
        states = mol.object.pb_conformations.states
        items.append((_key(mid), label + (' · Current structure' if len(states) > 1 else ''),
                      'Use the currently displayed coordinates', len(items)))
        if len(states) > 1:
            for state in states:
                items.append((_key(mid, state.uid), f'{label} · {state.name}', state.source, len(items)))
    return actions._stable(items or [('NONE', 'Import a protein first', '', 0)])


def _draw_playback(layout, dialog, obj):
    if obj is None:
        return
    box = layout.box()
    box.label(text=f'Frame {bpy.context.scene.frame_current}', icon='TIME')
    box.prop(dialog, 'progress', text='From → To', slider=True)
    row = box.row(align=True)
    for action, label, icon in [('START', 'From', 'REW'),
                               ('PLAY', 'Pause' if actions._playing else 'Play',
                                'PAUSE' if actions._playing else 'PLAY'), ('END', 'To', 'FF')]:
        op = row.operator('proteinblender.conformation_preview', text=label, icon=icon)
        op.transition_id, op.action = obj[core.TAG], action


class PROTEINBLENDER_OT_morph(Operator):
    """Choose conformations, preview their motion, or edit a saved morph"""
    bl_idname = 'proteinblender.morph'
    bl_label = 'Morph'
    bl_options = {'REGISTER', 'UNDO'}
    __annotations__ = {**actions.PROTEINBLENDER_OT_create_conformation.__annotations__,
                       **actions.PROTEINBLENDER_OT_edit_conformation.__annotations__}
    source_pick: EnumProperty(name='From', items=_endpoints)
    target_pick: EnumProperty(name='To', items=_endpoints)
    advanced: BoolProperty(name='Advanced', options={'SKIP_SAVE'})
    library_tools: BoolProperty(name='Library tools', options={'SKIP_SAVE'})
    show_comparison: BoolProperty(name='Show transparent reference')
    highlight_motion: BoolProperty(name='Highlight motion (Cα markers)')
    opacity: browsing.PROTEINBLENDER_OT_apply_conformation_view.__annotations__['opacity']
    motion_threshold: browsing.PROTEINBLENDER_OT_apply_conformation_view.__annotations__['motion_threshold']

    _analyze = actions.PROTEINBLENDER_OT_create_conformation._analyze
    _labels = actions.PROTEINBLENDER_OT_create_conformation._labels

    def invoke(self, context, event):
        self._editing = bool(self.transition_id)
        self._preview_id = ''
        self._preview_frame = context.scene.frame_current
        self._preview_end = context.scene.frame_end
        self._preview_signature = None
        self._browser_id = ''
        self._match, self._problem = None, ''
        self._interactive = True
        self._preview_dirty = False
        actions.stop_playback()
        if self._editing:
            obj = core.find(context.scene, self.transition_id)
            if obj is None:
                self.report({'WARNING'}, 'This morph is no longer available.')
                return {'CANCELLED'}
            self._load(obj)
        else:
            self._choose_endpoints(context)
            self._analyze()
            if not self.properties.is_property_set('start_frame'):
                self.start_frame = max(1, context.scene.frame_current)
            if not self.properties.is_property_set('end_frame'):
                self.end_frame = self.start_frame + 72
            if not self.properties.is_property_set('return_frame'):
                self.return_frame = self.end_frame + self.end_frame - self.start_frame
        self._last_match_input = self._match_input() if not self._editing else None
        actions._creation_dialog = self
        return context.window_manager.invoke_props_dialog(
            self, width=440, confirm_text='Done' if self._editing else 'Create Morph')

    def _load(self, obj):
        self.start_frame, self.end_frame = obj['pb_start_frame'], obj['pb_end_frame']
        self.return_to_start = obj.get('pb_return_to_start', False)
        self.return_frame = obj.get('pb_return_frame', self.end_frame * 2 - self.start_frame)
        self.repeat, self.smooth = obj.get('pb_repeat', False), obj['pb_smooth']
        self.show_context = obj.get('pb_show_context', True)
        self.context_opacity = obj.get('pb_context_opacity', .18)
        self.hide_originals = obj['pb_hide_originals']
        self.style = obj['pb_transition_style']
        from ..core.visual_style import get_object_color
        from ..core.cartoon_motion import stabilize
        self.color = get_object_color(obj)
        stabilize(obj)

    def _choose_endpoints(self, context):
        molecules = ProteinBlenderScene.get_instance().molecules
        identifiers = [item[0] for item in actions._molecules(self, context)]
        if not identifiers:
            return
        if not self.properties.is_property_set('source_id'):
            selected = [r.item_id for r in context.scene.outliner_items
                        if r.item_type == 'PROTEIN' and r.is_selected and r.item_id in identifiers]
            self.source_id = selected[0] if selected else identifiers[0]
        mol = molecules[self.source_id]
        lib = mol.object.pb_conformations
        if len(lib.states) > 1 and not self.properties.is_property_set('source_state'):
            self.source_state = lib.states[lib.active_index].uid
        if not self.properties.is_property_set('target_id'):
            others = [mid for mid in identifiers if mid != self.source_id]
            self.target_id = self.source_id if len(lib.states) > 1 or not others else others[0]
        target = molecules[self.target_id].object.pb_conformations
        if len(target.states) > 1 and not self.properties.is_property_set('target_state'):
            self.target_state = target.end_uid
            if self.source_id == self.target_id and self.target_state == self.source_state:
                self.target_state = next(s.uid for s in target.states if s.uid != self.source_state)
        if not self.properties.is_property_set('source_pick'):
            self.source_pick = _key(self.source_id, self.source_state)
        if not self.properties.is_property_set('target_pick'):
            self.target_pick = _key(self.target_id, self.target_state)
        self._sync_picks()

    def _sync_picks(self):
        for side in ('source', 'target'):
            value = getattr(self, side + '_pick')
            if value == 'NONE':
                continue
            identifier, uid = json.loads(value)
            previous = getattr(self, side + '_id')
            if identifier != previous:
                setattr(self, side + '_chain', 'ALL')
                setattr(self, side + '_region', '')
                self.chain_pairs = ''
            setattr(self, side + '_id', identifier)
            setattr(self, side + '_state', uid)
        if self.source_chain != 'ALL' or self.target_chain != 'ALL':
            self.chain_pairs = ''

    def _match_input(self):
        return tuple(getattr(self, field) for field in MATCH_FIELDS)

    def _signature(self):
        return self._match_input() + tuple(tuple(self.color) if field == 'color' else getattr(self, field)
                                           for field in EDIT_FIELDS)

    def check(self, context):
        if not self.return_to_start:
            self.repeat = False
        if not self._editing:
            self._sync_picks()
            if self._match_input() != self._last_match_input:
                self._analyze()
                self._last_match_input = self._match_input()
            self._preview_dirty = bool(self._preview_id and self._signature() != self._preview_signature)
        return True

    def _clear_preview(self, context):
        actions.stop_playback()
        obj = core.find(context.scene, getattr(self, '_preview_id', ''))
        if obj:
            core.remove(context, obj)
            context.scene.frame_end = self._preview_end
        if getattr(self, '_preview_id', ''):
            self.transition_id = ''
        self._preview_id = ''

    def _clear_comparison(self, context):
        if self._browser_id:
            browsing._close_browser(context, self._browser_id)
            self._browser_id = ''

    def apply(self, context):
        if self._editing:
            return bpy.ops.proteinblender.edit_conformation(
                'EXEC_DEFAULT', transition_id=self.transition_id,
                **{field: tuple(self.color) if field == 'color' else getattr(self, field)
                   for field in EDIT_FIELDS})
        self._sync_picks()
        self._analyze()
        try:
            if self._match is None:
                raise ValueError(self._problem)
            if self.end_frame <= self.start_frame:
                raise ValueError('End frame must be after start frame.')
            if self.return_to_start and self.return_frame <= self.end_frame:
                raise ValueError('Return frame must be after end frame.')
            old = core.find(context.scene, self._preview_id)
            progress = actions._progress(self) if old else 0
            molecules = ProteinBlenderScene.get_instance().molecules
            # Build the replacement first. A rejected Apply keeps the last
            # valid preview, original visibility ownership, and playback range.
            obj = core.create(context, molecules[self.source_id], molecules[self.target_id],
                              self._match, self.start_frame, smooth=self.smooth,
                              show_context=self.show_context, context_opacity=self.context_opacity,
                              **self._labels(), **actions._timing(self, context))
            if old:
                core.remove(context, old)
            context.scene.frame_end = max(
                self._preview_end,
                self.return_frame if self.return_to_start else self.end_frame)
            self.transition_id = self._preview_id = obj[core.TAG]
            actions.PROTEINBLENDER_OT_edit_conformation.execute(self, context)
            self._clear_comparison(context)
            context.scene.frame_set(round(self.start_frame + progress * (self.end_frame - self.start_frame)))
            self._preview_signature = self._signature()
            self._preview_dirty = False
            self._problem = ''
        except ValueError as exc:
            self._problem = str(exc)
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}

    def show_state(self, context, side):
        self._sync_picks()
        mid, uid = getattr(self, side + '_id'), getattr(self, side + '_state')
        if not uid:
            return {'CANCELLED'}
        self._clear_preview(context)
        self._clear_comparison(context)
        lib = browsing.molecule(mid).object.pb_conformations
        same_protein = self.source_id == self.target_id
        reference = self.source_state if same_protein else ''
        target = self.target_state if same_protein else ''
        result = bpy.ops.proteinblender.apply_conformation_view(
            molecule_id=mid, state_uid=uid, target_uid=target or lib.end_uid,
            reference_uid=reference or lib.reference_uid, fit=self.fit, fit_region=self.fit_region,
            show_comparison=self.show_comparison, highlight_motion=self.highlight_motion,
            opacity=self.opacity, motion_threshold=self.motion_threshold)
        if result == {'FINISHED'}:
            self._browser_id = mid
            context.scene.pb_conformation_browser = mid
        return result

    def execute(self, context):
        if not getattr(self, '_interactive', False):
            # The same public entry point also supports scripts and regression tests.
            if self.properties.is_property_set('source_pick') or self.properties.is_property_set('target_pick'):
                self._sync_picks()
            cls = (actions.PROTEINBLENDER_OT_edit_conformation if self.transition_id
                   else actions.PROTEINBLENDER_OT_create_conformation)
            args = {name: getattr(self, name) for name in cls.__annotations__
                    if self.properties.is_property_set(name)}
            operator = bpy.ops.proteinblender.edit_conformation if self.transition_id else bpy.ops.proteinblender.create_conformation
            return operator('EXEC_DEFAULT', **args)
        if self._editing:
            result = self.apply(context)
        else:
            self.check(context)
            result = ({'FINISHED'} if self._preview_id and self._signature() == self._preview_signature
                      else self.apply(context))
            if result == {'FINISHED'}:
                self._preview_id = ''  # Promote the preview; no duplicate geometry or second popup.
        self._finish(context, restore_frame=result == {'CANCELLED'})
        return result

    def _finish(self, context, restore_frame):
        self._clear_preview(context)
        self._clear_comparison(context)
        if restore_frame:
            context.scene.frame_set(self._preview_frame)
        if actions._creation_dialog == self:
            actions._creation_dialog = None

    def cancel(self, context):
        self._finish(context, restore_frame=True)

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        obj = core.find(context.scene, self.transition_id)
        if self._editing:
            if obj is None:
                layout.label(text='This morph is no longer available.', icon='ERROR')
                return
            layout.label(text=obj.name, icon='IPO_EASE_IN_OUT')
            layout.label(text='From: ' + obj.get('pb_start_label', 'Stored start'))
            layout.label(text='To: ' + obj.get('pb_end_label', 'Stored end'))
        else:
            for side, label in [('source', 'From'), ('target', 'To')]:
                row = layout.row(align=True)
                row.prop(self, side + '_pick', text=label)
                if getattr(self, side + '_state'):
                    op = row.operator('proteinblender.morph_action', text='', icon='HIDE_OFF')
                    op.action = 'SHOW_FROM' if side == 'source' else 'SHOW_TO'
        row = layout.row(align=True)
        row.prop(self, 'start_frame')
        row.prop(self, 'end_frame')
        layout.prop(self, 'return_to_start')
        if self.return_to_start:
            row = layout.row(align=True)
            row.prop(self, 'return_frame')
            row.prop(self, 'repeat', text='Repeat')
        row = layout.row()
        row.enabled = self._editing or self._match is not None
        row.operator('proteinblender.morph_action', text='Apply', icon='CHECKMARK').action = 'APPLY'
        _draw_playback(layout, self, obj)
        if self._preview_dirty:
            layout.label(text='Settings changed. Apply to update the preview.', icon='INFO')
        elif not self._editing and obj is None:
            layout.label(text='Apply to preview the motion here.')
        if self._problem:
            import textwrap
            for line in textwrap.wrap(self._problem, 58):
                layout.label(text=line, icon='INFO')
        layout.prop(self, 'advanced', icon='TRIA_DOWN' if self.advanced else 'TRIA_RIGHT', emboss=False)
        if self.advanced:
            self._draw_advanced(layout.box(), context, obj)

    def _draw_advanced(self, box, context, obj):
        if not self._editing:
            row = box.row(align=True)
            row.prop(self, 'source_chain', text='From chain')
            row.prop(self, 'target_chain', text='To chain')
            box.prop(self, 'source_region', text='From residues')
            box.prop(self, 'target_region', text='To residues')
            if self.source_chain == self.target_chain == 'ALL':
                box.prop(self, 'chain_pairs')
            box.prop(self, 'fit', text='Alignment')
            if self.fit == 'REGION':
                box.prop(self, 'fit_region')
        box.prop(self, 'smooth')
        box.prop(self, 'show_context')
        if self.show_context:
            box.prop(self, 'context_opacity', slider=True)
        box.prop(self, 'style')
        box.prop(self, 'color')
        box.prop(self, 'hide_originals')
        summary = json.loads(obj['pb_match']) if self._editing and obj else self._match.summary if self._match else None
        if summary:
            box.prop(self, 'show_details', icon='TRIA_DOWN' if self.show_details else 'TRIA_RIGHT', emboss=False)
            if self.show_details:
                actions._summary(box, summary)
        if not self._editing and self.source_state and self.source_id == self.target_id:
            box.label(text='Compare states with the eye buttons:')
            box.prop(self, 'show_comparison')
            if self.show_comparison:
                box.prop(self, 'opacity', slider=True)
            box.prop(self, 'highlight_motion')
            if self.highlight_motion:
                box.prop(self, 'motion_threshold')
        if not self._editing:
            box.prop(self, 'library_tools', icon='TRIA_DOWN' if self.library_tools else 'TRIA_RIGHT', emboss=False)
            if self.library_tools:
                self._draw_library(box.box())
        box.label(text='Morphs interpolate between the selected structures.', icon='INFO')

    def _draw_library(self, box):
        mol = ProteinBlenderScene.get_instance().molecules.get(self.source_id)
        if mol is None:
            return
        lib = mol.object.pb_conformations
        selected = next((s for s in lib.states if s.uid == self.source_state), None)
        box.label(text=f'From: {mol.identifier}')
        if selected:
            box.prop(selected, 'name')
            box.label(text=selected.source)
        if 'NMR' in lib.method:
            box.label(text='Model order does not define motion.', icon='INFO')
        row = box.row(align=True)
        row.operator_context = 'INVOKE_DEFAULT'
        row.operator('proteinblender.add_conformation_file', text='Add from File…').molecule_id = mol.identifier
        row.operator('proteinblender.add_conformation_pdb', text='Add from PDB…').molecule_id = mol.identifier
        box.label(text='From the displayed protein pose:')
        row = box.row(align=True)
        row.operator_context = 'INVOKE_DEFAULT'
        row.operator('proteinblender.capture_library_conformation', text='Capture Pose…').molecule_id = mol.identifier
        row.operator('proteinblender.extract_library_conformation', text='Extract as Protein').molecule_id = mol.identifier


class PROTEINBLENDER_OT_morph_action(Operator):
    """Apply the morph settings or show a selected conformation without closing"""
    bl_idname = 'proteinblender.morph_action'
    bl_label = 'Update Morph'
    bl_options = {'INTERNAL'}
    action: EnumProperty(items=[('APPLY', 'Apply', 'Update the preview without closing'),
                                ('SHOW_FROM', 'Show From conformation', 'Show the From state on its protein without creating a morph'),
                                ('SHOW_TO', 'Show To conformation', 'Show the To state on its protein without creating a morph')])

    @classmethod
    def description(cls, context, properties):
        return {'APPLY': 'Apply settings and preview the motion in this popup',
                'SHOW_FROM': 'Show the From conformation on its protein without creating a morph',
                'SHOW_TO': 'Show the To conformation on its protein without creating a morph'}.get(properties.action, '')

    def execute(self, context):
        dialog = actions._creation_dialog
        if dialog is None:
            return {'CANCELLED'}
        if self.action == 'APPLY':
            return dialog.apply(context)
        return dialog.show_state(context, 'source' if self.action == 'SHOW_FROM' else 'target')


CLASSES = [PROTEINBLENDER_OT_morph, PROTEINBLENDER_OT_morph_action]
