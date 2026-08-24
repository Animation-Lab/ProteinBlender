"""Regression: structures whose author chain ids are digits (1CD3).

1CD3 (the phiX174 procapsid) names its chains 1, 2, 3, 4, B, F and G. That
puts a chain's numeric *index* and another chain's author *id* in the same
namespace - index 1 is chain "2", but "1" is also chain "1" - and the chain
matcher accepted a domain under either reading at once. Every chain therefore
picked up its neighbour's domain: importing 1CD3 showed four chains already
split into two domains each, and every chain-level action (delete, copy,
recolour, select) reached into the neighbouring chain as well.

Ground truth is the fixture read as plain text - the chain id in column 22 of
each coordinate record - so nothing here is derived from the add-on's own
chain maps.
"""

import pytest
import bpy

import helpers as H
from proteinblender.utils.chain_utils import (chain_token_from_item,
                                              get_chain_domains,
                                              get_chain_objects)

FIXTURE = "1cd3.pdb"


def _chain_ids_from_file(filename=FIXTURE):
    """Author chain ids in a PDB fixture, sorted - read straight from the file.

    Sorted order is also chain-index order: the importer numbers chains by the
    sorted unique chain id, so index i is ``_chain_ids_from_file()[i]``.
    """
    ids = set()
    with open(H.data_path(filename)) as handle:
        for line in handle:
            if line.startswith(("ATOM", "HETATM")):
                ids.add(line[21])
    return sorted(ids)


def _chain_rows(molecule_id):
    return [item for item in bpy.context.scene.outliner_items
            if item.item_type == "CHAIN" and item.parent_id == molecule_id]


@pytest.fixture
def numeric_chains():
    """1CD3 imported from the offline fixture. Returns the molecule id."""
    return H.import_local(FIXTURE, "1cd3")


@pytest.mark.integration
def test_fixture_really_has_numeric_chain_ids():
    # Guards the premise: if the fixture ever stops having digit chain ids,
    # every other test in this module would pass without measuring anything.
    assert [c for c in _chain_ids_from_file() if c.isdigit()]


@pytest.mark.integration
def test_numeric_chains_import_unsplit(numeric_chains):
    """A freshly imported protein has no split chains, digits or not."""
    chain_ids = _chain_ids_from_file()
    rows = _chain_rows(numeric_chains)

    assert len(rows) == len(chain_ids)
    assert [row.has_domains for row in rows] == [False] * len(rows)
    assert [item for item in bpy.context.scene.outliner_items
            if item.item_type == "DOMAIN"] == []


@pytest.mark.integration
def test_each_chain_row_resolves_to_its_own_chain(numeric_chains):
    """Row i maps to exactly one domain, and it is chain i's own domain."""
    chain_ids = _chain_ids_from_file()
    molecule = H.sm().molecules[numeric_chains]
    rows = _chain_rows(numeric_chains)

    resolved = {}
    for index, row in enumerate(rows):
        assert chain_token_from_item(row) == str(index)
        pairs = get_chain_domains(molecule, row)
        assert len(pairs) == 1, (
            f"chain row {row.name!r} (index {index}) resolved to "
            f"{[d.name for _id, d in pairs]}, expected one domain")
        domain_id, domain = pairs[0]
        assert str(domain.chain_id) == chain_ids[index]
        assert len(get_chain_objects(molecule, row)) == 1
        resolved[row.item_id] = domain_id

    # One domain each, and no two rows sharing one.
    assert len(set(resolved.values())) == len(rows)


def _mesh_chain_alpha_carbons(obj, chain_index):
    """Raw mesh coordinates of one chain's alpha carbons, by chain index.

    Reads the mesh attributes MolecularNodes wrote - ``chain_id`` (the integer
    index) and ``is_alpha_carbon`` - and the vertex coordinates, so it is data,
    not the output of any resolver under test.
    """
    import numpy as np

    count = len(obj.data.vertices)
    chains = np.zeros(count, dtype=np.int32)
    obj.data.attributes["chain_id"].data.foreach_get("value", chains)
    alpha = np.zeros(count, dtype=bool)
    obj.data.attributes["is_alpha_carbon"].data.foreach_get("value", alpha)
    coords = np.zeros(count * 3)
    obj.data.vertices.foreach_get("co", coords)
    return coords.reshape(-1, 3)[alpha & (chains == chain_index)]


@pytest.mark.integration
def test_chain_domain_pivots_sit_on_their_own_chain(numeric_chains):
    """A whole-chain domain pivots at ITS chain's centre, not a blend of two.

    Same root cause on the geometry side: the chain filter resolved a digit
    chain id as an index *as well*, so chain "1"'s centre of mass was averaged
    over chains "1" and "2" and its pivot landed between them.
    """
    import numpy as np
    from proteinblender.core import domain_space

    molecule = H.sm().molecules[numeric_chains]
    labels = [str(label) for label in molecule.object["chain_ids"]]
    assert labels == _chain_ids_from_file()

    for domain in molecule.domains.values():
        alphas = _mesh_chain_alpha_carbons(
            molecule.object, labels.index(str(domain.chain_id)))
        assert len(alphas), f"no alpha carbons for chain {domain.chain_id}"
        expected = alphas.mean(axis=0)
        pivot = np.array(domain_space.get_pivot(domain.object))
        offset = float(np.linalg.norm(pivot - expected))
        assert offset < 1e-3, (
            f"chain {domain.chain_id}'s pivot is {offset:.4f} from its own "
            f"centre of mass")


@pytest.mark.integration
def test_deleting_one_numeric_chain_leaves_the_others(numeric_chains):
    """The trash can on chain "2" deletes chain "2" - and nothing else."""
    chain_ids = _chain_ids_from_file()
    doomed = "2"
    molecule = H.sm().molecules[numeric_chains]
    row = _chain_rows(numeric_chains)[chain_ids.index(doomed)]

    assert bpy.ops.molecule.delete_chain(
        "EXEC_DEFAULT", molecule_id=numeric_chains,
        chain_id=chain_token_from_item(row)) == {"FINISHED"}

    assert sorted(str(d.chain_id) for d in molecule.domains.values()) == [
        c for c in chain_ids if c != doomed]
