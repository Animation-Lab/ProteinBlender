"""Operators for creating and managing flexible linkers within a single puppet."""

import bpy
from bpy.types import Operator
from bpy.props import (
    StringProperty, IntProperty, EnumProperty,
    FloatProperty, FloatVectorProperty,
)
import logging

from .linker_props import generate_linker_uid
from .linker_geometry import (
    create_linker_curve,
    update_linker_curve,
    delete_linker_geometry,
    toggle_linker_visibility,
    get_residue_position_from_item,
    get_object_for_item,
    get_backbone_direction,
    compute_min_distance,
    _get_numeric_chain_id_from_item,
    BU_PER_RESIDUE,
    MN_SCALE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers for puppet / chain enumeration
# ---------------------------------------------------------------------------

def get_puppet_items(self, context):
    """Enum callback listing all puppets in the scene."""
    items = []
    if not hasattr(context.scene, 'outliner_items'):
        return [('NONE', "No Puppets", "")]

    for puppet_item in context.scene.outliner_items:
        if puppet_item.item_type != 'PUPPET' or puppet_item.item_id == "puppets_separator":
            continue
        if not puppet_item.puppet_memberships:
            continue
        items.append((puppet_item.item_id, puppet_item.name, f"Puppet: {puppet_item.name}"))

    if not items:
        items.append(('NONE', "No Puppets", "Create a puppet first"))
    return items


def _build_chain_items_for_puppet(context, puppet_id: str):
    """Build a list of chain/domain items belonging to a specific puppet."""
    items = []
    if not puppet_id or puppet_id == 'NONE':
        return [('NONE', "Select a puppet first", "")]
    if not hasattr(context.scene, 'outliner_items'):
        return [('NONE', "No Chains", "")]

    for puppet_item in context.scene.outliner_items:
        if puppet_item.item_id != puppet_id:
            continue
        if not puppet_item.puppet_memberships:
            break

        member_ids = [m.strip() for m in puppet_item.puppet_memberships.split(',') if m.strip()]
        outliner = context.scene.outliner_items
        # De-duplicate by endpoint id: a split chain and its own domains can both
        # be in the membership (selecting the chain cascades to its domains), and
        # the chain expands to those same domains below - without this guard each
        # domain is listed twice AND the two enum entries share an identifier,
        # which Blender does not allow.
        seen = set()

        def _add(item_id, label):
            if item_id in seen:
                return
            seen.add(item_id)
            items.append((item_id, label, f"{label} in {puppet_item.name}"))

        for member_id in member_ids:
            member = next((it for it in outliner if it.item_id == member_id), None)
            if member is None:
                continue
            # A chain that has been split contributes its DOMAIN pieces as the
            # linkable endpoints, never the chain as a whole. Linkers attach to
            # the individual domain objects; the parent chain's own object was
            # deleted by the split, so listing it gives an endpoint that resolves
            # to no residues ("Valid range: 1-999", residue 1 doesn't exist) and
            # every create fails with "Could not find residue". Expand on ANY
            # domain child - even one, e.g. after the sibling piece was deleted.
            # An unsplit chain (its whole-chain auto-domain has no separate
            # DOMAIN row) stays itself.
            domain_children = sorted(
                (it for it in outliner
                 if it.item_type == 'DOMAIN' and it.parent_id == member_id),
                key=lambda it: it.item_id)
            if member.item_type == 'CHAIN' and domain_children:
                for dom in domain_children:
                    _add(dom.item_id, dom.name)
            else:
                _add(member_id, member.name)
        break

    if not items:
        items.append(('NONE', "No Chains", "Puppet has no chains"))
    return items


# Blender caches dynamic enum items per callback function reference AND can
# confuse the selected value between two EnumProperties even with separate
# callbacks. To make this bulletproof, we prefix each item identifier with
# "A_" or "B_" so the two enums live in completely separate identifier
# namespaces — even if Blender shares the cache, the IDs cannot collide.
def get_chain_items_a(self, context):
    """Enum callback for endpoint A chain selection (A_ prefixed IDs)."""
    items = _build_chain_items_for_puppet(context, self.puppet_selector)
    return [(f"A_{id}", label, desc) for id, label, desc in items]


def get_chain_items_b(self, context):
    """Enum callback for endpoint B chain selection (B_ prefixed IDs)."""
    items = _build_chain_items_for_puppet(context, self.puppet_selector)
    return [(f"B_{id}", label, desc) for id, label, desc in items]


def _strip_endpoint_prefix(value: str) -> str:
    """Strip the A_/B_ prefix from an enum value to get the real item_id."""
    if value.startswith("A_") or value.startswith("B_"):
        return value[2:]
    return value


def _endpoint_first_residue(endpoint_value: str):
    """The first residue that actually exists in an endpoint item, or None.

    Endpoints that have been split off a chain start partway through the
    protein (e.g. residues 51-198), so residue 1 does not exist there. This
    returns the low end of the endpoint's real residue range so defaults land
    on a residue that exists instead of the hard-coded 1."""
    real = _strip_endpoint_prefix(endpoint_value or "")
    if not real or real == 'NONE':
        return None
    lo, hi = get_residue_range_for_item(real, get_chain_letter_for_item(real))
    # (1, 999) is the "couldn't resolve" fallback - don't trust it as a real
    # first residue.
    if (lo, hi) == (1, 999):
        return None
    return lo


def _update_endpoint_a_residue(self, context):
    """When endpoint A changes, snap its residue to the first one that exists."""
    lo = _endpoint_first_residue(self.endpoint_a_item)
    if lo is not None:
        self.endpoint_a_residue = lo


def _update_endpoint_b_residue(self, context):
    """When endpoint B changes, snap its residue to the first one that exists."""
    lo = _endpoint_first_residue(self.endpoint_b_item)
    if lo is not None:
        self.endpoint_b_residue = lo


def get_chain_letter_for_item(item_id: str) -> str:
    """Extract the chain letter from an outliner item.

    Reads the item's object mesh attributes to determine the chain ID letter.
    Falls back to extracting from the item name.
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return ""

    # A DOMAIN item's chain letter is authoritative in the molecule model - read
    # it there rather than parsing the display name (which is now "Chain A:
    # Residues 51-198" and would parse to "A:").
    from ..utils.scene_manager import ProteinBlenderScene
    scene_manager = ProteinBlenderScene.get_instance()
    for molecule in scene_manager.molecules.values():
        domain = getattr(molecule, 'domains', {}).get(item_id)
        if domain is not None and getattr(domain, 'chain_id', ''):
            return str(domain.chain_id)

    for item in scene.outliner_items:
        if item.item_id == item_id:
            # Try to get from item name (often "Chain A", "Chain B", etc.).
            # Strip a trailing ":" so "Chain A: Residues 51-198" yields "A".
            name = item.name
            if "Chain " in name:
                parts = name.split("Chain ")
                if len(parts) > 1:
                    return parts[-1].strip().split()[0].rstrip(':')

            # Try to get from the object's chain_id attribute
            obj = bpy.data.objects.get(item.object_name)
            if obj and obj.data and hasattr(obj.data, 'attributes'):
                from ..utils.chain_utils import get_chain_mapping_from_object
                chain_mapping = get_chain_mapping_from_object(obj)
                if chain_mapping:
                    # Return the first chain letter (domain objects usually have one chain)
                    for _, letter in sorted(chain_mapping.items()):
                        return letter

            return ""
    return ""


def get_residue_range_for_item(item_id: str, chain_id: str) -> tuple:
    """Get valid residue range (min, max) for a chain within an item.

    Args:
        item_id: Outliner item_id
        chain_id: Chain letter

    Returns:
        (min_residue, max_residue), or (1, 999) as fallback
    """
    from ..utils.chain_utils import get_chain_mapping_from_object

    # A DOMAIN endpoint carries its own residue range in the molecule model. Use
    # it directly: the domain object shares the whole-molecule mesh (masked to a
    # range inside geometry nodes), so reading res_id off the mesh would report
    # the parent chain's full span (e.g. 1-141) instead of the domain's 51-198 -
    # which then defaults the endpoint residue to 1, a residue outside the
    # domain the user picked.
    from ..utils.scene_manager import ProteinBlenderScene
    scene_manager = ProteinBlenderScene.get_instance()
    for molecule in scene_manager.molecules.values():
        domain = getattr(molecule, 'domains', {}).get(item_id)
        if domain is not None and hasattr(domain, 'start') and hasattr(domain, 'end'):
            return (domain.start, domain.end)

    obj = get_object_for_item(item_id)
    if not obj or not obj.data or not hasattr(obj.data, 'attributes'):
        return (1, 999)

    mesh = obj.data
    if "res_id" not in mesh.attributes:
        return (1, 999)

    try:
        res_ids = [r.value for r in mesh.attributes["res_id"].data]

        if "chain_id" in mesh.attributes and chain_id:
            # Use numeric chain_id from outliner item (most reliable)
            chain_numeric = _get_numeric_chain_id_from_item(item_id)

            # Fallback: try chain mapping from mesh
            if chain_numeric is None:
                chain_mapping = get_chain_mapping_from_object(obj)
                if chain_mapping:
                    for num_id, letter in chain_mapping.items():
                        if letter == chain_id:
                            chain_numeric = num_id
                            break

            if chain_numeric is not None:
                chain_attr = [c.value for c in mesh.attributes["chain_id"].data]
                chain_res = [res_ids[i] for i in range(len(res_ids))
                             if chain_attr[i] == chain_numeric]
                if chain_res:
                    return (min(chain_res), max(chain_res))

        # Fallback: all residues in the object
        if res_ids:
            return (min(res_ids), max(res_ids))
    except Exception as e:
        logger.warning(f"Failed to get residue range: {e}")

    return (1, 999)


def _draw_linker_form(layout, op):
    """Shared dialog body for Add Linker and Edit Linker.

    Both operators declare the same set of properties (puppet_selector,
    endpoint_a/b_item, endpoint_a/b_residue, linker_name, length_residues,
    style, behavior, color, tube_radius, bead_*, binding_zone_residues),
    so a single draw helper keeps the two dialogs guaranteed-identical.

    Reads the operator's current properties as ``op.<name>`` and the
    helper-callback context as ``self.puppet_selector`` from inside the
    EnumProperty callbacks (those use ``self`` because they're bound to
    the operator instance — same name on Add and Edit).
    """
    import math

    layout.prop(op, "linker_name")

    # Puppet selector
    layout.prop(op, "puppet_selector")
    layout.separator()

    # Strip prefixes to get real item_ids for helper lookups
    item_a = _strip_endpoint_prefix(op.endpoint_a_item)
    item_b = _strip_endpoint_prefix(op.endpoint_b_item)

    # Endpoint A
    box = layout.box()
    box.label(text="Start Endpoint", icon='TRACKING_BACKWARDS')
    box.prop(op, "endpoint_a_item")
    if item_a and item_a != 'NONE':
        chain_a = get_chain_letter_for_item(item_a)
        if chain_a:
            box.label(text=f"Chain: {chain_a}", icon='INFO')
        min_a, max_a = get_residue_range_for_item(item_a, chain_a)
        box.prop(op, "endpoint_a_residue")
        box.label(text=f"Valid range: {min_a} - {max_a}")

    layout.separator()

    # Endpoint B
    box = layout.box()
    box.label(text="End Endpoint", icon='TRACKING_FORWARDS')
    box.prop(op, "endpoint_b_item")
    if item_b and item_b != 'NONE':
        chain_b = get_chain_letter_for_item(item_b)
        if chain_b:
            box.label(text=f"Chain: {chain_b}", icon='INFO')
        min_b, max_b = get_residue_range_for_item(item_b, chain_b)
        box.prop(op, "endpoint_b_residue")
        box.label(text=f"Valid range: {min_b} - {max_b}")

    layout.separator()

    # Length / distance info
    min_residues = 3
    if (item_a and item_a != 'NONE'
            and item_b and item_b != 'NONE'):
        chain_a = get_chain_letter_for_item(item_a)
        chain_b = get_chain_letter_for_item(item_b)
        dist = compute_min_distance(
            item_a, chain_a, op.endpoint_a_residue,
            item_b, chain_b, op.endpoint_b_residue,
        )
        if dist >= 0:
            min_residues = max(min_residues, math.ceil(dist / BU_PER_RESIDUE))
            if op.length_residues < min_residues:
                op.length_residues = min_residues

    layout.prop(op, "length_residues")
    if min_residues > 3:
        layout.label(text=f"Minimum length: {min_residues} residues (current distance)")
    max_reach = op.length_residues * BU_PER_RESIDUE
    max_reach_angstrom = op.length_residues * 3.5
    layout.label(text=f"Max reach: {max_reach:.3f} BU ({max_reach_angstrom:.1f} Å)")

    if (item_a and item_a != 'NONE'
            and item_b and item_b != 'NONE'):
        chain_a = get_chain_letter_for_item(item_a)
        chain_b = get_chain_letter_for_item(item_b)
        dist = compute_min_distance(
            item_a, chain_a, op.endpoint_a_residue,
            item_b, chain_b, op.endpoint_b_residue,
        )
        if dist >= 0:
            dist_angstrom = dist / MN_SCALE if MN_SCALE > 0 else 0
            layout.label(text=f"Current distance: {dist:.3f} BU ({dist_angstrom:.1f} Å)")

    layout.separator()

    # Appearance
    box = layout.box()
    box.label(text="Appearance", icon='MATERIAL')
    box.prop(op, "style")
    box.prop(op, "behavior")
    if op.behavior == 'RANDOM_COIL':
        box.prop(op, "coil_width")
    box.prop(op, "color")
    if op.style == 'TUBE':
        box.prop(op, "tube_radius")
    elif op.style == 'BEADS':
        box.prop(op, "bead_radius")
        box.prop(op, "bead_radius_variance")
        box.prop(op, "bead_overlap")
        box.prop(op, "bead_jitter")

    bz_row = box.row(align=True)
    bz_row.prop(op, "binding_zone_residues")
    help_op = bz_row.operator("pb2.show_help_popup", text="", icon='QUESTION')
    help_op.title = "Binding Zone"
    help_op.message = (
        "The binding zone is the number of residues at each end of the "
        "linker that stay rigid and align with the backbone direction "
        "of the connected chain. This prevents the linker from bending "
        "unnaturally right at the attachment point, mimicking how real "
        "peptide linkers emerge from a protein surface."
    )


def get_puppet_controller(context, puppet_id: str):
    """Get the puppet controller Empty object."""
    if not hasattr(context.scene, 'outliner_items'):
        return None

    for item in context.scene.outliner_items:
        if item.item_id == puppet_id and item.item_type == 'PUPPET':
            return bpy.data.objects.get(item.controller_object_name)
    return None


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class PB2_OT_add_linker(Operator):
    """Add a flexible linker between two chains within the same puppet"""
    bl_idname = "pb2.add_linker"
    bl_label = "Add Flexible Linker"
    bl_options = {'REGISTER', 'UNDO'}

    puppet_selector: EnumProperty(
        name="Puppet",
        description="Puppet to create the linker within",
        items=get_puppet_items
    )

    endpoint_a_item: EnumProperty(
        name="Start Chain",
        description="Chain/domain for start endpoint",
        items=get_chain_items_a,
        update=_update_endpoint_a_residue
    )

    endpoint_a_residue: IntProperty(
        name="Residue A",
        description="Residue number for start endpoint",
        default=1,
        min=1
    )

    endpoint_b_item: EnumProperty(
        name="End Chain",
        description="Chain/domain for end endpoint",
        items=get_chain_items_b,
        update=_update_endpoint_b_residue
    )

    endpoint_b_residue: IntProperty(
        name="Residue B",
        description="Residue number for end endpoint",
        default=1,
        min=1
    )

    linker_name: StringProperty(
        name="Name",
        description="Display name for the linker",
        default="Linker"
    )

    length_residues: IntProperty(
        name="Length (residues)",
        description="Number of amino acid residues (determines max reach)",
        default=10,
        min=3,
        max=100
    )

    style: EnumProperty(
        name="Style",
        items=[
            ('TUBE', "Tube", "Smooth tube (adjustable radius)"),
            ('BEADS', "Beads", "Irregular beads representing each amino acid residue"),
        ],
        default='TUBE'
    )

    rendering_mode: EnumProperty(
        name="Rendering",
        items=[
            ('QUICK', "Quick", "Styled Bezier curve with catenary physics"),
            ('DETAILED', "Detailed (coming soon)",
             "MolecularNodes peptide geometry along curve. Not yet "
             "implemented — currently falls back to Quick so the linker "
             "stays visible"),
        ],
        default='QUICK'
    )

    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        min=0.0, max=1.0,
        default=(0.7, 0.7, 0.7, 1.0)
    )

    tube_radius: FloatProperty(
        name="Radius",
        description="Radius of the tube",
        default=0.015,
        min=0.001, soft_max=0.03, max=0.1,
        step=0.1
    )

    # Bead-style appearance — only drawn when style == 'BEADS'.
    bead_radius: FloatProperty(
        name="Bead Radius",
        description="Base radius of each bead",
        default=0.020,
        min=0.001, max=0.1,
        unit='LENGTH',
    )
    bead_radius_variance: FloatProperty(
        name="Radius Variance",
        description="How much bead sizes vary (0 = all same size, 1 = max variation)",
        default=0.5,
        min=0.0, max=1.0,
        subtype='FACTOR',
    )
    bead_overlap: FloatProperty(
        name="Bead Overlap",
        description="Fraction of overlap between adjacent beads (0 = touching, no overlap)",
        default=0.3,
        min=0.0, max=0.95,
        subtype='FACTOR',
    )
    bead_jitter: FloatProperty(
        name="Bead Jitter",
        description="Random positional offset perpendicular to the curve",
        default=0.3,
        min=0.0, max=1.0,
        subtype='FACTOR',
    )

    behavior: EnumProperty(
        name="Behavior",
        description="How the linker responds to slack",
        items=[
            ('RANDOM_COIL', "Random Coil", "Wiggly disordered path — realistic intrinsically disordered region"),
            ('GRAVITY', "Gravity", "Catenary droop — linker sags downward like a hanging chain"),
            ('ZERO_G', "Zero-G", "No gravity — slack distributes as a smooth arc with no preferred direction"),
        ],
        default='RANDOM_COIL'
    )

    coil_width: FloatProperty(
        name="Coil Width",
        description="Random-coil loop radius. Smaller = more, tighter coils; "
                    "larger = fewer, looser loops",
        default=0.06, min=0.005, soft_max=0.15, max=0.3, step=0.1, unit='LENGTH',
    )

    binding_zone_residues: IntProperty(
        name="Binding Zone (residues)",
        description="Rigid zone at each endpoint to prevent chain collision",
        default=3,
        min=1,
        max=10
    )

    def invoke(self, context, event):
        # Default the two endpoints to different items when possible, then snap
        # each residue to the first one that actually exists there (assigning
        # the endpoint items fires the update callbacks that do the snapping).
        items = _build_chain_items_for_puppet(context, self.puppet_selector)
        if items and items[0][0] != 'NONE':
            self.endpoint_a_item = f"A_{items[0][0]}"
        if len(items) >= 2:
            self.endpoint_b_item = f"B_{items[1][0]}"
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        _draw_linker_form(self.layout, self)

    def execute(self, context):
        scene = context.scene

        puppet_id = self.puppet_selector

        # Validate puppet selection
        if not puppet_id or puppet_id == 'NONE':
            self.report({'ERROR'}, "Please select a puppet")
            return {'CANCELLED'}

        # Strip A_/B_ prefixes to get real item_ids
        item_a = _strip_endpoint_prefix(self.endpoint_a_item)
        item_b = _strip_endpoint_prefix(self.endpoint_b_item)

        logger.info(f"Linker create: raw_a='{self.endpoint_a_item}' raw_b='{self.endpoint_b_item}'")
        logger.info(f"Linker create: item_a='{item_a}' item_b='{item_b}' puppet='{puppet_id}'")

        # Validate endpoints
        if item_a == 'NONE' or item_b == 'NONE':
            self.report({'ERROR'}, "Please select both endpoints")
            return {'CANCELLED'}

        chain_a = get_chain_letter_for_item(item_a)
        chain_b = get_chain_letter_for_item(item_b)

        logger.info(f"Linker create: chain_a='{chain_a}' chain_b='{chain_b}'")

        # Validate not linking same chain to itself
        if item_a == item_b:
            self.report({'ERROR'}, "Start and end must be different chains")
            return {'CANCELLED'}

        # Validate not linking same residue on same chain (safety net)
        if (item_a == item_b and
            self.endpoint_a_residue == self.endpoint_b_residue):
            self.report({'ERROR'}, "Cannot link a residue to itself")
            return {'CANCELLED'}

        # Get endpoint positions. If the requested residue doesn't exist in the
        # endpoint (typically the default 1 on a domain that starts at 51),
        # retry at the endpoint's first real residue rather than hard-failing.
        start_pos = get_residue_position_from_item(
            item_a, chain_a, self.endpoint_a_residue
        )
        if start_pos is None:
            lo_a = _endpoint_first_residue(self.endpoint_a_item)
            if lo_a is not None and lo_a != self.endpoint_a_residue:
                self.endpoint_a_residue = lo_a
                start_pos = get_residue_position_from_item(item_a, chain_a, lo_a)

        end_pos = get_residue_position_from_item(
            item_b, chain_b, self.endpoint_b_residue
        )
        if end_pos is None:
            lo_b = _endpoint_first_residue(self.endpoint_b_item)
            if lo_b is not None and lo_b != self.endpoint_b_residue:
                self.endpoint_b_residue = lo_b
                end_pos = get_residue_position_from_item(item_b, chain_b, lo_b)

        if start_pos is None:
            self.report({'ERROR'}, f"Could not find residue {chain_a}:{self.endpoint_a_residue}")
            return {'CANCELLED'}
        if end_pos is None:
            self.report({'ERROR'}, f"Could not find residue {chain_b}:{self.endpoint_b_residue}")
            return {'CANCELLED'}

        logger.info(f"Linker create: start_pos={start_pos} end_pos={end_pos}")

        # Ensure length covers the current distance between endpoints
        import math
        current_dist = (end_pos - start_pos).length
        min_residues = max(3, math.ceil(current_dist / BU_PER_RESIDUE))
        if self.length_residues < min_residues:
            self.length_residues = min_residues

        # Get backbone directions for rigid binding zones
        obj_a = get_object_for_item(item_a)
        obj_b = get_object_for_item(item_b)
        num_chain_a = _get_numeric_chain_id_from_item(item_a)
        num_chain_b = _get_numeric_chain_id_from_item(item_b)
        start_dir = get_backbone_direction(obj_a, chain_a, self.endpoint_a_residue,
                                           numeric_chain_id=num_chain_a) if obj_a else None
        end_dir = get_backbone_direction(obj_b, chain_b, self.endpoint_b_residue,
                                         numeric_chain_id=num_chain_b) if obj_b else None

        # Create linker definition
        linker = scene.pb2_linkers.add()
        linker.uid = generate_linker_uid()
        linker.name = self.linker_name or f"Linker {len(scene.pb2_linkers)}"
        linker.puppet_id = puppet_id

        linker.endpoint_a_item_id = item_a
        linker.endpoint_a_chain = chain_a
        linker.endpoint_a_residue = self.endpoint_a_residue

        linker.endpoint_b_item_id = item_b
        linker.endpoint_b_chain = chain_b
        linker.endpoint_b_residue = self.endpoint_b_residue

        linker.length_residues = self.length_residues
        linker.style = self.style
        linker.rendering_mode = self.rendering_mode
        linker.behavior = self.behavior
        linker.coil_width = self.coil_width
        linker.color = self.color
        linker.tube_radius = self.tube_radius
        linker.bead_radius = self.bead_radius
        linker.bead_radius_variance = self.bead_radius_variance
        linker.bead_overlap = self.bead_overlap
        linker.bead_jitter = self.bead_jitter
        linker.binding_zone_residues = self.binding_zone_residues

        # Parent to puppet controller
        controller = get_puppet_controller(context, puppet_id)
        collection = None
        if controller and controller.users_collection:
            collection = controller.users_collection[0]

        # Create geometry
        curve_obj = create_linker_curve(
            linker, start_pos, end_pos,
            start_dir, end_dir,
            collection, controller
        )

        if curve_obj:
            self.report({'INFO'}, f"Created linker: {linker.name}")
            scene.pb2_linkers_index = len(scene.pb2_linkers) - 1
            return {'FINISHED'}
        else:
            scene.pb2_linkers.remove(len(scene.pb2_linkers) - 1)
            self.report({'ERROR'}, "Failed to create linker geometry")
            return {'CANCELLED'}


class PB2_OT_remove_linker(Operator):
    """Remove a flexible linker"""
    bl_idname = "pb2.remove_linker"
    bl_label = "Remove Linker"
    bl_options = {'REGISTER', 'UNDO'}

    linker_uid: StringProperty(name="Linker UID")

    def execute(self, context):
        scene = context.scene

        linker_index = -1
        for i, linker in enumerate(scene.pb2_linkers):
            if linker.uid == self.linker_uid:
                linker_index = i
                break

        if linker_index < 0:
            self.report({'ERROR'}, "Linker not found")
            return {'CANCELLED'}

        linker = scene.pb2_linkers[linker_index]
        linker_name = linker.name

        delete_linker_geometry(linker)
        scene.pb2_linkers.remove(linker_index)

        if scene.pb2_linkers_index >= len(scene.pb2_linkers):
            scene.pb2_linkers_index = max(0, len(scene.pb2_linkers) - 1)

        self.report({'INFO'}, f"Removed linker: {linker_name}")
        return {'FINISHED'}


class PB2_OT_update_linker(Operator):
    """Update linker geometry"""
    bl_idname = "pb2.update_linker"
    bl_label = "Update Linker"
    bl_options = {'REGISTER', 'UNDO'}

    linker_uid: StringProperty(name="Linker UID")

    def execute(self, context):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                if update_linker_curve(linker):
                    self.report({'INFO'}, f"Updated linker: {linker.name}")
                    return {'FINISHED'}
                else:
                    self.report({'WARNING'}, f"Could not update linker: {linker.name}")
                    return {'CANCELLED'}

        self.report({'ERROR'}, "Linker not found")
        return {'CANCELLED'}


class PB2_OT_update_all_linkers(Operator):
    """Update all linker geometries"""
    bl_idname = "pb2.update_all_linkers"
    bl_label = "Update All Linkers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        updated = 0
        failed = 0

        for linker in context.scene.pb2_linkers:
            if update_linker_curve(linker):
                updated += 1
            else:
                failed += 1

        if failed > 0:
            self.report({'WARNING'}, f"Updated {updated} linkers, {failed} failed")
        else:
            self.report({'INFO'}, f"Updated {updated} linkers")

        return {'FINISHED'}


class PB2_OT_toggle_linker_visibility(Operator):
    """Toggle linker visibility"""
    bl_idname = "pb2.toggle_linker_visibility"
    bl_label = "Toggle Linker Visibility"
    bl_options = {'REGISTER', 'UNDO'}

    linker_uid: StringProperty(name="Linker UID")

    def execute(self, context):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                toggle_linker_visibility(linker, not linker.is_visible)
                return {'FINISHED'}

        self.report({'ERROR'}, "Linker not found")
        return {'CANCELLED'}


class PB2_OT_edit_linker(Operator):
    """Edit linker properties"""
    bl_idname = "pb2.edit_linker"
    bl_label = "Edit Linker"
    bl_options = {'REGISTER', 'UNDO'}

    linker_uid: StringProperty(name="Linker UID")

    # === Same property set as PB2_OT_add_linker (identical names so the
    # shared draw helper + the puppet/chain Enum callbacks bind to both).
    puppet_selector: EnumProperty(
        name="Puppet",
        description="Puppet the linker belongs to",
        items=get_puppet_items,
    )
    endpoint_a_item: EnumProperty(
        name="Start Chain",
        description="Chain/domain for start endpoint",
        items=get_chain_items_a,
    )
    endpoint_a_residue: IntProperty(
        name="Residue A",
        description="Residue number for start endpoint",
        default=1, min=1,
    )
    endpoint_b_item: EnumProperty(
        name="End Chain",
        description="Chain/domain for end endpoint",
        items=get_chain_items_b,
    )
    endpoint_b_residue: IntProperty(
        name="Residue B",
        description="Residue number for end endpoint",
        default=1, min=1,
    )

    linker_name: StringProperty(name="Name")
    length_residues: IntProperty(name="Length (residues)", min=3, max=100)
    style: EnumProperty(
        name="Style",
        items=[
            ('TUBE', "Tube", "Smooth tube (adjustable radius)"),
            ('BEADS', "Beads", "Irregular beads representing each amino acid residue"),
        ]
    )
    rendering_mode: EnumProperty(
        name="Rendering",
        items=[
            ('QUICK', "Quick", "Styled Bezier curve"),
            ('DETAILED', "Detailed (coming soon)",
             "MolecularNodes peptide geometry. Not yet implemented — "
             "currently falls back to Quick so the linker stays visible"),
        ]
    )
    behavior: EnumProperty(
        name="Behavior",
        items=[
            ('RANDOM_COIL', "Random Coil", "Wiggly disordered path — realistic intrinsically disordered region"),
            ('GRAVITY', "Gravity", "Catenary droop — linker sags downward like a hanging chain"),
            ('ZERO_G', "Zero-G", "No gravity — slack distributes as a smooth arc with no preferred direction"),
        ],
        default='RANDOM_COIL'
    )
    coil_width: FloatProperty(
        name="Coil Width", default=0.06, min=0.005, soft_max=0.15, max=0.3,
        step=0.1, unit='LENGTH')
    color: FloatVectorProperty(name="Color", subtype='COLOR', size=4, min=0.0, max=1.0)
    tube_radius: FloatProperty(name="Radius", default=0.015, min=0.001, soft_max=0.03, max=0.1, step=0.1)
    # Bead-style appearance — only drawn when style == 'BEADS'.
    bead_radius: FloatProperty(
        name="Bead Radius", default=0.020, min=0.001, max=0.1, unit='LENGTH')
    bead_radius_variance: FloatProperty(
        name="Radius Variance", default=0.5, min=0.0, max=1.0, subtype='FACTOR')
    bead_overlap: FloatProperty(
        name="Bead Overlap", default=0.3, min=0.0, max=0.95, subtype='FACTOR')
    bead_jitter: FloatProperty(
        name="Bead Jitter", default=0.3, min=0.0, max=1.0, subtype='FACTOR')
    binding_zone_residues: IntProperty(name="Binding Zone", min=1, max=10)

    def invoke(self, context, event):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                # Endpoint props use A_/B_ prefixed enum identifiers (so
                # the same outliner item_id can appear in both dropdowns
                # without colliding) \u2014 prefix when seeding from the
                # stored unprefixed values on the linker.
                self.puppet_selector = linker.puppet_id
                self.endpoint_a_item = f"A_{linker.endpoint_a_item_id}"
                self.endpoint_a_residue = linker.endpoint_a_residue
                self.endpoint_b_item = f"B_{linker.endpoint_b_item_id}"
                self.endpoint_b_residue = linker.endpoint_b_residue
                self.linker_name = linker.name
                self.length_residues = linker.length_residues
                self.style = linker.style
                self.rendering_mode = linker.rendering_mode
                self.behavior = linker.behavior
                self.coil_width = linker.coil_width
                self.color = linker.color
                self.tube_radius = linker.tube_radius
                self.bead_radius = linker.bead_radius
                self.bead_radius_variance = linker.bead_radius_variance
                self.bead_overlap = linker.bead_overlap
                self.bead_jitter = linker.bead_jitter
                self.binding_zone_residues = linker.binding_zone_residues
                break

        # width=450 matches PB2_OT_add_linker so both dialogs are the
        # same shape too.
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        # Shared body \u2014 guaranteed identical to PB2_OT_add_linker.
        _draw_linker_form(self.layout, self)

    def execute(self, context):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                # Resolve (possibly-changed) endpoints from the prefixed
                # enum values and write them back to the linker. If the
                # user re-routed via the dialog, the geometry rebuild
                # below uses the new endpoints.
                puppet_id = self.puppet_selector
                item_a = _strip_endpoint_prefix(self.endpoint_a_item)
                item_b = _strip_endpoint_prefix(self.endpoint_b_item)
                if not puppet_id or puppet_id == 'NONE':
                    self.report({'ERROR'}, "Please select a puppet")
                    return {'CANCELLED'}
                if item_a == 'NONE' or item_b == 'NONE':
                    self.report({'ERROR'}, "Please select both endpoints")
                    return {'CANCELLED'}
                if item_a == item_b:
                    self.report({'ERROR'}, "Start and end must be different chains")
                    return {'CANCELLED'}

                linker.puppet_id = puppet_id
                linker.endpoint_a_item_id = item_a
                linker.endpoint_a_chain = get_chain_letter_for_item(item_a)
                linker.endpoint_a_residue = self.endpoint_a_residue
                linker.endpoint_b_item_id = item_b
                linker.endpoint_b_chain = get_chain_letter_for_item(item_b)
                linker.endpoint_b_residue = self.endpoint_b_residue

                linker.name = self.linker_name
                linker.length_residues = self.length_residues
                linker.style = self.style
                linker.rendering_mode = self.rendering_mode
                linker.behavior = self.behavior
                linker.coil_width = self.coil_width
                linker.color = self.color
                linker.tube_radius = self.tube_radius
                linker.bead_radius = self.bead_radius
                linker.bead_radius_variance = self.bead_radius_variance
                linker.bead_overlap = self.bead_overlap
                linker.bead_jitter = self.bead_jitter
                linker.binding_zone_residues = self.binding_zone_residues

                # Rebuild geometry with new settings
                delete_linker_geometry(linker)

                start_pos = get_residue_position_from_item(
                    linker.endpoint_a_item_id,
                    linker.endpoint_a_chain,
                    linker.endpoint_a_residue
                )
                end_pos = get_residue_position_from_item(
                    linker.endpoint_b_item_id,
                    linker.endpoint_b_chain,
                    linker.endpoint_b_residue
                )

                if start_pos and end_pos:
                    obj_a = get_object_for_item(linker.endpoint_a_item_id)
                    obj_b = get_object_for_item(linker.endpoint_b_item_id)
                    num_chain_a = _get_numeric_chain_id_from_item(linker.endpoint_a_item_id)
                    num_chain_b = _get_numeric_chain_id_from_item(linker.endpoint_b_item_id)
                    start_dir = get_backbone_direction(
                        obj_a, linker.endpoint_a_chain, linker.endpoint_a_residue,
                        numeric_chain_id=num_chain_a
                    ) if obj_a else None
                    end_dir = get_backbone_direction(
                        obj_b, linker.endpoint_b_chain, linker.endpoint_b_residue,
                        numeric_chain_id=num_chain_b
                    ) if obj_b else None

                    # Parent to puppet controller
                    controller = get_puppet_controller(context, linker.puppet_id)
                    collection = None
                    if controller and controller.users_collection:
                        collection = controller.users_collection[0]

                    create_linker_curve(
                        linker, start_pos, end_pos,
                        start_dir, end_dir,
                        collection, controller
                    )

                self.report({'INFO'}, f"Updated linker: {linker.name}")
                return {'FINISHED'}

        self.report({'ERROR'}, "Linker not found")
        return {'CANCELLED'}


class PB2_OT_select_linker_object(Operator):
    """Select the linker object in the viewport"""
    bl_idname = "pb2.select_linker_object"
    bl_label = "Select Linker Object"

    linker_uid: StringProperty(name="Linker UID")

    def execute(self, context):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                obj = bpy.data.objects.get(linker.curve_object_name)
                if obj:
                    bpy.ops.object.select_all(action='DESELECT')
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    return {'FINISHED'}
                else:
                    self.report({'WARNING'}, "Linker object not found")
                    return {'CANCELLED'}

        self.report({'ERROR'}, "Linker not found")
        return {'CANCELLED'}


# Registration
CLASSES = [
    PB2_OT_add_linker,
    PB2_OT_remove_linker,
    PB2_OT_update_linker,
    PB2_OT_update_all_linkers,
    PB2_OT_toggle_linker_visibility,
    PB2_OT_edit_linker,
    PB2_OT_select_linker_object,
]


def register():
    """Register linker operators."""
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    """Unregister linker operators."""
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
