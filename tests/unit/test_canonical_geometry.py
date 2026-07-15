"""Pure-logic unit tests for proteinblender/dna_builder/canonical_geometry.py.

This module builds idealised LADDER-mode nucleotide templates procedurally
(0 bpy). Tests assert ring-atom counts, full template atom counts, that base
ring atoms lie in the z=0 plane, and that all coordinates are finite.
"""

import pytest
import numpy as np

from proteinblender.dna_builder import canonical_geometry as cg


# ---------------------------------------------------------------------------
# Ring builders
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pyrimidine_ring_has_six_atoms():
    ring = cg._pyrimidine_ring()
    assert set(ring) == {"N1", "C2", "N3", "C4", "C5", "C6"}
    assert len(ring) == 6
    # All ring atoms in the z=0 plane.
    assert all(pos[2] == pytest.approx(0.0) for pos in ring.values())


@pytest.mark.unit
def test_purine_rings_have_nine_ring_atoms():
    rings = cg._purine_rings()
    ring_atoms = {k: v for k, v in rings.items() if not k.startswith("_")}
    # 5-ring (N9,C4,C5,N7,C8) fused to 6-ring (adds N3,C2,N1,C6).
    assert set(ring_atoms) == {"N9", "C4", "C5", "N7", "C8", "N3", "C2", "N1", "C6"}
    assert len(ring_atoms) == 9
    assert all(pos[2] == pytest.approx(0.0) for pos in ring_atoms.values())
    # The helper stashes a hex-centre marker for exocyclic placement.
    assert "_hex_center" in rings


# ---------------------------------------------------------------------------
# build_canonical_template
# ---------------------------------------------------------------------------

# 11 backbone atoms + base atoms (rings + exocyclic substituents).
_EXPECTED_ATOM_COUNT = {
    "DA": 11 + 10,   # 9 ring + N6
    "DG": 11 + 11,   # 9 ring + O6 + N2
    "DC": 11 + 8,    # 6 ring + O2 + N4
    "DT": 11 + 9,    # 6 ring + O2 + O4 + C7
}


@pytest.mark.unit
@pytest.mark.parametrize("key,expected", _EXPECTED_ATOM_COUNT.items())
def test_build_canonical_template_atom_counts(key, expected):
    arr = cg.build_canonical_template(key, realistic=False)
    assert len(arr) == expected
    assert set(np.unique(arr.res_name)) == {key}


@pytest.mark.unit
@pytest.mark.parametrize("key", ["DA", "DG", "DC", "DT"])
def test_build_canonical_template_coords_finite(key):
    arr = cg.build_canonical_template(key, realistic=True)
    assert np.all(np.isfinite(arr.coord))
    # C1' anchors the template at the origin.
    c1 = arr.coord[arr.atom_name == "C1'"][0]
    assert np.allclose(c1, (0.0, 0.0, 0.0), atol=1e-6)


@pytest.mark.unit
def test_stylised_template_is_flat():
    # realistic=False collapses the whole residue (backbone + base) to z=0.
    arr = cg.build_canonical_template("DG", realistic=False)
    assert np.allclose(arr.coord[:, 2], 0.0, atol=1e-6)


@pytest.mark.unit
def test_realistic_backbone_has_z_extent():
    # realistic=True keeps a 3D backbone extent (some atoms off the z=0 plane).
    arr = cg.build_canonical_template("DG", realistic=True)
    assert np.any(np.abs(arr.coord[:, 2]) > 0.1)


@pytest.mark.unit
def test_base_ring_atoms_flat_even_when_realistic():
    # Base ring atoms are always in the z=0 plane so the cartoon rung is flat.
    arr = cg.build_canonical_template("DA", realistic=True)
    for name in ("N1", "C2", "N3", "C4", "C5", "C6", "N7", "C8", "N9"):
        z = arr.coord[arr.atom_name == name][0][2]
        assert z == pytest.approx(0.0, abs=1e-6)


@pytest.mark.unit
def test_build_canonical_template_unknown_key_raises():
    with pytest.raises(ValueError):
        cg.build_canonical_template("DX", realistic=False)


# ---------------------------------------------------------------------------
# get_canonical_templates
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("realistic", [False, True])
def test_get_canonical_templates_all_bases(realistic):
    templates = cg.get_canonical_templates(realistic=realistic)
    assert set(templates) == {"DA", "DT", "DG", "DC"}
    for key, arr in templates.items():
        assert len(arr) == _EXPECTED_ATOM_COUNT[key]
        assert np.all(np.isfinite(arr.coord))


@pytest.mark.unit
def test_schematic_purine_aligns_by_n3():
    # In schematic (uniform-rungs) mode purines are aligned by N3 onto -X,
    # so N3 lands on the negative X axis with ~zero y.
    arr = cg.build_canonical_template("DA", realistic=False, schematic=True)
    n3 = arr.coord[arr.atom_name == "N3"][0]
    assert n3[0] < 0.0
    assert n3[1] == pytest.approx(0.0, abs=1e-6)
