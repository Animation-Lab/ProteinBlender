"""Linker geometry creation using Blender curves with catenary physics.

This module handles creation of flexible linker curves between protein
domains within a puppet. The linker behaves like a string/ribbon:
- Fixed length determined by residue count
- Catenary shape when there's slack (floppy string under gravity)
- Rigid binding zones at endpoints aligned with backbone direction
- Two rendering modes: Quick (styled curve) and Detailed (MN Peptide to Curve)
"""

import bpy
import math
from mathutils import Vector, Matrix
from typing import Tuple, List, Optional
import logging

logger = logging.getLogger(__name__)

# Cache for ribbon profile curves
_ribbon_profile_cache = {}

# Constants
ANGSTROM_PER_RESIDUE = 3.5
MN_SCALE = 0.01  # MolecularNodes scale: 1 BU = 100 Angstroms
BU_PER_RESIDUE = ANGSTROM_PER_RESIDUE * MN_SCALE  # 0.035 BU per residue


def _get_or_create_ribbon_profile(width: float) -> Optional[bpy.types.Object]:
    """Get or create a flat ribbon profile curve for beveling.

    Args:
        width: Width of the ribbon in Blender units

    Returns:
        Curve object for use as bevel_object, or None on failure
    """
    global _ribbon_profile_cache

    width_key = round(width, 3)

    if width_key in _ribbon_profile_cache:
        profile_obj = _ribbon_profile_cache[width_key]
        if profile_obj and profile_obj.name in bpy.data.objects:
            return profile_obj

    try:
        profile_name = f"LinkerRibbonProfile_{width_key}"

        existing = bpy.data.objects.get(profile_name)
        if existing:
            _ribbon_profile_cache[width_key] = existing
            return existing

        curve_data = bpy.data.curves.new(name=profile_name, type='CURVE')
        curve_data.dimensions = '2D'

        spline = curve_data.splines.new('POLY')
        spline.points.add(1)

        half_width = width / 2
        spline.points[0].co = (-half_width, 0, 0, 1)
        spline.points[1].co = (half_width, 0, 0, 1)

        profile_obj = bpy.data.objects.new(name=profile_name, object_data=curve_data)
        bpy.context.scene.collection.objects.link(profile_obj)
        profile_obj.hide_viewport = True
        profile_obj.hide_render = True
        profile_obj.hide_select = True

        _ribbon_profile_cache[width_key] = profile_obj
        return profile_obj

    except Exception as e:
        logger.error(f"Failed to create ribbon profile: {e}")
        return None


# ---------------------------------------------------------------------------
# Residue position helpers
# ---------------------------------------------------------------------------

def get_residue_position_from_item(item_id: str, chain_id: str,
                                    residue_num: int) -> Optional[Vector]:
    """Get world position of a residue from an outliner item.

    Resolves the outliner item to a Blender object and searches its
    mesh attributes for the residue's alpha carbon position.

    Args:
        item_id: Outliner item_id (e.g., "mol123_chain_A")
        chain_id: Chain letter (e.g., 'A')
        residue_num: Residue number at the binding point

    Returns:
        World position Vector or None if not found
    """
    obj = get_object_for_item(item_id)
    if not obj:
        logger.warning(f"No object found for item {item_id}")
        return None

    return _get_residue_position_from_object(obj, chain_id, residue_num)


def get_object_for_item(item_id: str) -> Optional[bpy.types.Object]:
    """Resolve an outliner item_id to its Blender object."""
    scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return None

    for item in scene.outliner_items:
        if item.item_id == item_id:
            return bpy.data.objects.get(item.object_name)
    return None


