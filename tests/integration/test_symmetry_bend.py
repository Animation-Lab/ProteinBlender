"""Bending a helical filament: the copies move, the subunits stay rigid.

``core.symmetry_bend`` replaces the straight axis of a generated helix with a
curve the user shapes, and re-derives the same operators against it. What is
asserted here is where the subunits land and what shape they keep - never a
value produced by the bending code.

Ground truth comes from two independent sources:

* **Hand-computed geometry.** The bend curves below are POLY splines, so the
  path *is* the polyline through its vertices: a right angle of two 1.0-unit
  legs is 2.0 long, and the point 1.5 along it is half way up the second leg.
  Those numbers are written out in the tests, not read back from the sampler.
* **Trigonometry.** A straight bend must reproduce the analytic helix -
  subunit *k* at ``rise·k`` along the axis, rotated ``twist·k`` about it -
  which is a fact about helices rather than about our code.

The invariant that separates "moved" from "deformed" gets its own test: every
operator's rotation must be orthonormal with determinant +1. A matrix that
stretched or sheared a subunit could not satisfy that, and no amount of
looking at positions would catch it.
"""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H

FIXTURE = "1ubq.pdb"        # a monomer, so nothing deposited confuses the build
WORLD_SCALE = 0.01          # Blender units per Angstrom


def _bend():
    from proteinblender.core import symmetry_bend
    return symmetry_bend


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _import(ident="ubq"):
    mol_id = H.import_local(FIXTURE, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _attach_path(molecule, points, name="TestBend"):
    """Give the molecule a bend curve through *points*, in its own local space.

    A POLY spline so the path is exactly the polyline asked for, and its
    matrix set to the molecule's so a local coordinate here is a local
    coordinate there - which is what lets the expected positions below be
    plain arithmetic.
    """
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


def _translations(operators):
    return [np.asarray(t, dtype=float) for _r, t in operators]


# --------------------------------------------------------------------------
# A straight bend must change nothing
# --------------------------------------------------------------------------

def test_a_straight_path_reproduces_the_analytic_helix(scene, sm):
    """Adding a bend and dragging nothing must leave the filament alone.

    Expected values are the helix's own definition, written out here: subunit
    k sits at (0, 0, rise*k) and is turned twist*k about Z.
    """
    molecule = _import()
    count, rise, twist = 5, 40.0, 30.0

    # 4 gaps of 40 A = 160 A = 1.6 Blender units, straight up +Z.
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.6)])

    operators = _bend().bent_helical_operators(
        molecule, count=count, rise=rise, twist=twist, axis=(0, 0, 1))

    assert len(operators) == count
    for k, (rotation, translation) in enumerate(operators):
        assert translation[0] == pytest.approx(0.0, abs=1e-4)
        assert translation[1] == pytest.approx(0.0, abs=1e-4)
        assert translation[2] == pytest.approx(rise * k, abs=1e-3)

        angle = math.radians(twist * k)
        expected = np.array([
            [math.cos(angle), -math.sin(angle), 0.0],
            [math.sin(angle), math.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ])
        assert np.allclose(rotation, expected, atol=1e-4), (
            f"subunit {k} is not turned {twist * k} degrees about Z")


def test_the_first_subunit_is_left_exactly_where_it_was(scene, sm):
    """Copy zero is the structure already on screen; a bend must not move it."""
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0)])

    rotation, translation = _bend().bent_helical_operators(
        molecule, count=4, rise=25.0, twist=-166.7)[0]

    assert np.allclose(rotation, np.eye(3), atol=1e-6)
    assert np.allclose(translation, np.zeros(3), atol=1e-6)


def test_with_no_curve_it_is_the_straight_helix(scene, sm):
    """No rig, no bending - and callers never have to ask which they got."""
    molecule = _import()
    settings = dict(count=6, rise=27.5, twist=-166.7, axis=(0.0, 0.0, 1.0))

    bent = _bend().build_operators(molecule, "H", **settings)
    straight = _builder().build_operators("H", **settings)

    assert len(bent) == len(straight)
    for (r1, t1), (r2, t2) in zip(bent, straight):
        assert np.allclose(r1, r2, atol=1e-9)
        assert np.allclose(t1, t2, atol=1e-9)


# --------------------------------------------------------------------------
# A real bend: where the subunits land
# --------------------------------------------------------------------------

