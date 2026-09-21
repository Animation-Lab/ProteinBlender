"""Conformation creation and editing; legacy morph operators for saved scripts."""
import json

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from ..core import morphsets, conformation_sets

_ENUM_CACHE = {}


def _stable(key, values):
    # Blender keeps pointers to dynamic enum strings across redraws.
    return _ENUM_CACHE.setdefault((key, tuple(values)), values)


def source_items(self, context):
    from ..utils.scene_manager import ProteinBlenderScene
    values = [('SELECTED', 'Selected chains / domains', 'Use checked PB Outliner rows', 0)]
    for mid, mol in ProteinBlenderScene.get_instance().molecules.items():
        if mol.object.get('pb_is_nucleic_acid'):
            continue
        values.append((mid, getattr(mol, 'name', mid) + ' · all chains', 'All protein domains', len(values)))
        for did, domain in mol.domains.items():
            values.append((did, getattr(mol, 'name', mid) + ' · ' + domain.object.name, 'One chain or domain', len(values)))
    return _stable('sources', values)


def _models(source):
    from ..core.outliner_targets import resolve_target
    mol, _ = resolve_target(source)
    return _stable('models', [('CURRENT', 'Current structure', 'Use current atom coordinates', 0)] +
        ([(s.uid, s.name, 'Imported PDB model', i + 1)
          for i, s in enumerate(mol.object.pb_conformations.states)] if mol else []))


def start_models(self, context):
    return _source_models(context, self.source, getattr(self, 'member_ids', ''))


def end_models(self, context):
    same = self.end_source == 'SAME'
    return _source_models(context, self.source if same else self.end_source,
                          self.member_ids if same else self.end_member_ids)


def end_sources(self, context):
    return _stable('end_sources', [('SAME', 'Same members as Start', '', 0)] +
                   [(a, b, c, i + 1) for i, (a, b, c, _) in enumerate(source_items(self, context))])


def reset_start(self, context):
    if hasattr(self, 'member_ids'):
        self.member_ids = ''
    self.model = 'CURRENT'
    if hasattr(self, 'end_model'):
        self.end_model = 'CURRENT'


def reset_end(self, context):
    self.end_member_ids = ''
    self.end_model = 'CURRENT'


def _source_objects(source):
    from ..core.outliner_targets import resolve_target
    mol, objects = resolve_target(source, include_protein_domains=True)
    if mol and source == mol.identifier:
        objects = [d.object for d in mol.domains.values() if d.object]
    return objects


def _unused_source(context, source):
    objects = _source_objects(source)
    puppets = {r.controller_object_name for r in context.scene.outliner_items
               if r.item_type == 'PUPPET' and r.controller_object_name}
    return bool(objects) and all(not obj.get('pb_morphset_owner') and
                                not (obj.parent and obj.parent.name in puppets)
                                for obj in objects)


def _available_source(context, source):
    objects = _source_objects(source)
    puppets = {r.controller_object_name for r in context.scene.outliner_items
               if r.item_type == 'PUPPET' and r.controller_object_name}
    return bool(objects) and not any(obj.parent and obj.parent.name in puppets for obj in objects)


def _ids(context, source, encoded=''):
    if encoded:
        return json.loads(encoded)
    if source != 'SELECTED':
        return [source]
    selected = []
    for row in context.scene.outliner_items:
        if not row.is_selected:
            continue
        if row.item_type in {'PROTEIN', 'CHAIN', 'DOMAIN'}:
            selected.append(row.item_id)
        elif row.item_type == 'MORPH_MEMBER':
            from ..utils.scene_manager import ProteinBlenderScene
            obj = bpy.data.objects.get(row.object_name)
            # Resolve the actual domain, since a saved row_id can refer to a
            # whole protein even when only one shared member is checked.
            for mol in ProteinBlenderScene.get_instance().molecules.values():
                selected.extend(did for did, domain in mol.domains.items() if domain.object == obj)
    return list(dict.fromkeys(selected))


