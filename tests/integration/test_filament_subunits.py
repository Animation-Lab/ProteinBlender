"""A built filament's subunits: what they and their copies are called.

The names are judged against the shipped structure itself: which chain of the
tubulin dimer is alpha and which is beta is read off the start of each chain's
sequence in the PDB text (``filament_checks.tubulin_chains``), not taken from
the preset that names them.
"""

import re

from filament_checks import build as _build
from filament_checks import chain_rows as _chain_rows
from filament_checks import realize as _realize
from filament_checks import tubulin_chains as _tubulin_chains

# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def test_a_microtubule_names_its_chains_alpha_and_beta_tubulin():
    chains = _tubulin_chains()
    molecule = _build("MICROTUBULE", 17.0)

    assert sorted(_chain_rows(molecule.identifier)) == [
        "Alpha Tubulin", "Beta Tubulin"]
    by_chain = {str(d.chain_id): d.name for d in molecule.domains.values()}
    assert by_chain[chains["alpha"]] == "Alpha Tubulin"
    assert by_chain[chains["beta"]] == "Beta Tubulin"


def test_an_actin_filament_names_its_chain_actin():
    molecule = _build("ACTIN", 11.0)
    assert _chain_rows(molecule.identifier) == ["Actin"]


def test_realized_microtubule_copies_are_tubulin_dimers():
    """17 nm is two dimers up each of 13 protofilaments: 26, the original and 25 copies."""
    molecule = _build("MICROTUBULE", 17.0)
    made = _realize(molecule)

    assert len(made) == 25
    assert all(re.fullmatch(r"tubulin_dimer_\d+", name) for name in made), made
    assert sorted(int(name.rsplit("_", 1)[1]) for name in made) == list(range(1, 26))


def test_realized_tubulin_dimers_keep_their_chain_names():
    molecule = _build("MICROTUBULE", 9.0)
    made = _realize(molecule)
    assert made
    for name in made:
        assert sorted(_chain_rows(name)) == ["Alpha Tubulin", "Beta Tubulin"], name


def test_realized_actin_copies_are_named_actin():
    molecule = _build("ACTIN", 11.0)
    made = _realize(molecule)

    assert len(made) == 3
    assert made == ["actin_1", "actin_2", "actin_3"]


def test_realizing_a_second_microtubule_keeps_counting():
    """Identifiers are unique across the scene, so a second filament's copies go on from the first's."""
    first = _build("MICROTUBULE", 9.0)
    second = _build("MICROTUBULE", 9.0)
    made = _realize(first) + _realize(second)
    assert len(made) == len(set(made)) == 24
