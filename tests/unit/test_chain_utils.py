"""Pure-logic unit tests for proteinblender/utils/chain_utils.py.

Covers the string/JSON (de)serialisers that carry chain mappings and residue
ranges through PropertyGroup storage and undo/redo, and the chain-identity
resolvers built on them. Special attention to the "index vs letter" gotcha: a
gapped chain set like A, B, D must round-trip with index 2 -> "D" (NOT alphabet
math, which would give "C"), and a chain set that is itself numeric (1CD3's 1,
2, 3, 4, B, F, G) must not let one chain's index be read as another chain's id.
See the module design-goal note in tests/README.md for the wider context.
"""

import pytest

from proteinblender.utils import chain_utils


class _FakeMolecule:
    """The chain maps a MoleculeWrapper exposes, without Blender or a file."""

    def __init__(self, mapping, ranges=None):
        self.auth_chain_id_map = dict(mapping)
        self.chain_mapping = dict(mapping)
        self.idx_to_label_asym_id_map = dict(mapping)
        self.chain_residue_ranges = (
            ranges if ranges is not None
            else {author: (1, 100) for author in mapping.values()})


class _FakeDomain:
    def __init__(self, chain_id):
        self.chain_id = chain_id


# 1CD3: the author chain ids are digits, so chain index 1 is chain "2" while
# "1" is also a chain in its own right.
NUMERIC = _FakeMolecule({0: "1", 1: "2", 2: "3", 3: "4", 4: "B", 5: "F", 6: "G"})
GAPPED = _FakeMolecule({0: "A", 1: "B", 2: "D"})


# ---------------------------------------------------------------------------
# get_chain_mapping_from_string / chain_mapping_to_string
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_mapping_from_string_basic():
    assert chain_utils.get_chain_mapping_from_string("0:A,1:B,2:C") == {
        0: "A", 1: "B", 2: "C"
    }


@pytest.mark.unit
def test_mapping_from_string_gapped():
    # The gotcha: index 2 is "D", not "C". Parser must honour the literal map.
    assert chain_utils.get_chain_mapping_from_string("0:A,1:B,2:D") == {
        0: "A", 1: "B", 2: "D"
    }


@pytest.mark.unit
def test_mapping_from_string_empty():
    assert chain_utils.get_chain_mapping_from_string("") == {}


@pytest.mark.unit
def test_mapping_from_string_whitespace_and_bad_pairs():
    # Whitespace is stripped; entries without ":" are skipped; bad ints skipped.
    assert chain_utils.get_chain_mapping_from_string(" 0 : A , garbage , 1: B ") == {
        0: "A", 1: "B"
    }


@pytest.mark.unit
def test_mapping_to_string_sorted():
    # Output is sorted by integer key regardless of insertion order.
    assert chain_utils.chain_mapping_to_string({2: "D", 0: "A", 1: "B"}) == "0:A,1:B,2:D"


@pytest.mark.unit
def test_mapping_to_string_empty():
    assert chain_utils.chain_mapping_to_string({}) == ""


@pytest.mark.unit
def test_mapping_to_string_single():
    assert chain_utils.chain_mapping_to_string({0: "A"}) == "0:A"


@pytest.mark.unit
@pytest.mark.parametrize("mapping", [
    {0: "A", 1: "B", 2: "C"},
    {0: "A", 1: "B", 2: "D"},   # gapped
    {0: "S", 1: "T"},           # non-alphabetical letters
    {5: "A"},                    # single, non-zero index
    {},
])
def test_mapping_string_roundtrip(mapping):
    s = chain_utils.chain_mapping_to_string(mapping)
    assert chain_utils.get_chain_mapping_from_string(s) == mapping


# ---------------------------------------------------------------------------
# serialize_chain_mapping / deserialize_chain_mapping (JSON)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_serialize_chain_mapping_roundtrip():
    mapping = {0: "A", 1: "B", 2: "D"}
    js = chain_utils.serialize_chain_mapping(mapping)
    assert chain_utils.deserialize_chain_mapping(js) == mapping


@pytest.mark.unit
def test_serialize_chain_mapping_keys_are_strings_in_json():
    # int keys must be coerced to strings for JSON validity.
    import json
    js = chain_utils.serialize_chain_mapping({0: "A", 2: "D"})
    raw = json.loads(js)
    assert raw == {"0": "A", "2": "D"}


@pytest.mark.unit
def test_deserialize_chain_mapping_restores_int_keys():
    result = chain_utils.deserialize_chain_mapping('{"0": "A", "2": "D"}')
    assert result == {0: "A", 2: "D"}
    assert all(isinstance(k, int) for k in result)


@pytest.mark.unit
def test_deserialize_chain_mapping_empty_and_invalid():
    assert chain_utils.deserialize_chain_mapping("") == {}
    assert chain_utils.deserialize_chain_mapping("not json") == {}


