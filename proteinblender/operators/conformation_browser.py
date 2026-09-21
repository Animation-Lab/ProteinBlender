"""A flat, scrollable state library shared by the animation panel and outliner."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from ..core import morphsets as C, conformation_sets as S
from .morphset_operators import _stable


def libraries(self, context):
    return _stable('state_libraries', [(r[C.TAG], r.name, 'Chains/domains sharing a state choice', i)
        for i, r in enumerate(C.sets(context.scene))] or [('NONE', 'No Morphsets', '', 0)])


def change_library(self, context):
    S.clear_preview(context.scene, remove=True)
    self.index = 0
    sync(context.scene)


class PBStateBrowserItem(PropertyGroup):
    uid: StringProperty()
    name: StringProperty()
    source: StringProperty()


class PBStateBrowser(PropertyGroup):
    expanded: BoolProperty(name='Conformations', default=True, description='Show or collapse the state library')
    library: EnumProperty(name='Morphset', items=libraries, update=change_library)
    items: CollectionProperty(type=PBStateBrowserItem)
    index: IntProperty(min=0)
    owner: StringProperty()


def current(scene):
    browser = scene.pb_morph_browser
    root = C.find(scene, browser.library)
    return root or next(iter(C.sets(scene)), None)


def sync(scene):
    if not hasattr(scene, 'pb_morph_browser'):
        return
    browser = scene.pb_morph_browser
    root = current(scene)
    morph = S.subject(root, scene)
    values = C.states(morph) if morph else []
    desired = [(v['uid'], C.state_label(v), S.provenance(v)) for v in values]
    if [(v.uid, v.name, v.source) for v in browser.items] == desired:
        return
    chosen = browser.items[browser.index].uid if browser.index < len(browser.items) and browser.owner == (root[C.TAG] if root else '') else None
    browser.items.clear()
    for uid, name, source in desired:
        item = browser.items.add()
        item.uid, item.name, item.source = uid, name, source
    browser.owner = root[C.TAG] if root else ''
    browser.index = next((i for i, v in enumerate(values) if v['uid'] == chosen), min(browser.index, max(0, len(values)-1)))


def focus(context, root):
    context.scene.pb_morph_browser.expanded = True
    if context.scene.pb_morph_browser.library != root[C.TAG]:
        context.scene.pb_morph_browser.library = root[C.TAG]
    sync(context.scene)
    for area in context.screen.areas if context.screen else []:
        area.tag_redraw()


def _sync_later():
    if bpy.context.scene:
        sync(bpy.context.scene)


class PROTEINBLENDER_UL_states(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row()
        row.label(text=item.name, icon='SHAPEKEY_DATA')
        provenance = row.row()
        provenance.enabled = False
        provenance.label(text=item.source)


def draw_library(layout, context, *, selector=True):
    scene = context.scene
    browser = scene.pb_morph_browser
    root = current(scene)
    if root is None:
        return
    morph = S.subject(root, scene)
    if selector:
        row = layout.row(align=True)
        row.prop(browser, 'library', text='')
        row.operator('proteinblender.edit_morphset', text='', icon='GREASEPENCIL').morphset_id = root[C.TAG]
    if morph is None:
        layout.label(text='Choose members to start this library.')
        layout.operator('proteinblender.create_morphset', icon='ADD')
        return
    values = C.states(morph)
    wanted = [(v['uid'], C.state_label(v), S.provenance(v)) for v in values]
    if [(v.uid, v.name, v.source) for v in browser.items] != wanted:
        if not bpy.app.timers.is_registered(_sync_later):
            bpy.app.timers.register(_sync_later, first_interval=0)
        layout.label(text='Updating state library…')
        return
    names = [r['name'] for r in C.records(morph)]
    layout.label(text='Members: ' + ', '.join(names))
    row = layout.row()
    row.template_list('PROTEINBLENDER_UL_states', '', browser, 'items', browser, 'index', rows=4, maxrows=6)
    actions = row.column(align=True)
    actions.operator('proteinblender.add_morph_state', text='', icon='ADD').morph_id = morph[C.MORPH]
    value = values[browser.index] if browser.index < len(values) else None
    if value:
        op = actions.operator('proteinblender.edit_morph_state', text='', icon='GREASEPENCIL')
        op.morph_id, op.state_id = morph[C.MORPH], value['uid']
        remove = actions.column(align=True)
        remove.enabled = len(values) > 1 and not any(k['state'] == value['uid'] for k in C.morph_keys(scene, morph[C.MORPH]).values())
        op = remove.operator('proteinblender.remove_morph_state', text='', icon='REMOVE')
        op.morph_id, op.state_id = morph[C.MORPH], value['uid']
        row = layout.row(align=True)
        op = row.operator('proteinblender.preview_conformation', text='Preview State', icon='HIDE_OFF')
        op.morph_id, op.state_id = morph[C.MORPH], value['uid']
        op = row.operator('proteinblender.keyframe_conformation', text='Keyframe State…', icon='KEYFRAME')
        op.morph_id, op.state_id = morph[C.MORPH], value['uid']
    preview = scene.get('pb_conformation_preview')
    if preview:
        owner = C.find(scene, preview['morph'])
        showing = C.state(owner, preview['state']) if owner else None
        row = layout.row(align=True)
        row.label(text='Preview: ' + (C.state_label(showing) if showing else 'saved state'), icon='HIDE_OFF')
        row.operator('proteinblender.return_to_timeline', text='Return to Timeline', icon='PLAY')
    elif morph:
        row = layout.row()
        row.enabled = False
        row.label(text=f'{len(values)} states · Choose timing in Keyframes')
    sources = {r.get('source') for r in C.records(morph)} - {None}
    if any('NMR' in s.pb_conformations.method.upper() for s in sources):
        layout.label(text='NMR models are alternatives, not a time sequence.', icon='INFO')


class PROTEINBLENDER_OT_open_conformation_library(Operator):
    bl_idname = 'proteinblender.open_conformation_library'
    bl_label = 'Conformation Library'
    bl_description = 'Browse, preview and edit this Morphset’s states'
    morphset_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        S.upgrade(context)
        root = C.find(context.scene, self.morphset_id)
        if root is None:
            return {'CANCELLED'}
        focus(context, root)
        return context.window_manager.invoke_popup(self, width=620)

    def draw(self, context):
        draw_library(self.layout, context)

    def execute(self, context):
        return {'FINISHED'}


class PROTEINBLENDER_OT_preview_conformation(Operator):
    bl_idname = 'proteinblender.preview_conformation'
    bl_label = 'Preview State'
    bl_description = 'Inspect this saved structure in the viewport; scrubbing or saving restores the timeline'
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    state_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        try:
            S.preview(context, C.find(context.scene, self.morph_id), self.state_id)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_return_to_timeline(Operator):
    bl_idname = 'proteinblender.return_to_timeline'
    bl_label = 'Return to Timeline'
    bl_description = 'End the temporary structure preview without changing keyframes'

    def execute(self, context):
        S.clear_preview(context.scene, remove=True)
        return {'FINISHED'}


class PROTEINBLENDER_OT_keyframe_conformation(Operator):
    bl_idname = 'proteinblender.keyframe_conformation'
    bl_label = 'Keyframe State'
    bl_description = 'Open the shared keyframe editor with this state selected at the current frame'
    morph_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    state_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        return bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT',
            focus_morph=self.morph_id, focus_state=self.state_id)


CLASSES = [PBStateBrowserItem, PBStateBrowser, PROTEINBLENDER_UL_states,
           PROTEINBLENDER_OT_open_conformation_library, PROTEINBLENDER_OT_preview_conformation,
           PROTEINBLENDER_OT_return_to_timeline, PROTEINBLENDER_OT_keyframe_conformation]


def register_props():
    bpy.types.Scene.pb_morph_browser = PointerProperty(type=PBStateBrowser)
    S.register()


def unregister_props():
    S.unregister()
    if bpy.app.timers.is_registered(_sync_later):
        bpy.app.timers.unregister(_sync_later)
    del bpy.types.Scene.pb_morph_browser
