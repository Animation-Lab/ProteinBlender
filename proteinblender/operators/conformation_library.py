"""Persistent conformation browser and public, undoable library actions."""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, PropertyGroup
from bpy_extras.io_utils import ImportHelper

from ..core import conformation_library as core
from ..utils.scene_manager import ProteinBlenderScene

MODEL_INTERPRETATIONS = [
    ('AUTO', 'Detect from file', 'Use NMR/deposition provenance; ambiguous models need an explicit choice'),
    ('CONFORMATIONS', 'Conformations', 'Models are alternative conformations of the same protein'),
    ('ASSEMBLY', 'Assembly copies', 'Models are simultaneous copies forming one assembly'),
]
FIT_ITEMS = [
    ('CORE', 'Stable core', 'Align each conformation to the same reference using its stable core'),
    ('ALL', 'Whole protein', 'Align all matched alpha carbons to the reference'),
    ('REGION', 'Selected region', 'Keep the entered reference residues steady'),
    ('NONE', 'Original placement', 'Use the stored coordinates without superposition'),
]
_strings = {}


def molecule(identifier):
    result = ProteinBlenderScene.get_instance().molecules.get(identifier)
    if result is None:
        raise ValueError('The protein is no longer available.')
    return result


def _owner(library):
    return next((m for m in ProteinBlenderScene.get_instance().molecules.values()
                 if m.object == library.id_data), None)


def _refresh(self, context):
    owner = _owner(self)
    if owner is None or not self.states:
        return
    try:
        core.refresh(owner)
        self.error = ''
    except ValueError as exc:
        self.error = str(exc)


def _items(self, context):
    items = [(s.uid, s.name, f'{s.source} · Model {s.model}' if s.model else s.source, i)
             for i, s in enumerate(self.states)]
    if not items:
        items = [('NONE', 'No conformations', '', 0)]
    key = tuple(items)
    return _strings.setdefault(key, items)


def _get_active(self):
    return min(max(0, self.get('active_index', 0)), max(0, len(self.states) - 1))


def _set_active(self, value):
    previous = _get_active(self)
    self['active_index'] = min(max(0, value), max(0, len(self.states) - 1))
    _refresh(self, bpy.context)
    if self.error:
        self['active_index'] = previous


def _get_reference(self):
    return next((i for i, s in enumerate(self.states) if s.uid == self.reference_uid), 0)


def _set_reference(self, value):
    if self.states:
        self.reference_uid = self.states[value].uid
        _refresh(self, bpy.context)


class PBConformationState(PropertyGroup):
    uid: StringProperty()
    name: StringProperty(name='Conformation name')
    source: StringProperty()
    model: StringProperty()
    mesh: PointerProperty(type=bpy.types.Mesh)
    baked_pose: BoolProperty()


class PBConformationLibrary(PropertyGroup):
    states: CollectionProperty(type=PBConformationState)
    active_index: IntProperty(get=_get_active, set=_set_active, min=0)
    active: EnumProperty(name='Conformation', items=_items, get=_get_active, set=_set_active)
    browse: FloatProperty(name='Browse', subtype='FACTOR', min=0, max=1,
                          get=lambda s: _get_active(s) / max(1, len(s.states) - 1),
                          set=lambda s, v: _set_active(s, round(v * max(0, len(s.states) - 1))))
    reference: EnumProperty(name='Compare with', items=_items, get=_get_reference, set=_set_reference)
    reference_uid: StringProperty()
    start_uid: StringProperty()
    end_uid: StringProperty()
    fit: EnumProperty(name='Keep steady', items=FIT_ITEMS, default='CORE', update=_refresh)
    fit_region: StringProperty(name='Anchor residues', description='Reference residues, e.g. A:1-30', update=_refresh)
    show_comparison: BoolProperty(name='Show transparent reference', update=_refresh)
    highlight_motion: BoolProperty(name='Highlight motion (Cα markers)', update=_refresh)
    opacity: FloatProperty(name='Reference opacity', subtype='FACTOR', min=0, max=1, default=.18, update=_refresh)
    motion_threshold: FloatProperty(name='Motion threshold (Å)', min=.1, max=100, default=2, update=_refresh)
    method: StringProperty()
    interpretation: StringProperty()
    error: StringProperty()


def _popup_items(self, context):
    mol = ProteinBlenderScene.get_instance().molecules.get(self.molecule_id)
    return _items(mol.object.pb_conformations, context) if mol else [('NONE', 'Unavailable', '', 0)]


VIEW_FIELDS = ('fit', 'fit_region', 'show_comparison', 'highlight_motion',
               'opacity', 'motion_threshold')


def _close_browser(context, identifier):
    """Only clean up the protein that this popup owns, regardless of selection."""
    from ..core.conformation_comparison import clear
    mol = ProteinBlenderScene.get_instance().molecules.get(identifier)
    if mol:
        library = mol.object.pb_conformations
        library['show_comparison'] = False
        library['highlight_motion'] = False
        clear(mol)
    if context.scene.pb_conformation_browser == identifier:
        context.scene.pb_conformation_browser = ''


