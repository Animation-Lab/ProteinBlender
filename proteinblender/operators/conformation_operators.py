"""Contextual alignment and playback dialogs; no additional permanent panel."""
import json
import time

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, StringProperty)
from bpy.types import Operator

from ..core import conformation as core
from ..core import structural_alignment as alignment
from ..utils.scene_manager import ProteinBlenderScene

_enum_strings = {}
_playing = None
_creation_dialog = None


def _stable(items):
    # Blender retains pointers to strings returned by dynamic enum callbacks.
    key = tuple(items)
    return _enum_strings.setdefault(key, list(items))


def _molecules(self, context):
    return _stable([(mid, mol.object.get('pb_conformation_name', getattr(mol, 'name', mol.identifier)), 'Protein conformation')
                    for mid, mol in ProteinBlenderScene.get_instance().molecules.items()
                    if not mol.object.get('pb_is_nucleic_acid')])


def _chains(identifier):
    molecule = ProteinBlenderScene.get_instance().molecules.get(identifier)
    items = [('ALL', 'Whole protein', 'Match protein chains by sequence', 0)]
    if molecule:
        try:
            chains = alignment.protein_chains(alignment.read_identity(molecule))
            items += [(chain, f'Chain {chain or "(blank)"} · {len(residues)} residues',
                       'Use this protein chain', i + 1)
                      for i, (chain, residues) in enumerate(chains.items())]
        except ValueError:
            pass
    return _stable(items)


def _source_chains(self, context):
    return _chains(self.source_id)


def _target_chains(self, context):
    return _chains(self.target_id)


def _summary(layout, summary):
    box = layout.box()
    box.label(text='Residue match', icon='CHECKMARK')
    pairs = summary['mapping']
    for i in range(0, len(pairs), 5):
        box.label(text='Chains: ' + ', '.join(pairs[i:i + 5]))
    box.label(text=f"{summary['residues']} paired residues · {summary['identity']:.0%} sequence identity")
    box.label(text=f"Coverage: {summary['residues']}/{summary['source_residues']} start, "
                   f"{summary['residues']}/{summary['target_residues']} end")
    if summary.get('fit') == 'NONE':
        box.label(text='Current object placement; no superposition applied')
    else:
        box.label(text=f"Fit RMSD: {summary['fit_rmsd']:.2f} Å ({summary['fit_residues']} Cα pairs)")
    box.label(text=f"All paired Cα RMSD: {summary['rmsd']:.2f} Å")
    box.label(text=f"Playback: {summary['atoms']} shared atoms; unpaired atoms omitted")


