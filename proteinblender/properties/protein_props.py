import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, CollectionProperty
from bpy.types import PropertyGroup

# REMOVED: on_outliner_selection_change callback
# We no longer use row selection - only checkbox selection is allowed
# This prevents confusion between row highlighting and actual selection state

class ProteinOutlinerItem(PropertyGroup):
    """Unified item for protein outliner display"""
    item_type: EnumProperty(
        name="Item Type",
        items=[
            ('PROTEIN', 'Protein', 'Protein molecule'),
            ('CHAIN', 'Chain', 'Protein chain'),
            ('DOMAIN', 'Domain', 'Protein domain'),
            ('PUPPET', 'Puppet', 'Protein Puppet')
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
    
    # Puppet memberships (items can belong to multiple puppets)
    puppet_memberships: StringProperty(
        name="Puppet Memberships",
        description="Comma-separated list of puppet IDs this item belongs to",
        default=""
    )
    
    controller_object_name: StringProperty(
        name="Controller Object",
        description="Name of the Empty object that controls this puppet's transform",
        default=""
    )
    
    # Track if a chain has domains (for UI purposes)
    has_domains: BoolProperty(
        name="Has Domains",
        description="Whether this chain has domain children",
        default=False
    )

    # Tooltip text for this item
    tooltip: StringProperty(
        name="Tooltip",
        description="Tooltip text to display for this item",
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
    # outliner_index is kept for UIList compatibility but has no update callback
    # We don't use row selection - only checkbox selection
    bpy.types.Scene.outliner_index = IntProperty(
        name="Outliner Index",
        default=-1  # Default to -1 to indicate no row selection
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