def _source_models(context, source, encoded=''):
    if source != 'SELECTED':
        return _models(source)
    from ..core.outliner_targets import resolve_target
    ids = _ids(context, source, encoded)
    molecules = [resolve_target(uid)[0] for uid in ids]
    if molecules and all(m and m == molecules[0] for m in molecules):
        return _models(molecules[0].identifier)
    return _models('')


def state_sources(self, context):
    return _stable('state_sources', [('MORPH_MEMBERS', 'This Morphset’s members',
        'Use the chains/domains already defined in this state', 0)] +
        [(a, b, c, i + 1) for i, (a, b, c, _) in enumerate(source_items(self, context))])


def _state_members(self, context):
    morph = morphsets.find(context.scene, self.morph_id)
    if morph is None:
        return []
    value = morphsets.state(morph, self.state_id) if hasattr(self, 'state_id') else morphsets.states(morph)[0]
    return list(value['members']) if value else []


def _state_ids(self, context):
    if self.source == 'MORPH_MEMBERS':
        return list(dict.fromkeys(m['row_id'] for m in _state_members(self, context)))
    return _ids(context, self.source, self.member_ids)


def state_models(self, context):
    if self.source == 'MORPH_MEMBERS':
        members = _state_members(self, context)
        sources = {m.get('source') for m in members}
        items = _models(members[0]['row_id']) if len(sources) == 1 and None not in sources else _models('')
    else:
        items = _source_models(context, self.source, self.member_ids)
    if hasattr(self, 'state_id'):
        return _stable('editable_models', [('SAVED', 'Keep saved coordinates',
            'Keep the captured structure, including when its source is unavailable', 0)] +
            [(a, b, c, i + 1) for i, (a, b, c, _) in enumerate(items)])
    return items


def morph_state_items(self, context):
    morph = morphsets.find(context.scene, self.morph_id)
    values = morphsets.states(morph) if morph else []
    return _stable('morph_states', [
        (s['uid'], morphsets.state_label(s),
         'Reach this state at the keyed frame', i) for i, s in enumerate(values)
    ] or [('NONE', 'No states defined', '', 0)])


class PBMorphMemberVisibility(PropertyGroup):
    name: StringProperty()
    visible: BoolProperty(name='Visible', default=True)


class PBMorphKeyframeRow(PropertyGroup):
    morph_id: StringProperty()
    set_name: StringProperty()
    name: StringProperty()
    use_morph: BoolProperty(name='Keyframe', description='Record this subject at this frame; unchecked rows keep their existing animation')
    state: EnumProperty(name='State at this frame', items=morph_state_items)
    transition: EnumProperty(name='To next key', items=[
        ('MORPH', 'Morph', 'Interpolate atom coordinates toward the next keyed state'),
        ('HOLD', 'Hold, then switch', 'Keep this structure until the next key, then switch immediately')], default='MORPH')
    members: CollectionProperty(type=PBMorphMemberVisibility)
    show_visibility: BoolProperty(name='Visibility', default=False)
    visible: BoolProperty(name='Visible', default=True, description='Show this subject; expand for individual chains/domains')


def populate_keyframe_rows(operator, context):
    operator.morph_items.clear()
    keys = morphsets.keyframes(context.scene)
    frame = operator.frame_number
    for root in morphsets.sets(context.scene):
        for morph in morphsets.morphs(context.scene, root):
            row = operator.morph_items.add()
            row.morph_id, row.set_name, row.name = morph[morphsets.MORPH], root.name, root.name if root.get('pb_schema', 2) >= 3 else morph.name
            keyed = morphsets.morph_keys(context.scene, row.morph_id, keys)
            saved = keyed.get(str(frame))
            preceding = [f for f in keyed if int(f) <= frame]
            previous = saved or (keyed[max(preceding, key=int)] if preceding else keyed[min(keyed, key=int)] if keyed else None)
            row.use_morph = bool(saved)
            row.state = previous['state'] if previous else morphsets.states(morph)[0]['uid']
            row.transition = previous.get('transition', 'MORPH') if previous else 'MORPH'
            visibility = previous['visible'] if previous else [True] * len(morphsets.records(morph))
            row.visible = any(visibility)
            for m, visible in zip(morphsets.records(morph), visibility):
                member = row.members.add()
                member.name, member.visible = m['name'], visible
            # A wholly hidden row can be shown again without checking every member.
            if not row.visible:
                for member in row.members:
                    member.visible = True


