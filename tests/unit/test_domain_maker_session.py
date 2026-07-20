"""Unit tests for the Domain Maker session's pure planning helpers.

These exercise the range maths (`_even_ranges`) and the range validator
(`_validate_ranges`) directly, with expected values hand-computed in the test
rather than derived from the code under test.
"""

import pytest

from proteinblender.operators import domain_maker_session as dms


# --------------------------------------------------------------------------
# _even_ranges
# --------------------------------------------------------------------------

def _partition_invariants(ranges, start, end):
    """Assert `ranges` is a gap-free, non-overlapping cover of [start, end]."""
    assert ranges[0][0] == start
    assert ranges[-1][1] == end
    for s, e in ranges:
        assert s <= e
    for (sa, ea), (sb, eb) in zip(ranges, ranges[1:]):
        assert sb == ea + 1  # contiguous, no gap, no overlap


@pytest.mark.unit
def test_even_ranges_exact_partition():
    # 12 residues over 4 domains -> 3 each (hand-computed ground truth).
    assert dms._even_ranges(1, 12, 4) == [(1, 3), (4, 6), (7, 9), (10, 12)]


@pytest.mark.unit
def test_even_ranges_remainder_goes_to_earliest_domains():
    # 10 residues over 3 -> sizes 4,3,3 (remainder 1 to the first).
    ranges = dms._even_ranges(1, 10, 3)
    assert ranges == [(1, 4), (5, 7), (8, 10)]
    _partition_invariants(ranges, 1, 10)


@pytest.mark.unit
def test_even_ranges_non_unit_start():
    ranges = dms._even_ranges(20, 100, 4)  # 81 residues -> 21,20,20,20
    assert ranges == [(20, 40), (41, 60), (61, 80), (81, 100)]
    _partition_invariants(ranges, 20, 100)


@pytest.mark.unit
def test_even_ranges_single_domain_is_whole_span():
    assert dms._even_ranges(5, 30, 1) == [(5, 30)]


@pytest.mark.unit
def test_even_ranges_more_domains_than_residues():
    # 3 residues, 5 domains requested: never exceeds the last residue.
    ranges = dms._even_ranges(1, 3, 5)
    assert len(ranges) == 5
    assert all(1 <= s <= 3 and s == e for s, e in ranges)
    assert max(e for _, e in ranges) == 3


# --------------------------------------------------------------------------
# _validate_ranges
# --------------------------------------------------------------------------

@pytest.mark.unit
def test_validate_accepts_clean_partition():
    ranges = [("Domain 1", 1, 50), ("Domain 2", 51, 100)]
    assert dms._validate_ranges(ranges, 1, 100) == ""


@pytest.mark.unit
def test_validate_rejects_overlap():
    ranges = [("Domain 1", 1, 60), ("Domain 2", 50, 100)]
    msg = dms._validate_ranges(ranges, 1, 100)
    assert "overlap" in msg.lower()


@pytest.mark.unit
def test_validate_rejects_out_of_bounds():
    ranges = [("Domain 1", 1, 50), ("Domain 2", 51, 200)]
    msg = dms._validate_ranges(ranges, 1, 100)
    assert "outside" in msg.lower()


@pytest.mark.unit
def test_validate_rejects_start_past_end():
    ranges = [("Domain 1", 80, 40)]
    msg = dms._validate_ranges(ranges, 1, 100)
    assert msg  # non-empty error
    assert "past" in msg.lower()


@pytest.mark.unit
def test_validate_allows_gaps_between_domains():
    # A gap (residues 51-59 uncovered) is permitted; only overlap is illegal.
    ranges = [("Domain 1", 1, 50), ("Domain 2", 60, 100)]
    assert dms._validate_ranges(ranges, 1, 100) == ""
