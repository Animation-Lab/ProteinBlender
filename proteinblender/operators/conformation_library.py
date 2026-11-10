"""Imported model storage retained for Morphsets and .blend compatibility."""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

MODEL_INTERPRETATIONS = [
    ('AUTO', 'Detect from file',
     'A numbered assembly file (.pdb1) is read as copies and an NMR ensemble as states. '
     'Any other file with several models, such as a morph saved from ChimeraX, '
     'is read as states with a Morphset of all its chains'),
    ('CONFORMATIONS', 'States for Morphsets',
     'Each model is another state of the same protein, such as a morph or trajectory '
     'saved from ChimeraX. A Morphset of all its chains is made, ready to key'),
    ('ASSEMBLY', 'Assembly copies',
     'Each model is another copy in the same structure, all drawn together'),
]
# Old files may contain these values. They are no longer exposed as controls.
FIT_ITEMS = [(value, label, '') for value, label in (
    ('CORE', 'Stable core'), ('ALL', 'Whole protein'),
    ('REGION', 'Selected region'), ('NONE', 'Original placement'))]


class PBConformationState(PropertyGroup):
    uid: StringProperty()
    name: StringProperty(name='Conformation name')
    source: StringProperty()
    model: StringProperty()
    mesh: PointerProperty(type=bpy.types.Mesh)
    baked_pose: BoolProperty()


class PBConformationLibrary(PropertyGroup):
    states: CollectionProperty(type=PBConformationState)
    active_index: IntProperty(min=0)
    reference_uid: StringProperty()
    start_uid: StringProperty()
    end_uid: StringProperty()
    fit: EnumProperty(name='Keep steady', items=FIT_ITEMS, default='NONE')
    fit_region: StringProperty(name='Anchor residues', description='Reference residues, e.g. A:1-30')
    show_comparison: BoolProperty(name='Show transparent reference')
    highlight_motion: BoolProperty(name='Highlight motion (Cα markers)')
    opacity: FloatProperty(name='Reference opacity', subtype='FACTOR', min=0, max=1, default=.18)
    motion_threshold: FloatProperty(name='Motion threshold (Å)', min=.1, max=100, default=2)
    method: StringProperty()
    interpretation: StringProperty()
    error: StringProperty()



def register_props():
    bpy.types.Object.pb_conformations = PointerProperty(type=PBConformationLibrary)
    bpy.types.Scene.pb_conformation_browser = StringProperty()


def unregister_props():
    del bpy.types.Object.pb_conformations
    del bpy.types.Scene.pb_conformation_browser


CLASSES = [PBConformationState, PBConformationLibrary]
