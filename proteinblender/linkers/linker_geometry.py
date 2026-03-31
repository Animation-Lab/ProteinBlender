"""Linker geometry creation using Blender curves with catenary physics.

This module handles creation of flexible linker curves between protein
domains within a puppet. The linker behaves like a string/tube:
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

# Constants
ANGSTROM_PER_RESIDUE = 3.5
MN_SCALE = 0.01  # MolecularNodes scale: 1 BU = 100 Angstroms
BU_PER_RESIDUE = ANGSTROM_PER_RESIDUE * MN_SCALE  # 0.035 BU per residue


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

    # Get the numeric chain_id from the outliner item itself.
    # This is more reliable than chain_mapping_str on the mesh (which may not exist).
    numeric_chain_id = _get_numeric_chain_id_from_item(item_id)

    logger.info(f"Resolving position: item={item_id} -> obj='{obj.name}' "
                f"chain={chain_id} numeric_chain={numeric_chain_id} res={residue_num}")

    pos = _get_residue_position_from_object(obj, chain_id, residue_num,
                                             numeric_chain_id=numeric_chain_id)

    # If position not found on the item's own object (e.g., single-chain domain
    # object that doesn't contain the requested chain), try the parent molecule
    # object which may contain all chains.
    if pos is None and obj.parent:
        logger.info(f"  Not found on '{obj.name}', trying parent '{obj.parent.name}'")
        pos = _get_residue_position_from_object(obj.parent, chain_id, residue_num,
                                                 numeric_chain_id=numeric_chain_id)

    return pos


def _get_numeric_chain_id_from_item(item_id: str) -> Optional[int]:
    """Get the numeric chain_id stored on an outliner item.

    Outliner chain items store the numeric chain index (e.g., "0", "9") in
    their chain_id property. This directly corresponds to the chain_id mesh
    attribute values, making it the most reliable way to filter vertices by chain.

    Args:
        item_id: Outliner item_id

    Returns:
        Numeric chain_id as int, or None if not found
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return None

    for item in scene.outliner_items:
        if item.item_id == item_id:
            chain_str = getattr(item, 'chain_id', '')
            if chain_str and chain_str.isdigit():
                return int(chain_str)
            # Also check parent chain item if this is a domain item
            if item.item_type == 'DOMAIN' and item.parent_id:
                for parent_item in scene.outliner_items:
                    if parent_item.item_id == item.parent_id:
                        parent_chain = getattr(parent_item, 'chain_id', '')
                        if parent_chain and parent_chain.isdigit():
                            return int(parent_chain)
                        break
            return None
    return None


def get_object_for_item(item_id: str) -> Optional[bpy.types.Object]:
    """Resolve an outliner item_id to its Blender object."""
    scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return None

    for item in scene.outliner_items:
        if item.item_id == item_id:
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                logger.info(f"  item_id '{item_id}' -> object '{item.object_name}' "
                            f"(chain_id='{getattr(item, 'chain_id', '')}', "
                            f"item_type='{item.item_type}')")
            else:
                logger.warning(f"  item_id '{item_id}' -> object_name '{item.object_name}' NOT FOUND in bpy.data.objects")
            return obj
    return None


