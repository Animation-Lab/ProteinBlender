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

@pytest.mark.unit
def test_random_coil_endpoints_and_arc_length():
    start, end = Vector((0, 0, 0)), Vector((1, 0, 0))
    L = 3.0
    pts = lg.compute_random_coil_points(start, end, total_length=L,
                                        num_residues=30, seed=7)
    assert len(pts) >= 16
    assert _vclose(pts[0], start, tol=1e-4)
    assert _vclose(pts[-1], end, tol=1e-4)
    # Binary search targets arc length == L to within ~0.2%.
    arc = lg._arc_length(pts)
    assert arc == pytest.approx(L, rel=0.05)


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
def test_random_coil_size_bump_is_local_and_smooth():
    args = (
        Vector((0, 0, 0)), Vector((1, 0, 0)), 1.0, 101,
        Vector((0, 1, 0)), Vector((0, 0, 1)),
        [2.0, 3.4, 5.4], [1.0, 0.5, 0.25], [0.0] * 6,
    )
    plain = lg._generate_random_coil_shape(*args)
    bumped = lg._generate_random_coil_shape(
        *args, size_bumps=[(0.5, 0.05, 1.6)]
    )
    # Endpoints and regions far from the chosen central turn stay unchanged.
    assert _vclose(plain[0], bumped[0])
    assert _vclose(plain[-1], bumped[-1])
    assert _vclose(plain[10], bumped[10], tol=1e-4)
    # The selected region grows, with no discontinuous point-to-point jump.
    assert (bumped[50] - Vector((0.5, 0, 0))).length > \
        (plain[50] - Vector((0.5, 0, 0))).length
    steps = [(bumped[i + 1] - bumped[i]).length
             for i in range(len(bumped) - 1)]
    assert max(steps) < 0.5


@pytest.mark.unit
def test_random_coil_taut_is_straight():
    start, end = Vector((0, 0, 0)), Vector((3, 0, 0))
    pts = lg.compute_random_coil_points(start, end, total_length=3.0,
                                        num_residues=30, seed=1)
    assert _is_collinear(pts, tol=1e-4)


@pytest.mark.unit
def test_random_coil_never_doubles_back_along_endpoint_axis():
    """Noise may wander sideways, but must progress monotonically end to end."""
    start, end = Vector((0, 0, 0)), Vector((1, 0, 0))
    pts = lg.compute_random_coil_points(start, end, total_length=3.0,
                                        num_residues=86, seed=7)
    axial = [(point - start).dot((end - start).normalized()) for point in pts]
    assert all(b >= a for a, b in zip(axial, axial[1:]))


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