def _get_residue_position_from_object(obj: bpy.types.Object, chain_id: str,
                                       residue_num: int) -> Optional[Vector]:
    """Get residue position from a specific Blender mesh object.

    Searches mesh attributes for the target residue, preferring alpha
    carbon (CA) atoms.

    Args:
        obj: Blender mesh object to search
        chain_id: Chain letter (e.g., 'A')
        residue_num: Residue number

    Returns:
        World position Vector or None if not found
    """
    from ..utils.chain_utils import get_chain_mapping_from_object

    mesh = obj.data
    if not mesh or not hasattr(mesh, 'attributes'):
        return None

    if "res_id" not in mesh.attributes:
        return obj.matrix_world @ Vector((0, 0, 0))

    res_ids = mesh.attributes["res_id"].data
    positions = mesh.vertices
    has_chain_id_attr = "chain_id" in mesh.attributes
    has_is_alpha = "is_alpha_carbon" in mesh.attributes

    # Get chain mapping to convert letter -> numeric
    chain_mapping = get_chain_mapping_from_object(obj)
    chain_numeric = None
    if chain_mapping:
        for num_id, letter in chain_mapping.items():
            if letter == chain_id:
                chain_numeric = num_id
                break

    best_pos = None
    for i, res in enumerate(res_ids):
        if res.value != residue_num:
            continue

        # Check chain if available
        if has_chain_id_attr and chain_numeric is not None:
            chain_attr = mesh.attributes["chain_id"].data
            if chain_attr[i].value != chain_numeric:
                continue

        pos = Vector(positions[i].co)

        # Prefer alpha carbons
        if has_is_alpha:
            is_alpha = mesh.attributes["is_alpha_carbon"].data
            if is_alpha[i].value:
                return obj.matrix_world @ pos

        if best_pos is None:
            best_pos = obj.matrix_world @ pos

    return best_pos


def get_backbone_direction(obj: bpy.types.Object, chain_id: str,
                            residue_num: int) -> Optional[Vector]:
    """Get backbone direction at a residue by finding CA positions of neighbors.

    Computes the vector from CA(residue-1) to CA(residue+1) to get the
    local backbone direction at the binding point. This is used for
    rigid binding zones.

    Args:
        obj: Blender mesh object containing the chain
        chain_id: Chain letter
        residue_num: Residue number at the binding point

    Returns:
        Normalized direction vector in world space, or None
    """
    pos_prev = _get_residue_position_from_object(obj, chain_id, residue_num - 1)
    pos_next = _get_residue_position_from_object(obj, chain_id, residue_num + 1)
    pos_curr = _get_residue_position_from_object(obj, chain_id, residue_num)

    if pos_prev and pos_next:
        direction = (pos_next - pos_prev).normalized()
        return direction
    elif pos_next and pos_curr:
        return (pos_next - pos_curr).normalized()
    elif pos_prev and pos_curr:
        return (pos_curr - pos_prev).normalized()

    return None


def compute_min_distance(item_id_a: str, chain_a: str, res_a: int,
                          item_id_b: str, chain_b: str, res_b: int) -> float:
    """Compute current distance between two binding points.

    Args:
        item_id_a: Outliner item_id for endpoint A
        chain_a: Chain letter for endpoint A
        res_a: Residue number for endpoint A
        item_id_b: Outliner item_id for endpoint B
        chain_b: Chain letter for endpoint B
        res_b: Residue number for endpoint B

    Returns:
        Distance in Blender units, or -1 if positions can't be found
    """
    pos_a = get_residue_position_from_item(item_id_a, chain_a, res_a)
    pos_b = get_residue_position_from_item(item_id_b, chain_b, res_b)

    if pos_a is None or pos_b is None:
        return -1.0

    return (pos_b - pos_a).length


# ---------------------------------------------------------------------------
# Catenary curve computation
# ---------------------------------------------------------------------------