def _get_residue_position_from_object(obj: bpy.types.Object, chain_id: str,
                                       residue_num: int,
                                       numeric_chain_id: Optional[int] = None) -> Optional[Vector]:
    """Get residue position from a specific Blender mesh object.

    Searches mesh attributes for the target residue, preferring alpha
    carbon (CA) atoms. Uses the numeric chain ID from the outliner item
    for reliable chain filtering on multi-chain mesh objects.

    Args:
        obj: Blender mesh object to search
        chain_id: Chain letter (e.g., 'A')
        residue_num: Residue number
        numeric_chain_id: Numeric chain_id from the outliner item (most reliable)

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

    # Determine the numeric chain_id to filter by.
    # Priority: 1) numeric_chain_id from outliner item (most reliable)
    #           2) chain_mapping_str on mesh (may not exist)
    #           3) single-chain object detection
    chain_numeric = numeric_chain_id

    if chain_numeric is None:
        # Fallback: try chain mapping from mesh custom property
        chain_mapping = get_chain_mapping_from_object(obj)
        if chain_mapping:
            for num_id, letter in chain_mapping.items():
                if letter == chain_id:
                    chain_numeric = num_id
                    break

    # If still no match, try additional strategies
    if chain_numeric is None and has_chain_id_attr:
        chain_attr = mesh.attributes["chain_id"].data
        unique_chains = set()
        for c in chain_attr:
            unique_chains.add(c.value)

        if len(unique_chains) == 1:
            chain_numeric = unique_chains.pop()
            logger.info(f"  Single-chain object '{obj.name}' has chain_id={chain_numeric}")
        else:
            logger.info(f"  Multi-chain object '{obj.name}' has chain_ids={unique_chains}, "
                        f"no numeric_chain_id provided, looking for '{chain_id}'")

    logger.info(f"  Searching obj='{obj.name}' for chain_numeric={chain_numeric} "
                f"res={residue_num} (has_chain_attr={has_chain_id_attr})")

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
                            residue_num: int,
                            numeric_chain_id: Optional[int] = None) -> Optional[Vector]:
    """Get backbone direction at a residue by finding CA positions of neighbors.

    Computes the vector from CA(residue-1) to CA(residue+1) to get the
    local backbone direction at the binding point. This is used for
    rigid binding zones.

    Args:
        obj: Blender mesh object containing the chain
        chain_id: Chain letter
        residue_num: Residue number at the binding point
        numeric_chain_id: Numeric chain_id from the outliner item

    Returns:
        Normalized direction vector in world space, or None
    """
    pos_prev = _get_residue_position_from_object(obj, chain_id, residue_num - 1,
                                                  numeric_chain_id=numeric_chain_id)
    pos_next = _get_residue_position_from_object(obj, chain_id, residue_num + 1,
                                                  numeric_chain_id=numeric_chain_id)
    pos_curr = _get_residue_position_from_object(obj, chain_id, residue_num,
                                                  numeric_chain_id=numeric_chain_id)

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


def compute_zero_g_points(start: Vector, end: Vector,
                           total_length: float,
                           num_samples: int = 9) -> List[Vector]:
    """Compute points along a smooth arc with no gravity bias.

    When the linker has slack, the excess length is distributed as a
    symmetric parabolic bulge perpendicular to the start-end axis.
    The bulge direction is chosen automatically: perpendicular to the
    line connecting the endpoints, biased away from the midpoint of
    the two parent objects when possible, otherwise an arbitrary
    perpendicular direction.

    When taut, returns a straight line.

    Args:
        start: Start position (world space)
        end: End position (world space)
        total_length: Total linker length in BU
        num_samples: Number of sample points (including endpoints)

    Returns:
        List of Vector positions sampled along the arc
    """
    D = (end - start).length
    L = total_length

    # Taut or nearly taut: straight line
    if D >= L * 0.99 or D < 1e-6:
        return [start.lerp(end, t / max(num_samples - 1, 1))
                for t in range(num_samples)]

    direction = end - start

    # Find a perpendicular direction for the bulge
    # Try cross with world-up first, fall back to world-right
    perp = direction.cross(Vector((0, 0, 1)))
    if perp.length < 0.1:
        perp = direction.cross(Vector((0, 1, 0)))
    if perp.length < 0.1:
        perp = direction.cross(Vector((1, 0, 0)))
    perp = perp.normalized()

    # Amount of bulge from excess length
    # For a parabolic arc: L ≈ D + (8*sag²)/(3*D)
    # Solving for sag: sag = sqrt(3*D*(L-D)/8)
    sag_amount = math.sqrt(max(0, 3.0 * D * (L - D) / 8.0))

    points = []
    for i in range(num_samples):
        t = i / max(num_samples - 1, 1)
        base = start.lerp(end, t)
        # Parabolic bulge: maximum at t=0.5, zero at t=0 and t=1
        bulge = 4.0 * t * (1.0 - t) * sag_amount
        points.append(base + perp * bulge)

    return points


def _arc_length(points: List[Vector]) -> float:
    """Compute the total arc length of a polyline."""
    length = 0.0
    for i in range(1, len(points)):
        length += (points[i] - points[i - 1]).length
    return length


def _generate_random_coil_shape(start: Vector, end: Vector,
                                 amplitude: float,
                                 num_samples: int,
                                 perp1: Vector, perp2: Vector,
                                 freqs: List[float], amps: List[float],
                                 phase_offsets: List[float]) -> List[Vector]:
    """Generate wiggly coil points at a given amplitude scale.

    Helper for compute_random_coil_points — separated so we can iterate
    on the amplitude to match a target arc length.
    """
    amp_sum = sum(amps)
    points = []
    for i in range(num_samples):
        t = i / max(num_samples - 1, 1)
        base = start.lerp(end, t)

        # Envelope: zero at endpoints, max in middle
        envelope = 4.0 * t * (1.0 - t)

        # Sum sinusoidal components in both perpendicular directions
        offset1 = 0.0
        offset2 = 0.0
        for k in range(len(freqs)):
            angle1 = 2.0 * math.pi * freqs[k] * t + phase_offsets[k]
            angle2 = 2.0 * math.pi * freqs[k] * t + phase_offsets[k + 3]
            offset1 += amps[k] * math.sin(angle1)
            offset2 += amps[k] * math.cos(angle2)

        offset1 = (offset1 / amp_sum) * amplitude * envelope
        offset2 = (offset2 / amp_sum) * amplitude * envelope

        points.append(base + perp1 * offset1 + perp2 * offset2)

    return points


def compute_random_coil_points(start: Vector, end: Vector,
                                total_length: float,
                                num_residues: int = 10,
                                seed: int = 0) -> List[Vector]:
    """Compute points along a wiggly random-coil path whose arc length
    matches total_length.

    Simulates an intrinsically disordered region by layering sinusoidal
    perturbations at multiple frequencies in two perpendicular directions.
    The wiggle amplitude is iteratively adjusted so the polyline arc length
    equals total_length (the linker's physical length in BU).

    The seed (derived from the linker UID) makes the shape deterministic —
    same linker always produces the same wiggle pattern, but different
    linkers look distinct. When taut, returns a straight line.

    Args:
        start: Start position (world space)
        end: End position (world space)
        total_length: Target arc length of the path in BU
        num_residues: Number of residues (controls sample density)
        seed: Integer seed for deterministic noise pattern

    Returns:
        List of Vector positions sampled along the wiggly path
    """
    D = (end - start).length
    L = total_length

    # More samples for smoother wiggles (~3 per residue)
    num_samples = max(9, num_residues * 3)

    # Taut or nearly taut: straight line
    if D >= L * 0.99 or D < 1e-6:
        return [start.lerp(end, t / max(num_samples - 1, 1))
                for t in range(num_samples)]

    direction = (end - start).normalized()

    # Build two perpendicular axes
    perp1 = direction.cross(Vector((0, 0, 1)))
    if perp1.length < 0.1:
        perp1 = direction.cross(Vector((0, 1, 0)))
    perp1 = perp1.normalized()
    perp2 = direction.cross(perp1).normalized()

    # Phase offsets from seed so each linker looks different
    # Use golden ratio multiples for well-distributed phases
    phi = 1.6180339887
    phase_offsets = [seed * phi * (k + 1) for k in range(6)]

    # Frequency multipliers (prime-ish ratios avoid repetitive patterns)
    freqs = [2.0, 3.0, 5.0]
    # Amplitude falloff for higher frequencies (1/f character)
    amps = [1.0, 0.5, 0.25]

    # Binary search for the amplitude that makes arc length == total_length.
    # The straight-line distance D is the minimum arc length (amplitude=0).
    # We search between 0 and a generous upper bound.
    amp_lo = 0.0
    amp_hi = L  # generous upper bound
    best_amplitude = 0.0
    best_points = None

    for _ in range(30):
        amp_mid = (amp_lo + amp_hi) / 2.0
        pts = _generate_random_coil_shape(
            start, end, amp_mid, num_samples,
            perp1, perp2, freqs, amps, phase_offsets
        )
        arc = _arc_length(pts)

        if abs(arc - L) < L * 0.001:  # within 0.1% tolerance
            best_amplitude = amp_mid
            best_points = pts
            break

        if arc < L:
            amp_lo = amp_mid
        else:
            amp_hi = amp_mid

        best_amplitude = amp_mid
        best_points = pts

    return best_points


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

        # Clamp end position so the curve never stretches beyond max reach
        dist = (end_pos - start_pos).length
        if dist > total_length and dist > 1e-6:
            end_pos = start_pos + (end_pos - start_pos).normalized() * total_length

        # Compute curve sample points based on behavior
        behavior = linker_def.behavior
        if behavior == 'ZERO_G':
            catenary_points = compute_zero_g_points(start_pos, end_pos, total_length)
        elif behavior == 'RANDOM_COIL':
            catenary_points = compute_random_coil_points(
                start_pos, end_pos, total_length, linker_def.length_residues,
                seed=hash(linker_def.uid) & 0xFFFF
            )
        else:
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

        # Set up style-specific geometry nodes
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

    # Clamp end position so the curve never stretches beyond max reach
    dist = (end_pos - start_pos).length
    if dist > total_length and dist > 1e-6:
        end_pos = start_pos + (end_pos - start_pos).normalized() * total_length

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

    # Compute new curve points based on behavior
    behavior = linker_def.behavior
    if behavior == 'ZERO_G':
        catenary_points = compute_zero_g_points(start_pos, end_pos, total_length)
    elif behavior == 'RANDOM_COIL':
        catenary_points = compute_random_coil_points(
            start_pos, end_pos, total_length, linker_def.length_residues,
            seed=hash(linker_def.uid) & 0xFFFF
        )
    else:
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

    # Transform world-space catenary points to curve object's local space.
    # The curve is parented to the puppet controller, so bp.co must be in
    # local space — not world space — otherwise the linker won't follow
    # when the parent moves.
    inv_matrix = obj.matrix_world.inverted()

    for i, pos in enumerate(catenary_points):
        bp = spline.bezier_points[i]
        bp.co = inv_matrix @ pos
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'

    # Tag curve data so Blender knows it changed and GN modifiers re-evaluate
    obj.data.update_tag()
    obj.update_tag()

    # Reapply style (handles bevel changes if style or params changed)
    _apply_curve_style(obj.data, linker_def)

    # Handle style-specific GN modifiers — only rebuild if missing
    beads_mod = obj.modifiers.get("LinkerBeads")

    if linker_def.style == 'BEADS':
        if not beads_mod or not beads_mod.node_group:
            setup_beads_geometry_nodes(obj, linker_def)
    else:
        # TUBE style — remove any GN modifiers
        if beads_mod:
            _remove_beads_geometry_nodes(obj, linker_def.uid)

    # Update material
    setup_linker_material(obj, linker_def)

    return True


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

def _get_bsdf_color_input(bsdf):
    """Get the color input socket from a Principled BSDF node.

    Handles Blender version differences: 'Base Color' (pre-4.0)
    vs 'Color' (4.0+).
    """
    if "Base Color" in bsdf.inputs:
        return bsdf.inputs["Base Color"]
    if "Color" in bsdf.inputs:
        return bsdf.inputs["Color"]
    return None


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
        color_input = _get_bsdf_color_input(bsdf)
        if color_input:
            color_input.default_value = linker_def.color

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

    if style == 'TUBE':
        # Smooth round tube
        curve_data.bevel_depth = linker_def.tube_radius
        curve_data.bevel_resolution = 6  # Smooth circle cross-section
    elif style == 'BEADS':
        # No bevel on curve itself - geometry is added via geometry nodes
        curve_data.bevel_depth = 0
        curve_data.bevel_resolution = 0


def setup_beads_geometry_nodes(curve_obj: bpy.types.Object,
                                linker_def) -> None:
    """Set up geometry nodes for overlapping spherical beads.

    Simple and fast: UV spheres with random sizes placed along the curve
    with a small positional jitter perpendicular to the curve direction.
    No surface merging — just overlapping spheres with shade smooth.

    GN tree structure:
      Input Curve
        -> ResampleCurve (COUNT)
           -> SetPosition (random XYZ jitter offset)
           -> InstanceOnPoints (UV sphere, uniform random scale)
              -> SetMaterial -> SetShadeSmooth -> Output

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
        bpy.data.node_groups.remove(ng)

    ng = bpy.data.node_groups.new(ng_name, 'GeometryNodeTree')

    bead_radius = linker_def.bead_radius
    bead_overlap = linker_def.bead_overlap

    # Variance controls scale range: 0 = all same size, 1 = [1.0, 4.0]
    # Beads only grow larger — spacing is based on base size so beads
    # always touch at overlap=0, and any variance adds more contact.
    variance = linker_def.bead_radius_variance
    max_scale = 1.0 + (variance * 3.0)  # 1.0 at var=0, 4.0 at var=1

    # Overlap=0 means just touching (spacing = full diameter).
    # Overlap=1 would mean fully overlapping (spacing → 0).
    full_diameter = 2.0 * bead_radius  # diameter at scale 1.0
    spacing = full_diameter * (1.0 - bead_overlap)
    spacing = max(spacing, 0.001)

    # Convert spacing to bead count — COUNT mode distributes evenly
    # along the actual curve arc length, so no safety multiplier needed.
    curve_length = linker_def.length_residues * BU_PER_RESIDUE
    bead_count = max(3, round(curve_length / spacing))

    # Jitter amount — random positional offset, scaled by bead_radius
    jitter = bead_radius * linker_def.bead_jitter

    # Create interface sockets — only Geometry in/out
    ng.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry'
    )
    ng.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )

    nodes = ng.nodes
    links = ng.links

    # ── Group Input / Output ──
    input_node = nodes.new('NodeGroupInput')
    input_node.location = (-900, 0)
    output_node = nodes.new('NodeGroupOutput')
    output_node.location = (1200, 0)

    # ── Resample Curve (COUNT mode) ──
    resample = nodes.new('GeometryNodeResampleCurve')
    resample.location = (-500, 100)
    if hasattr(resample, 'mode'):
        resample.mode = 'COUNT'
    links.new(input_node.outputs["Geometry"], resample.inputs["Curve"])
    resample.inputs["Count"].default_value = bead_count

    # ── Positional jitter — random XYZ offset on resampled points ──
    rand_jitter = nodes.new('FunctionNodeRandomValue')
    rand_jitter.location = (-300, -100)
    if hasattr(rand_jitter, 'data_type'):
        rand_jitter.data_type = 'FLOAT_VECTOR'
    rand_jitter.inputs["Min"].default_value = (-jitter, -jitter, -jitter)
    rand_jitter.inputs["Max"].default_value = (jitter, jitter, jitter)
    rand_jitter.inputs["Seed"].default_value = 5

    set_pos = nodes.new('GeometryNodeSetPosition')
    set_pos.location = (-100, 100)
    links.new(resample.outputs["Curve"], set_pos.inputs["Geometry"])
    links.new(rand_jitter.outputs["Value"], set_pos.inputs["Offset"])

    # ── UV Sphere (unit sphere) ──
    uv_sphere = nodes.new('GeometryNodeMeshUVSphere')
    uv_sphere.location = (-500, -300)
    uv_sphere.inputs["Radius"].default_value = 1.0
    uv_sphere.inputs["Segments"].default_value = 16
    uv_sphere.inputs["Rings"].default_value = 8

    # ── Random scale (0.5 to 1.0) for size variation ──
    rand_scale = nodes.new('FunctionNodeRandomValue')
    rand_scale.location = (-300, -400)
    if hasattr(rand_scale, 'data_type'):
        rand_scale.data_type = 'FLOAT'
    rand_scale.inputs["Min"].default_value = 1.0
    rand_scale.inputs["Max"].default_value = max_scale
    rand_scale.inputs["Seed"].default_value = 1

    # Multiply random factor by bead_radius
    mul_radius = nodes.new('ShaderNodeMath')
    mul_radius.operation = 'MULTIPLY'
    mul_radius.location = (-100, -400)
    links.new(rand_scale.outputs["Value"], mul_radius.inputs[0])
    mul_radius.inputs[1].default_value = bead_radius

    # Combine into uniform scale vector (same value on all axes = sphere)
    combine_scale = nodes.new('ShaderNodeCombineXYZ')
    combine_scale.location = (100, -400)
    links.new(mul_radius.outputs[0], combine_scale.inputs['X'])
    links.new(mul_radius.outputs[0], combine_scale.inputs['Y'])
    links.new(mul_radius.outputs[0], combine_scale.inputs['Z'])

    # ── Instance on Points — place beads along jittered curve points ──
    instance_beads = nodes.new('GeometryNodeInstanceOnPoints')
    instance_beads.location = (350, 100)
    links.new(set_pos.outputs["Geometry"], instance_beads.inputs["Points"])
    links.new(uv_sphere.outputs["Mesh"], instance_beads.inputs["Instance"])
    links.new(combine_scale.outputs["Vector"], instance_beads.inputs["Scale"])

    # ── Set Material ──
    set_mat = nodes.new('GeometryNodeSetMaterial')
    set_mat.location = (600, 0)
    mat_name = f"Linker_{linker_def.uid}_material"
    mat = bpy.data.materials.get(mat_name)
    if mat:
        set_mat.inputs["Material"].default_value = mat
    links.new(instance_beads.outputs["Instances"], set_mat.inputs["Geometry"])

    # ── Set Shade Smooth ──
    shade_smooth = nodes.new('GeometryNodeSetShadeSmooth')
    shade_smooth.location = (850, 0)
    shade_smooth.inputs["Shade Smooth"].default_value = True
    links.new(set_mat.outputs["Geometry"], shade_smooth.inputs["Geometry"])

    # Connect to output
    links.new(shade_smooth.outputs["Geometry"], output_node.inputs["Geometry"])

    # Assign node group to modifier
    mod.node_group = ng


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
        # Clean up all style-specific geometry nodes before removing object
        _remove_beads_geometry_nodes(obj, linker_def.uid)

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


def register():
    """Register geometry-related items."""
    pass


def unregister():
    """Unregister geometry-related items."""
    pass