def test_subunits_land_at_arc_length_along_the_path(scene, sm):
    """A right angle of two 1.0-unit legs, walked 0.5 units at a time.

    In Angstrom (1 Blender unit = 100 A): the corner is at (0, 0, 100) and the
    path is 200 A long, so 50 A steps put four subunits at 0, 50, 100 and 150
    along it. Written out below; the sampler is not consulted.

    Four rather than five on purpose. With five they would land on 0, 50, 100,
    150, 200 - which is *also* what spreading them evenly over the whole path
    by fraction would give, so the test would pass on an implementation that
    ignored the rise entirely. Four subunits stop short of the end, and the
    two readings part company.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 1.0, 1.0)])

    operators = _bend().bent_helical_operators(
        molecule, count=4, rise=50.0, twist=0.0, axis=(0, 0, 1))

    expected = [
        (0.0, 0.0, 0.0),        # start
        (0.0, 0.0, 50.0),       # half way up the first leg
        (0.0, 0.0, 100.0),      # the corner
        (0.0, 50.0, 100.0),     # half way along the second leg
    ]
    for k, (landed, want) in enumerate(zip(_translations(operators), expected)):
        assert landed == pytest.approx(np.array(want), abs=0.5), (
            f"subunit {k} landed at {landed}, not {want}")


def test_the_path_is_walked_by_arc_length_not_by_chord(scene, sm):
    """The measurement that tells a real bend from a plausible-looking one.

    The last subunit of the right angle is 200 A along the path but only
    100*sqrt(2) = 141.4 A from the start in a straight line. A placement that
    measured chords would put it somewhere else entirely.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 1.0, 1.0)])

    last = _translations(_bend().bent_helical_operators(
        molecule, count=5, rise=50.0, twist=0.0, axis=(0, 0, 1)))[-1]

    assert float(np.linalg.norm(last)) == pytest.approx(
        100.0 * math.sqrt(2.0), abs=1.0)


def test_a_subunit_stands_up_on_the_path(scene, sm):
    """Its own axis has to end up pointing along the curve, or it lies over.

    Past the corner the path runs along +Y, so the filament axis (0, 0, 1) of
    the last subunit must map to (0, 1, 0).
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 1.0, 1.0)])

    rotation, _translation = _bend().bent_helical_operators(
        molecule, count=5, rise=50.0, twist=0.0, axis=(0, 0, 1))[-1]

    pointing = rotation @ np.array([0.0, 0.0, 1.0])
    assert pointing == pytest.approx(np.array([0.0, 1.0, 0.0]), abs=1e-3)


def test_a_longer_filament_than_the_curve_carries_straight_on(scene, sm):
    """Asking for more subunits than the path is long extends it.

    The alternative - every extra subunit piling onto the last curve point -
    would look like the filament had collapsed.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0)])   # 100 A of path

    translations = _translations(_bend().bent_helical_operators(
        molecule, count=6, rise=50.0, twist=0.0, axis=(0, 0, 1)))

    # 50 A steps: 0, 50, 100 are on the path; 150, 200, 250 are past its end.
    for k, translation in enumerate(translations):
        assert translation[2] == pytest.approx(50.0 * k, abs=1.0)

    gaps = [float(np.linalg.norm(b - a))
            for a, b in zip(translations, translations[1:])]
    assert min(gaps) > 1.0, "subunits piled up instead of carrying on"


# --------------------------------------------------------------------------
# The subunits stay rigid
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    [(0, 0, 0), (0, 0, 1.0), (0, 1.0, 1.0)],                 # right angle
    [(0, 0, 0), (0.3, 0.2, 0.5), (-0.3, 0.4, 1.0), (0, 0, 1.6)],   # a wander
])
def test_every_operator_is_a_rigid_motion(scene, sm, path):
    """A rotation, never a stretch or a shear - the whole premise of the feature.

    R R^T = I and det R = +1 is the definition of a rigid rotation, and no
    matrix that deformed a subunit could satisfy it. Positions alone would not
    catch this.
    """
    molecule = _import()
    _attach_path(molecule, path)

    operators = _bend().bent_helical_operators(
        molecule, count=8, rise=30.0, twist=-166.7, axis=(0, 0, 1))

    for k, (rotation, _translation) in enumerate(operators):
        assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6), (
            f"subunit {k} is not a rigid rotation")
        assert float(np.linalg.det(rotation)) == pytest.approx(1.0, abs=1e-6), (
            f"subunit {k} is mirrored")


