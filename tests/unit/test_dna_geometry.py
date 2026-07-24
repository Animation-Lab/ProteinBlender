"""Geometric-accuracy tests for the nucleic-acid builder (HELIX mode).

These assert *canonical* geometry against ground truth that is independent of
the builder's own code (covalent bond lengths, Watson-Crick H-bond distances,
and published fiber-diffraction helical constants) - never a value derived from
the function under test.  This is what distinguishes a real regression test
from a facade: the old extract-and-stamp builder produced these same
AtomArrays with a torn backbone (O3'->P of 2.5-8.7 A) and mispaired bases
(1/12 correct), and every assertion below fails on it.

Ground-truth constants (all external):
  * O3'(i)-O... P(i+1) is a covalent phosphodiester bond: ~1.6 A.
  * Watson-Crick partners sit ~10.5 A apart (C1'-C1').
  * A WC pair's purine-N1 / pyrimidine-N3 hydrogen bond is ~2.85 A.
  * Canonical fiber parameters: B-DNA 3.38 A / 36.0 deg; A-DNA 2.56 / 32.7;
    A-RNA 2.81 / 32.7  (Arnott fiber models).
"""

import math

import numpy as np
import pytest
import biotite.structure as struc

from proteinblender.dna_builder import sequence_builder as sb


_PURINE_RES = {"DA", "DG", "A", "G"}


def _atoms(arr, chain, name):
    m = (arr.chain_id == chain) & (arr.atom_name == name)
    return arr.coord[m], arr.res_id[m]


def _backbone_bond_lengths(arr, chain):
    """O3'(i) -> P(i+1) phosphodiester bond length for every step."""
    o3, o3r = _atoms(arr, chain, "O3'")
    p, pr = _atoms(arr, chain, "P")
    o3map = {int(r): c for r, c in zip(o3r, o3)}
    pmap = {int(r): c for r, c in zip(pr, p)}
    return np.array([np.linalg.norm(o3map[r] - pmap[r + 1])
                     for r in sorted(o3map) if r + 1 in pmap])


def _measured_rise_twist(arr, chain):
    """Mean rise (Å) and twist (deg) per step from the C1' trace.

    The fiber helix axis is +Z through the origin (the convention the bend rig
    depends on), so the twist is the azimuthal step of C1' measured about the
    origin - not about the C1' centroid, which is offset for a non-integer
    number of turns and biases A-form twist.
    """
    c1, r = _atoms(arr, chain, "C1'")
    c1 = c1[np.argsort(r)]
    rise = float(np.diff(c1[:, 2]).mean())
    ang = np.unwrap(np.arctan2(c1[:, 1], c1[:, 0]))
    twist = math.degrees(float(np.diff(ang).mean()))
    return rise, twist


# ---------------------------------------------------------------------------
# Backbone continuity
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("seq,nt,form", [
    ("CGCGAATTCGCG", "DNA", "B"),
    ("ATCGATCGATCGATCG", "DNA", "B"),
    ("GGGGCCCCAAAATTTT", "DNA", "A"),
    ("AUGCAUGCAUGC", "RNA", "B"),
])
def test_backbone_is_continuous(seq, nt, form):
    arr = sb.build_nucleic_acid(seq, nt, double_stranded=True, form=form)
    for chain in ("A", "B"):
        ds = _backbone_bond_lengths(arr, chain)
        assert len(ds) == len(seq) - 1, f"missing backbone steps on chain {chain}"
        # Phosphodiester bond ~1.6 A. A torn backbone (the old bug) is >2 A.
        assert ds.max() < 1.8, (
            f"chain {chain} backbone torn: O3'->P up to {ds.max():.2f} A "
            f"(covalent bond is ~1.6)")
        assert ds.min() > 1.4


