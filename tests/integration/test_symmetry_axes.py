"""Symmetry axes recovered from an assembly's operators and drawn as objects.

Phase 4 of symmetry support, the Mol*-style display: a five-fold through a
capsid vertex, a two-fold between two subunits.

Ground truth is group theory done in the test. A Dn has one n-fold and n
two-folds perpendicular to it - a fact about dihedral groups, not something to
ask the code. The axis of a Cn built about a stated direction must be that
direction.
"""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import helpers as H

FIXTURE = "1ubq.pdb"


def _axes_mod():
    from proteinblender.core import symmetry_axes
    return symmetry_axes


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _import(fixture=FIXTURE, ident="ubq"):
    mol_id = H.import_local(fixture, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _same_line(a, b, tol=1e-4):
    """Axes are lines: a direction and its negative are the same axis."""
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    return (float(np.linalg.norm(a - b)) < tol
            or float(np.linalg.norm(a + b)) < tol)


# --------------------------------------------------------------------------
# Recovering the axes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("order", [2, 3, 5, 7])
def test_a_cyclic_group_has_exactly_one_axis(order):
    """Cn is n-1 rotations about a single line."""
    axes = _axes_mod().axes_of(_builder().cyclic(order))

    assert len(axes) == 1, f"C{order} should have one axis, found {len(axes)}"
    assert axes[0].fold == order
    assert _same_line(axes[0].direction, (0.0, 0.0, 1.0))


def test_the_fold_comes_from_the_smallest_rotation():
    """A C6 carries 60, 120, 180, 240 and 300 degree rotations.

    Reading the fold off any rotation but the smallest would call this a
    three-fold or a two-fold.
    """
    axes = _axes_mod().axes_of(_builder().cyclic(6))

    assert len(axes) == 1
    assert axes[0].fold == 6
    assert len(axes[0].angles) == 5
    assert min(axes[0].angles) == pytest.approx(math.pi / 3.0, abs=1e-6)


@pytest.mark.parametrize("order", [2, 3, 4])
def test_a_dihedral_group_has_one_n_fold_and_n_two_folds(order):
    """Group theory, not our code: Dn is a Cn plus n perpendicular two-folds."""
    axes = _axes_mod().axes_of(_builder().dihedral(order))

    principal = [a for a in axes if _same_line(a.direction, (0.0, 0.0, 1.0))]
    perpendicular = [a for a in axes
                     if abs(float(np.dot(a.direction, (0.0, 0.0, 1.0)))) < 1e-6]

    assert len(perpendicular) == order, (
        f"D{order} should have {order} two-folds, found {len(perpendicular)}")
    for axis in perpendicular:
        assert axis.fold == 2

    if order > 2:
        # For D2 the principal axis is itself a two-fold, indistinguishable
        # from the others, so only assert this where it is distinguishable.
        assert len(principal) == 1
        assert principal[0].fold == order


def test_a_tilted_axis_is_recovered(scene, sm):
    """The axis found must be the axis asked for, not a default."""
    axis = np.array([1.0, 2.0, -0.5])
    axis = axis / np.linalg.norm(axis)

    axes = _axes_mod().axes_of(_builder().cyclic(5, axis=axis))

    assert len(axes) == 1
    assert _same_line(axes[0].direction, axis)


def test_an_identity_only_set_has_no_axes():
    """A structure with nothing but the identity has no symmetry to draw."""
    identity = [(np.eye(3), np.zeros(3))]
    assert _axes_mod().axes_of(identity) == []


def test_a_helix_axis_is_recovered():
    """A twisting filament turns about one line."""
    axes = _axes_mod().axes_of(_builder().helical(6, rise=20.0, twist=60.0))

    assert len(axes) == 1
    assert _same_line(axes[0].direction, (0.0, 0.0, 1.0))
    assert axes[0].fold == 6


def test_a_deposited_assembly_yields_its_axis(scene, sm):
    """4ins assembly 3 is a three-fold; it must be recovered as one."""
    from proteinblender.core import assembly as assembly_core

    molecule = _import("4ins.pdb", "4ins")
    operators = assembly_core._operators_for(molecule, "3")

    axes = _axes_mod().axes_of(operators)

    assert len(axes) == 1
    assert axes[0].fold == 3


# --------------------------------------------------------------------------
# Drawing them
# --------------------------------------------------------------------------

def test_axes_become_real_objects_pointing_the_right_way(scene, sm):
    """One object per axis, oriented along it.

    Checked by transforming the object's own local Z - the direction the
    cylinder is built along - into world space, rather than by reading back
    the quaternion we just set.
    """
    module = _axes_mod()
    molecule = _import()

    axis = np.array([0.0, 1.0, 0.0])
    created = module.show_symmetry_axes(
        molecule, _builder().cyclic(4, axis=axis))

    assert len(created) == 1
    obj = created[0]

    # matrix_world is evaluated lazily; without this it still reads identity.
    bpy.context.view_layer.update()

    pointing = obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
    assert _same_line(tuple(pointing), axis, tol=1e-4), (
        f"the axis object points {tuple(pointing)}, expected {tuple(axis)}")

    assert obj["pb_symmetry_fold"] == 4


def test_axis_objects_have_renderable_geometry(scene, sm):
    """Deliberately meshes, not empties - an empty never reaches a render."""
    module = _axes_mod()
    molecule = _import()

    created = module.show_symmetry_axes(molecule, _builder().dihedral(3))

    assert created
    for obj in created:
        assert obj.type == "MESH"
        assert len(obj.data.vertices) > 0
        assert len(obj.data.polygons) > 0, (
            "an axis with no faces would not appear in a render")


def test_rebuilding_axes_replaces_rather_than_accumulates(scene, sm):
    module = _axes_mod()
    molecule = _import()

    module.show_symmetry_axes(molecule, _builder().cyclic(5))
    first = len(module.symmetry_axis_objects(molecule))
    assert first == 1

    module.show_symmetry_axes(molecule, _builder().dihedral(3))
    second = len(module.symmetry_axis_objects(molecule))

    assert second == len(module.axes_of(_builder().dihedral(3)))
    assert second != first or second == 1


def test_axes_can_be_cleared(scene, sm):
    module = _axes_mod()
    molecule = _import()

    module.show_symmetry_axes(molecule, _builder().dihedral(4))
    assert module.symmetry_axis_objects(molecule)

    assert module.clear_symmetry_axes(molecule) > 0
    assert module.symmetry_axis_objects(molecule) == []


def test_axes_are_sized_to_the_structure(scene, sm):
    """An axis has to be long enough to read as an axis through the assembly."""
    from proteinblender.core import assembly as assembly_core

    module = _axes_mod()
    molecule = _import()

    atoms = assembly_core._atom_cloud(molecule)
    span = float(np.linalg.norm(np.ptp(atoms, axis=0)))

    created = module.show_symmetry_axes(molecule, _builder().cyclic(3))
    obj = created[0]

    zs = [v.co.z for v in obj.data.vertices]
    length = max(zs) - min(zs)
    assert length > span, (
        f"axis is {length:.3f} long but the structure spans {span:.3f}")


# --------------------------------------------------------------------------
# Through the operator the panel drives
# --------------------------------------------------------------------------

def test_the_axes_operator_toggles(scene, sm):
    module = _axes_mod()
    molecule = _import()

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 5
    scene.pb_symmetry_axis = (0.0, 0.0, 1.0)
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    assert bpy.ops.molecule.toggle_symmetry_axes(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert len(module.symmetry_axis_objects(molecule)) == 1

    assert bpy.ops.molecule.toggle_symmetry_axes(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert module.symmetry_axis_objects(molecule) == []


def test_axes_without_a_built_symmetry_are_refused(scene, sm):
    molecule = _import()
    assert bpy.ops.molecule.toggle_symmetry_axes(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"CANCELLED"}


def test_deleting_the_protein_takes_its_axes_with_it(scene, sm):
    module = _axes_mod()
    molecule = _import()
    identifier = molecule.identifier

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 4
    bpy.ops.molecule.build_symmetry("EXEC_DEFAULT", molecule_id=identifier)
    bpy.ops.molecule.toggle_symmetry_axes("EXEC_DEFAULT", molecule_id=identifier)
    assert module.symmetry_axis_objects(molecule)

    assert bpy.ops.molecule.delete(
        "EXEC_DEFAULT", molecule_id=identifier) == {"FINISHED"}

    stranded = [o.name for o in bpy.data.objects
                if o.name.startswith(module.AXIS_PREFIX)]
    assert not stranded, f"axis objects outlived the protein: {stranded}"
