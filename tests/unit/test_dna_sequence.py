"""Pure-logic unit tests for proteinblender/dna_builder/sequence_builder.py.

Covers the sequence utilities (complement, validation, helix info, wound
masks, cumulative twist) and a smoke build of a short duplex through
build_nucleic_acid, asserting the resulting biotite AtomArray has the
expected per-strand residue layout.
"""

import math

import pytest
import numpy as np

from proteinblender.dna_builder import sequence_builder as sb


# ---------------------------------------------------------------------------
# get_complement
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_complement_dna():
    # A<->T, G<->C
    assert sb.get_complement("ATGC", "DNA") == "TACG"


@pytest.mark.unit
def test_get_complement_dna_lowercase_uppercased():
    assert sb.get_complement("atgc", "DNA") == "TACG"


@pytest.mark.unit
def test_get_complement_rna():
    # A<->U, G<->C
    assert sb.get_complement("AUGC", "RNA") == "UACG"


# ---------------------------------------------------------------------------
# validate_sequence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_validate_sequence_accepts_valid_dna():
    assert sb.validate_sequence("ATGC", "DNA") == "ATGC"


@pytest.mark.unit
def test_validate_sequence_strips_invalid_and_uppercases():
    # Non-ATGC chars removed; case normalised.
    assert sb.validate_sequence("aXtZgQc", "DNA") == "ATGC"


@pytest.mark.unit
def test_validate_sequence_rna_rejects_thymine():
    # RNA valid alphabet is AUGC — T is stripped, U kept.
    assert sb.validate_sequence("AUGCT", "RNA") == "AUGC"


@pytest.mark.unit
def test_validate_sequence_empty():
    assert sb.validate_sequence("", "DNA") == ""


# ---------------------------------------------------------------------------
# calculate_helix_info
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_calculate_helix_info_dna_all_wound():
    info = sb.calculate_helix_info(10, "DNA")
    assert info["base_pairs"] == 10
    # rise = 3.38 A/bp
    assert info["helix_length_angstrom"] == pytest.approx(10 * 3.38)
    # 9 wound transitions * 36 deg / 360
    assert info["turns"] == pytest.approx(9 * 36.0 / 360.0)


@pytest.mark.unit
def test_calculate_helix_info_rna_uses_a_form():
    info = sb.calculate_helix_info(5, "RNA")
    assert info["helix_length_angstrom"] == pytest.approx(5 * 2.6)
    assert info["turns"] == pytest.approx(4 * 32.7 / 360.0)


@pytest.mark.unit
def test_calculate_helix_info_ladder_no_turns():
    # An all-unwound (ladder) mask contributes no wound transitions.
    mask = [False] * 6
    info = sb.calculate_helix_info(6, "DNA", wound_mask=mask)
    assert info["turns"] == pytest.approx(0.0)
    # z-extent is unaffected by unwinding.
    assert info["helix_length_angstrom"] == pytest.approx(6 * 3.38)


# ---------------------------------------------------------------------------
# make_wound_mask
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_make_wound_mask_helix_is_none():
    assert sb.make_wound_mask(10, "HELIX") is None


@pytest.mark.unit
def test_make_wound_mask_ladder_all_false():
    assert sb.make_wound_mask(4, "LADDER") == [False, False, False, False]


@pytest.mark.unit
def test_make_wound_mask_unknown_raises():
    with pytest.raises(ValueError):
        sb.make_wound_mask(4, "SPIRAL")


# ---------------------------------------------------------------------------
# _cumulative_twist
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cumulative_twist_all_wound():
    twist = 36.0
    cum = sb._cumulative_twist(3, twist, None)
    assert cum[0] == pytest.approx(0.0)
    assert cum[1] == pytest.approx(math.radians(36.0))
    assert cum[2] == pytest.approx(math.radians(72.0))


@pytest.mark.unit
def test_cumulative_twist_holds_across_unwound_gap():
    # A False endpoint freezes the angle across that transition.
    cum = sb._cumulative_twist(3, 36.0, [True, False, True])
    # k=1: wound[0] True but wound[1] False -> no increment.
    # k=2: wound[1] False -> no increment.
    assert cum == pytest.approx([0.0, 0.0, 0.0])


@pytest.mark.unit
def test_cumulative_twist_mask_length_mismatch_raises():
    with pytest.raises(ValueError):
        sb._cumulative_twist(3, 36.0, [True, True])


# ---------------------------------------------------------------------------
# build_nucleic_acid (smoke build of a real duplex)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_single_strand_residue_count():
    seq = "ATGC"
    arr = sb.build_nucleic_acid(seq, "DNA", double_stranded=False)
    # One chain, one residue per base.
    chains = set(np.unique(arr.chain_id))
    assert chains == {"A"}
    res_ids_a = np.unique(arr.res_id[arr.chain_id == "A"])
    assert len(res_ids_a) == len(seq)
    # Coordinates must be finite.
    assert np.all(np.isfinite(arr.coord))
    # Bonds were constructed.
    assert arr.bonds is not None and len(arr.bonds.as_array()) > 0


@pytest.mark.unit
def test_build_double_strand_two_chains():
    seq = "ATGC"
    arr = sb.build_nucleic_acid(seq, "DNA", double_stranded=True)
    chains = set(np.unique(arr.chain_id))
    assert chains == {"A", "B"}
    # Each strand carries one residue per base.
    assert len(np.unique(arr.res_id[arr.chain_id == "A"])) == len(seq)
    assert len(np.unique(arr.res_id[arr.chain_id == "B"])) == len(seq)
    # Double strand has strictly more atoms than the single strand.
    single = sb.build_nucleic_acid(seq, "DNA", double_stranded=False)
    assert len(arr) > len(single)


@pytest.mark.unit
def test_build_rna_uracil_has_no_c7():
    # RNA uracil drops the thymine-specific C7 methyl.
    arr = sb.build_nucleic_acid("AUGC", "RNA", double_stranded=False)
    u_mask = arr.res_name == "U"
    assert u_mask.any()
    assert "C7" not in set(arr.atom_name[u_mask])
