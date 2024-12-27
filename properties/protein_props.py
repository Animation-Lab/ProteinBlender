import bpy
from bpy.props import StringProperty, EnumProperty

class ProteinProperties(bpy.types.PropertyGroup):
    import_method: EnumProperty(
        items=[
            ('PDB', 'PDB', 'Import from PDB database'),
            ('ALPHAFOLD', 'AlphaFold', 'Import from AlphaFold database')
        ],
        name="Import Method",
        default='PDB'
    )
    
    pdb_id: StringProperty(
        name="PDB ID",
        description="PDB ID to import",
        default=""
    )
    
    uniprot_id: StringProperty(
        name="UniProt ID",
        description="UniProt ID for AlphaFold structure",
        default=""
    )

def register_properties():
    from bpy.utils import register_class
    register_class(ProteinProperties)
    bpy.types.Scene.protein_props = bpy.props.PointerProperty(type=ProteinProperties)

def unregister_properties():
    from bpy.utils import unregister_class
    del bpy.types.Scene.protein_props
    unregister_class(ProteinProperties)