class PROTEINBLENDER_OT_create_conformation(Operator):
    """Align two protein conformations and create an animated transition"""
    bl_idname = 'proteinblender.create_conformation'
    bl_label = 'Align & Morph'
    bl_options = {'REGISTER', 'UNDO'}

    source_id: EnumProperty(name='Start structure', items=_molecules)
    target_id: EnumProperty(name='End structure', items=_molecules)
    source_chain: EnumProperty(name='Start chain', items=_source_chains, default=0)
    target_chain: EnumProperty(name='End chain', items=_target_chains, default=0)
    fit: EnumProperty(name='Superpose using', items=[
        ('CORE', 'Stable core', 'Iteratively exclude distant Cα pairs from the fit, retaining at least half'),
        ('ALL', 'All paired residues', 'Fit every sequence-paired Cα equally'),
        ('REGION', 'Chosen anchor region', 'Keep a chosen matched region stationary'),
        ('NONE', 'Current placement', 'Use the current object placement without superposition')], default='CORE')
    source_region: StringProperty(name='Start residues', description='Empty for all; e.g. 1-40,65-76 on one chain or A:1-40,B:10-50')
    target_region: StringProperty(name='End residues', description='Empty for all; inclusive residue ranges')
    fit_region: StringProperty(name='Anchor residues', description='Matched start residues used for fitting, e.g. A:1-30')
    chain_pairs: StringProperty(name='Chain pairing', description='Empty for automatic; explicit pairs such as A:B,C:D')
    start_frame: IntProperty(name='Start frame', default=1, min=1, max=1_000_000)
    duration: FloatProperty(name='Duration (seconds)', default=3.0, min=.1, max=3600, options={'HIDDEN'})
    end_frame: IntProperty(name='End frame', default=73, min=2, max=1_000_000)
    show_context: BoolProperty(name='Show surrounding regions', default=True)
    context_opacity: FloatProperty(name='Surrounding opacity', default=.18, min=0, max=1, subtype='FACTOR')
    return_to_start: BoolProperty(name='Return to start', default=False)
    return_frame: IntProperty(name='Return frame', default=145, min=3, max=2_000_000)
    repeat: BoolProperty(name='Repeat breathing cycle', default=False)
    smooth: BoolProperty(name='Ease in and out', default=True,
                         description='Smooth the timing at the endpoints')

    def _analyze(self):
        self._match, self._problem = None, ''
        molecules = ProteinBlenderScene.get_instance().molecules
        try:
            source, target = molecules.get(self.source_id), molecules.get(self.target_id)
            if source is None or target is None:
                raise ValueError('Import two protein structures to compare their conformations.')
            self._match = alignment.match_structures(
                source, target, self.source_chain, self.target_chain, self.fit,
                source_region=self.source_region, target_region=self.target_region,
                fit_region=self.fit_region, chain_pairs=self.chain_pairs)
        except ValueError as exc:
            self._problem = str(exc)

    def invoke(self, context, event):
        global _creation_dialog
        _creation_dialog = self
        self._preview_id = ''
        self._preview_frame = context.scene.frame_current
        self._preview_end = context.scene.frame_end
        self._preview_dirty = False
        self._interactive = True
        items = _molecules(self, context)
        identifiers = [item[0] for item in items]
        if not self.properties.is_property_set('source_id') and identifiers:
            selected = [r.item_id for r in context.scene.outliner_items
                        if r.item_type == 'PROTEIN' and r.is_selected and r.item_id in identifiers]
            self.source_id = selected[0] if selected else identifiers[0]
        if not self.properties.is_property_set('target_id'):
            others = [mid for mid in identifiers if mid != self.source_id]
            if others:
                self.target_id = others[0]
        if not self.properties.is_property_set('start_frame'):
            self.start_frame = max(1, context.scene.frame_current)
        if not self.properties.is_property_set('end_frame'):
            self.end_frame = self.start_frame + 72
        if not self.properties.is_property_set('return_frame'):
            self.return_frame = self.end_frame + self.end_frame - self.start_frame
        self._last_proteins = (self.source_id, self.target_id)
        self._analyze()
        return context.window_manager.invoke_props_dialog(self, width=540, confirm_text='Create Morph')

    def check(self, context):
        if not self.return_to_start:
            self.repeat = False
        proteins = (self.source_id, self.target_id)
        if proteins != getattr(self, '_last_proteins', proteins):
            self.source_chain = self.target_chain = 'ALL'
        self._last_proteins = proteins
        self._preview_dirty = bool(getattr(self, '_preview_id', ''))
        self._analyze()
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text='Compare two conformations of a protein', icon='IPO_EASE_IN_OUT')
        layout.prop(self, 'source_id')
        layout.prop(self, 'source_chain', text='Include')
        layout.prop(self, 'source_region')
        layout.prop(self, 'target_id')
        layout.prop(self, 'target_chain', text='Include')
        layout.prop(self, 'target_region')
        if self.source_chain == self.target_chain == 'ALL':
            layout.prop(self, 'chain_pairs')
        layout.prop(self, 'fit')
        if self.fit == 'REGION':
            layout.prop(self, 'fit_region')
        if getattr(self, '_match', None):
            _summary(layout, self._match.summary)
        elif getattr(self, '_problem', ''):
            box = layout.box()
            box.alert = True
            # Break long actionable errors without relying on Blender wrapping.
            import textwrap
            for line in textwrap.wrap(self._problem, 70):
                box.label(text=line, icon='INFO')
        row = layout.row(align=True)
        row.prop(self, 'start_frame')
        row.prop(self, 'end_frame')
        layout.prop(self, 'return_to_start')
        if self.return_to_start:
            layout.prop(self, 'return_frame')
            layout.prop(self, 'repeat')
        layout.prop(self, 'smooth')
        layout.prop(self, 'show_context')
        if self.show_context:
            layout.prop(self, 'context_opacity', slider=True)
        preview = layout.row()
        preview.enabled = getattr(self, '_match', None) is not None
        preview.operator('proteinblender.preview_conformation_alignment', text='Update Preview' if getattr(self, '_preview_dirty', False) else 'Preview Regions and Alignment', icon='HIDE_OFF')
        layout.label(text='Blue: morphing atoms. Transparent gray: surrounding regions.')
        layout.label(text='The starting structure defines the reference frame.')
        layout.label(text='Interpolated motion; intermediate geometry may be distorted.', icon='INFO')

    def execute(self, context):
        global _creation_dialog
        if _creation_dialog is self:
            _creation_dialog = None
        self._clear_preview(context)
        self._analyze()
        if self._match is None:
            self.report({'WARNING'}, self._problem)
            return {'CANCELLED'}
        molecules = ProteinBlenderScene.get_instance().molecules
        try:
            obj = core.create(context, molecules[self.source_id], molecules[self.target_id],
                              self._match, self.start_frame, self.duration, self.smooth,
                              show_context=self.show_context, context_opacity=self.context_opacity,
                              **_timing(self, context))
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        context.scene.frame_set(self.start_frame)
        self.report({'INFO'}, 'Transition created. Its Outliner pencil opens playback.')
        if getattr(self, '_interactive', False) and not bpy.app.background:
            identifier = obj[core.TAG]
            def open_playback():
                if core.find(bpy.context.scene, identifier):
                    bpy.ops.proteinblender.edit_conformation('INVOKE_DEFAULT', transition_id=identifier)
                return None
            bpy.app.timers.register(open_playback, first_interval=.1)
        return {'FINISHED'}

    def _clear_preview(self, context):
        identifier = getattr(self, '_preview_id', '')
        obj = core.find(context.scene, identifier) if identifier else None
        if obj:
            core.remove(context, obj)
            context.scene.frame_end = self._preview_end
        self._preview_id = ''

    def cancel(self, context):
        global _creation_dialog
        self._clear_preview(context)
        context.scene.frame_set(getattr(self, '_preview_frame', context.scene.frame_current))
        _creation_dialog = None