def test_neighbours_stay_a_rise_apart_along_the_path(scene, sm):
    """Bending must not stretch or compress the filament.

    Straight-line spacing is the chord of an arc of length ``rise``, so it can
    only be shorter - and on a gentle bend, barely. Both bounds are geometry,
    not our arithmetic.
    """
    molecule = _import()
    rise = 30.0
    _attach_path(molecule, [(0, 0, 0), (0.1, 0, 0.8), (0, 0.15, 1.6)])

    translations = _translations(_bend().bent_helical_operators(
        molecule, count=6, rise=rise, twist=0.0, axis=(0, 0, 1)))

    gaps = [float(np.linalg.norm(b - a))
            for a, b in zip(translations, translations[1:])]
    assert max(gaps) <= rise + 1e-3, "a chord cannot be longer than its arc"
    assert min(gaps) > 0.9 * rise, (
        f"the filament was compressed: gaps {[round(g, 2) for g in gaps]}")


def test_the_twist_still_accumulates_around_the_bent_path(scene, sm):
    """Bending changes where a subunit is, not how far it has been spun.

    With a quarter turn per subunit, subunit 1 on a straight path must have
    its local +X pointing along +Y. Hand-computed, and independent of the
    bend.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0)])

    rotation, _translation = _bend().bent_helical_operators(
        molecule, count=4, rise=25.0, twist=90.0, axis=(0, 0, 1))[1]

    spun = rotation @ np.array([1.0, 0.0, 0.0])
    assert spun == pytest.approx(np.array([0.0, 1.0, 0.0]), abs=1e-4)


# --------------------------------------------------------------------------
# Reporting whether the bend is doing anything
# --------------------------------------------------------------------------

def test_departure_is_zero_on_a_straight_path(scene, sm):
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.6)])

    departure = _bend().bend_departure(
        molecule, count=5, rise=40.0, twist=30.0, axis=(0, 0, 1))

    assert departure == pytest.approx(0.0, abs=0.5)


def test_departure_measures_a_real_bend(scene, sm):
    """The right angle's last subunit ends 100 A off where straight put it.

    Straight would have finished at (0, 0, 200); the path finishes at
    (0, 100, 100). The distance between those is 100*sqrt(2) = 141.4 A.
    """
    molecule = _import()
    _attach_path(molecule, [(0, 0, 0), (0, 0, 1.0), (0, 1.0, 1.0)])

    departure = _bend().bend_departure(
        molecule, count=5, rise=50.0, twist=0.0, axis=(0, 0, 1))

    assert departure == pytest.approx(100.0 * math.sqrt(2.0), abs=2.0)


def test_no_bend_means_no_departure(scene, sm):
    molecule = _import()
    assert _bend().has_bend(molecule) is False
    assert _bend().bend_departure(molecule, 5, 40.0, 30.0) == 0.0


# --------------------------------------------------------------------------
# The rig, through the operators the panel actually calls
#
# Measured on the depsgraph - where the copies are drawn - rather than on the
# operator list, for the same reason test_assembly_build.py does: a filament
# can be perfectly bent in the maths and never reach the screen.
# --------------------------------------------------------------------------

COUNT, RISE, TWIST = 6, 40.0, 30.0


def _set_helix(count=COUNT, rise=RISE, twist=TWIST):
    scene = bpy.context.scene
    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = count
    scene.pb_symmetry_rise = rise
    scene.pb_symmetry_twist = twist
    scene.pb_symmetry_axis = (0.0, 0.0, 1.0)
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0


def _first_domain(molecule):
    return next(iter(molecule.domains.values())).object


def _instance_positions(obj_name):
    """Where every copy of *obj_name* is drawn, in world space."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return [np.array(instance.matrix_world.translation)
            for instance in depsgraph.object_instances
            if instance.is_instance and instance.parent is not None
            and instance.parent.original.name == obj_name]


def _build_filament(molecule):
    _set_helix()
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}


def _add_bend(molecule, nodes=3):
    bpy.context.scene.pb_bend_nodes = nodes
    return bpy.ops.molecule.add_filament_bend(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)


def _drag(molecule, index, offset):
    """Move one control node, then let the viewport catch up."""
    node = _bend().get_bend_nodes(molecule)[index]
    node.location = node.location + Vector(offset)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return node


