"""Pure-logic unit tests for proteinblender/utils/chain_utils.py.

Covers the string/JSON (de)serialisers that carry chain mappings and residue
ranges through PropertyGroup storage and undo/redo. Special attention to the
"index vs letter" gotcha: a gapped chain set like A, B, D must round-trip with
index 2 -> "D" (NOT alphabet math, which would give "C"). See the module
docstring of tests/test_chain_operations.py for the wider context.
"""

import pytest

from proteinblender.utils import chain_utils


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