class PROTEINBLENDER_OT_preview_conformation_alignment(Operator):
    """Preview the selected morph regions without committing a morph"""
    bl_idname = 'proteinblender.preview_conformation_alignment'
    bl_label = 'Preview Regions and Alignment'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        dialog = _creation_dialog
        if dialog is None:
            return {'CANCELLED'}
        dialog._clear_preview(context)
        dialog._analyze()
        if dialog._match is None:
            self.report({'WARNING'}, dialog._problem)
            return {'CANCELLED'}
        molecules = ProteinBlenderScene.get_instance().molecules
        try:
            obj = core.create(context, molecules[dialog.source_id], molecules[dialog.target_id],
                              dialog._match, dialog.start_frame, dialog.duration, dialog.smooth,
                              show_context=dialog.show_context, context_opacity=dialog.context_opacity,
                              **_timing(dialog, context))
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        dialog._preview_id = obj[core.TAG]
        dialog._preview_dirty = False
        context.scene.frame_set(obj['pb_start_frame'])
        return {'FINISHED'}


def _timing(operator, context, obj=None):
    supplied = operator.properties.is_property_set
    if supplied('duration') and not supplied('end_frame'):
        end = operator.start_frame + max(1, round(operator.duration * context.scene.render.fps / context.scene.render.fps_base))
    elif obj is not None and not supplied('end_frame'):
        end = obj['pb_end_frame']
    else:
        end = operator.end_frame
    result = dict(end=end)
    for name, default in (('return_to_start', False), ('return_frame', end + end - operator.start_frame), ('repeat', False)):
        result[name] = (getattr(operator, name) if supplied(name) else
                        obj.get('pb_' + name, default) if obj is not None else default)
    return result