def compute_catenary_points(start: Vector, end: Vector,
                             total_length: float,
                             num_samples: int = 9,
                             gravity_dir: Vector = None) -> List[Vector]:
    """Compute points along a catenary curve of fixed length.

    The catenary is the shape a uniform flexible chain assumes hanging
    freely under gravity between two fixed endpoints. This gives the
    linker its "floppy string" behavior when there's slack.

    Args:
        start: Start position (world space)
        end: End position (world space)
        total_length: Total linker length in BU
        num_samples: Number of sample points (including endpoints)
        gravity_dir: Direction of gravity (default: -Z)

    Returns:
        List of Vector positions sampled along the catenary
    """
    if gravity_dir is None:
        gravity_dir = Vector((0, 0, -1))

    D = (end - start).length
    L = total_length

    # Taut or nearly taut: straight line
    if D >= L * 0.99 or D < 1e-6:
        return [start.lerp(end, t / max(num_samples - 1, 1))
                for t in range(num_samples)]

    direction = end - start
    grav_norm = gravity_dir.normalized()

    # Build local coordinate frame:
    # u_horiz: horizontal direction (start-to-end projected perpendicular to gravity)
    # u_vert: gravity direction
    vertical_component = direction.dot(grav_norm) * grav_norm
    horizontal_component = direction - vertical_component

    h_dist = horizontal_component.length  # horizontal span
    v_dist = direction.dot(grav_norm)      # signed vertical drop

    # If endpoints are nearly vertical, pick a perpendicular sag direction
    if h_dist < 1e-6:
        # Vertical connection: sag in an arbitrary perpendicular direction
        perp = direction.cross(Vector((1, 0, 0)))
        if perp.length < 0.1:
            perp = direction.cross(Vector((0, 1, 0)))
        perp = perp.normalized()

        # Distribute points along the vertical with parabolic sag sideways
        sag_amount = math.sqrt(max(0, L * L - D * D)) / 2
        points = []
        for i in range(num_samples):
            t = i / max(num_samples - 1, 1)
            base = start.lerp(end, t)
            # Parabolic bulge: max at t=0.5, zero at t=0 and t=1
            bulge = 4.0 * t * (1.0 - t) * sag_amount
            points.append(base + perp * bulge)
        return points

    u_horiz = horizontal_component.normalized()

    # Solve for catenary parameter 'a':
    # Arc length of catenary between x=0 and x=h_dist:
    #   L_cat = sqrt(v_dist^2 + (2*a*sinh(h_dist/(2*a)))^2) approximately
    # For the symmetric case (v_dist=0): L = 2*a*sinh(h_dist/(2*a))
    # For general case, we use a different parameterization.
    #
    # We solve in the projected horizontal plane, then correct for vertical offset.
    # The catenary sag gives us the additional droop below the straight line.

    # Compute how much extra length is available for sag
    straight_dist = D
    excess = L - straight_dist  # always positive since D < L*0.99

    # For a symmetric catenary y = a*cosh(x/a) - a between x=-h/2 and x=h/2:
    # Arc length = 2*a*sinh(h/(2*a))
    # We need: 2*a*sinh(h_dist/(2*a)) = L_horizontal
    # where L_horizontal accounts for the horizontal component of the total length

    # Simpler approach: solve for sag depth using the relationship between
    # excess length and sag for a parabolic approximation (accurate for moderate sag)
    # For a parabola: L ~= D + (8*sag^2)/(3*D), so sag = sqrt(3*D*excess/8)
    # For a catenary, we use Newton-Raphson for better accuracy

    # Newton-Raphson to solve: 2*a*sinh(h_dist/(2*a)) = L_target
    # where L_target is the horizontal arc length component
    L_target = math.sqrt(L * L - v_dist * v_dist) if abs(v_dist) < L else L * 0.99

    if L_target <= h_dist:
        # No room for sag after accounting for vertical drop
        return [start.lerp(end, t / max(num_samples - 1, 1))
                for t in range(num_samples)]

    a = _solve_catenary_parameter(h_dist, L_target)

    if a is None:
        # Solver failed, fall back to parabolic approximation
        sag = math.sqrt(max(0, 3.0 * h_dist * (L_target - h_dist) / 8.0))
        points = []
        for i in range(num_samples):
            t = i / max(num_samples - 1, 1)
            base = start.lerp(end, t)
            bulge = 4.0 * t * (1.0 - t) * sag
            points.append(base + grav_norm * bulge)
        return points

    # Sample the catenary in local 2D coordinates
    # x in [0, h_dist], y = a*cosh((x - x0)/a) + c
    # where x0 is the x-coordinate of the catenary minimum
    # and c is chosen to match endpoint heights

    # For the general (asymmetric) case with vertical offset:
    # We parameterize: x from -h_dist/2 to +h_dist/2
    # y(x) = a * cosh(x/a)
    # Then offset to match start/end vertical positions

    half_h = h_dist / 2.0
    y_start_local = a * math.cosh(-half_h / a)
    y_end_local = a * math.cosh(half_h / a)
    y_min_local = a  # minimum of cosh at x=0

    points = []
    for i in range(num_samples):
        t = i / max(num_samples - 1, 1)

        # Local x coordinate along horizontal span
        x_local = -half_h + t * h_dist

        # Catenary y (sag depth below the line connecting endpoints)
        y_cat = a * math.cosh(x_local / a)

        # Normalize: at endpoints y should be 0 (no sag), maximum sag at center
        # y_cat ranges from y_min_local (center) to y_start_local/y_end_local (edges)
        # We want sag = y_cat - (lerp between y_start and y_end)
        y_line = y_start_local + t * (y_end_local - y_start_local)
        sag_at_t = y_cat - y_line  # negative = below the line

        # Since cosh is convex, the middle sags below the chord
        # But we computed it as y_cat - y_line which is negative at the center
        # The actual droop below the chord: negate it and apply along gravity
        droop = -(y_cat - y_line)

        # World position: interpolate along start-to-end, then offset by droop
        base = start.lerp(end, t)
        points.append(base + grav_norm * droop)

    return points


