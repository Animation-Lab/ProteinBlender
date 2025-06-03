import bpy
from bpy.props import StringProperty, EnumProperty

class ProteinProperties(bpy.types.PropertyGroup):
    import_method: EnumProperty(
        items=[
            ('PDB', 'PDB', 'Import from PDB database'),
            ('ALPHAFOLD', 'AlphaFold', 'Import from AlphaFold database'),
            ('MMCIF', 'mmCIF', 'Import from local mmCIF file'),
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

    mmcif_path: StringProperty(
        name="mmCIF File",
        description="Path to the mmCIF file to import",
        default="",
        subtype="FILE_PATH"
    )

    remote_format: EnumProperty(
        name="Remote Format",
        description="File format to download from the PDB",
        items=[
            ('pdb', 'PDB', 'Download as .pdb'),
            ('cif', 'mmCIF', 'Download as .cif (mmCIF)'),
        ],
        default='pdb',
    )

def register():
    from bpy.utils import register_class
    
    # Safe registration - unregister first if already registered
    try:
        unregister()
    except Exception:
        pass
    
    # Now register
    register_class(ProteinProperties)
    bpy.types.Scene.protein_props = bpy.props.PointerProperty(type=ProteinProperties)

def unregister():
    from bpy.utils import unregister_class
    
    # Safe unregistration with try/except blocks
    if hasattr(bpy.types.Scene, "protein_props"):
        del bpy.types.Scene.protein_props
    
    try:
        unregister_class(ProteinProperties)
    except Exception:
        pass