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
        for member_id in member_ids:
            for item in context.scene.outliner_items:
                if item.item_id == member_id:
                    items.append((member_id, item.name, f"{item.name} in {puppet_item.name}"))
                    break
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


def get_chain_letter_for_item(item_id: str) -> str:
    """Extract the chain letter from an outliner item.

    Reads the item's object mesh attributes to determine the chain ID letter.
    Falls back to extracting from the item name.
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return ""

    for item in scene.outliner_items:
        if item.item_id == item_id:
            # Try to get from item name (often "Chain A", "Chain B", etc.)
            name = item.name
            if "Chain " in name:
                parts = name.split("Chain ")
                if len(parts) > 1:
                    return parts[-1].strip().split()[0]

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
        items=get_chain_items_a
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
        items=get_chain_items_b
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
            ('DETAILED', "Detailed", "MolecularNodes peptide geometry along curve"),
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

    behavior: EnumProperty(
        name="Behavior",
        description="How the linker responds to slack",
        items=[
            ('GRAVITY', "Gravity", "Catenary droop — linker sags downward like a hanging chain"),
            ('ZERO_G', "Zero-G", "No gravity — slack distributes as a smooth arc with no preferred direction"),
            ('RANDOM_COIL', "Random Coil", "Wiggly disordered path — realistic intrinsically disordered region"),
        ],
        default='GRAVITY'
    )

    binding_zone_residues: IntProperty(
        name="Binding Zone (residues)",
        description="Rigid zone at each endpoint to prevent chain collision",
        default=3,
        min=1,
        max=10
    )

    def invoke(self, context, event):
        # Default endpoint B to a different chain than A when possible
        items = _build_chain_items_for_puppet(context, self.puppet_selector)
        if len(items) >= 2:
            self.endpoint_b_item = f"B_{items[1][0]}"
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "linker_name")

        # Puppet selector
        layout.prop(self, "puppet_selector")
        layout.separator()

        # Strip prefixes to get real item_ids for helper lookups
        item_a = _strip_endpoint_prefix(self.endpoint_a_item)
        item_b = _strip_endpoint_prefix(self.endpoint_b_item)

        # Endpoint A
        box = layout.box()
        box.label(text="Start Endpoint", icon='TRACKING_BACKWARDS')
        box.prop(self, "endpoint_a_item")

        if item_a and item_a != 'NONE':
            chain_a = get_chain_letter_for_item(item_a)
            if chain_a:
                box.label(text=f"Chain: {chain_a}", icon='INFO')
            min_a, max_a = get_residue_range_for_item(item_a, chain_a)
            box.prop(self, "endpoint_a_residue")
            box.label(text=f"Valid range: {min_a} - {max_a}")

        layout.separator()

        # Endpoint B
        box = layout.box()
        box.label(text="End Endpoint", icon='TRACKING_FORWARDS')
        box.prop(self, "endpoint_b_item")

        if item_b and item_b != 'NONE':
            chain_b = get_chain_letter_for_item(item_b)
            if chain_b:
                box.label(text=f"Chain: {chain_b}", icon='INFO')
            min_b, max_b = get_residue_range_for_item(item_b, chain_b)
            box.prop(self, "endpoint_b_residue")
            box.label(text=f"Valid range: {min_b} - {max_b}")

        layout.separator()

        # Length and distance info
        # Compute minimum residues needed to span current distance
        import math
        min_residues = 3  # absolute floor
        if (item_a and item_a != 'NONE' and
            item_b and item_b != 'NONE'):
            chain_a = get_chain_letter_for_item(item_a)
            chain_b = get_chain_letter_for_item(item_b)
            dist = compute_min_distance(
                item_a, chain_a, self.endpoint_a_residue,
                item_b, chain_b, self.endpoint_b_residue
            )
            if dist >= 0:
                min_residues = max(min_residues, math.ceil(dist / BU_PER_RESIDUE))
                # Auto-clamp length upward if below minimum
                if self.length_residues < min_residues:
                    self.length_residues = min_residues

        layout.prop(self, "length_residues")
        if min_residues > 3:
            layout.label(text=f"Minimum length: {min_residues} residues (current distance)")
        max_reach = self.length_residues * BU_PER_RESIDUE
        max_reach_angstrom = self.length_residues * 3.5
        layout.label(text=f"Max reach: {max_reach:.3f} BU ({max_reach_angstrom:.1f} \u00C5)")

        # Show current distance
        if (item_a and item_a != 'NONE' and
            item_b and item_b != 'NONE'):
            chain_a = get_chain_letter_for_item(item_a)
            chain_b = get_chain_letter_for_item(item_b)
            dist = compute_min_distance(
                item_a, chain_a, self.endpoint_a_residue,
                item_b, chain_b, self.endpoint_b_residue
            )
            if dist >= 0:
                dist_angstrom = dist / MN_SCALE if MN_SCALE > 0 else 0
                layout.label(text=f"Current distance: {dist:.3f} BU ({dist_angstrom:.1f} \u00C5)")

        layout.separator()

        # Appearance
        box = layout.box()
        box.label(text="Appearance", icon='MATERIAL')
        box.prop(self, "style")
        box.prop(self, "rendering_mode")
        box.prop(self, "behavior")
        box.prop(self, "color")

        if self.style == 'TUBE':
            box.prop(self, "tube_radius")

        box.prop(self, "binding_zone_residues")

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

        # Get endpoint positions
        start_pos = get_residue_position_from_item(
            item_a, chain_a, self.endpoint_a_residue
        )
        end_pos = get_residue_position_from_item(
            item_b, chain_b, self.endpoint_b_residue
        )

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
        linker.color = self.color
        linker.tube_radius = self.tube_radius
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
            ('DETAILED', "Detailed", "MolecularNodes peptide geometry"),
        ]
    )
    behavior: EnumProperty(
        name="Behavior",
        items=[
            ('GRAVITY', "Gravity", "Catenary droop — linker sags downward like a hanging chain"),
            ('ZERO_G', "Zero-G", "No gravity — slack distributes as a smooth arc with no preferred direction"),
            ('RANDOM_COIL', "Random Coil", "Wiggly disordered path — realistic intrinsically disordered region"),
        ]
    )
    color: FloatVectorProperty(name="Color", subtype='COLOR', size=4, min=0.0, max=1.0)
    tube_radius: FloatProperty(name="Radius", default=0.015, min=0.001, soft_max=0.03, max=0.1, step=0.1)
    binding_zone_residues: IntProperty(name="Binding Zone", min=1, max=10)

    def invoke(self, context, event):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                self.linker_name = linker.name
                self.length_residues = linker.length_residues
                self.style = linker.style
                self.rendering_mode = linker.rendering_mode
                self.behavior = linker.behavior
                self.color = linker.color
                self.tube_radius = linker.tube_radius
                self.binding_zone_residues = linker.binding_zone_residues
                break

        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "linker_name")
        layout.prop(self, "length_residues")

        max_reach = self.length_residues * BU_PER_RESIDUE
        layout.label(text=f"Max reach: {max_reach:.3f} BU ({self.length_residues * 3.5:.1f} \u00C5)")

        layout.separator()
        box = layout.box()
        box.label(text="Appearance", icon='MATERIAL')
        box.prop(self, "style")
        box.prop(self, "rendering_mode")
        box.prop(self, "behavior")
        box.prop(self, "color")

        if self.style == 'TUBE':
            box.prop(self, "tube_radius")

        box.prop(self, "binding_zone_residues")

    def execute(self, context):
        for linker in context.scene.pb2_linkers:
            if linker.uid == self.linker_uid:
                linker.name = self.linker_name
                linker.length_residues = self.length_residues
                linker.style = self.style
                linker.rendering_mode = self.rendering_mode
                linker.behavior = self.behavior
                linker.color = self.color
                linker.tube_radius = self.tube_radius
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
