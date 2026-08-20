"""Generative symmetry - building an assembly the file does not describe.

Phase 3 of symmetry support. Cyclic, dihedral and helical symmetry generated
from parameters rather than read from `REMARK 350`, following ChimeraX's `sym`
vocabulary.

Ground truth here is trigonometry done in the test, never the generator. A
Cn ring of a point ``r`` from the axis puts consecutive copies
``2 r sin(pi/n)`` apart - a fact about circles, not about our code. Asserting
against ``build_operators`` output would pass whatever that function did.
"""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H

FIXTURE = "1ubq.pdb"           # a monomer: no deposited symmetry to confuse things
WORLD_SCALE = 0.01


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _import(fixture=FIXTURE, ident="ubq"):
    mol_id = H.import_local(fixture, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _instance_matrices(obj_name):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return [i.matrix_world.copy() for i in depsgraph.object_instances
            if i.is_instance and i.parent is not None
            and i.parent.original.name == obj_name]


def _chain_centroid_angstrom(fixture, chain_letter):
    coords = []
    with open(H.data_path(fixture)) as handle:
        for line in handle:
            if line.startswith("ATOM") and line[21] == chain_letter:
                coords.append([float(line[30:38]), float(line[38:46]),
                               float(line[46:54])])
    return np.array(coords).mean(axis=0)


def _landing_points(molecule, fixture=FIXTURE, chain_letter="A"):
    """Where the chain's centroid lands under each copy, in world space."""
    from proteinblender.core import domain_space

    obj = next(d.object for d in molecule.domains.values()
               if str(d.chain_id) == chain_letter)
    pivot = np.array(domain_space.get_pivot(obj))
    local = np.array(_chain_centroid_angstrom(fixture, chain_letter)) * WORLD_SCALE - pivot

    return [np.array(m @ Vector(local.tolist()))
            for m in _instance_matrices(obj.name)]


# --------------------------------------------------------------------------
# The operators themselves - pure maths, no Blender
# --------------------------------------------------------------------------

def test_cyclic_generates_evenly_spaced_rotations():
    """Cn must be n rotations at 360/n, starting from the identity."""
    builder = _builder()

    for order in (2, 3, 5, 7):
        operators = builder.cyclic(order)
        assert len(operators) == order

        assert np.allclose(operators[0][0], np.eye(3), atol=1e-9), (
            "the first copy of a ring must be the original, untouched")

        for k, (rotation, translation) in enumerate(operators):
            # A rotation by theta has trace 1 + 2 cos(theta).
            expected = 1.0 + 2.0 * math.cos(2.0 * math.pi * k / order)
            assert float(np.trace(rotation)) == pytest.approx(expected, abs=1e-9)
            assert np.allclose(translation, 0.0, atol=1e-9), (
                "a ring about the origin needs no translation")


def test_dihedral_is_a_ring_plus_a_flipped_ring():
    """Dn must be 2n operators, n of them reversing handedness.

    A proper rotation has determinant +1 either way, so the discriminator is
    that exactly half the copies are flipped relative to the axis: their
    two-fold sends the axis direction to its negative.
    """
    builder = _builder()

    for order in (2, 3, 6):
        operators = builder.dihedral(order)
        assert len(operators) == 2 * order

        axis = np.array([0.0, 0.0, 1.0])
        upright = sum(1 for rotation, _t in operators
                      if float(rotation @ axis @ axis) > 0.999)
        flipped = sum(1 for rotation, _t in operators
                      if float(rotation @ axis @ axis) < -0.999)
        assert upright == order, f"D{order}: expected {order} upright, got {upright}"
        assert flipped == order, f"D{order}: expected {order} flipped, got {flipped}"

        for rotation, _t in operators:
            assert float(np.linalg.det(rotation)) == pytest.approx(1.0, abs=1e-9), (
                "a symmetry copy must be a rotation, never a reflection")


def test_helical_advances_by_the_rise_and_twist():
    """Each helical subunit is one rise along the axis and one twist about it."""
    builder = _builder()

    rise, twist, count = 27.5, -166.7, 8
    operators = builder.helical(count, rise=rise, twist=twist)
    assert len(operators) == count

    axis = np.array([0.0, 0.0, 1.0])
    for k, (rotation, translation) in enumerate(operators):
        assert float(translation @ axis) == pytest.approx(rise * k, abs=1e-6)
        expected = 1.0 + 2.0 * math.cos(math.radians(twist) * k)
        assert float(np.trace(rotation)) == pytest.approx(expected, abs=1e-6)


def test_an_off_origin_axis_is_folded_into_the_translation():
    """Rotating about a centre must map that centre to itself."""
    builder = _builder()

    centre = np.array([10.0, -4.0, 3.0])
    for rotation, translation in builder.cyclic(5, centre=centre):
        assert np.allclose(rotation @ centre + translation, centre, atol=1e-9), (
            "the centre of rotation moved")


def test_a_tilted_axis_is_respected():
    """A non-Z axis must be the thing that stays fixed."""
    builder = _builder()

    axis = np.array([1.0, 1.0, 0.0]) / math.sqrt(2.0)
    for rotation, _t in builder.cyclic(6, axis=axis):
        assert np.allclose(rotation @ axis, axis, atol=1e-9), (
            "the symmetry axis is supposed to be invariant")


# --------------------------------------------------------------------------
# Placed in the scene
# --------------------------------------------------------------------------

def test_cyclic_places_copies_around_a_ring(scene, sm):
    """C7 on a monomer must produce seven copies on a circle.

    The expected gap is 2 r sin(pi/n) where r is the chain centroid's distance
    from the axis - trigonometry, computed here, owing nothing to the code
    under test.
    """
    molecule = _import()
    builder, core = _builder(), _assembly_core()

    order = 7
    assert builder.apply_symmetry(molecule, "C", order=order)

    points = _landing_points(molecule)
    assert len(points) == order

    centroid = _chain_centroid_angstrom(FIXTURE, "A") * WORLD_SCALE
    radius = float(np.linalg.norm(centroid[:2]))     # distance from the Z axis
    assert radius > 0.01, "fixture sits on the axis - the test would prove nothing"

    expected_gap = 2.0 * radius * math.sin(math.pi / order)

    # Consecutive copies, in generation order, are one step apart.
    for i in range(order):
        gap = float(np.linalg.norm(points[(i + 1) % order] - points[i]))
        assert gap == pytest.approx(expected_gap, rel=0.02), (
            f"copies {i} and {i+1} are {gap:.4f} apart, a C{order} ring of "
            f"radius {radius:.4f} puts them {expected_gap:.4f} apart")

    # And they all sit at the same height and the same radius.
    heights = [p[2] for p in points]
    assert max(heights) - min(heights) < 1e-5, "a ring should be planar"


def test_dihedral_places_twice_as_many_copies(scene, sm):
    molecule = _import()
    builder = _builder()

    assert builder.apply_symmetry(molecule, "D", order=4)
    assert len(_landing_points(molecule)) == 8


def test_helical_places_a_filament(scene, sm):
    """Consecutive subunits must climb the axis by exactly the rise."""
    molecule = _import()
    builder = _builder()

    rise, count = 25.0, 6
    assert builder.apply_symmetry(molecule, "H", count=count, rise=rise, twist=60.0)

    points = _landing_points(molecule)
    assert len(points) == count

    climbs = [float(points[i + 1][2] - points[i][2]) for i in range(count - 1)]
    for climb in climbs:
        assert climb == pytest.approx(rise * WORLD_SCALE, rel=0.01), (
            f"subunits climb {climb:.4f} but the rise is "
            f"{rise * WORLD_SCALE:.4f}")


def test_generated_symmetry_animates_like_a_deposited_one(scene, sm):
    """Generated copies must inherit the assemble/disassemble factor."""
    molecule = _import()
    builder, core = _builder(), _assembly_core()

    assert builder.apply_symmetry(molecule, "C", order=5)

    core.set_assembly_factor(molecule, 0.0)
    collapsed = _landing_points(molecule)
    for point in collapsed[1:]:
        assert np.allclose(point, collapsed[0], atol=1e-6), (
            "at factor 0 the generated copies should sit on the original")

    core.set_assembly_factor(molecule, 1.0)
    opened = _landing_points(molecule)
    spread = max(float(np.linalg.norm(opened[i] - opened[j]))
                 for i in range(len(opened)) for j in range(i + 1, len(opened)))
    assert spread > 0.01


def test_generated_symmetry_clears(scene, sm):
    molecule = _import()
    builder, core = _builder(), _assembly_core()

    assert builder.apply_symmetry(molecule, "C", order=5)
    assert builder.built_symmetry_kind(molecule) == "C"

    assert core.clear_assembly(molecule)
    assert core.built_assembly_id(molecule) is None
    assert builder.built_symmetry_kind(molecule) is None


def test_generated_symmetry_works_on_a_structure_with_no_deposited_assembly(scene, sm):
    """The whole point: 1ubq offers nothing, and can still be given symmetry."""
    molecule = _import()
    core = _assembly_core()

    assert not core.has_buildable_symmetry(molecule)
    assert _builder().apply_symmetry(molecule, "C", order=3)
    assert len(_landing_points(molecule)) == 3


def test_the_cubic_groups_are_refused_rather_than_guessed(scene, sm):
    """T/O/I need an explicit orientation convention, so they are not offered.

    Silently picking one would put every capsid subunit in the wrong place,
    which is exactly the class of bug this feature has already produced once.
    """
    builder = _builder()
    kinds = {kind for kind, _label, _desc in builder.SYMMETRY_KINDS}

    assert kinds == {"C", "D", "H"}
    for unsupported in ("T", "O", "I"):
        assert builder.build_operators(unsupported) == []


# --------------------------------------------------------------------------
# Through the operator the panel drives
# --------------------------------------------------------------------------

def test_build_symmetry_operator_reads_the_panel_settings(scene, sm):
    molecule = _import()

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 6
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert len(_landing_points(molecule)) == 6

    scene.pb_symmetry_kind = "D"
    scene.pb_symmetry_order = 3
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert len(_landing_points(molecule)) == 6

    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = 9
    scene.pb_symmetry_rise = 20.0
    scene.pb_symmetry_twist = 40.0
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert len(_landing_points(molecule)) == 9


def test_the_axis_setting_reaches_the_placed_copies(scene, sm):
    """A helix built along X must climb X, not Z."""
    molecule = _import()

    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = 5
    scene.pb_symmetry_rise = 30.0
    scene.pb_symmetry_twist = 0.0
    scene.pb_symmetry_axis = (1.0, 0.0, 0.0)

    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    points = _landing_points(molecule)
    climbs_x = [float(points[i + 1][0] - points[i][0]) for i in range(len(points) - 1)]
    climbs_z = [float(points[i + 1][2] - points[i][2]) for i in range(len(points) - 1)]

    for climb in climbs_x:
        assert climb == pytest.approx(30.0 * WORLD_SCALE, rel=0.01)
    for climb in climbs_z:
        assert abs(climb) < 1e-6, "the filament climbed Z despite an X axis"


def test_generated_symmetry_replaces_a_deposited_one(scene, sm):
    """Building either kind must replace the other, never stack."""
    core = _assembly_core()
    builder = _builder()

    molecule = _import("4ins.pdb", "4ins")
    assert core.build_assembly(molecule, "3")
    assert core.built_assembly_id(molecule) == "3"

    assert builder.apply_symmetry(molecule, "C", order=5)
    assert builder.built_symmetry_kind(molecule) == "C"
    assert len(_landing_points(molecule, "4ins.pdb", "A")) == 5
