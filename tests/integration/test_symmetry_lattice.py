"""A filament of more than one strand - the lattice behind a microtubule.

One rise and one twist describe a single helix: actin, a pilus, tobacco mosaic
virus. A microtubule is not that. It is thirteen straight protofilaments set
round a tube, each one stepped a little along the axis from its neighbour, and
no single rise/twist pair generates it. The lattice adds the second level:
``strands`` of them, each ``strand_twist`` degrees round from the last and
``stagger`` Angstrom along.

Ground truth here is the lattice's own definition worked out in the test. A
subunit ``k`` along strand ``j`` sits at height ``rise*k + stagger*j`` and is
turned ``twist*k + strand_twist*j`` about the axis, so a point ``r`` from the
axis lands at ``(r cos a, r sin a, height)`` - trigonometry written out below,
never a value read back from the generator. The generator's own site list is
not consulted for an expected value anywhere in this file.
"""

import math

import bpy
import numpy as np
import pytest

import helpers as H

FIXTURE = "1ubq.pdb"        # a monomer, so nothing deposited confuses the build

# A textbook microtubule, to the precision that matters for a lattice test:
# 13 protofilaments, tubulin dimers 82 A apart along each, and neighbouring
# protofilaments offset so that one trip round the tube climbs a dimer and a
# half - the offset that leaves a seam where alpha meets beta.
MT_STRANDS = 13
MT_RISE = 82.0
MT_STAGGER = 1.5 * MT_RISE / MT_STRANDS      # 9.4615... A
MT_STRAND_TWIST = 360.0 / MT_STRANDS         # 27.692... degrees
MT_RADIUS = 112.0                            # A, axis to protofilament


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _bend():
    from proteinblender.core import symmetry_bend
    return symmetry_bend


