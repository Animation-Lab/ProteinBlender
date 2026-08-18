import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty, FloatProperty, FloatVectorProperty, CollectionProperty
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
            ('PUPPET', 'Puppet', 'Protein Puppet'),
            ('DNA_RNA', 'DNA/RNA', 'DNA or RNA molecule'),
            ('MEMBRANE', 'Membrane', 'Lipid bilayer membrane'),
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
    
    # For PUPPET items only: comma-separated list of member item IDs
    puppet_memberships: StringProperty(
        name="Puppet Members",
        description="For PUPPET items: comma-separated list of member item IDs",
        default=""
    )
    
    # For reference items (shown under puppets): ID of the original item this references
    reference_target_id: StringProperty(
        name="Reference Target",
        description="For reference items: the item_id of the original item this references",
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
            ('cif', 'mmCIF', 'Download as .cif (mmCIF)'),
            ('pdb', 'PDB', 'Download as .pdb (legacy format)'),
        ],
        # mmCIF is the wwPDB's own default and the only format that can carry a
        # large structure at all: legacy PDB runs out of atom serial numbers at
        # 99,999 and chain identifiers at 62, so a viral capsid or a big
        # biological assembly is unreachable through it.
        default='cif',
    )

def _push_assembly_factor(self, context):
    """Send the sliders straight to the assembly nodes of the active protein.

    The value lives on the nodes, not here: that is what a keyframe keys and
    what a .blend carries, so this property is only ever a live handle on it.
    """
    from ..core import assembly as assembly_core
    from ..utils.scene_manager import resolve_active_molecule

    molecule = resolve_active_molecule(context)
    if molecule is None:
        return
    assembly_core.set_assembly_factor(
        molecule, self.pb_assembly_factor, stagger=self.pb_assembly_stagger)


def _symmetry_kind_items(self, context):
    from ..core.symmetry_builder import SYMMETRY_KINDS
    return list(SYMMETRY_KINDS)


def _assembly_enum_items(self, context):
    """Deposited assemblies worth offering for the active protein.

    Imported lazily: ``core.assembly`` reaches the scene manager, which imports
    this module back.
    """
    from ..operators.assembly_operators import assembly_enum_items
    return assembly_enum_items(self, context)


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
    # Which deposited assembly the Symmetry panel will build. Scene-level
    # rather than per-molecule because it is a transient UI choice, not state
    # worth persisting - what is *built* is read back off the node itself.
    bpy.types.Scene.pb_assembly_id = EnumProperty(
        name="Assembly",
        description="Which deposited biological assembly to build",
        items=_assembly_enum_items,
    )
    bpy.types.Scene.pb_assembly_factor = FloatProperty(
        name="Assembled",
        description=("How far the copies have travelled from the asymmetric "
                     "unit to the full assembly. Keyframe this to animate the "
                     "assembly forming"),
        min=0.0, max=1.0, default=1.0, subtype="FACTOR",
        update=_push_assembly_factor,
    )
    bpy.types.Scene.pb_symmetry_kind = EnumProperty(
        name="Symmetry",
        description="What kind of symmetry to generate",
        items=_symmetry_kind_items,
    )
    bpy.types.Scene.pb_symmetry_order = IntProperty(
        name="Order",
        description="n, for Cn or Dn - how many copies around the axis",
        default=3, min=1, max=60,
    )
    bpy.types.Scene.pb_symmetry_count = IntProperty(
        name="Subunits",
        description="How many subunits to place along the helix",
        default=10, min=1, max=200,
    )
    bpy.types.Scene.pb_symmetry_rise = FloatProperty(
        name="Rise",
        description="Angstrom advanced along the axis per subunit",
        default=27.5, min=-500.0, max=500.0,
    )
    bpy.types.Scene.pb_symmetry_twist = FloatProperty(
        name="Twist",
        description="Degrees rotated about the axis per subunit",
        default=-166.7, min=-360.0, max=360.0,
    )
    bpy.types.Scene.pb_symmetry_axis = FloatVectorProperty(
        name="Axis",
        description="Direction of the symmetry axis",
        default=(0.0, 0.0, 1.0), size=3, subtype="XYZ",
    )
    bpy.types.Scene.pb_symmetry_range = FloatProperty(
        name="Range",
        description=("Drop copies whose centre lands further than this many "
                     "Angstrom from the original. 0 keeps every copy"),
        default=0.0, min=0.0, max=10000.0,
    )
    bpy.types.Scene.pb_symmetry_contact = FloatProperty(
        name="Contact",
        description=("Keep only copies with an atom within this many Angstrom "
                     "of the original. 0 keeps every copy"),
        default=0.0, min=0.0, max=100.0,
    )
    bpy.types.Scene.pb_assembly_stagger = FloatProperty(
        name="Stagger",
        description=("Spread the copies' arrivals across the animation "
                     "instead of moving them together"),
        min=0.0, max=1.0, default=0.0, subtype="FACTOR",
        update=_push_assembly_factor,
    )
    bpy.types.Scene.outliner_items = CollectionProperty(type=ProteinOutlinerItem)
    # outliner_index is kept for UIList compatibility but has no update callback
    # We don't use row selection - only checkbox selection
    bpy.types.Scene.outliner_index = IntProperty(
        name="Outliner Index",
        default=-1  # Default to -1 to indicate no row selection
    )

def unregister():
    from bpy.utils import unregister_class
    
    # Safe unregistration with try/except blocks
    for name in ("pb_symmetry_contact", "pb_symmetry_range", "pb_symmetry_axis", "pb_symmetry_twist", "pb_symmetry_rise",
                 "pb_symmetry_count", "pb_symmetry_order", "pb_symmetry_kind",
                 "pb_assembly_stagger", "pb_assembly_factor", "pb_assembly_id"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

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