def _solve_catenary_parameter(h_dist: float, L_target: float,
                                max_iterations: int = 50) -> Optional[float]:
    """Solve for catenary parameter 'a' using Newton-Raphson.

    Solves: 2*a*sinh(h_dist/(2*a)) = L_target

    Args:
        h_dist: Horizontal distance between endpoints
        L_target: Target arc length (must be > h_dist)
        max_iterations: Max Newton iterations

    Returns:
        Catenary parameter 'a', or None if solver failed
    """
    if L_target <= h_dist * 1.001:
        return None  # Nearly straight, catenary parameter would be huge

    # Initial guess based on parabolic approximation
    # For a parabola with sag s: L ~= D + 8s^2/(3D)
    # So s ~= sqrt(3*D*(L-D)/8)
    # And for catenary: a ~= D^2/(8*s)
    sag_approx = math.sqrt(max(1e-10, 3.0 * h_dist * (L_target - h_dist) / 8.0))
    a = max(1e-6, h_dist * h_dist / (8.0 * sag_approx))

    half_h = h_dist / 2.0

    for _ in range(max_iterations):
        try:
            sinh_val = math.sinh(half_h / a)
            cosh_val = math.cosh(half_h / a)
        except OverflowError:
            a *= 2.0
            continue

        f = 2.0 * a * sinh_val - L_target
        # Derivative: f'(a) = 2*sinh(h/(2a)) - h*cosh(h/(2a))/a
        f_prime = 2.0 * sinh_val - (h_dist * cosh_val) / a

        if abs(f_prime) < 1e-15:
            break

        a_new = a - f / f_prime

        if a_new <= 0:
            a *= 0.5
            continue

        if abs(a_new - a) < 1e-12 * abs(a):
            return a_new

        a = a_new

    return a


# ---------------------------------------------------------------------------
# Rigid binding zones
# ---------------------------------------------------------------------------

def apply_rigid_binding_zones(points: List[Vector],
                               start_direction: Optional[Vector],
                               end_direction: Optional[Vector],
                               zone_length_bu: float) -> List[Vector]:
    """Force first/last portions of curve to align with backbone direction.

    Makes the linker exit each chain smoothly in the backbone direction,
    preventing visual collision between the linker and the protein chain.

    Args:
        points: Catenary sample points
        start_direction: Backbone direction at start (world space)
        end_direction: Backbone direction at end (world space)
        zone_length_bu: Length of rigid zone in BU

    Returns:
        Modified list of points
    """
    if len(points) < 3:
        return points

    result = [p.copy() for p in points]
    total_length = sum((points[i + 1] - points[i]).length
                       for i in range(len(points) - 1))

    if total_length < 1e-8:
        return result

    # Apply start binding zone
    if start_direction is not None:
        cumulative = 0.0
        for i in range(1, len(result)):
            seg_len = (points[i] - points[i - 1]).length
            cumulative += seg_len

            if cumulative > zone_length_bu:
                break

            # Blend factor: 1.0 at start, 0.0 at zone boundary
            blend = 1.0 - (cumulative / zone_length_bu)
            # Smooth cubic ease
            blend = blend * blend * (3.0 - 2.0 * blend)

            # Rigid position: project along backbone direction
            rigid_pos = points[0] + start_direction * cumulative
            # Blend between rigid and catenary
            result[i] = rigid_pos.lerp(points[i], 1.0 - blend)

    # Apply end binding zone
    if end_direction is not None:
        # Reverse direction for end (linker approaches chain from outside)
        end_dir_reversed = -end_direction
        cumulative = 0.0
        for i in range(len(result) - 2, -1, -1):
            seg_len = (points[i + 1] - points[i]).length
            cumulative += seg_len

            if cumulative > zone_length_bu:
                break

            blend = 1.0 - (cumulative / zone_length_bu)
            blend = blend * blend * (3.0 - 2.0 * blend)

            rigid_pos = points[-1] + end_dir_reversed * cumulative
            result[i] = rigid_pos.lerp(points[i], 1.0 - blend)

    return result


# ---------------------------------------------------------------------------
# Curve creation and update
# ---------------------------------------------------------------------------

