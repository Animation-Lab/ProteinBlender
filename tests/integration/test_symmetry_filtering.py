"""Trimming an assembly down to a legible patch.

Phase 4 of symmetry support: ChimeraX's `range` and `contact` options on
`sym`, which are what turn a 60-copy capsid into "the subunits around this
one".

Ground truth is geometry computed here. A Cn ring of a point `r` from the axis
puts the copy `k` steps round at `2 r sin(k pi / n)` from the original - so
which copies survive a given range limit is arithmetic, not something to ask
the filter about.
"""

import math

import bpy
import numpy as np
import pytest

import helpers as H

FIXTURE = "1ubq.pdb"
WORLD_SCALE = 0.01


def _core():
    from proteinblender.core import assembly
    return assembly


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _import(fixture=FIXTURE, ident="ubq"):
    mol_id = H.import_local(fixture, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _centroid_angstrom(fixture=FIXTURE, chain_letter="A"):
    coords = []
    with open(H.data_path(fixture)) as handle:
        for line in handle:
            if line.startswith("ATOM") and line[21] == chain_letter:
                coords.append([float(line[30:38]), float(line[38:46]),
                               float(line[46:54])])
    return np.array(coords).mean(axis=0)


def _ring_gaps(order, radius_angstrom):
    """Distance from copy 0 to copy k, for a ring of this radius."""
    return [2.0 * radius_angstrom * math.sin(math.pi * k / order)
            for k in range(order)]


# --------------------------------------------------------------------------
# Range
# --------------------------------------------------------------------------

def test_range_keeps_exactly_the_copies_within_it(scene, sm):
    """Which copies survive is arithmetic on a circle, not a question for us.

    The molecule's own centroid is what the filter measures, so the ring
    radius is that centroid's distance from the axis.
    """
    molecule = _import()
    core, builder = _core(), _builder()

    order = 8
    atoms = core._atom_cloud(molecule)
    assert atoms is not None
    centroid = atoms.mean(axis=0)
    radius = float(np.linalg.norm(centroid[:2])) / WORLD_SCALE   # Angstrom

    gaps = _ring_gaps(order, radius)
    operators = builder.cyclic(order)

    # A limit halfway between the second and third distinct distances keeps
    # the original plus the copies nearer than it.
    ordered = sorted(set(round(g, 6) for g in gaps))
    assert len(ordered) >= 3, "ring too degenerate to test a cutoff on"
    limit = (ordered[1] + ordered[2]) / 2.0

    expected = sum(1 for g in gaps if g <= limit)
    kept = core.filter_operators(molecule, operators, range_limit=limit)

    assert len(kept) == expected, (
        f"a {limit:.2f} A limit on a C{order} ring of radius {radius:.2f} A "
        f"should keep {expected} copies, kept {len(kept)}")


def test_range_zero_keeps_only_the_original(scene, sm):
    """The identity always survives - trimming away what you are looking at
    would be a strange reading of "show me its neighbours"."""
    molecule = _import()
    core, builder = _core(), _builder()

    kept = core.filter_operators(molecule, builder.cyclic(6), range_limit=0.0)

    assert len(kept) == 1
    assert np.allclose(kept[0][0], np.eye(3), atol=1e-9)


def test_a_generous_range_keeps_everything(scene, sm):
    molecule = _import()
    core, builder = _core(), _builder()

    operators = builder.cyclic(6)
    kept = core.filter_operators(molecule, operators, range_limit=1e6)

    assert len(kept) == len(operators)


def test_no_limits_means_no_filtering(scene, sm):
    molecule = _import()
    core, builder = _core(), _builder()

    operators = builder.cyclic(5)
    assert len(core.filter_operators(molecule, operators)) == len(operators)


# --------------------------------------------------------------------------
# Contact
# --------------------------------------------------------------------------

def test_contact_drops_copies_that_never_touch(scene, sm):
    """A filament spread far apart has no touching subunits but the original."""
    molecule = _import()
    core, builder = _core(), _builder()

    # 200 A apart is far beyond any contact for a protein this size.
    operators = builder.helical(5, rise=200.0, twist=0.0)
    kept = core.filter_operators(molecule, operators, contact_distance=4.0)

    assert len(kept) == 1, "nothing should touch across a 200 A gap"


def test_contact_keeps_copies_that_do_touch(scene, sm):
    """Subunits stacked almost on top of each other are all in contact."""
    molecule = _import()
    core, builder = _core(), _builder()

    operators = builder.helical(4, rise=1.0, twist=0.0)
    kept = core.filter_operators(molecule, operators, contact_distance=4.0)

    assert len(kept) == len(operators), (
        "subunits 1 A apart are certainly in contact")


def test_contact_threshold_is_in_angstrom(scene, sm):
    """The cutoff must behave as Angstrom, not as Blender units.

    A rise just beyond the threshold must drop the copy, and one just inside
    must keep it - a factor-of-100 scale error would fail one of these.
    """
    molecule = _import()
    core, builder = _core(), _builder()

    atoms = core._atom_cloud(molecule)
    extent = float(np.ptp(atoms[:, 2])) / WORLD_SCALE     # Angstrom along Z

    # Translate the copy clear of the original, then ask for a cutoff either
    # side of the gap that leaves.
    rise = extent + 20.0
    operators = builder.helical(2, rise=rise, twist=0.0)

    assert len(core.filter_operators(
        molecule, operators, contact_distance=5.0)) == 1
    assert len(core.filter_operators(
        molecule, operators, contact_distance=rise + 10.0)) == 2


# --------------------------------------------------------------------------
# Through a real build
# --------------------------------------------------------------------------

def test_a_filtered_assembly_places_only_the_kept_copies(scene, sm):
    """Filtering has to reach the scene, not just the operator list."""
    molecule = _import()
    core, builder = _core(), _builder()

    operators = builder.cyclic(8)
    kept = core.filter_operators(molecule, operators, range_limit=0.0)
    assert len(kept) == 1

    assert core.apply_operators(molecule, kept, "filtered")

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    domain = next(iter(molecule.domains.values())).object
    placed = sum(1 for i in depsgraph.object_instances
                 if i.is_instance and i.parent is not None
                 and i.parent.original.name == domain.name)

    assert placed == 1, f"expected the original only, {placed} copies placed"


def test_the_panel_limits_reach_the_build_operators(scene, sm):
    """Range and contact set in the panel must trim a real build."""
    molecule = _import()

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 8
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0

    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    unfiltered = _placed(molecule)
    assert unfiltered == 8

    # A range of 0 keeps only the original.
    scene.pb_symmetry_range = 0.0001
    assert bpy.ops.molecule.build_symmetry(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    assert _placed(molecule) == 1

    scene.pb_symmetry_range = 0.0


def _placed(molecule):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    domain = next(iter(molecule.domains.values())).object
    return sum(1 for i in depsgraph.object_instances
               if i.is_instance and i.parent is not None
               and i.parent.original.name == domain.name)
