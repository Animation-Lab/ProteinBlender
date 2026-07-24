"""Pure-logic unit tests for proteinblender/linkers/linker_geometry.py.

Covers the curve-shape maths that do not need a Blender scene: catenary sag,
zero-gravity arc, random-coil path, polyline arc length, the Newton-Raphson
catenary-parameter solver, and the rigid binding-zone blend.
"""

import math

import pytest
from mathutils import Vector

from proteinblender.linkers import linker_geometry as lg


def _vclose(a: Vector, b: Vector, tol: float = 1e-5) -> bool:
    return (a - b).length < tol


def _is_collinear(points, tol: float = 1e-4) -> bool:
    """True if every point lies on the line through the first and last point."""
    a, b = points[0], points[-1]
    axis = (b - a)
    if axis.length < 1e-9:
        return True
    axis = axis.normalized()
    for p in points:
        rel = p - a
        perp = rel - rel.dot(axis) * axis
        if perp.length > tol:
            return False
    return True


# ---------------------------------------------------------------------------
# compute_catenary_points
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_catenary_point_count_and_endpoints():
    start, end = Vector((0, 0, 0)), Vector((2, 0, 0))
    pts = lg.compute_catenary_points(start, end, total_length=3.0, num_samples=9)
    assert len(pts) == 9
    assert _vclose(pts[0], start)
    assert _vclose(pts[-1], end)


@pytest.mark.unit
def test_catenary_slack_sags_below_chord():
    # Chord lies at z=0; a slack chain under -Z gravity must dip below it.
    start, end = Vector((0, 0, 0)), Vector((2, 0, 0))
    pts = lg.compute_catenary_points(start, end, total_length=4.0, num_samples=11)
    min_z = min(p.z for p in pts)
    assert min_z < -1e-3
    # The lowest point should be near the middle, not at an endpoint.
    lowest = min(range(len(pts)), key=lambda i: pts[i].z)
    assert 0 < lowest < len(pts) - 1


@pytest.mark.unit
def test_catenary_taut_is_straight():
    # total_length ~= distance -> no slack -> straight line.
    start, end = Vector((0, 0, 0)), Vector((3, 0, 0))
    pts = lg.compute_catenary_points(start, end, total_length=3.0, num_samples=9)
    assert _is_collinear(pts)


@pytest.mark.unit
def test_catenary_arc_length_between_chord_and_total():
    start, end = Vector((0, 0, 0)), Vector((2, 0, 0))
    L = 4.0
    pts = lg.compute_catenary_points(start, end, total_length=L, num_samples=25)
    chord = (end - start).length
    arc = lg._arc_length(pts)
    # Sampled polyline sags -> longer than the chord, but cannot exceed the
    # true (smooth) arc length that the construction targets.
    assert arc >= chord
    assert arc <= L * 1.02


# ---------------------------------------------------------------------------
# compute_zero_g_points
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_zero_g_point_count_and_endpoints():
    start, end = Vector((0, 0, 0)), Vector((2, 0, 0))
    pts = lg.compute_zero_g_points(start, end, total_length=3.0, num_samples=9)
    assert len(pts) == 9
    assert _vclose(pts[0], start)
    assert _vclose(pts[-1], end)


@pytest.mark.unit
def test_zero_g_taut_is_collinear():
    start, end = Vector((0, 0, 0)), Vector((3, 0, 0))
    pts = lg.compute_zero_g_points(start, end, total_length=3.0, num_samples=9)
    assert _is_collinear(pts)


@pytest.mark.unit
def test_zero_g_has_no_gravity_sag():
    # Unlike the catenary, the zero-g arc bulges perpendicular to the axis with
    # no downward (-Z) bias. For an X-axis chord the whole arc stays at z~=0.
    start, end = Vector((0, 0, 0)), Vector((2, 0, 0))
    pts = lg.compute_zero_g_points(start, end, total_length=4.0, num_samples=11)
    assert all(abs(p.z) < 1e-6 for p in pts)
    # There is a genuine bulge (not a straight line) when slack.
    assert not _is_collinear(pts, tol=1e-3)


# ---------------------------------------------------------------------------
# _arc_length
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_arc_length_of_polyline():
    pts = [Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((1, 1, 0))]
    assert lg._arc_length(pts) == pytest.approx(2.0)


@pytest.mark.unit
def test_arc_length_straight_equals_distance():
    pts = [Vector((0, 0, 0)), Vector((3, 4, 0))]
    assert lg._arc_length(pts) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# compute_random_coil_points
# ---------------------------------------------------------------------------

# The confused-fly coil wanders off the straight start->end chord by two
# channels of smooth band-limited noise, pinned at both endpoints, with its
# amplitude solved so the arc length matches the residue count. Its defining,
# independently-checkable properties are: exact endpoints, arc length ~ target,
# gently-rounded turns (no jagged cusps - the whole point of the rework), a
# genuinely 3-D (non-planar) path, and shape that varies from seed to seed. The
# helpers below derive those from the output geometry alone, never from the
# generator's own maths.

