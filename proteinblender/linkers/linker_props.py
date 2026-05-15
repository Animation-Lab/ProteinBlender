"""Linker properties for ProteinBlender.

Linkers connect chains/domains within a single puppet. A puppet must
exist before creating a linker. The linker length is determined by
residue count, which sets a hard constraint on max distance.

All references use string-based IDs to ensure undo/redo stability.
"""

import bpy
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    EnumProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup
import uuid


def generate_linker_uid():
    """Generate a unique identifier for a linker."""
    return str(uuid.uuid4())[:8]


def _on_linker_bead_param_update(self, context):
    """Called when bead radius or overlap is changed in the UI."""
    obj = bpy.data.objects.get(self.curve_object_name)
    if not obj:
        return
    try:
        from .linker_geometry import setup_beads_geometry_nodes
        setup_beads_geometry_nodes(obj, self)
    except Exception:
        pass


def _on_linker_color_update(self, context):
    """Called when linker color is changed in the UI."""
    obj = bpy.data.objects.get(self.curve_object_name)
    if not obj:
        return
    try:
        from .linker_geometry import setup_linker_material
        setup_linker_material(obj, self)
    except Exception:
        pass


class PB2_LinkerDefinition(PropertyGroup):
    """Definition of a flexible linker connecting chains within a single puppet.

    Stored at scene level. Both endpoints must belong to the same puppet.
    All object references use string names for undo/redo stability.
    """

    # Unique identifier (never changes)
    uid: StringProperty(
        name="UID",
        description="Unique identifier for this linker",
        default=""
    )

    # Display name (user-editable)
    name: StringProperty(
        name="Name",
        description="Display name for this linker",
        default="Linker"
    )

    # Puppet reference - both endpoints must belong to this puppet
    puppet_id: StringProperty(
        name="Puppet",
        description="ID of the puppet this linker belongs to",
        default=""
    )

    # Endpoint A - outliner item + chain/residue within it
    endpoint_a_item_id: StringProperty(
        name="Endpoint A Item",
        description="Outliner item_id of the chain/domain at endpoint A",
        default=""
    )
    endpoint_a_chain: StringProperty(
        name="Endpoint A Chain",
        description="Chain letter at endpoint A",
        default=""
    )
    endpoint_a_residue: IntProperty(
        name="Endpoint A Residue",
        description="Residue number at endpoint A",
        default=1,
        min=1
    )

    # Endpoint B - outliner item + chain/residue within it
    endpoint_b_item_id: StringProperty(
        name="Endpoint B Item",
        description="Outliner item_id of the chain/domain at endpoint B",
        default=""
    )
    endpoint_b_chain: StringProperty(
        name="Endpoint B Chain",
        description="Chain letter at endpoint B",
        default=""
    )
    endpoint_b_residue: IntProperty(
        name="Endpoint B Residue",
        description="Residue number at endpoint B",
        default=1,
        min=1
    )

    # Linker length in residues - determines max reach
    # Max reach = length_residues * 3.5 Angstroms * 0.01 scale = length_residues * 0.035 BU
    length_residues: IntProperty(
        name="Length (residues)",
        description="Number of amino acid residues in the linker (determines max reach)",
        default=10,
        min=3,
        max=100
    )

    # Visual style
    style: EnumProperty(
        name="Style",
        description="Visual appearance of the linker",
        items=[
            ('TUBE', "Tube", "Smooth tube (adjustable radius)"),
            ('BEADS', "Beads", "Spherical beads with random sizing"),
        ],
        default='TUBE'
    )

    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0, max=1.0,
        default=(0.7, 0.7, 0.7, 1.0),
        update=_on_linker_color_update
    )

    # Style-specific size parameters
    tube_radius: FloatProperty(
        name="Radius",
        description="Radius of the tube",
        default=0.015,
        min=0.001, soft_max=0.03, max=0.1,
        step=0.1,
        unit='LENGTH'
    )

    bead_radius: FloatProperty(
        name="Bead Radius",
        description="Base radius of each bead",
        default=0.020,
        min=0.001, max=0.1,
        unit='LENGTH',
        update=_on_linker_bead_param_update
    )

    bead_overlap: FloatProperty(
        name="Bead Overlap",
        description="Fraction of overlap between adjacent beads (0 = touching, no overlap)",
        default=0.3,
        min=0.0, max=0.95,
        subtype='FACTOR',
        update=_on_linker_bead_param_update
    )

    bead_jitter: FloatProperty(
        name="Bead Jitter",
        description="Random positional offset perpendicular to the curve",
        default=0.3,
        min=0.0, max=1.0,
        subtype='FACTOR',
        update=_on_linker_bead_param_update
    )

    bead_radius_variance: FloatProperty(
        name="Radius Variance",
        description="How much bead sizes vary (0 = all same size, 1 = max variation)",
        default=0.5,
        min=0.0, max=1.0,
        subtype='FACTOR',
        update=_on_linker_bead_param_update
    )

    # Rendering mode
    rendering_mode: EnumProperty(
        name="Rendering",
        description="How the linker is rendered",
        items=[
            ('QUICK', "Quick", "Styled Bezier curve (tube) with catenary physics"),
            ('DETAILED', "Detailed", "MolecularNodes peptide geometry along curve"),
        ],
        default='QUICK'
    )

    # Physics behavior
    behavior: EnumProperty(
        name="Behavior",
        description="How the linker responds to slack (excess length beyond the endpoint distance)",
        items=[
            ('GRAVITY', "Gravity", "Catenary droop — linker sags downward like a hanging chain"),
            ('ZERO_G', "Zero-G", "No gravity — slack distributes as a smooth arc with no preferred direction"),
            ('RANDOM_COIL', "Random Coil", "Wiggly disordered path — realistic intrinsically disordered region"),
        ],
        default='GRAVITY'
    )

    # Rigid binding zone length at each end
    binding_zone_residues: IntProperty(
        name="Binding Zone",
        description="Number of residues for rigid binding zones at each endpoint",
        default=3,
        min=1,
        max=10
    )

    # Blender object reference (by name, not pointer)
    curve_object_name: StringProperty(
        name="Curve Object",
        description="Name of the Blender curve object",
        default=""
    )

    # State flags
    is_valid: BoolProperty(
        name="Valid",
        description="Whether both endpoints still exist",
        default=True
    )

    is_visible: BoolProperty(
        name="Visible",
        description="Whether the linker is visible",
        default=True
    )

    is_expanded: BoolProperty(
        name="Expanded",
        description="Whether linker settings are expanded in UI",
        default=False
    )

    def get_max_reach_bu(self):
        """Max reach in Blender units: length_residues * 3.5A * 0.01 scale."""
        return self.length_residues * 0.035

    def belongs_to_puppet(self, puppet_id):
        """True if this linker belongs to the given puppet."""
        return self.puppet_id == puppet_id

    def get_endpoint_a_display(self):
        """Get display string for endpoint A."""
        return f"{self.endpoint_a_chain}:{self.endpoint_a_residue}"

    def get_endpoint_b_display(self):
        """Get display string for endpoint B."""
        return f"{self.endpoint_b_chain}:{self.endpoint_b_residue}"


# Registration
CLASSES = [
    PB2_LinkerDefinition,
]


def register():
    """Register linker property classes."""
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass

    if not hasattr(bpy.types.Scene, "pb2_linkers"):
        bpy.types.Scene.pb2_linkers = CollectionProperty(
            type=PB2_LinkerDefinition,
            name="Linkers",
            description="Flexible linkers in the scene"
        )

    if not hasattr(bpy.types.Scene, "pb2_linkers_index"):
        bpy.types.Scene.pb2_linkers_index = IntProperty(
            name="Active Linker Index",
            default=0,
            min=0
        )


def unregister():
    """Unregister linker property classes."""
    if hasattr(bpy.types.Scene, "pb2_linkers_index"):
        del bpy.types.Scene.pb2_linkers_index

    if hasattr(bpy.types.Scene, "pb2_linkers"):
        del bpy.types.Scene.pb2_linkers

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