class PROTEINBLENDER_OT_apply_conformation_view(Operator):
    """Show the chosen conformation and comparison settings without closing the popup"""
    bl_idname = 'proteinblender.apply_conformation_view'
    bl_label = 'Apply Conformation'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty(options={'HIDDEN'})
    state_uid: EnumProperty(name='Conformation', items=_popup_items)
    target_uid: EnumProperty(name='Morph to', items=_popup_items)
    reference_uid: EnumProperty(name='Reference', items=_popup_items)
    fit: EnumProperty(name='Keep steady', items=FIT_ITEMS, default='CORE')
    fit_region: StringProperty(name='Anchor residues', description='Reference residues, e.g. A:1-30')
    show_comparison: BoolProperty(name='Show transparent reference')
    highlight_motion: BoolProperty(name='Highlight motion (Cα markers)')
    opacity: FloatProperty(name='Reference opacity', subtype='FACTOR', min=0, max=1, default=.18)
    motion_threshold: FloatProperty(name='Motion threshold (Å)', min=.1, max=100, default=2)

    def execute(self, context):
        try:
            mol = molecule(self.molecule_id)
            library = mol.object.pb_conformations
            for uid in (self.state_uid, self.target_uid, self.reference_uid):
                core.state(mol, uid)
            values = {name: getattr(self, name) for name in VIEW_FIELDS}
            # Write the fields together, then refresh once. A failed alignment
            # must not leave the dropdown and displayed coordinates disagreeing.
            values['fit'] = next(i for i, item in enumerate(FIT_ITEMS) if item[0] == self.fit)
            values.update(active_index=next(i for i, s in enumerate(library.states) if s.uid == self.state_uid),
                          reference_uid=self.reference_uid, start_uid=self.state_uid, end_uid=self.target_uid)
            before = {name: library.get(name) for name in values}
            for name, value in values.items():
                library[name] = value
            try:
                core.refresh(mol)
            except ValueError:
                for name, value in before.items():
                    if value is None:
                        del library[name]
                    else:
                        library[name] = value
                core.refresh(mol)
                raise
            library.error = ''
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_browse_conformations(Operator):
    """Browse this protein's conformations and choose a pair to morph"""
    bl_idname = 'proteinblender.browse_conformations'
    bl_label = 'Browse Conformations'
    bl_options = {'REGISTER', 'UNDO'}
    __annotations__ = PROTEINBLENDER_OT_apply_conformation_view.__annotations__.copy()
    show_comparison_tools: BoolProperty(name='Alignment & comparison', options={'SKIP_SAVE'})
    show_library_tools: BoolProperty(name='Library tools', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return bpy.ops.proteinblender.morph('INVOKE_DEFAULT', source_id=self.molecule_id)

    def _open(self, context):
        try:
            mol = molecule(self.molecule_id)
            previous = ProteinBlenderScene.get_instance().molecules.get(context.scene.pb_conformation_browser)
            if previous and previous.object != mol.object:
                _close_browser(context, previous.identifier)
            core.initialize(mol)
            context.scene.pb_conformation_browser = self.molecule_id
            core.refresh(mol)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}

    def execute(self, context):
        # Preserve the public noninteractive entry point used by scripts.
        if not self.properties.is_property_set('state_uid'):
            return self._open(context)
        result = PROTEINBLENDER_OT_apply_conformation_view.execute(self, context)
        # Blender also dismisses a confirmed dialog when execute() cancels.
        _close_browser(context, self.molecule_id)
        return result

    def cancel(self, context):
        # Apply commits coordinates; Escape only discards pending fields and
        # removes temporary viewport comparison helpers, as in Lighting.
        _close_browser(context, self.molecule_id)


class PROTEINBLENDER_OT_close_conformations(Operator):
    """Close the browser and remove its viewport comparison helpers"""
    bl_idname = 'proteinblender.close_conformations'
    bl_label = 'Close Conformation Browser'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _close_browser(context, context.scene.pb_conformation_browser)
        return {'FINISHED'}