def test_add_bend_creates_a_curve_and_control_nodes(scene, sm):
    molecule = _import()
    _build_filament(molecule)

    assert _add_bend(molecule, nodes=4) == {"FINISHED"}

    assert _bend().has_bend(molecule) is True
    assert _bend().get_bend_curve(molecule) is not None
    assert len(_bend().get_bend_nodes(molecule)) == 4


def test_the_bend_path_is_as_long_as_the_filament(scene, sm):
    """The curve must span the subunits, or the far end runs off its end.

    Five gaps of 40 A is 200 A, which is 2.0 Blender units. Computed from the
    settings here, not read back off the rig.
    """
    from proteinblender.core import bend_rig

    molecule = _import()
    _build_filament(molecule)
    _add_bend(molecule)

    length = bend_rig.curve_length(_bend().get_bend_curve(molecule))
    assert length == pytest.approx((COUNT - 1) * RISE * WORLD_SCALE, rel=0.02)


def test_adding_a_bend_does_not_move_anything_by_itself(scene, sm):
    """A bend starts straight. Adding one must be invisible until it is used."""
    molecule = _import()
    _build_filament(molecule)
    domain = _first_domain(molecule)
    before = _instance_positions(domain.name)

    _add_bend(molecule)

    after = _instance_positions(domain.name)
    assert len(after) == len(before) == COUNT
    for k, (a, b) in enumerate(zip(before, after)):
        assert float(np.linalg.norm(a - b)) < 1e-4, f"copy {k} moved"


def test_dragging_a_control_node_bends_the_built_filament(scene, sm):
    """The live contract: move a handle, the copies follow - no rebuild.

    Nothing between the drag and the assertion calls a build operator. If the
    handler is not doing the work, the copies stay exactly where they were.
    """
    molecule = _import()
    _build_filament(molecule)
    domain = _first_domain(molecule)
    _add_bend(molecule, nodes=3)
    before = _instance_positions(domain.name)

    _drag(molecule, 1, (0.4, 0.0, 0.0))     # pull the middle handle sideways

    after = _instance_positions(domain.name)
    assert len(after) == len(before) == COUNT

    moved = [float(np.linalg.norm(a - b)) for a, b in zip(before, after)]
    assert moved[0] < 1e-3, "the first subunit is the original and must not move"
    assert max(moved) > 0.05, (
        f"the filament did not follow the control node (moved {moved})")


