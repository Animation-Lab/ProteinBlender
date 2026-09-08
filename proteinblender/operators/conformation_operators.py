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


def _stable(items):
    # Blender retains pointers to strings returned by dynamic enum callbacks.
    key = tuple(items)
    return _enum_strings.setdefault(key, list(items))


def _molecules(self, context):
    return _stable([(mid, getattr(mol, 'name', mol.identifier), 'Imported protein conformation')
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
    box.label(text=f"Fit RMSD: {summary['fit_rmsd']:.2f} Å ({summary['fit_residues']} Cα pairs)")
    box.label(text=f"All paired Cα RMSD: {summary['rmsd']:.2f} Å")
    box.label(text=f"Playback: {summary['atoms']} shared atoms; unpaired atoms omitted")


class PROTEINBLENDER_OT_create_conformation(Operator):
    """Align two protein conformations and create an animated transition"""
    bl_idname = 'proteinblender.create_conformation'
    bl_label = 'Align & Animate'
    bl_options = {'REGISTER', 'UNDO'}

    source_id: EnumProperty(name='Start structure', items=_molecules)
    target_id: EnumProperty(name='End structure', items=_molecules)
    source_chain: EnumProperty(name='Start chain', items=_source_chains, default=0)
    target_chain: EnumProperty(name='End chain', items=_target_chains, default=0)
    fit: EnumProperty(name='Superpose using', items=[
        ('CORE', 'Stable core', 'Iteratively exclude distant Cα pairs from the fit, retaining at least half'),
        ('ALL', 'All paired residues', 'Fit every sequence-paired Cα equally')], default='CORE')
    start_frame: IntProperty(name='Start frame', default=1, min=1, max=1_000_000)
    duration: FloatProperty(name='Duration (seconds)', default=3.0, min=.1, max=3600)
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
                source, target, self.source_chain, self.target_chain, self.fit)
        except ValueError as exc:
            self._problem = str(exc)

    def invoke(self, context, event):
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
        self._last_proteins = (self.source_id, self.target_id)
        self._analyze()
        return context.window_manager.invoke_props_dialog(self, width=540, confirm_text='Create Transition')

    def check(self, context):
        proteins = (self.source_id, self.target_id)
        if proteins != getattr(self, '_last_proteins', proteins):
            self.source_chain = self.target_chain = 'ALL'
        self._last_proteins = proteins
        self._analyze()
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text='Compare two conformations of a protein', icon='IPO_EASE_IN_OUT')
        layout.prop(self, 'source_id')
        layout.prop(self, 'source_chain', text='Include')
        layout.prop(self, 'target_id')
        layout.prop(self, 'target_chain', text='Include')
        layout.prop(self, 'fit')
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
        row.prop(self, 'duration')
        layout.prop(self, 'smooth')
        layout.label(text='Uses imported conformations, with the start structure held fixed.')
        layout.label(text='Interpolated motion; intermediate geometry may be distorted.', icon='INFO')

    def execute(self, context):
        self._analyze()
        if self._match is None:
            self.report({'WARNING'}, self._problem)
            return {'CANCELLED'}
        molecules = ProteinBlenderScene.get_instance().molecules
        obj = core.create(context, molecules[self.source_id], molecules[self.target_id],
                          self._match, self.start_frame, self.duration, self.smooth)
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


def _progress(self):
    scene = bpy.context.scene
    obj = core.find(scene, self.transition_id)
    if obj is None:
        return 0.0
    return min(1.0, max(0.0, (scene.frame_current - obj['pb_start_frame']) /
                       (obj['pb_end_frame'] - obj['pb_start_frame'])))


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
        frames = obj['pb_end_frame'] - obj['pb_start_frame']
        elapsed = (time.monotonic() - started) * scene.render.fps / scene.render.fps_base
        # Ping-pong preview makes the endpoints easy to compare, without
        # changing the user's scene range or native animation playback state.
        phase = elapsed % (2 * frames)
        offset = phase if phase <= frames else 2 * frames - phase
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
            if not 0 <= offset <= obj['pb_end_frame'] - obj['pb_start_frame']:
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
    duration: FloatProperty(name='Duration (seconds)', min=.1, max=3600, default=3)
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
        self.progress = min(1, max(0, (self._old_frame - obj['pb_start_frame']) /
                                  (obj['pb_end_frame'] - obj['pb_start_frame'])))
        self.start_frame, self.duration = obj['pb_start_frame'], obj['pb_duration']
        self.smooth = obj['pb_smooth']
        self.hide_originals = obj['pb_hide_originals']
        self.style = obj['pb_transition_style']
        from ..core.visual_style import get_object_color
        self.color = get_object_color(obj)
        return context.window_manager.invoke_props_dialog(self, width=540, confirm_text='Done')

    def check(self, context):
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
        row.prop(self, 'duration')
        layout.prop(self, 'smooth')
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
        core.set_timing(obj, self.start_frame, self.duration, self.smooth)
        core.source_visibility(obj, self.hide_originals)
        if obj['pb_transition_style'] != self.style:
            from ..core.visual_style import apply_style_to_object
            apply_style_to_object(obj, self.style)
            obj['pb_transition_style'] = self.style
        from ..core.cartoon_motion import stabilize
        stabilize(obj)
        from ..core.visual_style import apply_color_to_object
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


CLASSES = [PROTEINBLENDER_OT_create_conformation, PROTEINBLENDER_OT_conformation_preview,
           PROTEINBLENDER_OT_edit_conformation, PROTEINBLENDER_OT_delete_conformation]
