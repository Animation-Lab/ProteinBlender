"""The shared bend rig's geometry - reading a path and shaping one.

``core.bend_rig`` is what the DNA strand bender and the Symmetry panel's
filament bender both stand on. The rig-building half (curves, hooks, control
nodes) is exercised end to end by ``tests/integration/test_dna.py``; what is
tested here is the *maths* those two features read out of a finished path, and
the starting shapes they can put into one.

Ground truth is hand-computed geometry on paths whose answers are known before
the code runs - a straight line of a stated length, a right-angle bend whose
arc length is the sum of two sides - never a value produced by the sampler
being tested. On a POLY spline the sampler's own flattening step is the
identity, so an expected position is plain linear interpolation done in this
file.
"""

import math

import bpy
import pytest
from mathutils import Vector


def _rig():
    from proteinblender.core import bend_rig
    return bend_rig


def _poly_curve(points, name="TestPath"):
    """A polyline curve object through *points*, in world space.

    POLY rather than BEZIER on purpose: a polyline is exactly the path its
    vertices describe, so arc lengths and positions along it can be computed by
    hand. A Bezier's shape depends on handle placement, which would make the
    "expected" value depend on the very code under test.
    """
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (co[0], co[1], co[2], 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def _bezier_curve(points, name="TestBezier"):
    rig = _rig()
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bezier_point, co in zip(spline.bezier_points, points):
        bezier_point.co = Vector(co)
    rig.set_aligned_handles_along_path(spline)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


# --------------------------------------------------------------------------
# Reading a path: position
# --------------------------------------------------------------------------

def test_a_straight_path_samples_at_the_distance_asked_for(scene):
    """Two metres along +X: the sample at s is at x = s, and nowhere else."""
    curve = _poly_curve([(0, 0, 0), (2, 0, 0)])

    samples = _rig().sample_along(curve, [0.0, 0.5, 1.0, 2.0])

    assert len(samples) == 4
    for expected, (position, _tangent, _normal) in zip([0.0, 0.5, 1.0, 2.0], samples):
        assert position.x == pytest.approx(expected, abs=1e-6)
        assert position.y == pytest.approx(0.0, abs=1e-6)
        assert position.z == pytest.approx(0.0, abs=1e-6)


def test_arc_length_follows_the_path_round_a_corner(scene):
    """A right angle: 1 along +X then 1 along +Y, so s=1.5 is half up the second leg.

    Computed here, not by the sampler: the corner is at (1, 0, 0), the total
    length is 1 + 1 = 2, and 1.5 is 0.5 past the corner along +Y.
    """
    curve = _poly_curve([(0, 0, 0), (1, 0, 0), (1, 1, 0)])

    (position, _t, _n), = _rig().sample_along(curve, [1.5])

    assert position.x == pytest.approx(1.0, abs=1e-6)
    assert position.y == pytest.approx(0.5, abs=1e-6)
    assert position.z == pytest.approx(0.0, abs=1e-6)


def test_a_straight_line_is_not_the_same_as_the_chord(scene):
    """Sampling by arc length, not by straight-line distance from the start.

    The chord from (0,0,0) to the s=2 point of the right angle is sqrt(2)
    long, so a sampler that measured chords would put s=2 somewhere else
    entirely. This is the assertion that tells the two apart.
    """
    curve = _poly_curve([(0, 0, 0), (1, 0, 0), (1, 1, 0)])

    (position, _t, _n), = _rig().sample_along(curve, [2.0])

    assert (position - Vector((1.0, 1.0, 0.0))).length == pytest.approx(0, abs=1e-6)
    assert position.length == pytest.approx(math.sqrt(2.0), abs=1e-6)


def test_past_the_end_the_path_carries_straight_on(scene):
    """More subunits than the curve is long must extend it, not pile them up.

    The path ends at (1, 1, 0) travelling +Y, so s = 3 - one past the end -
    belongs at (1, 2, 0).
    """
    curve = _poly_curve([(0, 0, 0), (1, 0, 0), (1, 1, 0)])

    (position, tangent, _n), = _rig().sample_along(curve, [3.0])

    assert position.x == pytest.approx(1.0, abs=1e-6)
    assert position.y == pytest.approx(2.0, abs=1e-6)
    assert tangent.y == pytest.approx(1.0, abs=1e-6)


def test_curve_length_is_the_sum_of_the_legs(scene):
    curve = _poly_curve([(0, 0, 0), (3, 0, 0), (3, 4, 0)])
    assert _rig().curve_length(curve) == pytest.approx(7.0, abs=1e-5)


# --------------------------------------------------------------------------
# Reading a path: the frame
# --------------------------------------------------------------------------

def test_the_tangent_points_along_the_path(scene):
    curve = _poly_curve([(0, 0, 0), (0, 0, 5)])

    (_p, tangent, _n), = _rig().sample_along(curve, [2.0])

    assert tangent.length == pytest.approx(1.0, abs=1e-6)
    assert tangent.z == pytest.approx(1.0, abs=1e-6)


def test_the_normal_stays_square_to_the_tangent_everywhere(scene):
    """A frame whose normal drifts off the tangent would shear every subunit."""
    curve = _bezier_curve([(0, 0, 0), (1, 1, 0), (2, 0, 0.5), (3, -1, 0)])

    for _position, tangent, normal in _rig().sample_along(
            curve, [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]):
        assert normal.length == pytest.approx(1.0, abs=1e-5)
        assert abs(normal.dot(tangent)) < 1e-5


def test_the_normal_does_not_flip_at_an_inflection(scene):
    """The reason the frame is transported rather than recomputed per sample.

    A Frenet normal is defined from the curvature vector, which reverses sign
    where an S-shaped path changes which way it bends. Every subunit past that
    point would snap half a turn around the filament. A carried-forward frame
    cannot do that, so consecutive normals must never oppose each other.
    """
    rig = _rig()
    # An S: bends one way, then the other, so it has a genuine inflection.
    curve = _bezier_curve([(0, 0, 0), (1, 1, 0), (2, -1, 0), (3, 0, 0)])

    total = rig.curve_length(curve)
    steps = [total * i / 40.0 for i in range(41)]
    normals = [normal for _p, _t, normal in rig.sample_along(curve, steps)]

    assert len(normals) == 41
    worst = min(a.dot(b) for a, b in zip(normals, normals[1:]))
    assert worst > 0.9, (
        f"the frame flipped or spun between samples (worst dot {worst:.3f})")


def test_a_degenerate_path_is_survivable(scene):
    """A one-point curve has no direction; asking for samples must not raise."""
    curve = _poly_curve([(0, 0, 0)])
    assert _rig().sample_along(curve, [0.0, 1.0]) == []
    assert _rig().curve_length(curve) == pytest.approx(0.0)


def test_sampling_nothing_is_not_an_error(scene):
    curve = _poly_curve([(0, 0, 0), (1, 0, 0)])
    assert _rig().sample_along(curve, []) == []


# --------------------------------------------------------------------------
# Shaping a path: the starting presets
# --------------------------------------------------------------------------

def test_straight_preset_is_a_straight_line_of_the_length_asked_for(scene):
    points = [co for co, _l, _r in _rig().preset_points("STRAIGHT", 4.0, 5)]

    assert len(points) == 5
    assert (points[0] - Vector((0, 0, 0))).length == pytest.approx(0, abs=1e-6)
    assert (points[-1] - Vector((0, 0, 4.0))).length == pytest.approx(0, abs=1e-6)
    # Collinear: every point's cross product with the axis is zero.
    for point in points:
        assert point.cross(Vector((0, 0, 1))).length == pytest.approx(0, abs=1e-6)


def test_arc_leaves_the_axis_and_comes_back_to_it(scene):
    """A bow: both ends on the axis, the middle furthest from it."""
    points = [co for co, _l, _r in _rig().preset_points("ARC", 4.0, 5)]
    axis = Vector((0, 0, 1))

    def off_axis(point):
        return (point - axis * point.dot(axis)).length

    assert off_axis(points[0]) == pytest.approx(0, abs=1e-6)
    assert off_axis(points[-1]) == pytest.approx(0, abs=1e-6)
    assert off_axis(points[2]) > 0.5, "the middle of an arc must leave the axis"
    assert off_axis(points[2]) == max(off_axis(p) for p in points)


def test_the_s_curve_bends_both_ways(scene):
    """An S is only an S if the two halves depart to opposite sides."""
    points = [co for co, _l, _r in _rig().preset_points("S", 4.0, 9)]
    axis = Vector((0, 0, 1))

    def side(point):
        offset = point - axis * point.dot(axis)
        return offset.x + offset.y      # signed, since the side is one vector

    first_half = side(points[2])
    second_half = side(points[6])
    assert first_half * second_half < 0, (
        f"both halves went the same way ({first_half:.3f}, {second_half:.3f})")


def test_the_coil_comes_back_round_to_where_it_started(scene):
    """A full loop: the last point returns near the first, having gone away."""
    points = [co for co, _l, _r in _rig().preset_points("COIL", 4.0, 9)]

    span = max((p - points[0]).length for p in points)
    assert span > 0.5, "the coil never left the start"
    assert (points[-1] - points[0]).length < 0.1 * span, (
        "the coil did not close back on itself")


def test_an_unknown_preset_falls_back_to_straight(scene):
    straight = _rig().preset_points("STRAIGHT", 3.0, 4)
    unknown = _rig().preset_points("NOT_A_PRESET", 3.0, 4)
    for (a, _l1, _r1), (b, _l2, _r2) in zip(straight, unknown):
        assert (Vector(a) - Vector(b)).length == pytest.approx(0, abs=1e-9)


def test_every_advertised_preset_can_be_built(scene):
    rig = _rig()
    for identifier, _label, _description in rig.PRESETS:
        points = rig.preset_points(identifier, 2.0, 4)
        assert len(points) == 4, f"{identifier} produced {len(points)} points"


# --------------------------------------------------------------------------
# Reshaping a path: arc-length resampling
# --------------------------------------------------------------------------

def test_resampling_keeps_the_ends_and_the_length(scene):
    """More handles must not move the path, only how it is controlled."""
    rig = _rig()
    curve = _bezier_curve([(0, 0, 0), (1, 1, 0), (2, 0, 0)])

    before_first = curve.data.splines[0].bezier_points[0].co.copy()
    before_last = curve.data.splines[0].bezier_points[-1].co.copy()
    before_length = rig.curve_length(curve)

    rig.resample_curve_arc_length(curve, 6)
    bpy.context.view_layer.update()

    points = curve.data.splines[0].bezier_points
    assert len(points) == 6
    assert (points[0].co - before_first).length == pytest.approx(0, abs=1e-5)
    assert (points[-1].co - before_last).length == pytest.approx(0, abs=1e-5)
    assert rig.curve_length(curve) == pytest.approx(before_length, rel=0.02)


def test_resampling_spaces_the_handles_evenly_along_the_path(scene):
    """"Arc-length" is the claim; equal gaps between neighbours is the test."""
    rig = _rig()
    curve = _bezier_curve([(0, 0, 0), (1, 1.5, 0), (2, 0, 0), (3, -1.5, 0)])

    rig.resample_curve_arc_length(curve, 7)
    points = [p.co.copy() for p in curve.data.splines[0].bezier_points]

    gaps = [(b - a).length for a, b in zip(points, points[1:])]
    assert max(gaps) - min(gaps) < 0.25 * max(gaps), (
        f"handles are not evenly spaced: {[round(g, 3) for g in gaps]}")


def test_resampling_to_the_same_count_leaves_the_curve_untouched(scene):
    rig = _rig()
    curve = _bezier_curve([(0, 0, 0), (1, 1, 0), (2, 0, 0)])
    before = [p.co.copy() for p in curve.data.splines[0].bezier_points]

    rig.resample_curve_arc_length(curve, 3)

    after = [p.co.copy() for p in curve.data.splines[0].bezier_points]
    for a, b in zip(before, after):
        assert (a - b).length == pytest.approx(0, abs=1e-9)


def test_resampling_is_clamped_to_a_usable_number_of_handles(scene):
    rig = _rig()
    curve = _bezier_curve([(0, 0, 0), (1, 1, 0), (2, 0, 0)])

    rig.resample_curve_arc_length(curve, 999)
    assert len(curve.data.splines[0].bezier_points) == rig.RES_MAX

    rig.resample_curve_arc_length(curve, 0)
    assert len(curve.data.splines[0].bezier_points) == rig.RES_MIN
