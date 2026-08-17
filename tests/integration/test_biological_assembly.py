"""Biological assembly (BIOMT / mmCIF) parsing and building.

Reported: building the biological assembly of a structure imported as ``.pdb``
crashed. ``PDBAssemblyParser.get_transformations`` returned
``(chain_ids, matrix)`` tuples while its only consumer,
``utils.array_quaternions_from_dict``, indexes them as dicts by
``chain_ids`` / ``matrix`` / ``pdb_model_num`` - so building raised
``TypeError: list indices must be integers or slices, not str``.

``CIFAssemblyParser`` already returned the dict form, so the two parsers
implementing the same abstract interface disagreed about what that interface
is. The fix makes both return the dict form and corrects the stale contract
docstring on ``AssemblyParser`` that still described the tuple.

Ground truth here is the ``REMARK 350`` text of the fixture, parsed by
``_remark_350_transforms`` below, plus hand-read constants copied out of
``tests/data/4ins.pdb``. Neither goes anywhere near the parser under test.

4ins (insulin) is the fixture because it exercises what the smaller fixtures
cannot: seven assemblies, genuinely non-identity rotations (the other bundled
structures carry only an identity transform), asymmetric rotation matrices so
a row/column transposition cannot pass unnoticed, and - in assembly 6 - two
``APPLY THE FOLLOWING TO CHAINS`` blocks naming *different* chains.
"""

import numpy as np
import pytest

import helpers as H

FIXTURE_PDB = "4ins.pdb"
FIXTURE_CIF = "4ins.cif"

CONTRACT_KEYS = {"chain_ids", "matrix", "pdb_model_num"}