def _progress(self):
    scene = bpy.context.scene
    obj = core.find(scene, self.transition_id)
    if obj is None:
        return 0.0
    return float(obj.data.shape_keys.key_blocks['End conformation'].value)


def _scrub(self, value):
    stop_playback()
    scene = bpy.context.scene
    obj = core.find(scene, self.transition_id)
    if obj:
        frame = obj['pb_start_frame'] + value * (obj['pb_end_frame'] - obj['pb_start_frame'])
        scene.frame_set(round(frame))


def stop_playback():
    global _playing
    _playing = None


def _tick():
    global _playing
    if _playing is None:
        return None
    identifier, scene, started = _playing
    try:
        if scene != bpy.context.scene:
            stop_playback()
            return None
        obj = core.find(scene, identifier)
        if obj is None:
            stop_playback()
            return None
        end = obj.get('pb_return_frame', obj['pb_end_frame']) if obj.get('pb_return_to_start') else obj['pb_end_frame']
        frames = end - obj['pb_start_frame']
        elapsed = (time.monotonic() - started) * scene.render.fps / scene.render.fps_base
        if obj.get('pb_repeat'):
            offset = elapsed % frames
        else:
            offset = min(elapsed, frames)
            if elapsed >= frames:
                stop_playback()
        scene.frame_set(obj['pb_start_frame'] + round(offset))
        if bpy.context.screen:
            for area in bpy.context.screen.areas:
                area.tag_redraw()
    except (ReferenceError, RuntimeError):
        stop_playback()
        return None
    return 1 / 30