def _max_turn_angle_deg(points):
    """Largest direction change between consecutive segments (jaggedness)."""
    worst = 0.0
    for i in range(1, len(points) - 1):
        v1, v2 = points[i] - points[i - 1], points[i + 1] - points[i]
        if v1.length < 1e-9 or v2.length < 1e-9:
            continue
        cos = max(-1.0, min(1.0, v1.normalized().dot(v2.normalized())))
        worst = max(worst, math.degrees(math.acos(cos)))
    return worst


def _planarity_ratio(points):
    """Smallest / largest singular value of the centred point cloud.

    ~0 means the points lie in a plane (a flat ribbon); a clearly positive
    value means the path genuinely occupies 3-D space.
    """
    import numpy as np
    m = np.array([[p.x, p.y, p.z] for p in points], dtype=float)
    m -= m.mean(axis=0)
    sv = np.linalg.svd(m, compute_uv=False)
    return float(sv[2] / sv[0]) if sv[0] > 1e-12 else 0.0


def _perp_winding(points, start, end):
    """Total angle (radians) the curve sweeps around its chord axis.

    Measures how many times the coil winds around the straight start->end line -
    the quantity that must NOT change as the endpoints move, or the coil visibly
    corkscrews. Sampled only where the off-axis offset is large enough to have a
    well-defined direction (the ends taper to zero).
    """
    import numpy as np
    A = np.array([start.x, start.y, start.z], dtype=float)
    B = np.array([end.x, end.y, end.z], dtype=float)
    axis = (B - A) / np.linalg.norm(B - A)
    ref1 = np.cross(axis, [0.0, 0.0, 1.0])
    if np.linalg.norm(ref1) < 0.1:
        ref1 = np.cross(axis, [0.0, 1.0, 0.0])
    ref1 /= np.linalg.norm(ref1)
    ref2 = np.cross(axis, ref1)

    P = np.array([[p.x, p.y, p.z] for p in points], dtype=float)
    rel = P - A
    perp = rel - np.outer(rel @ axis, axis)
    x, y = perp @ ref1, perp @ ref2
    mag = np.hypot(x, y)
    thresh = 0.2 * mag.max() if mag.max() > 0 else 0.0
    ang = np.arctan2(y, x)

    total, prev = 0.0, None
    for i in range(len(ang)):
        if mag[i] < thresh:
            prev = None            # don't bridge across the tapered ends
            continue
        if prev is not None:
            d = (ang[i] - prev + np.pi) % (2 * np.pi) - np.pi
            total += d
        prev = ang[i]
    return abs(total)


@pytest.mark.unit
def test_random_coil_winding_is_distance_invariant_no_corkscrew():
    """Moving the endpoints must not wind or unwind the coil (no corkscrew).

    The loop count is a fixed property of the linker, not the endpoint gap, so
    the total angle the coil sweeps around its axis is the same whether the ends
    are near or far - moving them only breathes the amplitude. Pre-fix the loop
    count scaled with slack (`(L-D)/...`), so the coil corkscrewed as the
    endpoints moved (user report). Same seed + axis, two endpoint distances.
    """
    L = 2.0
    a = Vector((0, 0, 0))
    near = lg.compute_random_coil_points(a, Vector((0.4, 0, 0)), L,
                                         num_residues=40, seed=7)
    far = lg.compute_random_coil_points(a, Vector((1.2, 0, 0)), L,
                                        num_residues=40, seed=7)
    w_near = _perp_winding(near, a, Vector((0.4, 0, 0)))
    w_far = _perp_winding(far, a, Vector((1.2, 0, 0)))
    assert w_near > 1.0, "expected a coil that actually winds"
    assert w_near == pytest.approx(w_far, rel=0.15)


@pytest.mark.unit
def test_random_coil_endpoints_exact_and_absorbs_slack():
    start, end = Vector((0, 0, 0)), Vector((1, 0, 0))
    L = 3.0
    pts = lg.compute_random_coil_points(start, end, total_length=L,
                                        num_residues=40, seed=7)
    assert len(pts) >= 16
    assert _vclose(pts[0], start, tol=1e-4)
    assert _vclose(pts[-1], end, tol=1e-4)
    # The wandering path spends the slack: far longer than the 1.0 chord, and
    # solved to match the requested residue length.
    arc = lg._arc_length(pts)
    assert arc > (end - start).length * 1.5
    assert arc == pytest.approx(L, rel=0.05)


@pytest.mark.unit
def test_random_coil_turns_are_gently_rounded_not_jagged():
    """A moderate-slack linker must turn in smooth arcs, not sharp cusps.

    This is the aesthetic fix: the old sine-sum coil cusped at ~71 deg on this
    exact case (reading as a jagged EKG trace); the band-limited wander stays
    well under half that. The threshold sits between the two so a regression to
    sharp turns fails here.
    """
    start, end = Vector((0, 0, 0)), Vector((0.5, 0, 0))
    pts = lg.compute_random_coil_points(start, end, total_length=1.0,
                                        num_residues=28, seed=7)
    assert _max_turn_angle_deg(pts) < 45.0