# Hand-read straight out of tests/data/4ins.pdb, REMARK 350 BIOMOLECULE: 3.
# A three-fold rotation about z: cos(120) = -0.5, sin(120) = 0.866025.
THREEFOLD_PLUS = [
    [-0.500000, -0.866025, 0.0, 0.0],
    [0.866025, -0.500000, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


# --------------------------------------------------------------------------
# Independent ground truth: read REMARK 350 out of the file as plain text.
# --------------------------------------------------------------------------

def _remark_350_transforms(filename):
    """``{assembly_id: [(chain_ids, 4x4 matrix), ...]}`` straight from the text.

    Deliberately hand-rolled rather than reusing anything under
    ``utils.molecularnodes``: a test that derived its expected transforms from
    the parser it is checking would pass whether that parser is right or wrong.

    A ``BIOMT1`` line opens a new transform (carrying whichever chain set is
    currently in force), and the ``BIOMT2`` / ``BIOMT3`` lines after it fill in
    the remaining rows.
    """
    assemblies = {}
    current, chains, records = None, [], None

    with open(H.data_path(filename)) as handle:
        for line in handle:
            if not line.startswith("REMARK 350"):
                continue
            body = line[10:].strip()

            if body.startswith("BIOMOLECULE:"):
                current = body.split(":", 1)[1].strip()
                records = assemblies.setdefault(current, [])
                chains = []
            elif body.startswith("APPLY THE FOLLOWING TO CHAINS:"):
                chains = [c.strip() for c in body.split(":", 1)[1].split(",") if c.strip()]
            elif body.startswith("AND CHAINS:"):
                chains = chains + [
                    c.strip() for c in body.split(":", 1)[1].split(",") if c.strip()
                ]
            elif body.startswith("BIOMT") and records is not None:
                parts = body.split()
                row = int(parts[0][-1])          # BIOMT1 / BIOMT2 / BIOMT3
                values = [float(v) for v in parts[2:6]]
                if row == 1:
                    records.append((list(chains), [values]))
                else:
                    records[-1][1].append(values)

    # Close each 3x4 block into a 4x4 homogeneous matrix.
    return {
        aid: [(chain_ids, rows + [[0.0, 0.0, 0.0, 1.0]]) for chain_ids, rows in records]
        for aid, records in assemblies.items()
    }


def _parsed_assemblies(filename):
    """Run the parser under test over a bundled fixture."""
    from proteinblender.utils.molecularnodes.entities.molecule import pdb as mn_pdb
    from proteinblender.utils.molecularnodes.entities.molecule import pdbx as mn_pdbx

    path = H.data_path(filename)
    reader = mn_pdbx.CIF if filename.endswith(".cif") else mn_pdb.PDB
    return reader(path).assemblies()


# --------------------------------------------------------------------------
# The ground-truth reader must itself be sane before anything leans on it.
# --------------------------------------------------------------------------

def test_ground_truth_reader_sees_the_hand_read_records():
    """Anchor the independent reader against constants read by eye."""
    truth = _remark_350_transforms(FIXTURE_PDB)

    assert sorted(truth) == ["1", "2", "3", "4", "5", "6", "7"]

    # Assembly 3: one identity plus the two thirds of a three-fold, all on ABCD.
    chains_3 = [chain_ids for chain_ids, _ in truth["3"]]
    assert chains_3 == [["A", "B", "C", "D"]] * 3
    assert np.allclose(truth["3"][1][1], THREEFOLD_PLUS, atol=1e-6)

    # Assembly 6 is the awkward one: two chain-set blocks naming different
    # chains, so a parser that keeps only the first (or the last) is wrong.
    assert [chain_ids for chain_ids, _ in truth["6"]] == [["A", "B"], ["C", "D"]]
    assert np.allclose(truth["6"][1][1], THREEFOLD_PLUS, atol=1e-6)


# --------------------------------------------------------------------------
# The contract both parsers are supposed to implement
# --------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [FIXTURE_PDB, FIXTURE_CIF])
def test_parser_returns_the_documented_dict_contract(filename):
    """Both parsers must hand back dicts carrying the documented keys.

    This is the defect itself: the PDB parser returned bare tuples, which the
    consumer then indexed by string key.
    """
    assemblies = _parsed_assemblies(filename)
    assert assemblies, f"{filename} parsed to no assemblies at all"

    for assembly_id, transforms in assemblies.items():
        assert transforms, f"assembly {assembly_id} has no transforms"
        for transform in transforms:
            assert isinstance(transform, dict), (
                f"{filename} assembly {assembly_id}: transform is a "
                f"{type(transform).__name__}, not the documented dict")
            assert set(transform) == CONTRACT_KEYS
            assert np.shape(transform["matrix"]) == (4, 4)
            assert all(isinstance(c, str) for c in transform["chain_ids"])


@pytest.mark.parametrize("filename", [FIXTURE_PDB, FIXTURE_CIF])
def test_matrices_are_proper_homogeneous_transforms(filename):
    """The bottom row of every 4x4 must be exactly [0, 0, 0, 1].

    The mmCIF extractor allocated its matrices with ``np.empty`` and then
    filled only rows 0-2, leaving the homogeneous row as whatever happened to
    be in memory - denormal floats like 1.5e-312. A shape check passes on that
    happily, and the damage shows up much later: an identity operator no
    longer compares equal to the identity, so a monomer looks like it has
    symmetry.
    """
    for assembly_id, transforms in _parsed_assemblies(filename).items():
        for i, transform in enumerate(transforms):
            bottom = np.array(transform["matrix"], dtype=float)[3, :]
            assert np.array_equal(bottom, [0.0, 0.0, 0.0, 1.0]), (
                f"{filename} assembly {assembly_id} transform {i}: bottom row "
                f"is {bottom.tolist()}, not [0, 0, 0, 1] - uninitialised memory")


def test_mmcif_matrices_do_not_leak_uninitialised_memory(monkeypatch):
    """The mmCIF extractor must write the homogeneous row, not inherit it.

    ``_extract_matrices`` allocated with ``np.empty`` and filled only rows 0-2,
    so the bottom row was whatever happened to be in that memory. That is not
    reliably observable - a fresh allocation often *does* come back looking
    like a valid matrix, which is exactly what makes it dangerous - so this
    test poisons the allocator to make the defect deterministic.

    Seen for real: a downloaded 1ubq came back with a bottom row of
    ``[1.5e-312, 1.1e-312, 1.5e-312, 1.1e-312]``, which stopped its identity
    operator comparing equal to the identity and put a Symmetry panel on a
    monomer.
    """
    import numpy

    real_empty = numpy.empty

    def poisoned_empty(*args, **kwargs):
        array = real_empty(*args, **kwargs)
        try:
            array.fill(numpy.nan)
        except (ValueError, TypeError):
            pass
        return array

    monkeypatch.setattr(numpy, "empty", poisoned_empty)

    for assembly_id, transforms in _parsed_assemblies(FIXTURE_CIF).items():
        for i, transform in enumerate(transforms):
            matrix = np.array(transform["matrix"], dtype=float)
            assert not np.isnan(matrix).any(), (
                f"assembly {assembly_id} transform {i} carries uninitialised "
                f"memory:\n{matrix}")
            assert np.array_equal(matrix[3, :], [0.0, 0.0, 0.0, 1.0]), (
                f"assembly {assembly_id} transform {i}: bottom row is "
                f"{matrix[3, :].tolist()}, not [0, 0, 0, 1]")


def test_an_identity_operator_is_recognised_as_one():
    """An identity transform must compare equal to the identity in both formats.

    This is what the symmetry gate rests on: assembly 1 of 4ins is a single
    identity operator, so neither format may report it as symmetry.
    """
    for filename in (FIXTURE_PDB, FIXTURE_CIF):
        assemblies = _parsed_assemblies(filename)
        first = assemblies[list(assemblies)[0]]
        matrix = np.array(first[0]["matrix"], dtype=float)
        assert np.allclose(matrix, np.eye(4), atol=1e-6), (
            f"{filename}: the first operator should be the identity, got "
            f"{matrix.tolist()}")


def test_both_formats_agree_on_the_rotation_values():
    """The same structure must give the same operators either way.

    Compares the rotation+translation rows only, and with a tolerance: the
    formats legitimately differ on chain naming, on assembly ordering, and on
    stored precision (``REMARK 350`` writes 0.866025 where mmCIF carries more
    digits). What they must not differ on is the geometry.
    """
    def operator_rows(assemblies):
        return [
            np.array(transform["matrix"], dtype=float)[:3, :]
            for transforms in assemblies.values()
            for transform in transforms
        ]

    pdb_ops = operator_rows(_parsed_assemblies(FIXTURE_PDB))
    cif_ops = operator_rows(_parsed_assemblies(FIXTURE_CIF))

    for operator in pdb_ops:
        assert any(np.allclose(operator, other, atol=1e-4) for other in cif_ops), (
            f"this operator appears in the PDB file but in no mmCIF operator:\n"
            f"{operator}")


def test_both_parsers_agree_on_the_contract():
    """The same structure in either format must yield the same shape.

    The formats legitimately differ on chain naming (mmCIF reports
    ``label_asym_id``) and on assembly numbering, so this compares the
    *contract*, not the values.
    """
    from_pdb = _parsed_assemblies(FIXTURE_PDB)
    from_cif = _parsed_assemblies(FIXTURE_CIF)

    def shape_of(assemblies):
        return {
            type(t) for transforms in assemblies.values() for t in transforms
        }, {
            frozenset(t) for transforms in assemblies.values() for t in transforms
        }

    assert shape_of(from_pdb) == shape_of(from_cif)


# --------------------------------------------------------------------------
# Values, against the REMARK 350 text
# --------------------------------------------------------------------------

def test_pdb_transforms_match_remark_350():
    """Every parsed transform must match the file's own BIOMT records."""
    truth = _remark_350_transforms(FIXTURE_PDB)
    parsed = _parsed_assemblies(FIXTURE_PDB)

    assert sorted(parsed) == sorted(truth), "parsed a different set of assemblies"

    for assembly_id, expected in truth.items():
        got = parsed[assembly_id]
        assert len(got) == len(expected), (
            f"assembly {assembly_id}: parsed {len(got)} transforms, "
            f"REMARK 350 declares {len(expected)}")

        for i, (expected_chains, expected_matrix) in enumerate(expected):
            assert got[i]["chain_ids"] == expected_chains, (
                f"assembly {assembly_id} transform {i}: chains")
            assert np.allclose(got[i]["matrix"], expected_matrix, atol=1e-6), (
                f"assembly {assembly_id} transform {i}: matrix")


def test_non_identity_rotation_survives_parsing():
    """Guard the transposition the symmetric fixtures would have hidden.

    4ins's three-fold is asymmetric, so a parser that filled the matrix in
    column-major order would produce the *inverse* rotation and still look
    plausible. Pin the exact orientation, and assert it is not its own
    transpose so this test cannot quietly become vacuous.
    """
    parsed = _parsed_assemblies(FIXTURE_PDB)
    matrix = np.array(parsed["3"][1]["matrix"])

    assert not np.allclose(matrix, matrix.T, atol=1e-6), (
        "fixture no longer has an asymmetric rotation - this test proves nothing")
    assert np.allclose(matrix, THREEFOLD_PLUS, atol=1e-6)


# --------------------------------------------------------------------------
# End to end: the crash that was actually reported
# --------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [FIXTURE_PDB, FIXTURE_CIF])
def test_building_the_assembly_does_not_raise(filename):
    """Building the biological assembly must work from either format.

    Entering at the MolecularNodes boundary because that is the layer being
    fixed - ProteinBlender does not expose an assembly toggle yet.
    """
    import bpy
    from proteinblender.utils.molecularnodes.entities import load_local

    name = f"assembly_{filename.replace('.', '_')}"
    molecule = load_local(
        file_path=H.data_path(filename),
        name=name,
        style="spheres",
        build_assembly=True,
    )

    obj = molecule.object
    assert obj.mn.biological_assemblies, "assemblies were not stored on the object"

    modifier = next((m for m in obj.modifiers if m.type == "NODES"), None)
    assert modifier is not None, "no geometry nodes modifier was created"

    assembly_nodes = [
        n for n in modifier.node_group.nodes
        if getattr(n, "node_tree", None)
        and n.node_tree.name.startswith("Assembly")
    ]
    assert assembly_nodes, "the assembly node was never inserted into the tree"

    # The instances are what actually place the copies in the scene.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    assert any(i.is_instance for i in depsgraph.object_instances), (
        "the assembly node produced no instances")


# --------------------------------------------------------------------------
# Import default
# --------------------------------------------------------------------------

def test_remote_format_defaults_to_mmcif():
    """Downloads default to mmCIF.

    Legacy PDB cannot express a large assembly at all - it runs out of atom
    serial numbers at 99,999 and chain identifiers at 62 - so a capsid is only
    reachable through mmCIF.
    """
    import bpy

    props = bpy.context.scene.protein_props
    assert props.bl_rna.properties["remote_format"].default == "cif"
    assert props.remote_format == "cif"