class PROTEINBLENDER_OT_create_morphset(Operator):
    bl_idname = 'proteinblender.create_morphset'
    bl_label = 'Create Morphset'
    bl_description = 'Give a protein, chain/domain, or complex a library of states to keyframe'
    bl_options = {'REGISTER', 'UNDO'}
    _active_instance = None
    name: StringProperty(name='Name', options={'SKIP_SAVE'})
    source: EnumProperty(name='Members', items=source_items, options={'SKIP_SAVE'})
    member_ids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def check(self, context):
        return True

    def invoke(self, context, event):
        conformation_sets.upgrade(context)
        if not self.properties.is_property_set('source'):
            selected = _ids(context, 'SELECTED')
            available = [uid for uid, *_ in source_items(self, context)
                         if uid != 'SELECTED' and _available_source(context, uid)]
            self.source = 'SELECTED' if selected else next(iter(available), 'SELECTED')
        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=550)

    def draw(self, context):
        self.layout.prop(self, 'source')
        self.layout.prop(self, 'name', placeholder='Use protein name')
        ids = _ids(context, self.source, self.member_ids)
        models = _source_models(context, self.source, self.member_ids)[1:]
        self.layout.label(text=f'{len(models)} imported states will be available immediately.' if models else
                          'The current structure becomes the first state.', icon='SHAPEKEY_DATA')
        if not ids:
            self.layout.label(text='Choose a protein, or check chains/domains in the PB Outliner.', icon='INFO')
        self.layout.label(text='Members share one state choice. Set timing in Keyframes.')

    def cancel(self, context):
        type(self)._active_instance = None

    def execute(self, context):
        type(self)._active_instance = None
        # Old scripts create an empty container then call add_morph. Preserve
        # that non-UI API while the interactive path always creates a library.
        if not self.options.is_invoke and not self.properties.is_property_set('source') and not self.member_ids:
            morphsets.create(context, self.name)
            return {'FINISHED'}
        try:
            root = conformation_sets.create(context, self.name, _ids(context, self.source, self.member_ids))
        except (ValueError, KeyError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        from .conformation_browser import focus
        focus(context, root)
        self.report({'INFO'}, 'State library ready. Choose a state in Create / Edit Keyframe.')
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_morphset(Operator):
    bl_idname = 'proteinblender.edit_morphset'
    bl_label = 'Rename Morphset'
    bl_options = {'REGISTER', 'UNDO'}
    morphset_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(name='Name')

    def invoke(self, context, event):
        root = morphsets.find(context.scene, self.morphset_id)
        if root is None:
            return {'CANCELLED'}
        self.name = root.name
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        self.layout.prop(self, 'name')

    def execute(self, context):
        root = morphsets.find(context.scene, self.morphset_id)
        if root:
            root.name = self.name.strip() or root.name
            for morph in morphsets.morphs(context.scene, root):
                if root.get('pb_schema', 2) >= 3:
                    morph.name = root.name
            morphsets.rebuild(context)
        return {'FINISHED'}


class PROTEINBLENDER_OT_add_morph(Operator):
    bl_idname = 'proteinblender.add_morph'
    bl_label = 'Add Morph'
    bl_description = 'Define another transition; the same protein or chains can be used in multiple morph rows'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    _active_instance = None
    morphset_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    # Choose fresh defaults from the current selection and existing transitions
    # instead of Blender's remembered operator values.
    name: StringProperty(name='Morph name', default='Morph', options={'SKIP_SAVE'})
    source: EnumProperty(name='Members', items=source_items, update=reset_start, options={'SKIP_SAVE'})
    model: EnumProperty(name='Model / State', items=start_models, options={'SKIP_SAVE'})
    end_source: EnumProperty(name='Members', items=end_sources, update=reset_end, options={'SKIP_SAVE'})
    end_model: EnumProperty(name='Model / State', items=end_models, options={'SKIP_SAVE'})
    start_name: StringProperty(name='State name', default='Start', options={'SKIP_SAVE'})
    end_name: StringProperty(name='State name', default='End', options={'SKIP_SAVE'})
    member_ids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    end_member_ids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def check(self, context):
        return True

    def invoke(self, context, event):
        root = morphsets.find(context.scene, self.morphset_id)
        if root is None:
            self.report({'WARNING'}, 'Choose a Morphset first.')
            return {'CANCELLED'}
        if not self.properties.is_property_set('name'):
            self.name = f'Morph {len(morphsets.morphs(context.scene, root)) + 1}'
        if not self.properties.is_property_set('source'):
            selected = _ids(context, 'SELECTED')
            if selected and all(_available_source(context, uid) for uid in selected):
                self.source = 'SELECTED'
            else:
                from ..utils.scene_manager import ProteinBlenderScene
                available = [uid for uid, *_ in source_items(self, context)
                             if uid != 'SELECTED' and _available_source(context, uid)]
                unused = [uid for uid in available if _unused_source(context, uid)]
                choices = unused or available
                proteins = ProteinBlenderScene.get_instance().molecules
                self.source = next((uid for uid in choices if uid in proteins),
                                   choices[0] if choices else 'SELECTED')
            # A second transition on the same members naturally begins at the
            # previous row's End model. Independent proteins keep fresh defaults.
            selected_objects = {obj for uid in _ids(context, self.source) for obj in _source_objects(uid)}
            previous = next((m for m in reversed(morphsets.morphs(context.scene))
                             if {r.get('object') for r in morphsets.records(m)} == selected_objects), None)
            if previous:
                model = morphsets.states(previous)[-1].get('model_uid', '')
                if model and model in {item[0] for item in start_models(self, context)}:
                    self.model = self.end_model = model
        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=580)

    def draw(self, context):
        type(self)._active_instance = self
        layout = self.layout
        layout.prop(self, 'name')
        for title, source, model, name in [('Start', 'source', 'model', 'start_name'),
                                         ('End', 'end_source', 'end_model', 'end_name')]:
            box = layout.box()
            box.label(text=title)
            box.prop(self, source)
            box.prop(self, model)
            box.prop(self, name)
        layout.label(text='Use matching atoms and prepare PDB alignment before import.', icon='INFO')
        start = _ids(context, self.source, self.member_ids)
        end = start if self.end_source == 'SAME' else _ids(context, self.end_source, self.end_member_ids)
        owners = {obj.get('pb_morphset_owner') for uid in start + end
                  for obj in _source_objects(uid) if obj.get('pb_morphset_owner')}
        if owners:
            layout.label(text='These members share one animation across morph rows.', icon='INFO')
        elif self.source == 'SELECTED' and not _ids(context, self.source, self.member_ids):
            layout.label(text='Choose another protein or chain in Members.', icon='INFO')

    def cancel(self, context):
        type(self)._active_instance = None

    def execute(self, context):
        type(self)._active_instance = None
        try:
            start = _ids(context, self.source, self.member_ids)
            end = start if self.end_source == 'SAME' and not self.end_member_ids else _ids(context, self.end_source, self.end_member_ids)
            morphsets.add_morph(context, morphsets.find(context.scene, self.morphset_id), self.name,
                               start, end, '' if self.model == 'CURRENT' else self.model,
                               '' if self.end_model == 'CURRENT' else self.end_model,
                               self.start_name, self.end_name)
        except (ValueError, KeyError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_morph(Operator):
    bl_idname = 'proteinblender.edit_morph'
    bl_label = 'Edit Morph'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(name='Morph name')

    def check(self, context):
        return True

    def invoke(self, context, event):
        morph = morphsets.find(context.scene, self.morph_id)
        if not morph:
            return {'CANCELLED'}
        self.name = morph.name
        return context.window_manager.invoke_props_dialog(self, width=540)

    def draw(self, context):
        self.layout.prop(self, 'name')
        morph = morphsets.find(context.scene, self.morph_id)
        if not morph:
            return
        values = morphsets.states(morph)
        for i, value in enumerate(values):
            row = self.layout.row(align=True)
            row.label(text=f"{'Start' if i == 0 else 'End' if i == len(values)-1 else 'State'} — {morphsets.state_label(value)}")
            op = row.operator('proteinblender.edit_morph_state', text='', icon='GREASEPENCIL')
            op.morph_id, op.state_id = self.morph_id, value['uid']
            if 0 < i < len(values)-1:
                op = row.operator('proteinblender.remove_morph_state', text='', icon='REMOVE')
                op.morph_id, op.state_id = self.morph_id, value['uid']
        self.layout.operator('proteinblender.add_morph_state', text='Add Model / State', icon='ADD').morph_id = self.morph_id
        self.layout.label(text='Use the pencils to change models or names.', icon='INFO')
        self.layout.label(text='In Create Keyframe, choose the state to reach at that frame.')

    def execute(self, context):
        morph = morphsets.find(context.scene, self.morph_id)
        if morph:
            morph.name = self.name.strip() or morph.name
            morphsets.rebuild(context)
        return {'FINISHED'}


class PROTEINBLENDER_OT_add_morph_state(Operator):
    bl_idname = 'proteinblender.add_morph_state'
    bl_label = 'Add State'
    bl_description = 'Save another aligned structure as a reusable state'
    bl_options = {'REGISTER', 'UNDO'}
    _active_instance = None
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(name='State name', default='', options={'SKIP_SAVE'})
    source: EnumProperty(name='Members', items=state_sources, update=reset_start, options={'SKIP_SAVE'})
    model: EnumProperty(name='Model / State', items=state_models, options={'SKIP_SAVE'})
    member_ids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def check(self, context):
        return True

    def invoke(self, context, event):
        if morphsets.find(context.scene, self.morph_id) is None:
            return {'CANCELLED'}
        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        self.layout.prop(self, 'name')
        self.layout.prop(self, 'source')
        self.layout.prop(self, 'model')
        self.layout.label(text='Use structures with matching atoms, aligned before import.', icon='INFO')

    def cancel(self, context):
        type(self)._active_instance = None

    def execute(self, context):
        type(self)._active_instance = None
        try:
            morphsets.add_state(context, morphsets.find(context.scene, self.morph_id), self.name or next((label for uid, label, *_ in state_models(self, context) if uid == self.model), 'Structure'),
                                _state_ids(self, context), '' if self.model == 'CURRENT' else self.model)
        except (ValueError, KeyError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_edit_morph_state(Operator):
    bl_idname = 'proteinblender.edit_morph_state'
    bl_label = 'Edit State'
    bl_description = 'Change this state’s model or name while preserving the keyframes that use it'
    bl_options = {'REGISTER', 'UNDO'}
    _active_instance = None
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    state_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(name='State name', options={'SKIP_SAVE'})
    source: EnumProperty(name='Members', items=state_sources, update=reset_start, options={'SKIP_SAVE'})
    model: EnumProperty(name='Model / State', items=state_models, options={'SKIP_SAVE'})
    member_ids: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def check(self, context):
        return True

    def invoke(self, context, event):
        morph = morphsets.find(context.scene, self.morph_id)
        value = morphsets.state(morph, self.state_id) if morph else None
        if value is None:
            return {'CANCELLED'}
        self.name = value['name']
        self.source = 'MORPH_MEMBERS'
        model = value.get('model_uid', 'SAVED') or 'CURRENT'
        self.model = model if model in {item[0] for item in state_models(self, context)} else 'SAVED'
        self._original_choice = (self.source, self.model, self.member_ids)
        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        self.layout.prop(self, 'name')
        self.layout.prop(self, 'source')
        self.layout.prop(self, 'model')
        self.layout.label(text='Existing keyframes keep their times and use the updated state.', icon='KEYFRAME')

    def cancel(self, context):
        type(self)._active_instance = None

    def execute(self, context):
        type(self)._active_instance = None
        unchanged = self.model == 'SAVED' or (
            self.options.is_invoke and getattr(self, '_original_choice', None) ==
            (self.source, self.model, self.member_ids))
        try:
            morphsets.edit_state(context, morphsets.find(context.scene, self.morph_id),
                self.state_id, self.name, None if unchanged else _state_ids(self, context),
                '' if self.model == 'CURRENT' else self.model)
        except (ValueError, KeyError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_rename_morph_state(Operator):
    bl_idname = 'proteinblender.rename_morph_state'
    bl_label = 'Rename State'
    bl_options = {'REGISTER', 'UNDO'}
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    state_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(name='State name')

    def check(self, context):
        return True

    def invoke(self, context, event):
        value = morphsets.state(morphsets.find(context.scene, self.morph_id), self.state_id)
        self.name = value['name']
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        morphsets.edit_state(context, morphsets.find(context.scene, self.morph_id), self.state_id, self.name)
        return {'FINISHED'}

    def draw(self, context):
        self.layout.prop(self, 'name')


class PROTEINBLENDER_OT_remove_morph_state(Operator):
    bl_idname = 'proteinblender.remove_morph_state'
    bl_label = 'Remove State'
    bl_options = {'REGISTER', 'UNDO'}
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    state_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        try:
            morphsets.remove_state(context, morphsets.find(context.scene, self.morph_id), self.state_id)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_remove_morph(Operator):
    bl_idname = 'proteinblender.remove_morph'
    bl_label = 'Remove Morph'
    bl_description = 'Remove this morph and its keys; return members to their proteins (Undo available)'
    bl_options = {'REGISTER', 'UNDO'}
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        morph = morphsets.find(context.scene, self.morph_id)
        if morph:
            morphsets.remove_morph(context, morph)
        return {'FINISHED'}


class PROTEINBLENDER_OT_delete_morphset(Operator):
    bl_idname = 'proteinblender.delete_morphset'
    bl_label = 'Remove Morphset'
    bl_options = {'REGISTER', 'UNDO'}
    morphset_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        root = morphsets.find(context.scene, self.morphset_id)
        if root:
            morphsets.remove(context, root)
        return {'FINISHED'}


class PROTEINBLENDER_OT_remove_morph_key(Operator):
    bl_idname = 'proteinblender.remove_morph_key'
    bl_label = 'Remove Morph Keyframe'
    bl_description = 'Remove only this subject’s key at this frame'
    bl_options = {'REGISTER', 'UNDO'}
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    frame: IntProperty()

    def execute(self, context):
        morphsets.delete_key(context, self.frame, self.morph_id)
        from .keyframe_operators import PROTEINBLENDER_OT_create_keyframe
        dialog = PROTEINBLENDER_OT_create_keyframe._active_instance
        if dialog:
            for row in dialog.morph_items:
                if row.morph_id == self.morph_id:
                    row.use_morph = False
        return {'FINISHED'}


CLASSES = [PBMorphMemberVisibility, PBMorphKeyframeRow,
           PROTEINBLENDER_OT_create_morphset, PROTEINBLENDER_OT_edit_morphset,
           PROTEINBLENDER_OT_add_morph, PROTEINBLENDER_OT_edit_morph,
           PROTEINBLENDER_OT_add_morph_state, PROTEINBLENDER_OT_edit_morph_state,
           PROTEINBLENDER_OT_rename_morph_state,
           PROTEINBLENDER_OT_remove_morph_state, PROTEINBLENDER_OT_remove_morph,
           PROTEINBLENDER_OT_delete_morphset, PROTEINBLENDER_OT_remove_morph_key]
