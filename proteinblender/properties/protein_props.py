import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, CollectionProperty
from bpy.types import PropertyGroup

def on_outliner_selection_change(self, context):
    """Callback when outliner selection changes via index"""
    # Get the selected item
    scene = context.scene
    if 0 <= scene.outliner_index < len(scene.outliner_items):
        selected_item = scene.outliner_items[scene.outliner_index]
        
        # Clear all selections first
        for item in scene.outliner_items:
            item.is_selected = False
        
        # Select the clicked item
        selected_item.is_selected = True
        
        # Sync to Blender selection
        from ..handlers.selection_sync import sync_outliner_to_blender_selection
        sync_outliner_to_blender_selection(context, selected_item.item_id)

class ProteinOutlinerItem(PropertyGroup):
    """Unified item for protein outliner display"""
    item_type: EnumProperty(
        name="Item Type",
        items=[
            ('PROTEIN', 'Protein', 'Protein molecule'),
            ('CHAIN', 'Chain', 'Protein chain'),
            ('DOMAIN', 'Domain', 'Protein domain'),
            ('GROUP', 'Group', 'Group of items')
        ],
        default='PROTEIN'
    )
    
    item_id: StringProperty(
        name="Item ID",
        description="Unique identifier for this item"
    )
    
    parent_id: StringProperty(
        name="Parent ID",
        description="ID of parent item for hierarchy"
    )
    
    # Reference to actual object/data
    object_name: StringProperty(
        name="Object Name",
        description="Name of the Blender object this item represents"
    )
    
    # Visual states
    is_expanded: BoolProperty(
        name="Expanded",
        description="Whether this item is expanded in the outliner",
        default=True
    )
    
    is_selected: BoolProperty(
        name="Selected",
        description="Whether this item is selected",
        default=False
    )
    
    is_visible: BoolProperty(
        name="Visible",
        description="Whether this item is visible",
        default=True
    )
    
    # Display properties
    indent_level: IntProperty(
        name="Indent Level",
        description="Indentation level for hierarchy display",
        default=0,
        min=0
    )
    
    icon: StringProperty(
        name="Icon",
        description="Icon to display for this item",
        default='DOT'
    )
    
    # Item-specific data
    chain_id: StringProperty(
        name="Chain ID",
        description="For chain items, the chain identifier"
    )
    
    chain_start: IntProperty(
        name="Chain Start",
        description="For chain items, start residue number",
        default=1,
        min=1
    )
    
    chain_end: IntProperty(
        name="Chain End",
        description="For chain items, end residue number",
        default=1,
        min=1
    )
    
    domain_start: IntProperty(
        name="Domain Start",
        description="For domain items, start residue"
    )
    
    domain_end: IntProperty(
        name="Domain End",
        description="For domain items, end residue"
    )
    
    # Group memberships (items can belong to multiple groups)
    group_memberships: StringProperty(
        name="Group Memberships",
        description="Comma-separated list of group IDs this item belongs to",
        default=""
    )

class ProteinProperties(bpy.types.PropertyGroup):
    import_method: EnumProperty(
        items=[
            ('PDB', 'PDB', 'Download PDB file from RCSB'),
            ('MMCIF', 'mmCIF', 'Download mmCIF file from RCSB'),
            ('ALPHAFOLD', 'AlphaFold', 'Download structure from AlphaFold'),
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
    register_class(ProteinOutlinerItem)
    register_class(ProteinProperties)
    
    # Add properties to scene
    bpy.types.Scene.protein_props = bpy.props.PointerProperty(type=ProteinProperties)
    bpy.types.Scene.outliner_items = CollectionProperty(type=ProteinOutlinerItem)
    bpy.types.Scene.outliner_index = IntProperty(
        name="Outliner Index",
        default=0,
        update=on_outliner_selection_change
    )
    
    # Register placeholder property for animation panel
    bpy.types.Scene.placeholder_brownian = BoolProperty(
        name="Brownian Motion",
        description="Placeholder for Brownian motion option",
        default=False
    )

def unregister():
    from bpy.utils import unregister_class
    
    # Safe unregistration with try/except blocks
    if hasattr(bpy.types.Scene, "placeholder_brownian"):
        del bpy.types.Scene.placeholder_brownian
        
    if hasattr(bpy.types.Scene, "outliner_index"):
        del bpy.types.Scene.outliner_index
    
    if hasattr(bpy.types.Scene, "outliner_items"):
        del bpy.types.Scene.outliner_items
    
    if hasattr(bpy.types.Scene, "protein_props"):
        del bpy.types.Scene.protein_props
    
    try:
        unregister_class(ProteinProperties)
    except Exception:
        pass
    
    try:
        unregister_class(ProteinOutlinerItem)
    except Exception:
        pass