class PROTEINBLENDER_OT_switch_conformation(Operator):
    """Show a stored conformation without moving the scene playhead"""
    bl_idname = 'proteinblender.switch_conformation'
    bl_label = 'Switch Conformation'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()
    index: IntProperty(default=-1, min=-1)
    step: IntProperty(default=0)

    def execute(self, context):
        try:
            library = molecule(self.molecule_id).object.pb_conformations
            index = self.index if self.index >= 0 else library.active_index + self.step
            if not 0 <= index < len(library.states):
                raise ValueError('The requested conformation is outside this library.')
            library.active_index = index
            if library.error:
                raise ValueError(library.error)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_mark_conformation(Operator):
    """Use the displayed conformation as a morph endpoint"""
    bl_idname = 'proteinblender.mark_conformation'
    bl_label = 'Set Morph Endpoint'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()
    endpoint: EnumProperty(items=[('START', 'Start', ''), ('END', 'End', '')])

    def execute(self, context):
        try:
            library = molecule(self.molecule_id).object.pb_conformations
            uid = library.states[library.active_index].uid
            setattr(library, 'start_uid' if self.endpoint == 'START' else 'end_uid', uid)
        except (ValueError, IndexError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_add_conformation_file(Operator, ImportHelper):
    """Add compatible coordinate sets from a file to this protein"""
    bl_idname = 'proteinblender.add_conformation_file'
    bl_label = 'Add Conformations from File'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()
    filename_ext = '.pdb'
    filter_glob: StringProperty(default='*.pdb;*.cif;*.mmcif;*.bcif;*.gz', options={'HIDDEN'})
    model_interpretation: EnumProperty(name='Multiple models', items=MODEL_INTERPRETATIONS)

    def execute(self, context):
        try:
            count = core.add_file(molecule(self.molecule_id), self.filepath, self.model_interpretation)
        except (ValueError, OSError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Added {count} conformations. The displayed state is unchanged.')
        return {'FINISHED'}


class PROTEINBLENDER_OT_capture_library_conformation(Operator):
    """Store the current chain/domain pose as a named endpoint in this library"""
    bl_idname = 'proteinblender.capture_library_conformation'
    bl_label = 'Capture Current Pose'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()
    name: StringProperty(name='Conformation name', default='Captured pose')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            if not self.name.strip():
                raise ValueError('Enter a name for the conformation.')
            core.capture_pose(molecule(self.molecule_id), self.name.strip())
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class PROTEINBLENDER_OT_add_conformation_pdb(Operator):
    """Add compatible conformations from an RCSB PDB entry"""
    bl_idname = 'proteinblender.add_conformation_pdb'
    bl_label = 'Add Conformations from PDB'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()
    pdb_id: StringProperty(name='PDB ID')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import io
        from ..utils.molecularnodes.download import download, FileDownloadPDBError
        from ..utils.molecularnodes.entities import parse
        try:
            mol = molecule(self.molecule_id)
            if not self.pdb_id.strip():
                raise ValueError('Enter a PDB ID.')
            path = download(code=self.pdb_id.strip(), format='cif')
            parsed = parse(path, stream_format_hint='cif') if isinstance(path, (io.StringIO, io.BytesIO)) else parse(path)
            core.prepare_import(parsed, deposited=True)
            count = core.append_parsed(mol, parsed, self.pdb_id.strip().upper())
        except (ValueError, OSError, FileDownloadPDBError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Added {count} conformations.')
        return {'FINISHED'}


class PROTEINBLENDER_OT_extract_library_conformation(Operator):
    """Create an independent protein showing the current conformation"""
    bl_idname = 'proteinblender.extract_library_conformation'
    bl_label = 'Extract as Separate Protein'
    bl_options = {'REGISTER', 'UNDO'}
    molecule_id: StringProperty()

    def execute(self, context):
        from ..core.conformation import rebuild_outliner
        try:
            mol = molecule(self.molecule_id)
            library = mol.object.pb_conformations
            item = library.states[library.active_index]
            name, source, model = item.name, item.source, item.model
            # Duplicate the displayed geometry/presentation. Immutable state
            # meshes can be shared until the copy becomes a one-state library.
            before = set(ProteinBlenderScene.get_instance().molecules)
            result = bpy.ops.molecule.duplicate_protein(molecule_id=self.molecule_id)
            if result != {'FINISHED'}:
                return {'CANCELLED'}
            identifier = (set(ProteinBlenderScene.get_instance().molecules) - before).pop()
            copied = molecule(identifier)
            core.clear(copied)
            coords = core.read_mesh(copied.object.data)
            state = core.add_coordinates(copied, coords, name, source, model)
            new_library = copied.object.pb_conformations
            new_library['active_index'] = 0
            new_library['show_comparison'] = new_library['highlight_motion'] = False
            new_library.start_uid = new_library.end_uid = new_library.reference_uid = state.uid
            new_library.fit = 'NONE'
            copied.object['pb_conformation_name'] = name
            core.refresh(copied)
            rebuild_outliner(context)
        except (ValueError, IndexError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def register_props():
    bpy.types.Object.pb_conformations = PointerProperty(type=PBConformationLibrary)
    bpy.types.Scene.pb_conformation_browser = StringProperty()


def unregister_props():
    del bpy.types.Object.pb_conformations
    del bpy.types.Scene.pb_conformation_browser


CLASSES = [PBConformationState, PBConformationLibrary,
           PROTEINBLENDER_OT_apply_conformation_view,
           PROTEINBLENDER_OT_browse_conformations, PROTEINBLENDER_OT_close_conformations,
           PROTEINBLENDER_OT_switch_conformation, PROTEINBLENDER_OT_mark_conformation,
           PROTEINBLENDER_OT_add_conformation_file, PROTEINBLENDER_OT_capture_library_conformation,
           PROTEINBLENDER_OT_add_conformation_pdb, PROTEINBLENDER_OT_extract_library_conformation]