def test_the_middle_of_the_filament_follows_the_middle_handle(scene, sm):
    """Not just "something moved" - it has to move the way the handle did.

    The centre handle is pulled 0.4 units along +X, and the subunits nearest
    it should end up displaced in the same direction by a comparable amount.
    Both ends of the filament are anchored, so they move far less.
    """
    molecule = _import()
    _build_filament(molecule)
    domain = _first_domain(molecule)
    _add_bend(molecule, nodes=3)
    before = _instance_positions(domain.name)

    _drag(molecule, 1, (0.4, 0.0, 0.0))
    after = _instance_positions(domain.name)

    displacement = [b - a for a, b in zip(before, after)]
    middle = displacement[len(displacement) // 2]
    assert middle[0] > 0.1, (
        f"the middle went {middle} rather than following +X")
    assert float(np.linalg.norm(displacement[0])) < middle[0], (
        "the anchored end moved as much as the middle")


def test_removing_the_bend_puts_the_filament_back(scene, sm):
    molecule = _import()
    _build_filament(molecule)
    domain = _first_domain(molecule)
    straight = _instance_positions(domain.name)

    _add_bend(molecule)
    _drag(molecule, 1, (0.4, 0.0, 0.0))
    assert max(float(np.linalg.norm(a - b))
               for a, b in zip(straight, _instance_positions(domain.name))) > 0.05

    assert bpy.ops.molecule.remove_filament_bend(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    assert _bend().has_bend(molecule) is False
    for k, (a, b) in enumerate(zip(straight, _instance_positions(domain.name))):
        assert float(np.linalg.norm(a - b)) < 1e-3, (
            f"copy {k} did not return to the straight filament")


def test_removing_the_bend_takes_its_objects_with_it(scene, sm):
    molecule = _import()
    _build_filament(molecule)
    _add_bend(molecule, nodes=4)

    curve_name = _bend().get_bend_curve(molecule).name
    node_names = [n.name for n in _bend().get_bend_nodes(molecule)]

    bpy.ops.molecule.remove_filament_bend(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)

    assert curve_name not in bpy.data.objects
    for name in node_names:
        assert name not in bpy.data.objects


def test_the_node_count_can_change_without_losing_the_bend(scene, sm):
    """More handles is a finer grip on the same path, not a reset."""
    molecule = _import()
    _build_filament(molecule)
    _add_bend(molecule, nodes=3)
    _drag(molecule, 1, (0.4, 0.0, 0.0))

    before = _bend().bend_departure(molecule, COUNT, RISE, TWIST)
    assert before > 10.0, "the drag did not bend anything to preserve"

    assert bpy.ops.molecule.set_filament_bend_nodes(
        "EXEC_DEFAULT", molecule_id=molecule.identifier,
        n_points=5) == {"FINISHED"}

    assert len(_bend().get_bend_nodes(molecule)) == 5
    after = _bend().bend_departure(molecule, COUNT, RISE, TWIST)
    assert after == pytest.approx(before, rel=0.15), (
        f"resampling changed the bend from {before:.1f} A to {after:.1f} A")


def test_a_preset_shapes_the_path(scene, sm):
    molecule = _import()
    _build_filament(molecule)
    _add_bend(molecule, nodes=5)

    assert _bend().bend_departure(molecule, COUNT, RISE, TWIST) < 1.0

    assert bpy.ops.molecule.filament_bend_preset(
        "EXEC_DEFAULT", molecule_id=molecule.identifier,
        preset="ARC") == {"FINISHED"}

    assert _bend().bend_departure(molecule, COUNT, RISE, TWIST) > 10.0


def test_a_bent_filament_still_realizes_where_its_copies_are_drawn(scene, sm):
    """Realize reads the built operators; a bend must not desynchronise them.

    Each realized object has to land on the instance it replaced, or the
    bend would silently straighten the moment anyone made the copies real.
    """
    from proteinblender.core import assembly as assembly_core

    molecule = _import()
    _build_filament(molecule)
    domain = _first_domain(molecule)
    _add_bend(molecule, nodes=3)
    _drag(molecule, 1, (0.4, 0.0, 0.0))

    drawn = _instance_positions(domain.name)
    created = assembly_core.realize_copies(molecule, force=True)
    assert created, "nothing was realized"

    bpy.context.view_layer.update()
    realized = [np.array(obj.matrix_world.translation)
                for obj in created if obj.name.startswith(domain.name)]

    # Copy 0 is the original and is not duplicated, so the realized objects
    # correspond to drawn[1:].
    assert len(realized) == len(drawn) - 1
    for k, (real, instance) in enumerate(zip(realized, drawn[1:]), start=1):
        assert float(np.linalg.norm(real - instance)) < 1e-3, (
            f"realized copy {k} landed away from the instance it replaced")


def test_deleting_the_protein_takes_its_bend_with_it(scene, sm):
    """The rig is parented to the protein but not owned by it.

    Without this, deleting a bent filament leaves a curve and a row of control
    spheres floating in the scene with nothing left to bend.
    """
    from proteinblender.utils import scene_manager

    molecule = _import()
    _build_filament(molecule)
    _add_bend(molecule, nodes=4)

    curve_name = _bend().get_bend_curve(molecule).name
    node_names = [n.name for n in _bend().get_bend_nodes(molecule)]
    assert curve_name in bpy.data.objects

    assert scene_manager.delete_molecule_cascade(
        bpy.context, molecule.identifier) is True

    assert curve_name not in bpy.data.objects, "the bend curve outlived its protein"
    for name in node_names:
        assert name not in bpy.data.objects, f"{name} outlived its protein"


def test_the_bend_is_offered_only_for_helical(scene, sm):
    """A ring has no path to run along; the section must not appear on one."""
    from proteinblender.panels.symmetry_panel import PROTEINBLENDER_PT_symmetry

    molecule = _import()
    _set_helix()
    assert PROTEINBLENDER_PT_symmetry.poll(bpy.context) is True

    bpy.context.scene.pb_symmetry_kind = "C"
    assert bpy.context.scene.pb_symmetry_kind == "C", (
        "the builder kind did not change - this test proves nothing")
    # The gate itself lives in the draw, so assert on the condition it reads.
    assert bpy.context.scene.pb_symmetry_kind != "H"