@pytest.mark.unit
def test_random_coil_is_three_dimensional_not_a_flat_ribbon():
    start, end = Vector((0, 0, 0)), Vector((0.5, 0, 0))
    pts = lg.compute_random_coil_points(start, end, total_length=1.0,
                                        num_residues=28, seed=7)
    # The handedness precession pushes the path out of any single plane.
    assert _planarity_ratio(pts) > 0.05


@pytest.mark.unit
def test_random_coil_deterministic_for_seed():
    start, end = Vector((0, 0, 0)), Vector((1, 0, 0))
    a = lg.compute_random_coil_points(start, end, 3.0, num_residues=30, seed=42)
    b = lg.compute_random_coil_points(start, end, 3.0, num_residues=30, seed=42)
    assert len(a) == len(b)
    assert all(_vclose(pa, pb) for pa, pb in zip(a, b))


@pytest.mark.unit
def test_random_coil_seed_varies_shape_without_moving_endpoints():
    start, end = Vector((0, 0, 0)), Vector((1, 0, 0))
    a = lg.compute_random_coil_points(start, end, 3.0,
                                      num_residues=30, seed=7)
    b = lg.compute_random_coil_points(start, end, 3.0,
                                      num_residues=30, seed=8)
    assert _vclose(a[0], start) and _vclose(a[-1], end)
    assert _vclose(b[0], start) and _vclose(b[-1], end)
    assert any(not _vclose(pa, pb) for pa, pb in zip(a[1:-1], b[1:-1]))


@pytest.mark.unit
def test_random_coil_taut_is_straight():
    start, end = Vector((0, 0, 0)), Vector((3, 0, 0))
    pts = lg.compute_random_coil_points(start, end, total_length=3.0,
                                        num_residues=30, seed=1)
    assert _is_collinear(pts, tol=1e-4)


@pytest.mark.unit
def test_stable_coil_seed_is_repeatable_and_uid_specific():
    assert lg._stable_coil_seed("linker-one") == lg._stable_coil_seed("linker-one")
    assert lg._stable_coil_seed("linker-one") != lg._stable_coil_seed("linker-two")


# ---------------------------------------------------------------------------
# _solve_catenary_parameter
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_solve_catenary_parameter_recovers_known_a():
    a_true = 1.0
    h = 2.0
    # Forward relation the solver inverts: L = 2*a*sinh(h/(2a)).
    L_target = 2.0 * a_true * math.sinh(h / (2.0 * a_true))
    a = lg._solve_catenary_parameter(h, L_target)
    assert a is not None
    assert a == pytest.approx(a_true, rel=1e-3)


@pytest.mark.unit
def test_solve_catenary_parameter_none_when_nearly_straight():
    # L_target <= h*1.001 -> catenary parameter blows up, solver returns None.
    assert lg._solve_catenary_parameter(2.0, 2.0) is None


# ---------------------------------------------------------------------------
# apply_rigid_binding_zones
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_rigid_zones_noop_without_directions():
    pts = [Vector((0, 0, 0)), Vector((1, 1, 0)), Vector((2, 0, 0)),
           Vector((3, 1, 0)), Vector((4, 0, 0))]
    out = lg.apply_rigid_binding_zones(pts, None, None, zone_length_bu=1.0)
    assert len(out) == len(pts)
    assert all(_vclose(a, b) for a, b in zip(out, pts))


@pytest.mark.unit
def test_rigid_zones_preserve_endpoints():
    pts = [Vector((0, 0, 0)), Vector((1, 1, 0)), Vector((2, 0, 0)),
           Vector((3, 1, 0)), Vector((4, 0, 0))]
    sdir = Vector((1, 0, 0))
    edir = Vector((1, 0, 0))
    out = lg.apply_rigid_binding_zones(pts, sdir, edir, zone_length_bu=2.0)
    assert len(out) == len(pts)
    assert _vclose(out[0], pts[0])
    assert _vclose(out[-1], pts[-1])


@pytest.mark.unit
def test_rigid_zone_pulls_early_point_toward_backbone():
    # With a +X start direction, points inside the zone are pulled toward the
    # straight backbone ray (y -> 0) relative to their kinked input.
    pts = [Vector((0, 0, 0)), Vector((1, 1, 0)), Vector((2, 0, 0)),
           Vector((3, 1, 0)), Vector((4, 0, 0))]
    out = lg.apply_rigid_binding_zones(pts, Vector((1, 0, 0)), None,
                                       zone_length_bu=3.0)
    # The first interior point started at y=1; the rigid pull reduces its
    # off-axis (y) deviation.
    assert abs(out[1].y) < abs(pts[1].y)


@pytest.mark.unit
def test_rigid_zones_short_input_returned_unchanged():
    pts = [Vector((0, 0, 0)), Vector((1, 0, 0))]
    out = lg.apply_rigid_binding_zones(pts, Vector((1, 0, 0)),
                                       Vector((1, 0, 0)), zone_length_bu=1.0)
    assert out == pts