def create_linker_curve(linker_def, start_pos: Vector, end_pos: Vector,
                         start_backbone_dir: Optional[Vector] = None,
                         end_backbone_dir: Optional[Vector] = None,
                         collection: Optional[bpy.types.Collection] = None,
                         parent: Optional[bpy.types.Object] = None
                         ) -> Optional[bpy.types.Object]:
    """Create a Bezier curve object for a linker with catenary shape.

    Args:
        linker_def: PB2_LinkerDefinition PropertyGroup
        start_pos: World position of start endpoint
        end_pos: World position of end endpoint
        start_backbone_dir: Backbone direction at start residue
        end_backbone_dir: Backbone direction at end residue
        collection: Collection to link the curve to
        parent: Parent object (puppet controller Empty)

    Returns:
        Created curve object or None on failure
    """
    try:
        total_length = linker_def.length_residues * BU_PER_RESIDUE
        zone_length = linker_def.binding_zone_residues * BU_PER_RESIDUE

        # Compute catenary sample points
        catenary_points = compute_catenary_points(start_pos, end_pos, total_length)

        # Apply rigid binding zones
        catenary_points = apply_rigid_binding_zones(
            catenary_points, start_backbone_dir, end_backbone_dir, zone_length
        )

        # Create curve data
        curve_name = f"Linker_{linker_def.uid}_curve"
        curve_data = bpy.data.curves.new(name=curve_name, type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 12
        curve_data.fill_mode = 'FULL'

        # Create Bezier spline from catenary points
        spline = curve_data.splines.new('BEZIER')
        num_points = len(catenary_points)
        spline.bezier_points.add(num_points - 1)

        for i, pos in enumerate(catenary_points):
            bp = spline.bezier_points[i]
            bp.co = pos
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'

        # Apply style-specific bevel/geometry
        _apply_curve_style(curve_data, linker_def)

        # Create curve object
        obj_name = f"Linker_{linker_def.uid}"
        curve_obj = bpy.data.objects.new(name=obj_name, object_data=curve_data)

        # Link to collection
        if collection:
            collection.objects.link(curve_obj)
        else:
            bpy.context.scene.collection.objects.link(curve_obj)

        # Parent to puppet controller
        if parent:
            curve_obj.parent = parent
            curve_obj.matrix_parent_inverse = parent.matrix_world.inverted()

        # Store reference
        linker_def.curve_object_name = curve_obj.name

        # Set up material
        setup_linker_material(curve_obj, linker_def)

        # Set up beads geometry nodes if BEADS style
        if linker_def.style == 'BEADS':
            setup_beads_geometry_nodes(curve_obj, linker_def)

        # Set up detailed rendering mode if requested
        if linker_def.rendering_mode == 'DETAILED':
            setup_detailed_mode(linker_def, curve_obj)

        logger.info(f"Created linker curve '{curve_obj.name}' from {start_pos} to {end_pos}")
        return curve_obj

    except Exception as e:
        logger.error(f"Failed to create linker curve: {e}")
        import traceback
        traceback.print_exc()
        return None


def update_linker_curve(linker_def) -> bool:
    """Update linker curve geometry based on current endpoint positions.

    Recomputes the catenary and updates the existing spline points.

    Args:
        linker_def: PB2_LinkerDefinition PropertyGroup

    Returns:
        True if update succeeded
    """
    obj = bpy.data.objects.get(linker_def.curve_object_name)
    if not obj or not obj.data or not obj.data.splines:
        return False

    # Get current endpoint positions
    start_pos = get_residue_position_from_item(
        linker_def.endpoint_a_item_id,
        linker_def.endpoint_a_chain,
        linker_def.endpoint_a_residue
    )
    end_pos = get_residue_position_from_item(
        linker_def.endpoint_b_item_id,
        linker_def.endpoint_b_chain,
        linker_def.endpoint_b_residue
    )

    if start_pos is None or end_pos is None:
        linker_def.is_valid = False
        return False

    linker_def.is_valid = True

    total_length = linker_def.length_residues * BU_PER_RESIDUE
    zone_length = linker_def.binding_zone_residues * BU_PER_RESIDUE

    # Get backbone directions
    obj_a = get_object_for_item(linker_def.endpoint_a_item_id)
    obj_b = get_object_for_item(linker_def.endpoint_b_item_id)

    start_dir = None
    end_dir = None
    if obj_a:
        start_dir = get_backbone_direction(
            obj_a, linker_def.endpoint_a_chain, linker_def.endpoint_a_residue
        )
    if obj_b:
        end_dir = get_backbone_direction(
            obj_b, linker_def.endpoint_b_chain, linker_def.endpoint_b_residue
        )

    # Compute new catenary points
    catenary_points = compute_catenary_points(start_pos, end_pos, total_length)
    catenary_points = apply_rigid_binding_zones(
        catenary_points, start_dir, end_dir, zone_length
    )

    # Update spline
    spline = obj.data.splines[0]
    num_existing = len(spline.bezier_points)
    num_new = len(catenary_points)

    if num_existing != num_new:
        # Need to rebuild spline (point count changed)
        obj.data.splines.remove(spline)
        spline = obj.data.splines.new('BEZIER')
        spline.bezier_points.add(num_new - 1)

    for i, pos in enumerate(catenary_points):
        bp = spline.bezier_points[i]
        bp.co = pos
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'

    # Reapply style (handles bevel changes if style or params changed)
    _apply_curve_style(obj.data, linker_def)

    # Handle beads geometry nodes
    has_beads_mod = obj.modifiers.get("LinkerBeads") is not None
    if linker_def.style == 'BEADS':
        setup_beads_geometry_nodes(obj, linker_def)
    elif has_beads_mod:
        _remove_beads_geometry_nodes(obj, linker_def.uid)

    # Update material
    setup_linker_material(obj, linker_def)

    return True


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

def setup_linker_material(obj: bpy.types.Object, linker_def) -> None:
    """Create and assign material for linker."""
    mat_name = f"Linker_{linker_def.uid}_material"

    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Roughness"].default_value = 0.6

    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = linker_def.color

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Style-specific curve setup
# ---------------------------------------------------------------------------

def _apply_curve_style(curve_data, linker_def) -> None:
    """Apply style-specific bevel/profile to curve data.

    Args:
        curve_data: Blender CurveData
        linker_def: PB2_LinkerDefinition PropertyGroup
    """
    style = linker_def.style

    if style == 'CARTOON':
        # Smooth round tube - spaghetti noodle look
        curve_data.bevel_depth = linker_def.cartoon_radius
        curve_data.bevel_resolution = 6  # Smooth circle cross-section
    elif style == 'RIBBON':
        # Flat ribbon using bevel profile object
        profile_curve = _get_or_create_ribbon_profile(linker_def.ribbon_width)
        if profile_curve:
            curve_data.bevel_mode = 'OBJECT'
            curve_data.bevel_object = profile_curve
        else:
            # Fallback to flat-ish profile
            curve_data.bevel_depth = linker_def.ribbon_width / 2
            curve_data.bevel_resolution = 0
    elif style == 'BEADS':
        # No bevel on curve itself - beads are added via geometry nodes
        curve_data.bevel_depth = 0
        curve_data.bevel_resolution = 0


def setup_beads_geometry_nodes(curve_obj: bpy.types.Object,
                                linker_def) -> None:
    """Set up geometry nodes to instance bead shapes along the curve.

    Creates one bead per residue with slight random scale variation
    to give an organic, irregular amino acid bead appearance.

    Args:
        curve_obj: The linker curve object
        linker_def: PB2_LinkerDefinition PropertyGroup
    """
    mod_name = "LinkerBeads"
    mod = curve_obj.modifiers.get(mod_name)
    if not mod:
        mod = curve_obj.modifiers.new(mod_name, 'NODES')

    ng_name = f"LinkerBeads_{linker_def.uid}"
    ng = bpy.data.node_groups.get(ng_name)

    if ng:
        # Remove and recreate to pick up new parameters
        bpy.data.node_groups.remove(ng)

    ng = bpy.data.node_groups.new(ng_name, 'GeometryNodeTree')

    # Create interface sockets
    ng.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry'
    )
    ng.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    count_socket = ng.interface.new_socket(
        name="Count", in_out='INPUT', socket_type='NodeSocketInt'
    )
    count_socket.default_value = linker_def.length_residues
    count_socket.min_value = 1

    size_socket = ng.interface.new_socket(
        name="Bead Size", in_out='INPUT', socket_type='NodeSocketFloat'
    )
    size_socket.default_value = linker_def.bead_size
    size_socket.min_value = 0.001

    randomness_socket = ng.interface.new_socket(
        name="Randomness", in_out='INPUT', socket_type='NodeSocketFloat'
    )
    randomness_socket.default_value = 0.3
    randomness_socket.min_value = 0.0
    randomness_socket.max_value = 1.0

    nodes = ng.nodes
    links = ng.links

    # Group Input / Output
    input_node = nodes.new('NodeGroupInput')
    input_node.location = (-800, 0)
    output_node = nodes.new('NodeGroupOutput')
    output_node.location = (800, 0)

    # Resample Curve - resample to exactly `Count` points
    resample = nodes.new('GeometryNodeResampleCurve')
    resample.location = (-400, 0)
    # Set mode to COUNT - handle both old property API and new menu socket API
    if hasattr(resample, 'mode'):
        resample.mode = 'COUNT'
    elif "Mode" in resample.inputs:
        resample.inputs["Mode"].default_value = 'Count'
    links.new(input_node.outputs["Geometry"], resample.inputs["Curve"])
    links.new(input_node.outputs["Count"], resample.inputs["Count"])

    # Ico Sphere mesh for bead shape (subdivision=2 for irregular feel)
    ico_sphere = nodes.new('GeometryNodeMeshIcoSphere')
    ico_sphere.location = (-200, -250)
    ico_sphere.inputs["Radius"].default_value = 1.0
    ico_sphere.inputs["Subdivisions"].default_value = 2

    # Random Value node for per-instance scale variation
    random_val = nodes.new('FunctionNodeRandomValue')
    random_val.location = (-200, -450)
    if hasattr(random_val, 'data_type'):
        random_val.data_type = 'FLOAT'
    # Min scale factor = 1.0 - randomness, max = 1.0 + randomness
    # We'll use a Math node to compute the range from the Randomness input

    # Math: 1.0 - Randomness (min scale)
    math_sub = nodes.new('ShaderNodeMath')
    math_sub.operation = 'SUBTRACT'
    math_sub.location = (-450, -400)
    math_sub.inputs[0].default_value = 1.0
    links.new(input_node.outputs["Randomness"], math_sub.inputs[1])

    # Math: 1.0 + Randomness (max scale)
    math_add = nodes.new('ShaderNodeMath')
    math_add.operation = 'ADD'
    math_add.location = (-450, -550)
    math_add.inputs[0].default_value = 1.0
    links.new(input_node.outputs["Randomness"], math_add.inputs[1])

    # Connect min/max to random value
    links.new(math_sub.outputs[0], random_val.inputs["Min"])
    links.new(math_add.outputs[0], random_val.inputs["Max"])

    # Multiply random scale factor by bead size
    math_scale = nodes.new('ShaderNodeMath')
    math_scale.operation = 'MULTIPLY'
    math_scale.location = (0, -350)
    links.new(random_val.outputs["Value"], math_scale.inputs[0])
    links.new(input_node.outputs["Bead Size"], math_scale.inputs[1])

    # Combine XYZ to make a scale vector from the single float
    combine_scale = nodes.new('ShaderNodeCombineXYZ')
    combine_scale.location = (200, -350)
    links.new(math_scale.outputs[0], combine_scale.inputs['X'])
    links.new(math_scale.outputs[0], combine_scale.inputs['Y'])
    links.new(math_scale.outputs[0], combine_scale.inputs['Z'])

    # Instance on Points - place beads at each resampled point
    instance_on_pts = nodes.new('GeometryNodeInstanceOnPoints')
    instance_on_pts.location = (400, 0)
    links.new(resample.outputs["Curve"], instance_on_pts.inputs["Points"])
    links.new(ico_sphere.outputs["Mesh"], instance_on_pts.inputs["Instance"])
    links.new(combine_scale.outputs["Vector"], instance_on_pts.inputs["Scale"])

    # Realize Instances - convert to real geometry
    realize = nodes.new('GeometryNodeRealizeInstances')
    realize.location = (600, 0)
    links.new(instance_on_pts.outputs["Instances"], realize.inputs["Geometry"])

    # Connect to output
    links.new(realize.outputs["Geometry"], output_node.inputs["Geometry"])

    # Assign node group to modifier
    mod.node_group = ng

    # Set modifier input values via socket identifiers
    for item in ng.interface.items_tree:
        if item.in_out != 'INPUT':
            continue
        ident = item.identifier
        if ident not in mod:
            continue
        if item.name == "Count":
            mod[ident] = linker_def.length_residues
        elif item.name == "Bead Size":
            mod[ident] = linker_def.bead_size
        elif item.name == "Randomness":
            mod[ident] = 0.3