class PROTEINBLENDER_OT_conformation_preview(Operator):
    """Preview this transition without changing the scene's animation range"""
    bl_idname = 'proteinblender.conformation_preview'
    bl_label = 'Preview Transition'
    transition_id: StringProperty()
    action: EnumProperty(items=[('PLAY', 'Play / Pause', ''), ('START', 'Start', ''), ('END', 'End', '')])

    def execute(self, context):
        global _playing
        obj = core.find(context.scene, self.transition_id)
        if obj is None:
            return {'CANCELLED'}
        was_playing = _playing is not None and _playing[0] == self.transition_id
        stop_playback()
        if self.action == 'PLAY' and not was_playing:
            offset = context.scene.frame_current - obj['pb_start_frame']
            end = obj.get('pb_return_frame') if obj.get('pb_return_to_start') else obj['pb_end_frame']
            if not 0 <= offset < end - obj['pb_start_frame']:
                offset = 0
            _playing = (self.transition_id, context.scene,
                        time.monotonic() - offset / (context.scene.render.fps / context.scene.render.fps_base))
            if not bpy.app.timers.is_registered(_tick):
                bpy.app.timers.register(_tick, first_interval=.01)
        elif self.action != 'PLAY':
            context.scene.frame_set(obj['pb_start_frame' if self.action == 'START' else 'pb_end_frame'])
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_conformation(Operator):
    """Scrub the conformational transition, preview playback, or change its timing"""
    bl_idname = 'proteinblender.edit_conformation'
    bl_label = 'Conformational Transition'
    bl_options = {'REGISTER', 'UNDO'}
    transition_id: StringProperty()
    progress: FloatProperty(name='Start → End', min=0, max=1, subtype='FACTOR',
                            get=_progress, set=_scrub)
    start_frame: IntProperty(name='Start frame', min=1, max=1_000_000, default=1)
    duration: FloatProperty(name='Duration (seconds)', min=.1, max=3600, default=3, options={'HIDDEN'})
    end_frame: IntProperty(name='End frame', default=73, min=2, max=1_000_000)
    show_context: BoolProperty(name='Show surrounding regions', default=True)
    context_opacity: FloatProperty(name='Surrounding opacity', default=.18, min=0, max=1, subtype='FACTOR')
    return_to_start: BoolProperty(name='Return to start', default=False)
    return_frame: IntProperty(name='Return frame', default=145, min=3, max=2_000_000)
    repeat: BoolProperty(name='Repeat breathing cycle', default=False)
    smooth: BoolProperty(name='Ease in and out', default=True)
    hide_originals: BoolProperty(name='Hide original structures', default=True,
                                description='Restore their previous visibility when unchecked')
    show_details: BoolProperty(name='Match details', default=False, options={'SKIP_SAVE'})
    style: EnumProperty(name='Representation', items=[('cartoon', 'Cartoon', ''),
                         ('surface', 'Surface', 'Molecular surface of the changing conformation'),
                         ('spheres', 'Spheres', ''), ('ball_and_stick', 'Ball and stick', '')])
    color: FloatVectorProperty(name='Color', subtype='COLOR', size=4,
                               min=0, max=1, default=(.25, .65, .9, 1.0))

    def invoke(self, context, event):
        obj = core.find(context.scene, self.transition_id)
        if obj is None:
            return {'CANCELLED'}
        from ..core.cartoon_motion import stabilize
        stabilize(obj)
        self._old_frame = context.scene.frame_current
        self.start_frame, self.duration = obj['pb_start_frame'], obj['pb_duration']
        self.end_frame = obj['pb_end_frame']
        self.return_to_start = obj.get('pb_return_to_start', False)
        self.return_frame = obj.get('pb_return_frame', self.end_frame + self.end_frame - self.start_frame)
        self.repeat = obj.get('pb_repeat', False)
        self.smooth = obj['pb_smooth']
        self.show_context = obj.get('pb_show_context', True)
        self.context_opacity = obj.get('pb_context_opacity', .18)
        self.hide_originals = obj['pb_hide_originals']
        self.style = obj['pb_transition_style']
        from ..core.visual_style import get_object_color
        self.color = get_object_color(obj)
        return context.window_manager.invoke_props_dialog(self, width=540, confirm_text='Done')

    def check(self, context):
        if not self.return_to_start:
            self.repeat = False
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        obj = core.find(context.scene, self.transition_id)
        if obj is None:
            layout.label(text='This transition was removed.')
            return
        layout.label(text=obj.name, icon='IPO_EASE_IN_OUT')
        # The actual keyed value follows playback even while the popup is open.
        frame = context.scene.frame_current
        layout.label(text=f"Frame {frame} · {obj['pb_start_frame']}–{obj['pb_end_frame']}")
        layout.prop(self, 'progress', slider=True)
        row = layout.row(align=True)
        for action, label, icon in [('START', 'Start', 'REW'), ('PLAY', 'Pause' if _playing else 'Play',
                                    'PAUSE' if _playing else 'PLAY'), ('END', 'End', 'FF')]:
            op = row.operator('proteinblender.conformation_preview', text=label, icon=icon)
            op.transition_id, op.action = self.transition_id, action
        row = layout.row(align=True)
        row.prop(self, 'start_frame')
        row.prop(self, 'end_frame')
        layout.prop(self, 'return_to_start')
        if self.return_to_start:
            layout.prop(self, 'return_frame')
            layout.prop(self, 'repeat')
        layout.prop(self, 'smooth')
        layout.prop(self, 'show_context')
        if self.show_context:
            layout.prop(self, 'context_opacity', slider=True)
        layout.prop(self, 'style')
        layout.prop(self, 'color')
        layout.prop(self, 'hide_originals')
        layout.prop(self, 'show_details', icon='TRIA_DOWN' if self.show_details else 'TRIA_RIGHT', emboss=False)
        if self.show_details:
            _summary(layout, json.loads(obj['pb_match']))
        layout.label(text='Illustrative interpolation between imported conformations.', icon='INFO')

    def execute(self, context):
        stop_playback()
        obj = core.find(context.scene, self.transition_id)
        if obj is None:
            return {'CANCELLED'}
        try:
            if not self.properties.is_property_set('start_frame'):
                self.start_frame = obj['pb_start_frame']
            core.set_timing(obj, self.start_frame, self.duration,
                            self.smooth if self.properties.is_property_set('smooth') else obj['pb_smooth'],
                            **_timing(self, context, obj))
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        supplied = self.properties.is_property_set
        core.source_visibility(obj, self.hide_originals if supplied('hide_originals') else obj['pb_hide_originals'])
        from ..core import morph_context
        morph_context.set_visible(obj,
            self.show_context if supplied('show_context') else obj.get('pb_show_context', True),
            self.context_opacity if supplied('context_opacity') else obj.get('pb_context_opacity', .18))
        if supplied('style') and obj['pb_transition_style'] != self.style:
            from ..core.visual_style import apply_style_to_object
            apply_style_to_object(obj, self.style)
            obj['pb_transition_style'] = self.style
        from ..core.cartoon_motion import stabilize
        stabilize(obj)
        from ..core.visual_style import apply_color_to_object
        if supplied('color'):
            apply_color_to_object(obj, self.color)
        core.rebuild_outliner(context)
        return {'FINISHED'}

    def cancel(self, context):
        stop_playback()
        context.scene.frame_set(getattr(self, '_old_frame', context.scene.frame_current))