@pytest.mark.unit
def test_serialize_chain_mapping_empty():
    assert chain_utils.deserialize_chain_mapping(
        chain_utils.serialize_chain_mapping({})
    ) == {}


# ---------------------------------------------------------------------------
# serialize_residue_ranges / deserialize_residue_ranges (JSON)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_serialize_residue_ranges_roundtrip():
    ranges = {"A": (1, 76), "B": (1, 129), "D": (5, 200)}
    js = chain_utils.serialize_residue_ranges(ranges)
    restored = chain_utils.deserialize_residue_ranges(js)
    assert restored == ranges
    # Values must come back as tuples, not lists.
    assert all(isinstance(v, tuple) for v in restored.values())


@pytest.mark.unit
def test_serialize_residue_ranges_stores_lists_in_json():
    import json
    js = chain_utils.serialize_residue_ranges({"A": (1, 76)})
    assert json.loads(js) == {"A": [1, 76]}


@pytest.mark.unit
def test_deserialize_residue_ranges_empty_and_invalid():
    assert chain_utils.deserialize_residue_ranges("") == {}
    assert chain_utils.deserialize_residue_ranges("{bad") == {}


@pytest.mark.unit
def test_serialize_residue_ranges_empty():
    assert chain_utils.deserialize_residue_ranges(
        chain_utils.serialize_residue_ranges({})
    ) == {}


# ---------------------------------------------------------------------------
# chain_author_id / chain_index_token / domain_in_chain
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_chain_author_id_reads_a_digit_as_an_index():
    # Index 1 is chain "2" - even though "1" is also one of this molecule's
    # chains. A chain row's token is an index, and that reading wins.
    assert chain_utils.chain_author_id(NUMERIC, "1") == "2"
    assert chain_utils.chain_author_id(NUMERIC, 0) == "1"
    assert chain_utils.chain_author_id(NUMERIC, "4") == "B"


@pytest.mark.unit
def test_chain_author_id_honours_a_gapped_map():
    # Index 2 is "D", not the "C" alphabet math would give.
    assert chain_utils.chain_author_id(GAPPED, "2") == "D"
    assert chain_utils.chain_author_id(GAPPED, "B") == "B"


@pytest.mark.unit
def test_chain_author_id_invents_nothing_for_an_unmapped_index():
    # No chain at index 9, and no map at all: the token comes back untouched
    # rather than as a guessed letter, which is what keeps a mapless molecule
    # (domains keyed by index) internally consistent.
    assert chain_utils.chain_author_id(GAPPED, "9") == "9"
    assert chain_utils.chain_author_id(_FakeMolecule({}), "1") == "1"


@pytest.mark.unit
def test_chain_index_token_is_the_inverse():
    assert chain_utils.chain_index_token(NUMERIC, "B") == "4"
    assert chain_utils.chain_index_token(NUMERIC, "1") == "1"   # already an index
    assert chain_utils.chain_index_token(GAPPED, "D") == "2"
    assert chain_utils.chain_index_token(GAPPED, "Z") is None


@pytest.mark.unit
def test_domain_chain_author_id_reads_a_digit_as_a_chain_id():
    # The domain side stores the author id, so "1" is chain "1" here - the
    # opposite reading from a chain row's token, which is the whole point.
    assert chain_utils.domain_chain_author_id(NUMERIC, "1") == "1"
    # A digit that is not one of this molecule's chains is a legacy index.
    assert chain_utils.domain_chain_author_id(GAPPED, "2") == "D"


@pytest.mark.unit
def test_domain_in_chain_does_not_confuse_numeric_neighbours():
    # 1CD3's bug: chain row "1" (chain "2") also matched chain "1"'s domain.
    assert chain_utils.domain_in_chain(NUMERIC, "0", _FakeDomain("1"))
    assert not chain_utils.domain_in_chain(NUMERIC, "1", _FakeDomain("1"))
    assert chain_utils.domain_in_chain(NUMERIC, "1", _FakeDomain("2"))
    # ...and chain row "4" (chain "B") also matched chain "4"'s domain.
    assert not chain_utils.domain_in_chain(NUMERIC, "4", _FakeDomain("4"))
    assert chain_utils.domain_in_chain(NUMERIC, "4", _FakeDomain("B"))


@pytest.mark.unit
def test_domain_in_chain_bridges_index_and_letter():
    assert chain_utils.domain_in_chain(GAPPED, "2", _FakeDomain("D"))
    assert chain_utils.domain_in_chain(GAPPED, "D", _FakeDomain("D"))
    assert not chain_utils.domain_in_chain(GAPPED, "0", _FakeDomain("D"))
    assert not chain_utils.domain_in_chain(GAPPED, "0", _FakeDomain(None))
