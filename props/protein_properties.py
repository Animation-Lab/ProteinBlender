# protein_workspace/props/properties_protein.py
import bpy

class ProteinProperties(bpy.types.PropertyGroup):
    pdb_id: bpy.props.StringProperty(
        name="PDB ID",
        description="Enter a Protein Data Bank (PDB) ID",
        default=""
    )

def register_protein_properties():
    print('registering protein properties')
    bpy.utils.register_class(ProteinProperties)
    bpy.types.Scene.protein_props = bpy.props.PointerProperty(type=ProteinProperties)

def unregister_protein_properties():
    print('unregistering protein properties')
    del bpy.types.Scene.protein_props
    bpy.utils.unregister_class(ProteinProperties)