# ---------------------------------------------------------------------------
# Watson-Crick pairing
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("seq,nt,form", [
    ("CGCGAATTCGCG", "DNA", "B"),
    ("ATCGATCGATCGATCG", "DNA", "B"),
    ("AUGCAUGCAUGC", "RNA", "B"),
])
def test_watson_crick_pairing(seq, nt, form):
    arr = sb.build_nucleic_acid(seq, nt, double_stranded=True, form=form)
    n = len(seq)

    ca, ra = _atoms(arr, "A", "C1'")
    cb, rb = _atoms(arr, "B", "C1'")
    a_c1 = {int(r): c for r, c in zip(ra, ca)}
    b_c1 = {int(r): c for r, c in zip(rb, cb)}

    for j in range(1, n + 1):
        partner = n + 1 - j  # A res j pairs B res (n+1-j)
        d = np.linalg.norm(a_c1[j] - b_c1[partner])
        # Canonical WC C1'-C1' ~10.5 A. The old bug collapsed strands to ~7.5.
        assert 9.5 < d < 11.5, (
            f"pair A{j}/B{partner}: C1'-C1' {d:.2f} A (canonical ~10.5)")


@pytest.mark.unit
def test_base_pairs_hydrogen_bond():
    """Every base pair forms a real WC purine-N1 / pyrimidine-N3 H-bond (~2.85 A).

    The old builder mispaired bases, so the correct-orientation N1-N3 distance
    was large (wrong partner) - this is the assertion that bug most clearly
    violates.
    """
    seq = "CGCGAATTCGCG"
    arr = sb.build_nucleic_acid(seq, "DNA", double_stranded=True, form="B")
    n = len(seq)

    def atom(chain, resid, name):
        m = ((arr.chain_id == chain) & (arr.res_id == resid)
             & (arr.atom_name == name))
        c = arr.coord[m]
        return c[0] if len(c) else None

    for j in range(1, n + 1):
        partner = n + 1 - j
        rn_a = arr.res_name[(arr.chain_id == "A") & (arr.res_id == j)][0]
        # purine strand supplies N1, pyrimidine strand supplies N3
        if rn_a in _PURINE_RES:
            n1 = atom("A", j, "N1"); n3 = atom("B", partner, "N3")
        else:
            n1 = atom("B", partner, "N1"); n3 = atom("A", j, "N3")
        assert n1 is not None and n3 is not None
        d = np.linalg.norm(n1 - n3)
        assert d < 3.2, f"pair A{j}/B{partner}: N1-N3 {d:.2f} A (WC H-bond ~2.85)"


# ---------------------------------------------------------------------------
# Helical parameters match the canonical fiber constants
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("seq,nt,form,exp_rise,exp_twist", [
    ("ATCGATCGATCGATCG", "DNA", "B", 3.38, 36.0),
    ("GGGGCCCCAAAATTTT", "DNA", "A", 2.56, 32.7),
    ("AUGCAUGCAUGCAUGC", "RNA", "B", 2.81, 32.7),
])
def test_helical_parameters(seq, nt, form, exp_rise, exp_twist):
    arr = sb.build_nucleic_acid(seq, nt, double_stranded=True, form=form)
    rise, twist = _measured_rise_twist(arr, "A")
    assert rise == pytest.approx(exp_rise, abs=0.05)
    assert abs(twist) == pytest.approx(exp_twist, abs=1.5)


# ---------------------------------------------------------------------------
# MolecularNodes gate: biotite must recognise these as nucleotides
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_recognised_as_nucleic_by_biotite():
    arr = sb.build_nucleic_acid("ATCGATCG", "DNA", double_stranded=True, form="B")
    # MN selects the nucleic cartoon path via struc.filter_nucleotides.
    assert struc.filter_nucleotides(arr).all()


@pytest.mark.unit
def test_no_stretched_bonds():
    """No bond in the built duplex exceeds a real covalent length."""
    arr = sb.build_nucleic_acid("ATCGATCGATCG", "DNA", double_stranded=True,
                                form="B")
    assert arr.bonds is not None
    for i, j, _ in arr.bonds.as_array():
        d = np.linalg.norm(arr.coord[i] - arr.coord[j])
        assert d < 2.0, (
            f"stretched bond {arr.atom_name[i]}-{arr.atom_name[j]} = {d:.2f} A")