def _remove_beads_geometry_nodes(curve_obj: bpy.types.Object,
                                  linker_uid: str) -> None:
    """Remove beads geometry nodes from a linker curve."""
    if not curve_obj:
        return
    mod = curve_obj.modifiers.get("LinkerBeads")
    if mod:
        curve_obj.modifiers.remove(mod)

    ng_name = f"LinkerBeads_{linker_uid}"
    ng = bpy.data.node_groups.get(ng_name)
    if ng and ng.users == 0:
        bpy.data.node_groups.remove(ng)


# ---------------------------------------------------------------------------
# Detailed rendering mode (MN Peptide to Curve)
# ---------------------------------------------------------------------------

def setup_detailed_mode(linker_def, curve_obj: bpy.types.Object) -> bool:
    """Set up MolecularNodes 'Animate Peptide to Curve' for detailed rendering.

    Appends the GN tree from the MN data file and creates a NODES modifier
    on the linker curve object.

    Args:
        linker_def: PB2_LinkerDefinition PropertyGroup
        curve_obj: The linker curve object

    Returns:
        True if setup succeeded
    """
    try:
        from ..utils.molecularnodes.blender.nodes import append, get_mod

        # Append the peptide-to-curve node tree
        tree = bpy.data.node_groups.get("Animate Peptide to Curve")
        if not tree:
            tree = append("Animate Peptide to Curve")

        if not tree:
            logger.warning("Could not load 'Animate Peptide to Curve' node tree")
            return False

        # Create modifier
        mod = get_mod(curve_obj, "LinkerPeptideToCurve")
        mod.node_group = tree

        logger.info(f"Set up detailed rendering for linker {linker_def.uid}")
        return True

    except Exception as e:
        logger.warning(f"Failed to set up detailed rendering: {e}")
        return False