def _import(ident="ubq"):
    mol_id = H.import_local(FIXTURE, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _attach_path(molecule, points, name="TestLatticeBend"):
    """A polyline bend curve through *points*, in the molecule's local space."""
    bend = _bend()
    owner = bend.owner_object(molecule)

    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (co[0], co[1], co[2], 1.0)

    curve = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(curve)
    curve.matrix_world = owner.matrix_world.copy()
    owner[bend.CURVE_PROP] = curve.name
    bpy.context.view_layer.update()
    return curve


def _place(operator, point):
    rotation, translation = operator
    return np.asarray(rotation, dtype=float) @ np.asarray(point, dtype=float) \
        + np.asarray(translation, dtype=float)


def _on_the_tube(radius, angle_degrees, height):
    """Where a point ``radius`` out on +X goes after a turn and a climb."""
    angle = math.radians(angle_degrees)
    return np.array([radius * math.cos(angle), radius * math.sin(angle), height])


def _microtubule(count=4, **overrides):
    settings = dict(count=count, rise=MT_RISE, twist=0.0, strands=MT_STRANDS,
                    stagger=MT_STAGGER)
    settings.update(overrides)
    return settings


# --------------------------------------------------------------------------
# The straight lattice - pure maths
# --------------------------------------------------------------------------

def test_a_lattice_has_a_subunit_for_every_strand_and_every_step():
    operators = _builder().helical(**_microtubule(count=4))
    assert len(operators) == 4 * MT_STRANDS


def test_the_first_subunit_of_a_lattice_is_the_original():
    """Copy zero is the structure already on screen, whatever the lattice."""
    rotation, translation = _builder().helical(**_microtubule())[0]
    assert np.allclose(rotation, np.eye(3), atol=1e-12)
    assert np.allclose(translation, np.zeros(3), atol=1e-12)


def test_every_subunit_lands_where_the_lattice_says():
    """Each of the 13 x 4 subunits, against trigonometry done here.

    Matched as a set rather than by index: the lattice is the same lattice
    whichever order its subunits are listed in, and pinning an order here
    would be testing a detail nobody can see.
    """
    count = 4
    operators = _builder().helical(**_microtubule(count=count))
    start = np.array([MT_RADIUS, 0.0, 0.0])
    landed = [_place(op, start) for op in operators]

    for k in range(count):
        for j in range(MT_STRANDS):
            want = _on_the_tube(MT_RADIUS, MT_STRAND_TWIST * j,
                                MT_RISE * k + MT_STAGGER * j)
            nearest = min(float(np.linalg.norm(got - want)) for got in landed)
            assert nearest < 1e-6, (
                f"nothing at strand {j}, step {k}: closest subunit is "
                f"{nearest:.3f} A from {want}")


def test_the_strands_close_the_tube():
    """Thirteen strands at 360/13 must come back round to where they began.

    Seen from above, the thirteen subunits of one ring are the corners of a
    regular 13-gon: every neighbouring pair the same chord apart,
    ``2 r sin(pi/13)``, *including* the pair that closes it.
    """
    operators = _builder().helical(**_microtubule(count=1))
    start = np.array([MT_RADIUS, 0.0, 0.0])
    ring = [_place(op, start) for op in operators]
    assert len(ring) == MT_STRANDS

    # Order by angle so "neighbour" does not depend on the listing order.
    ring.sort(key=lambda p: math.atan2(p[1], p[0]) % (2.0 * math.pi))
    chord = 2.0 * MT_RADIUS * math.sin(math.pi / MT_STRANDS)
    for a, b in zip(ring, ring[1:] + ring[:1]):
        flat = float(np.linalg.norm((a - b)[:2]))
        assert flat == pytest.approx(chord, abs=1e-6)


def test_the_stagger_leaves_a_seam_a_dimer_and_a_half_high():
    """Once round a microtubule climbs 1.5 dimers - that is the seam.

    Twelve neighbouring pairs step up by one stagger. The thirteenth pair,
    closing the tube, has to make up the difference to a whole number of
    dimers, and with a stagger of 1.5/13 of a dimer it cannot: the last strand
    sits 12 staggers above the first, which is short of 1.5 dimers by exactly
    one stagger.
    """
    operators = _builder().helical(**_microtubule(count=1))
    heights = sorted(float(_place(op, (MT_RADIUS, 0.0, 0.0))[2])
                     for op in operators)

    steps = np.diff(heights)
    assert np.allclose(steps, MT_STAGGER, atol=1e-9)
    assert heights[-1] - heights[0] == pytest.approx(
        1.5 * MT_RISE - MT_STAGGER, abs=1e-9)


def test_one_strand_is_still_the_plain_helix():
    """The default must not have moved anything that was already right."""
    rise, twist, count = 27.5, -166.7, 8
    operators = _builder().helical(count, rise=rise, twist=twist)
    assert len(operators) == count

    start = np.array([15.0, 0.0, 0.0])
    for k, operator in enumerate(operators):
        want = _on_the_tube(15.0, twist * k, rise * k)
        assert _place(operator, start) == pytest.approx(want, abs=1e-9)


def test_actin_as_two_strands_is_actin_as_one():
    """The same filament described two ways must be the same filament.

    Actin is quoted as one helix of 27.5 A and -166.7 degrees per subunit. It
    is equally two long-pitch strands: along a strand every second subunit,
    so 55 A and -333.4 degrees, with the second strand one subunit step away
    from the first. The expected positions are the one-helix description,
    computed here.
    """
    rise, twist, pairs = 27.5, -166.7, 6
    operators = _builder().helical(
        count=pairs, rise=2.0 * rise, twist=2.0 * twist,
        strands=2, stagger=rise, strand_twist=twist)
    assert len(operators) == 2 * pairs

    start = np.array([15.0, 0.0, 0.0])
    landed = [_place(op, start) for op in operators]
    for n in range(2 * pairs):
        want = _on_the_tube(15.0, twist * n, rise * n)
        nearest = min(float(np.linalg.norm(got - want)) for got in landed)
        assert nearest < 1e-6, f"no subunit at step {n} of the one-start helix"


def test_every_lattice_operator_is_a_rigid_motion():
    for rotation, _translation in _builder().helical(**_microtubule()):
        assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
        assert float(np.linalg.det(rotation)) == pytest.approx(1.0, abs=1e-9)


def test_a_lattice_about_a_centre_turns_about_that_centre():
    """A point on the axis only ever moves along the axis."""
    centre = np.array([30.0, -12.0, 5.0])
    for k_and_j, operator in enumerate(_builder().helical(
            **_microtubule(count=2), centre=centre)):
        moved = _place(operator, centre) - centre
        assert np.allclose(moved[:2], 0.0, atol=1e-9), (
            f"subunit {k_and_j} dragged the axis sideways by {moved[:2]}")


def test_build_operators_passes_the_lattice_through():
    operators = _builder().build_operators("H", **_microtubule(count=3))
    assert len(operators) == 3 * MT_STRANDS


def test_the_summary_names_the_strands():
    """A reader of the summary line has to be able to tell a tube from a helix."""
    builder = _builder()
    tube = builder.describe("H", count=4, rise=MT_RISE, twist=0.0,
                            strands=MT_STRANDS)
    assert "13" in tube and "strand" in tube.lower()
    assert "strand" not in builder.describe("H", count=4, rise=27.5,
                                            twist=-166.7).lower()

    assert builder.short_label("H", count=4, strands=MT_STRANDS) != \
        builder.short_label("H", count=4)


# --------------------------------------------------------------------------
# The lattice on a bent path
# --------------------------------------------------------------------------

def test_the_path_is_as_long_as_the_lattice_is_tall():
    """Twelve staggers stand on top of the last step, and the path must reach.

    3 steps of 82 A plus 12 staggers of 9.4615 A = 359.54 A = 3.5954 Blender
    units. Sized to the rise alone, the last ring's upper strands would hang
    off the end of the curve.
    """
    length = _bend().filament_length(count=4, rise=MT_RISE,
                                     strands=MT_STRANDS, stagger=MT_STAGGER)
    assert length == pytest.approx((3 * 82.0 + 12 * MT_STAGGER) * 0.01, abs=1e-9)

    # And one strand is what it always was.
    assert _bend().filament_length(count=4, rise=MT_RISE) == pytest.approx(
        3 * 82.0 * 0.01, abs=1e-9)


def test_a_straight_path_reproduces_the_straight_lattice(scene, sm):
    """Adding a bend and dragging nothing must leave the tube alone."""
    molecule = _import()
    count = 3
    _attach_path(molecule, [(0, 0, 0), (0, 0, 4.0)])

    operators = _bend().bent_helical_operators(
        molecule, axis=(0, 0, 1), **_microtubule(count=count))
    assert len(operators) == count * MT_STRANDS

    start = np.array([MT_RADIUS, 0.0, 0.0])
    landed = [_place(op, start) for op in operators]
    for k in range(count):
        for j in range(MT_STRANDS):
            want = _on_the_tube(MT_RADIUS, MT_STRAND_TWIST * j,
                                MT_RISE * k + MT_STAGGER * j)
            nearest = min(float(np.linalg.norm(got - want)) for got in landed)
            assert nearest < 1e-2, (
                f"strand {j}, step {k} moved {nearest:.3f} A on a straight path")


def test_each_strand_walks_the_path_from_its_own_height(scene, sm):
    """Round a corner, every subunit's stretch of axis is on the curve.

    A right angle: 100 A up +Z, then off along +Y. Where a subunit's own point
    on the axis lands depends only on how far along the path it is, so it can
    be read off the polyline by hand: before the corner at (0, 0, d), after
    it at (0, d - 100, 100). The stagger is what puts neighbouring strands at
    different distances, so a lattice that sampled the path once per ring
    would leave twelve of every thirteen in the wrong place.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 3.0, 1.0)])

    count = 3
    operators = _bend().bent_helical_operators(
        molecule, axis=(0, 0, 1), **_microtubule(count=count))
    axis_points = [_place(op, (0.0, 0.0, 0.0)) for op in operators]

    for k in range(count):
        for j in range(MT_STRANDS):
            distance = MT_RISE * k + MT_STAGGER * j
            want = (np.array([0.0, 0.0, distance]) if distance <= 100.0
                    else np.array([0.0, distance - 100.0, 100.0]))
            nearest = min(float(np.linalg.norm(got - want)) for got in axis_points)
            assert nearest < 0.5, (
                f"strand {j}, step {k} should sit {distance:.1f} A along the "
                f"path at {want}; the closest subunit is {nearest:.2f} A away")


def test_a_bent_lattice_keeps_its_first_subunit_still(scene, sm):
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0.4, 1.0), (0, 2.0, 1.5)])

    rotation, translation = _bend().bent_helical_operators(
        molecule, **_microtubule(count=3))[0]
    assert np.allclose(rotation, np.eye(3), atol=1e-6)
    assert np.allclose(translation, np.zeros(3), atol=1e-6)


def test_a_backward_stagger_does_not_pile_up_at_the_start(scene, sm):
    """Strands that step *down* the tube must still each get their own place.

    A left-handed lattice has its stagger opposite to its rise. Nothing can be
    placed before the start of a curve, so a naive walk would put every
    subunit that wanted a negative distance on the very first point. Here all
    thirteen of the first ring must stay their stagger apart along the axis.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 4.0)])

    operators = _bend().bent_helical_operators(
        molecule, axis=(0, 0, 1),
        **_microtubule(count=1, stagger=-MT_STAGGER))
    heights = sorted(float(_place(op, (0.0, 0.0, 0.0))[2]) for op in operators)

    assert len(heights) == MT_STRANDS
    assert np.allclose(np.diff(heights), MT_STAGGER, atol=1e-2), (
        f"strands are not a stagger apart: {np.round(np.diff(heights), 3)}")


def test_build_operators_bends_a_lattice(scene, sm):
    """The one entry point the panel uses must carry the lattice to the bend."""
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 3.0, 1.0)])

    operators = _bend().build_operators(molecule, "H", **_microtubule(count=3))
    assert len(operators) == 3 * MT_STRANDS

    # Past the corner the path runs along +Y, so something must have left the
    # Z axis - which a straight lattice never does.
    off_axis = max(abs(float(_place(op, (0.0, 0.0, 0.0))[1])) for op in operators)
    assert off_axis > 50.0
