"""Filament presets - a named filament that builds as the real one.

A preset is a shipped subunit plus the lattice that repeats it. Both halves
can be wrong independently: a lattice with the right numbers still builds the
wrong filament if the subunit is not standing where the axis expects it, and a
perfectly placed subunit builds nonsense under the wrong rise.

So the check that matters is against the structure the subunit was cut from.
PDB 8A2T is five actin subunits of a real filament; PDB 7SJ7 is six tubulin
dimers of a real 13-protofilament microtubule. Each deposit holds the
subunit's *neighbours*, and ``tests/data/filaments`` records where a few of
their C-alpha atoms are - deposited coordinates, moved rigidly into the
shipped subunit's frame and otherwise untouched. A preset is right if building
its lattice in Blender draws copies standing to one another as the subunit
stands to those neighbours. Nothing here asks the lattice generator, or the
preset, where a copy should be: the drawn atoms are read back out of the
evaluated scene and compared with the deposit.
"""

import os

import bpy
import numpy as np
import pytest

import filament_checks as F
import helpers as H

#: How closely two built copies have to reproduce a deposited neighbour pair,
#: in Angstrom. A cryo-EM filament is not perfectly regular - neighbouring
#: pairs in 7SJ7 differ from one another by about half an Angstrom - so this
#: is that, plus room. A wrong lattice misses by tens of Angstrom.
TOLERANCE = 1.0


def _presets():
    return F.presets()


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _import(preset):
    path = _presets().structure_path(preset)
    mol_id = H.import_local(path, preset.id.lower())
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


# --------------------------------------------------------------------------
# What ships
# --------------------------------------------------------------------------

def test_there_is_an_actin_and_a_microtubule_preset():
    ids = {preset.id for preset in _presets().PRESETS}
    assert {"ACTIN", "MICROTUBULE"} <= ids


@pytest.mark.parametrize("preset_id", ["ACTIN", "MICROTUBULE"])
def test_a_preset_ships_its_subunit(preset_id):
    presets = _presets()
    path = presets.structure_path(presets.get(preset_id))
    assert os.path.exists(path), f"{preset_id} names a structure that is not shipped"
    assert F.alpha_carbons(path), "the shipped structure has no protein in it"


def test_an_unknown_preset_is_none_rather_than_a_guess():
    assert _presets().get("NOT_A_FILAMENT") is None


# --------------------------------------------------------------------------
# The numbers, against the literature rather than against themselves
# --------------------------------------------------------------------------

def test_actin_has_actins_helix():
    """27.5 A and -166.7 degrees per subunit: one start, left-handed."""
    actin = _presets().get("ACTIN")
    assert actin.strands == 1
    assert actin.rise == pytest.approx(27.5, abs=0.3)
    assert actin.twist == pytest.approx(-166.7, abs=0.3)


def test_a_microtubule_closes_and_has_its_seam():
    """Two facts about a 13-protofilament microtubule, neither a parameter.

    Thirteen strands must come back to where they started, and they wind
    left-handed. And one trip round must climb three tubulin *monomers* - a
    dimer and a half - which is what leaves the seam.
    """
    tube = _presets().get("MICROTUBULE")
    assert tube.strands == 13
    assert tube.strand_twist * tube.strands == pytest.approx(-360.0, abs=1e-6)
    assert tube.stagger * tube.strands == pytest.approx(1.5 * tube.rise, abs=1e-6)
    # A tubulin dimer is about 8 nm long.
    assert tube.rise == pytest.approx(81.5, abs=1.5)
    # Protofilaments of a 13-strand microtubule run straight up it.
    assert tube.twist == pytest.approx(0.0, abs=0.5)


