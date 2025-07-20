# protein_blender/properties/__init__.py
from .protein_props import register as register_protein_props, unregister as unregister_protein_props
from .molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .outliner_properties import register as register_outliner_props, unregister as unregister_outliner_props
from .group_props import register as register_group_props, unregister as unregister_group_props

def register():
    register_protein_props()
    register_molecule_props()
    register_outliner_props()
    register_group_props()

def unregister():
    unregister_group_props()
    unregister_outliner_props()
    unregister_molecule_props()
    unregister_protein_props() 