def remove_detailed_mode(curve_obj: bpy.types.Object) -> None:
    """Remove the detailed rendering modifier from a linker curve."""
    if not curve_obj:
        return
    mod = curve_obj.modifiers.get("LinkerPeptideToCurve")
    if mod:
        curve_obj.modifiers.remove(mod)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def delete_linker_geometry(linker_def) -> None:
    """Remove linker geometry from scene."""
    obj = bpy.data.objects.get(linker_def.curve_object_name)
    if obj:
        # Clean up beads geometry nodes before removing object
        _remove_beads_geometry_nodes(obj, linker_def.uid)

        # Clean up ribbon profile reference
        if obj.data and hasattr(obj.data, 'bevel_object') and obj.data.bevel_object:
            profile = obj.data.bevel_object
            obj.data.bevel_object = None
            if profile and profile.users <= 1:
                profile_data = profile.data
                bpy.data.objects.remove(profile, do_unlink=True)
                if profile_data and profile_data.users == 0:
                    bpy.data.curves.remove(profile_data)

        curve_data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if curve_data and curve_data.users == 0:
            bpy.data.curves.remove(curve_data)

    # Remove material
    mat_name = f"Linker_{linker_def.uid}_material"
    mat = bpy.data.materials.get(mat_name)
    if mat and mat.users == 0:
        bpy.data.materials.remove(mat)

    linker_def.curve_object_name = ""


def toggle_linker_visibility(linker_def, visible: bool) -> None:
    """Toggle linker visibility."""
    obj = bpy.data.objects.get(linker_def.curve_object_name)
    if obj:
        obj.hide_viewport = not visible
        obj.hide_render = not visible
    linker_def.is_visible = visible


def cleanup_ribbon_profiles():
    """Clean up cached ribbon profile curves."""
    global _ribbon_profile_cache

    for width_key, profile_obj in list(_ribbon_profile_cache.items()):
        try:
            if profile_obj and profile_obj.name in bpy.data.objects:
                if profile_obj.data and profile_obj.data.users <= 1:
                    curve_data = profile_obj.data
                    bpy.data.objects.remove(profile_obj, do_unlink=True)
                    if curve_data and curve_data.users == 0:
                        bpy.data.curves.remove(curve_data)
        except (ReferenceError, KeyError):
            pass
        finally:
            _ribbon_profile_cache.pop(width_key, None)


def register():
    """Register geometry-related items."""
    pass


def unregister():
    """Unregister geometry-related items."""
    cleanup_ribbon_profiles()