class PROTEINBLENDER_OT_delete_conformation(Operator):
    """Remove this transition and restore original structure visibility"""
    bl_idname = 'proteinblender.delete_conformation'
    bl_label = 'Delete Transition'
    bl_options = {'REGISTER', 'UNDO'}
    transition_id: StringProperty()

    def execute(self, context):
        obj = core.find(context.scene, self.transition_id)
        if obj is None:
            return {'CANCELLED'}
        stop_playback()
        core.remove(context, obj)
        return {'FINISHED'}


class PROTEINBLENDER_OT_capture_conformation(Operator):
    """Capture the current chain/domain pose as a new, independent conformation"""
    bl_idname = 'proteinblender.capture_conformation'
    bl_label = 'Capture Conformation'
    bl_options = {'REGISTER', 'UNDO'}
    source_id: EnumProperty(name='Protein', items=_molecules)
    name: StringProperty(name='Conformation name', default='New Conformation')

    def invoke(self, context, event):
        identifiers = [item[0] for item in _molecules(self, context)]
        if not identifiers:
            self.report({'WARNING'}, 'Import a protein before capturing a conformation.')
            return {'CANCELLED'}
        if not self.properties.is_property_set('source_id'):
            selected = [r.item_id for r in context.scene.outliner_items
                        if r.item_type == 'PROTEIN' and r.is_selected and r.item_id in identifiers]
            self.source_id = selected[0] if selected else identifiers[0]
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        self.layout.prop(self, 'source_id')
        self.layout.prop(self, 'name')
        self.layout.label(text='Capture the protein at the current frame.')

    def execute(self, context):
        from ..core.conformation_capture import capture
        molecule = ProteinBlenderScene.get_instance().molecules.get(self.source_id)
        if molecule is None or not self.name.strip():
            self.report({'WARNING'}, 'Choose a protein and enter a conformation name.')
            return {'CANCELLED'}
        try:
            capture(context, molecule, self.name.strip())
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Conformation captured. Choose it as an endpoint in Align & Morph.')
        return {'FINISHED'}


CLASSES = [PROTEINBLENDER_OT_preview_conformation_alignment, PROTEINBLENDER_OT_capture_conformation, PROTEINBLENDER_OT_create_conformation, PROTEINBLENDER_OT_conformation_preview,
           PROTEINBLENDER_OT_edit_conformation, PROTEINBLENDER_OT_delete_conformation]