def test_length_is_counted_along_one_strand():
    """A micron of microtubule is a micron of protofilament, thirteen times.

    10,000 A at 81.5 A a dimer is 122.7, so 123 dimers along each strand -
    not 123 dimers in all, and not 13 times too many.
    """
    presets = _presets()
    tube, actin = presets.get("MICROTUBULE"), presets.get("ACTIN")
    assert tube.count_for_length(10000.0) == 123
    assert actin.count_for_length(275.0) == 10
    assert actin.count_for_length(0.0) == 1, "a filament has at least one subunit"

    assert tube.subunit_total(123) == 123 * 13
    assert actin.subunit_total(10) == 10


def test_settings_are_what_the_builder_takes():
    """A preset's settings must build as they stand - no translation layer."""
    tube = _presets().get("MICROTUBULE")
    settings = tube.settings(count=2)
    assert settings.pop("kind") == "H"
    assert len(_builder().build_operators("H", **settings)) == 2 * 13


# --------------------------------------------------------------------------
# The filament itself, against the structure it was cut from
# --------------------------------------------------------------------------

def test_actin_lands_on_the_neighbours_in_the_deposit(scene, sm):
    """One and two subunits either side along the filament, as PDB 8A2T has them.

    Chain C is the shipped subunit. D and E are the next two up from it and B
    and A the two below; a pair of copies one step apart stands both ways
    round, so all four are arrangements the built filament must contain.
    """
    preset = _presets().get("ACTIN")
    molecule = _import(preset)
    settings = preset.settings(count=4)
    assert _builder().apply_symmetry(molecule, settings.pop("kind"), **settings)

    neighbours = F.truth("ACTIN")["neighbours"]
    assert {n["deposit_chain"] for n in neighbours} == {"A", "B", "D", "E"}
    for neighbour in neighbours:
        miss = F.worst_miss(molecule, preset, neighbour)
        assert miss < TOLERANCE, (
            f"no two copies stand as the subunit and deposited chain "
            f"{neighbour['deposit_chain']} do: the closest pair is "
            f"{miss:.1f} A out")


def test_a_microtubule_lands_on_the_neighbours_in_the_deposit(scene, sm):
    """Next protofilament, next dimer, and both at once, as PDB 7SJ7 has them.

    Chain D is the one that shows the dimer moves as a unit: it is the *beta*
    tubulin of the neighbouring protofilament, checked against the shipped
    beta chain.
    """
    preset = _presets().get("MICROTUBULE")
    molecule = _import(preset)
    settings = preset.settings(count=2)
    assert _builder().apply_symmetry(molecule, settings.pop("kind"), **settings)

    neighbours = F.truth("MICROTUBULE")["neighbours"]
    assert {n["deposit_chain"] for n in neighbours} == {"C", "D", "K", "L"}
    for neighbour in neighbours:
        miss = F.worst_miss(molecule, preset, neighbour)
        assert miss < TOLERANCE, (
            f"no two copies stand as the subunit and deposited chain "
            f"{neighbour['deposit_chain']} do: the closest pair is "
            f"{miss:.1f} A out")


def test_a_microtubule_is_a_tube_of_the_right_width(scene, sm):
    """About 25 nm across, measured on the copies rather than read from a file.

    The published outer diameter is 25 nm and the wall is about 5 nm thick, so
    the middle of the wall - where a dimer's centre is - is near 11 nm out.
    Every copy's centre must be that far from the axis, which a subunit that
    was not standing on the axis could not manage: its ring would be lopsided.
    """
    preset = _presets().get("MICROTUBULE")
    molecule = _import(preset)
    settings = preset.settings(count=1)
    assert _builder().apply_symmetry(molecule, settings.pop("kind"), **settings)

    centres = F.chain_centres(molecule, preset, "A")
    assert len(centres) == 13

    # The middle of a regular 13-gon is the mean of its corners, so the axis
    # is found from the copies themselves rather than assumed to be anywhere.
    middle = centres.mean(axis=0)
    radii = np.hypot(centres[:, 0] - middle[0], centres[:, 1] - middle[1])
    assert radii.min() == pytest.approx(110.0, abs=8.0)
    assert radii.max() - radii.min() < 0.01, "the ring is not round"
