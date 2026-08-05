"""The Domain Splitter: editing a chain's domain layout in place.

The feature exists because the old route to "change this domain's range" was
delete-and-recreate, and a domain's id embeds its residue range while its object
name embeds the range too. Everything downstream keys off one of those two
strings - puppet membership, linker endpoints, saved poses, the pose library,
per-domain animation, the pivot - so re-ranging silently orphaned all of it.

These tests pin the invariant that makes the feature safe: **a domain the user
did not remove keeps its identity across a layout edit.**

Ground truth is kept independent of the code under test (see CLAUDE.md):

  * chain residue bounds come from parsing the PDB fixture with biotite
    (``H.pdb_amino_acid_cas``), never from ``molecule.chain_residue_ranges``;
  * "did the geometry actually follow the range" is measured as evaluated
    vertex counts (``H.eval_positions``), whose expected *ordering* comes from
    the PDB - more residues means more atoms - not from any addon helper;
  * identity preservation is asserted against ids and object names captured
    *before* the edit, so the assertion cannot move with the bug;
  * animation survival is read from Blender's own ``animation_data``.
"""

import json

import bpy
import pytest

import helpers as H

from proteinblender.core import domain_layout
from proteinblender.operators import domain_splitter as ds


# --------------------------------------------------------------------------
# Setup helpers
# --------------------------------------------------------------------------

def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_rows(mid):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == "CHAIN" and it.parent_id == mid]


def _row_by_id(item_id):
    return next((it for it in bpy.context.scene.outliner_items
                 if it.item_id == item_id), None)


def _pdb_chain_bounds(filename, chain_letter):
    """(min, max) author residue number for a chain, straight from the PDB.

    Independent ground truth: biotite re-parses the fixture, so this cannot
    agree with a bug in the addon's own chain-range resolution.

    Every residue in the chain counts, not just the amino acids. That is what
    the addon's chain range means today, and it is deliberately what this
    asserts - 1ubq's chain A runs to 134 because residues 77-134 are
    crystallographic waters. (Offering solvent as a domain boundary is its own
    UX question, tracked separately; pinning the current contract here keeps
    this suite honest about what the code actually promises.)
    """
    import biotite.structure.io.pdb as pdb

    array = pdb.PDBFile.read(H.data_path(filename)).get_structure(model=1)
    chain = array[array.chain_id == chain_letter]
    assert len(chain), f"no atoms parsed for chain {chain_letter}"
    return int(chain.res_id.min()), int(chain.res_id.max())


def _apply(chain_row, specs):
    """Drive the Domain Splitter headlessly with an explicit layout."""
    payload = json.dumps([
        {"name": name, "start": start, "end": end, "domain_id": domain_id or ""}
        for name, start, end, domain_id in specs])
    result = bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=chain_row.item_id, layout_json=payload,
        chain_name=chain_row.name)
    assert result == {'FINISHED'}, f"splitter rejected the layout: {result}"


def _domains_on_chain(mol, chain_letter):
    return {did: d for did, d in mol.domains.items()
            if str(d.chain_id) == chain_letter and not getattr(d, "is_copy", False)}


def _single_chain_setup():
    """Import 1ubq (one chain) and return (mid, chain_row, bounds, letter)."""
    mid = H.import_local("1ubq.pdb", "1ubq")
    _build_outliner()
    rows = _chain_rows(mid)
    assert rows, "import produced no chain rows"
    mol = H.sm().molecules[mid]
    letter = sorted(mol.chain_mapping.values())[0]
    return mid, rows[0], _pdb_chain_bounds("1ubq.pdb", letter), letter


# --------------------------------------------------------------------------
# Layout arithmetic - pure logic, asserted as properties
# --------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("count", [1, 2, 3, 4, 7, 10])
def test_even_split_tiles_the_chain_exactly(count):
    """Pieces are contiguous, gapless, in-bounds and within one residue of equal.

    Asserted as properties rather than against a recomputed expectation, so the
    test cannot pass by mirroring the implementation's own arithmetic.
    """
    low, high = 3, 79
    pieces = domain_layout.even_split(low, high, count)

    assert len(pieces) == count
    assert pieces[0][0] == low
    assert pieces[-1][1] == high
    for (_, prev_end), (next_start, _) in zip(pieces, pieces[1:]):
        assert next_start == prev_end + 1, "pieces must be contiguous and gapless"
    sizes = [e - s + 1 for s, e in pieces]
    assert all(size >= 1 for size in sizes)
    assert max(sizes) - min(sizes) <= 1, "pieces must be within one residue of equal"
    assert sum(sizes) == high - low + 1, "pieces must cover the chain exactly"


@pytest.mark.integration
def test_even_split_never_produces_empty_pieces_for_short_chains():
    """Asking for more domains than residues yields one domain per residue."""
    pieces = domain_layout.even_split(10, 12, 9)
    assert pieces == [(10, 10), (11, 11), (12, 12)]


@pytest.mark.integration
def test_validate_layout_rejects_overlap_and_out_of_bounds():
    spec = domain_layout.DomainSpec
    overlapping = [spec("A", 1, 50), spec("B", 40, 90)]
    assert any("overlap" in e for e in domain_layout.validate_layout(overlapping, 1, 90))

    outside = [spec("A", 1, 200)]
    assert domain_layout.validate_layout(outside, 1, 90)

    backwards = [spec("A", 60, 10)]
    assert domain_layout.validate_layout(backwards, 1, 90)

    duplicate_names = [spec("Same", 1, 40), spec("Same", 41, 90)]
    assert any("named" in e for e in
               domain_layout.validate_layout(duplicate_names, 1, 90))

    valid = [spec("A", 1, 40), spec("B", 41, 90)]
    assert domain_layout.validate_layout(valid, 1, 90) == []


# --------------------------------------------------------------------------
# Default names
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_auto_generated_names_name_the_chain_and_the_range():
    from proteinblender.utils.chain_utils import (default_domain_name,
                                                  is_default_domain_name)

    assert default_domain_name("A", 1, 248) == "Chain A: 1-248"
    assert default_domain_name("D", 249, 400) == "Chain D: 249-400"
    # Whatever the generator produces must read back as auto-generated, or a
    # name would freeze the moment it was first written.
    assert is_default_domain_name(default_domain_name("A", 1, 248))


@pytest.mark.integration
def test_every_historical_auto_name_is_recognised_as_auto():
    """All the shapes the create/split/dialog paths have produced count as auto.

    Each of these was a default at some point. Any one that stops being
    recognised freezes as if the user had typed it, which is how the same chain
    ended up showing "Chain A: Residues 1-248" next to "Domain 1".
    """
    from proteinblender.utils.chain_utils import is_default_domain_name

    for name in ("", "   ", "Residues 1-50", "Chain A", "Chain A: 1-248",
                 "Chain A: Residues 1-248", "Domain 1", "Domain 12"):
        assert is_default_domain_name(name), f"{name!r} should count as auto"


@pytest.mark.integration
def test_a_name_the_user_typed_is_never_treated_as_auto():
    from proteinblender.utils.chain_utils import is_default_domain_name

    for name in ("Catalytic core", "Kinase domain", "SH2", "N-lobe",
                 "Chain A tail", "Residues of interest", "Domain of unknown"):
        assert not is_default_domain_name(name), f"{name!r} is a user rename"


@pytest.mark.integration
def test_split_domains_are_all_named_for_the_chain_and_their_range(scene):
    """Every piece of a split chain gets a consistent, range-accurate name.

    The reported defect: the first domain read "Chain A: Residues 1-248" while
    the second read "Domain 1" - two different generators disagreeing.
    """
    from proteinblender.utils.chain_utils import default_domain_name

    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    row_id = chain_row.item_id  # every _apply rebuilds and invalidates the row
    low = max(1, pdb_min)
    pieces = domain_layout.even_split(low, pdb_max, 3)

    # Create them the way the dialog does for auto-named rows.
    _apply(chain_row, [(default_domain_name(letter, s, e), s, e, None)
                       for s, e in pieces])
    _build_outliner()

    rows = [it for it in bpy.context.scene.outliner_items
            if it.item_type == "DOMAIN" and it.parent_id == row_id]
    assert len(rows) == 3
    shown = sorted(it.name for it in rows)
    assert shown == sorted(default_domain_name(letter, s, e) for s, e in pieces)
    # Nothing may read "Domain N" or carry the old "Residues" wording.
    assert not any("Residues" in name or name.startswith("Domain ")
                   for name in shown), shown


@pytest.mark.integration
def test_the_outliner_keeps_a_name_the_user_typed(scene):
    """A rename survives the rebuild; its auto-named sibling still tracks."""
    from proteinblender.utils.chain_utils import default_domain_name

    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)
    midpoint = (low + pdb_max) // 2
    _apply(chain_row, [("Catalytic core", low, midpoint, None),
                       (default_domain_name(letter, midpoint + 1, pdb_max),
                        midpoint + 1, pdb_max, None)])
    _build_outliner()

    names = [it.name for it in bpy.context.scene.outliner_items
             if it.item_type == "DOMAIN"]
    assert "Catalytic core" in names, (
        f"the user's name was overwritten by the rebuild: {names}")
    assert default_domain_name(letter, midpoint + 1, pdb_max) in names

    # Re-range the auto-named one: its name follows, the typed one does not.
    layout = domain_layout.current_layout(mol, chain_row.chain_id)
    typed = next(s for s in layout if s.name == "Catalytic core")
    auto = next(s for s in layout if s.name != "Catalytic core")
    shifted = midpoint + 10
    chain_row = _row_by_id(chain_row.item_id)
    _apply(chain_row, [("Catalytic core", low, shifted, typed.domain_id),
                       (default_domain_name(letter, shifted + 1, pdb_max),
                        shifted + 1, pdb_max, auto.domain_id)])
    _build_outliner()

    names = [it.name for it in bpy.context.scene.outliner_items
             if it.item_type == "DOMAIN"]
    assert "Catalytic core" in names, "the rename did not survive a re-range"
    assert default_domain_name(letter, shifted + 1, pdb_max) in names, (
        f"the auto name did not follow its new range: {names}")


# --------------------------------------------------------------------------
# Boundary dragging: the layout re-tiles itself
# --------------------------------------------------------------------------

def _tiles(specs, low, high):
    """True if ``specs`` covers [low, high] exactly, with no gaps or overlaps."""
    ordered = sorted(specs, key=lambda s: s.start)
    if ordered[0].start != low or ordered[-1].end != high:
        return False
    return all(nxt.start == prev.end + 1
               for prev, nxt in zip(ordered, ordered[1:]))


@pytest.mark.integration
def test_moving_a_start_moves_the_boundary_with_the_domain_above():
    """A domain's start and the previous domain's end are one boundary."""
    spec = domain_layout.DomainSpec
    layout = [spec("A", 1, 50, "a"), spec("B", 51, 100, "b")]

    # The user drags B's start from 51 to 71.
    edited = [layout[0], layout[1]._replace(start=71)]
    result, index = domain_layout.retile_after_edit(edited, 1, 1, 100,
                                                    moved_start=True)

    assert index == 1
    assert [(s.start, s.end) for s in result] == [(1, 70), (71, 100)]
    assert _tiles(result, 1, 100)
    # Identity is untouched: this is still the same two domains.
    assert [s.domain_id for s in result] == ["a", "b"]


@pytest.mark.integration
def test_moving_an_end_moves_the_boundary_with_the_domain_below():
    spec = domain_layout.DomainSpec
    layout = [spec("A", 1, 50, "a"), spec("B", 51, 100, "b")]

    # The user drags A's end from 50 to 30.
    edited = [layout[0]._replace(end=30), layout[1]]
    result, index = domain_layout.retile_after_edit(edited, 0, 1, 100,
                                                    moved_start=False)

    assert index == 0
    assert [(s.start, s.end) for s in result] == [(1, 30), (31, 100)]
    assert _tiles(result, 1, 100)
    assert [s.domain_id for s in result] == ["a", "b"]


@pytest.mark.integration
def test_pulling_the_first_start_off_the_chain_creates_a_domain_above():
    """Residues left with no owner get a new domain rather than vanishing."""
    spec = domain_layout.DomainSpec
    edited = [spec("A", 20, 100, "a")]

    result, index = domain_layout.retile_after_edit(edited, 0, 1, 100,
                                                    moved_start=True)

    assert len(result) == 2, "a domain should have been created above"
    assert (result[0].start, result[0].end) == (1, 19)
    assert result[0].domain_id is None, "the new domain must be a fresh one"
    assert (result[1].start, result[1].end) == (20, 100)
    assert result[1].domain_id == "a", "the edited domain kept its identity"
    assert index == 1, "the edited domain shifted down by the insertion"
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_pulling_the_last_end_off_the_chain_creates_a_domain_below():
    spec = domain_layout.DomainSpec
    edited = [spec("A", 1, 80, "a")]

    result, index = domain_layout.retile_after_edit(edited, 0, 1, 100,
                                                    moved_start=False)

    assert len(result) == 2
    assert (result[0].start, result[0].end) == (1, 80)
    assert result[0].domain_id == "a"
    assert (result[1].start, result[1].end) == (81, 100)
    assert result[1].domain_id is None
    assert index == 0
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_complete_layout_gives_an_orphaned_head_its_own_domain():
    """Dragging the first Start up the chain leaves a head with no owner.

    The row list is deliberately allowed to stop short while the value is being
    dragged - inserting the domain on the spot moves the edited row out from
    under the cursor - so the completion has to happen on commit instead.
    """
    spec = domain_layout.DomainSpec
    rows = [spec("A", 30, 66, "a"), spec("B", 67, 100, "b")]

    result = domain_layout.complete_layout(rows, 1, 100)

    assert [(s.start, s.end) for s in result] == [(1, 29), (30, 66), (67, 100)]
    assert result[0].domain_id is None, "the filler must be a fresh domain"
    assert result[1].domain_id == "a", "the edited domain kept its identity"
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_complete_layout_gives_an_orphaned_tail_its_own_domain():
    spec = domain_layout.DomainSpec
    rows = [spec("A", 1, 40, "a"), spec("B", 41, 80, "b")]

    result = domain_layout.complete_layout(rows, 1, 100)

    assert [(s.start, s.end) for s in result] == [(1, 40), (41, 80), (81, 100)]
    assert result[-1].domain_id is None
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_complete_layout_leaves_a_layout_that_already_tiles_alone():
    """Committing an untouched chain must not invent anything."""
    spec = domain_layout.DomainSpec
    rows = [spec("A", 1, 50, "a"), spec("B", 51, 100, "b")]

    result = domain_layout.complete_layout(rows, 1, 100)

    assert [(s.name, s.start, s.end, s.domain_id) for s in result] == [
        ("A", 1, 50, "a"), ("B", 51, 100, "b")]


@pytest.mark.integration
def test_complete_layout_fills_both_ends_at_once():
    """Both ends can be open together - one drag each - and both must close."""
    spec = domain_layout.DomainSpec
    rows = [spec("A", 30, 66, "a"), spec("B", 67, 80, "b")]

    result = domain_layout.complete_layout(rows, 1, 100)

    assert [(s.start, s.end) for s in result] == [
        (1, 29), (30, 66), (67, 80), (81, 100)]
    assert [s.domain_id for s in result] == [None, "a", "b", None]
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_complete_layout_closes_an_interior_hole_too():
    """A layout is completed, not just capped.

    Interior holes should not arise - re-tiling keeps the middle contiguous -
    but if one ever does, committing it would hand those residues to no domain
    at all, which is the failure this whole function exists to prevent.
    """
    spec = domain_layout.DomainSpec
    rows = [spec("A", 1, 30, "a"), spec("B", 61, 100, "b")]

    result = domain_layout.complete_layout(rows, 1, 100)

    assert [(s.start, s.end) for s in result] == [(1, 30), (31, 60), (61, 100)]
    assert result[1].domain_id is None
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_complete_layout_of_nothing_is_the_whole_chain():
    """The degenerate case still yields a chain that is fully owned."""
    result = domain_layout.complete_layout([], 1, 100)

    assert [(s.start, s.end) for s in result] == [(1, 100)]
    assert result[0].domain_id is None


@pytest.mark.integration
def test_complete_layout_does_not_mutate_what_it_was_given():
    """execute() validates the completed layout; the rows must be untouched."""
    spec = domain_layout.DomainSpec
    rows = [spec("A", 30, 100, "a")]
    before = list(rows)

    domain_layout.complete_layout(rows, 1, 100)

    assert rows == before, "complete_layout edited the caller's list in place"


@pytest.mark.integration
def test_complete_layout_names_what_it_creates():
    """A filler domain reaches the user, so it needs a name a user recognises."""
    from proteinblender.utils.chain_utils import is_default_domain_name

    spec = domain_layout.DomainSpec
    result = domain_layout.complete_layout(
        [spec("A", 30, 100, "a")], 1, 100,
        name_for=lambda start, end: f"Chain A: {start}-{end}")

    assert result[0].name == "Chain A: 1-29"
    assert is_default_domain_name(result[0].name), (
        "an invented name must read back as auto-generated, or it freezes as "
        "though the user had typed it")


@pytest.mark.integration
def test_a_boundary_cannot_swallow_its_neighbour():
    """Dragging through a neighbour stops at one residue instead of deleting it.

    Removing a domain is what Merge and the row's X button are for; it must not
    happen as a side effect of dragging a boundary too far.
    """
    spec = domain_layout.DomainSpec
    layout = [spec("A", 1, 50, "a"), spec("B", 51, 100, "b")]

    # Drag B's start all the way to 1, well past A's start.
    edited = [layout[0], layout[1]._replace(start=1)]
    result, _ = domain_layout.retile_after_edit(edited, 1, 1, 100,
                                                moved_start=True)
    assert len(result) == 2, "the neighbour must survive"
    assert (result[0].start, result[0].end) == (1, 1), "A keeps one residue"
    assert (result[1].start, result[1].end) == (2, 100)
    assert _tiles(result, 1, 100)

    # And symmetrically, dragging A's end past B's end.
    edited = [layout[0]._replace(end=100), layout[1]]
    result, _ = domain_layout.retile_after_edit(edited, 0, 1, 100,
                                                moved_start=False)
    assert len(result) == 2
    assert (result[0].start, result[0].end) == (1, 99)
    assert (result[1].start, result[1].end) == (100, 100)
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_retiling_clamps_to_the_chain_and_never_inverts_a_domain():
    spec = domain_layout.DomainSpec

    # A start typed past the chain end is clamped, and never passes its own end.
    edited = [spec("A", 1, 40, "a"), spec("B", 41, 100, "b")]
    edited[1] = edited[1]._replace(start=9999)
    result, _ = domain_layout.retile_after_edit(edited, 1, 1, 100,
                                                moved_start=True)
    assert all(s.start <= s.end for s in result)
    assert all(1 <= s.start and s.end <= 100 for s in result)
    assert _tiles(result, 1, 100)

    # An end typed below the chain start likewise.
    edited = [spec("A", 1, 40, "a"), spec("B", 41, 100, "b")]
    edited[0] = edited[0]._replace(end=-50)
    result, _ = domain_layout.retile_after_edit(edited, 0, 1, 100,
                                                moved_start=False)
    assert all(s.start <= s.end for s in result)
    assert all(1 <= s.start and s.end <= 100 for s in result)
    assert _tiles(result, 1, 100)


@pytest.mark.integration
def test_retiling_a_single_full_chain_domain_is_a_no_op():
    """Touching a boundary that is already at the chain edge changes nothing."""
    spec = domain_layout.DomainSpec
    layout = [spec("A", 1, 100, "a")]

    result, index = domain_layout.retile_after_edit(layout, 0, 1, 100,
                                                    moved_start=True)
    assert result == layout and index == 0

    result, index = domain_layout.retile_after_edit(layout, 0, 1, 100,
                                                    moved_start=False)
    assert result == layout and index == 0


@pytest.mark.integration
def test_coverage_gaps_reports_uncovered_spans_without_failing_validation():
    """A deliberate hole in the layout is reported but is not an error."""
    spec = domain_layout.DomainSpec
    specs = [spec("A", 1, 20), spec("B", 41, 60)]
    assert domain_layout.validate_layout(specs, 1, 80) == []
    assert domain_layout.coverage_gaps(specs, 1, 80) == [(21, 40), (61, 80)]


# --------------------------------------------------------------------------
# The chain range the dialog offers must be the chain's real range
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_chain_range_matches_the_pdb(scene):
    """The splitter's valid range agrees with the residues actually in the file."""
    mid, chain_row, (pdb_min, pdb_max) = _single_chain_setup()[:3]
    mol = H.sm().molecules[mid]

    low, high = domain_layout.chain_residue_range(
        mol, domain_layout.chain_match_tokens(mol, chain_row.chain_id).pop())

    # 1ubq's chain A runs 1-76; the addon normalises the floor to 1.
    assert low == max(1, pdb_min)
    assert high == pdb_max


# --------------------------------------------------------------------------
# Splitting a whole chain
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_splitting_a_chain_produces_the_requested_domains(scene):
    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)

    pieces = domain_layout.even_split(low, pdb_max, 3)
    _apply(chain_row, [(f"Part {i}", s, e, None)
                       for i, (s, e) in enumerate(pieces, start=1)])

    domains = _domains_on_chain(mol, letter)
    assert len(domains) == 3
    ranges = sorted((d.start, d.end) for d in domains.values())
    assert ranges == pieces
    assert sorted(d.name for d in domains.values()) == ["Part 1", "Part 2", "Part 3"]
    for domain in domains.values():
        assert domain.object is not None
        assert domain.object.name in bpy.data.objects


def _isolate_and_render(keep_obj, tmp_path):
    """Pixels covered by ``keep_obj`` alone, with everything else hidden.

    Measured with Blender's renderer rather than with evaluated vertices: a
    MolecularNodes style emits instanced geometry, so ``to_mesh()`` reports
    zero for every molecule and domain object in the scene. The rendered image
    is what the user actually sees, and it cannot move in lock-step with a bug
    in the addon's own geometry maths.
    """
    hidden = []
    for obj in bpy.data.objects:
        if obj is not keep_obj and not obj.hide_render:
            obj.hide_render = True
            hidden.append(obj)
    keep_obj.hide_render = False
    try:
        bpy.context.view_layer.update()
        return int(H.render_coverage(tmp_path).sum())
    finally:
        for obj in hidden:
            obj.hide_render = False


@pytest.mark.integration
def test_domain_geometry_follows_its_range(scene, tmp_path):
    """Re-ranging a domain retargets what it actually renders.

    The risk in an in-place update is that the model's start/end change while
    the geometry-nodes residue selection keeps the old range: the domain would
    report the new range and keep drawing the old one, and every non-visual
    assertion in this file would still pass. Rendered pixel coverage is the
    witness that cannot. The expected *ordering* comes from the PDB - a range
    covering a quarter of the residues draws less protein - not from any addon
    helper.
    """
    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)
    midpoint = (low + pdb_max) // 2

    _apply(chain_row, [("Head", low, midpoint, None),
                       ("Tail", midpoint + 1, pdb_max, None)])

    domains = _domains_on_chain(mol, letter)
    head_id = next(d for d, dom in domains.items() if dom.name == "Head")
    wide_pixels = _isolate_and_render(mol.domains[head_id].object, tmp_path)
    assert wide_pixels > 0, "the domain rendered nothing to begin with"

    # Shrink Head to a quarter of its span, in place, keeping its identity.
    quarter_end = low + max(1, (midpoint - low) // 4)
    chain_row = _row_by_id(chain_row.item_id)
    _apply(chain_row, [("Head", low, quarter_end, head_id),
                       ("Tail", midpoint + 1, pdb_max, None)])

    head = mol.domains[head_id]
    assert (head.start, head.end) == (low, quarter_end)
    narrow_pixels = _isolate_and_render(head.object, tmp_path)
    assert narrow_pixels < wide_pixels, (
        "the domain still draws its old range: the geometry nodes were not "
        f"retargeted ({narrow_pixels} px for {low}-{quarter_end} vs "
        f"{wide_pixels} px for {low}-{midpoint})")


# --------------------------------------------------------------------------
# The core invariant: identity survives a layout edit
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_reranging_keeps_the_domain_id_and_its_object(scene):
    """A re-ranged domain is the *same* domain, not a replacement.

    Ground truth is the id and object name captured before the edit. Under the
    old delete-and-recreate route both changed, because each embeds the residue
    range.
    """
    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)
    midpoint = (low + pdb_max) // 2

    _apply(chain_row, [("Head", low, midpoint, None),
                       ("Tail", midpoint + 1, pdb_max, None)])

    domains = _domains_on_chain(mol, letter)
    head_id = next(d for d, dom in domains.items() if dom.name == "Head")
    tail_id = next(d for d, dom in domains.items() if dom.name == "Tail")
    head_obj_name = mol.domains[head_id].object.name
    tail_obj_name = mol.domains[tail_id].object.name

    # Move the boundary: both domains change range, neither is removed.
    new_boundary = midpoint + 10
    chain_row = _row_by_id(chain_row.item_id)
    _apply(chain_row, [("Head", low, new_boundary, head_id),
                       ("Tail", new_boundary + 1, pdb_max, tail_id)])

    assert head_id in mol.domains, "re-ranging replaced the domain instead of editing it"
    assert tail_id in mol.domains
    assert mol.domains[head_id].object.name == head_obj_name, (
        "the domain's object was recreated; the scene pose library and any "
        "animation on it key off this name")
    assert mol.domains[tail_id].object.name == tail_obj_name
    assert (mol.domains[head_id].start, mol.domains[head_id].end) == (low, new_boundary)
    assert (mol.domains[tail_id].start, mol.domains[tail_id].end) == (new_boundary + 1, pdb_max)


@pytest.mark.integration
def test_reranging_preserves_per_domain_animation(scene):
    """Keyframes on a domain object survive a range edit.

    Animation lives on the domain's Blender object. Recreating that object
    destroys its action outright and unrecoverably, so this is the sharpest
    observable consequence of losing identity. Read from Blender's own
    animation_data, which knows nothing about the addon.
    """
    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)
    midpoint = (low + pdb_max) // 2

    _apply(chain_row, [("Head", low, midpoint, None),
                       ("Tail", midpoint + 1, pdb_max, None)])
    domains = _domains_on_chain(mol, letter)
    head_id = next(d for d, dom in domains.items() if dom.name == "Head")
    obj = mol.domains[head_id].object

    # Two distinct keyed poses, so the assertion below tests that the *curve*
    # survived rather than just that some action object exists.
    obj.location = (1.0, 2.0, 3.0)
    obj.keyframe_insert(data_path="location", frame=1)
    obj.location = (7.0, 8.0, 9.0)
    obj.keyframe_insert(data_path="location", frame=20)
    assert obj.animation_data and obj.animation_data.action
    action_name = obj.animation_data.action.name

    def _location_at(frame):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return tuple(round(v, 4) for v in obj.location)

    assert _location_at(1) == (1.0, 2.0, 3.0)
    assert _location_at(20) == (7.0, 8.0, 9.0)

    chain_row = _row_by_id(chain_row.item_id)
    _apply(chain_row, [("Head", low, midpoint - 5, head_id),
                       ("Tail", midpoint + 1, pdb_max, None)])

    obj = mol.domains[head_id].object
    assert obj.animation_data is not None, "the domain lost its animation data"
    assert obj.animation_data.action is not None
    assert obj.animation_data.action.name == action_name
    # Evaluate the curve rather than inspecting fcurves directly: Blender's
    # slotted-action API moved them, and the animated value is what matters.
    assert _location_at(1) == (1.0, 2.0, 3.0)
    assert _location_at(20) == (7.0, 8.0, 9.0)


@pytest.mark.integration
def test_reranging_preserves_puppet_membership_and_controller(scene):
    """A puppet keeps its members - and its controller - across a layout edit.

    Membership is stored as domain ids. When a re-range changed the id, the
    outliner rebuild pruned the now-unknown member, and a puppet left with no
    members has its controller Empty deleted outright, taking the puppet's
    animation with it.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    chain_rows = _chain_rows(mid)
    assert len(chain_rows) >= 2
    mol = H.sm().molecules[mid]

    target_row_id = chain_rows[0].item_id

    # Split the chain first, so the puppet has real domains to own.
    row = _row_by_id(target_row_id)
    low, high = domain_layout.chain_residue_range(mol, row.chain_id)
    pieces = domain_layout.even_split(low, high, 2)
    _apply(row, [(f"Piece {i}", s, e, None)
                 for i, (s, e) in enumerate(pieces, start=1)])
    _build_outliner()

    # Build the puppet from the DOMAIN rows, not the chain row. Membership then
    # stores domain ids, which is the state a range edit actually threatens - a
    # chain row's id is derived from the chain index and never moves, so a
    # chain-level puppet would survive even the broken delete-and-recreate route
    # and prove nothing.
    domain_row_ids = [it.item_id for it in bpy.context.scene.outliner_items
                      if it.item_type == "DOMAIN" and it.parent_id == target_row_id]
    assert len(domain_row_ids) == 2, "the chain did not split into two domain rows"
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in set(domain_row_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="P")
    puppet = next(it for it in bpy.context.scene.outliner_items
                  if it.item_type == "PUPPET" and it.name == "P")
    members_before = set(puppet.puppet_memberships.split(','))
    assert members_before == set(domain_row_ids), (
        "the puppet must be keyed on the domain ids for this test to bite")
    controller_name = puppet.controller_object_name
    assert controller_name in bpy.data.objects

    # Now nudge the split boundary on the puppeted chain.
    domains = {did: d for did, d in mol.domains.items()
               if did.startswith(mid) and d.name.startswith("Piece")}
    by_start = sorted(domains.items(), key=lambda kv: kv[1].start)
    first_id, first = by_start[0]
    second_id, second = by_start[1]
    boundary = first.end + 5

    row = _row_by_id(target_row_id)
    _apply(row, [("Piece 1", first.start, boundary, first_id),
                 ("Piece 2", boundary + 1, second.end, second_id)])
    _build_outliner()

    puppet = next((it for it in bpy.context.scene.outliner_items
                   if it.item_type == "PUPPET" and it.name == "P"), None)
    assert puppet is not None, "the puppet was deleted by a domain range edit"
    assert set(puppet.puppet_memberships.split(',')) == members_before, (
        "puppet membership changed; the re-ranged domains lost their ids")
    assert controller_name in bpy.data.objects, (
        "the puppet's controller Empty was deleted, taking its animation")


@pytest.mark.integration
def test_reranging_preserves_linker_endpoints(scene):
    """A linker anchored to a domain still points at it after a range edit.

    Linker endpoints store the domain id, and ``prune_dangling_linkers`` deletes
    linkers whose endpoint id no longer resolves - so losing identity here
    deletes the user's linker outright.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]
    # Capture ids, not rows: every _apply rebuilds scene.outliner_items, which
    # invalidates previously held row structs.
    row_ids = [it.item_id for it in _chain_rows(mid)][:2]
    assert len(row_ids) == 2

    # Split two chains so there are real domains to link between.
    for row_index, row_id in enumerate(row_ids):
        row = _row_by_id(row_id)
        low, high = domain_layout.chain_residue_range(mol, row.chain_id)
        pieces = domain_layout.even_split(low, high, 2)
        _apply(row, [(f"C{row_index}_{i}", s, e, None)
                     for i, (s, e) in enumerate(pieces, start=1)])
        _build_outliner()

    def _domain_named(prefix):
        return next(did for did, d in mol.domains.items()
                    if d.name.startswith(prefix))

    a_id = _domain_named("C0_1")
    b_id = _domain_named("C1_1")

    # Linker endpoints are only offered within a puppet, so build one over the
    # two split chains first.
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in set(row_ids)
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="LinkP")
    _build_outliner()

    # The endpoint enums namespace their values with an A_/B_ prefix.
    result = bpy.ops.pb2.add_linker('EXEC_DEFAULT',
                                    endpoint_a_item=f"A_{a_id}",
                                    endpoint_b_item=f"B_{b_id}")
    assert result == {'FINISHED'}
    assert len(bpy.context.scene.pb2_linkers) == 1
    linker_before = bpy.context.scene.pb2_linkers[0]
    endpoint_a = linker_before.endpoint_a_item_id
    endpoint_b = linker_before.endpoint_b_item_id
    residue_a = linker_before.endpoint_a_residue
    assert endpoint_a == a_id

    # Re-range the domain the linker is anchored to, keeping the anchor residue
    # inside it.
    domain_a = mol.domains[a_id]
    other_a = next(did for did, d in mol.domains.items()
                   if d.name.startswith("C0_2"))
    new_end = max(residue_a, domain_a.end - 3)

    row = _row_by_id(row_ids[0])
    _apply(row, [("C0_1", domain_a.start, new_end, a_id),
                 ("C0_2", new_end + 1, mol.domains[other_a].end, other_a)])
    _build_outliner()

    assert len(bpy.context.scene.pb2_linkers) == 1, (
        "the linker was pruned; its endpoint domain lost its id")
    linker_after = bpy.context.scene.pb2_linkers[0]
    assert linker_after.endpoint_a_item_id == endpoint_a
    assert linker_after.endpoint_b_item_id == endpoint_b


# --------------------------------------------------------------------------
# Removal still cleans up
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_removing_a_domain_strips_it_from_puppet_membership(scene):
    """Dropping a domain from the layout removes it from puppets too.

    The counterpart to the preservation tests: identity is kept for domains the
    user *keeps*, but a domain they genuinely delete must not leave a dangling
    member id behind.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]
    row = _chain_rows(mid)[0]
    row_id = row.item_id

    low, high = domain_layout.chain_residue_range(mol, row.chain_id)
    pieces = domain_layout.even_split(low, high, 3)
    _apply(row, [(f"Piece {i}", s, e, None)
                 for i, (s, e) in enumerate(pieces, start=1)])
    _build_outliner()

    domain_rows = [it for it in bpy.context.scene.outliner_items
                   if it.item_type == "DOMAIN" and it.parent_id == row_id]
    assert len(domain_rows) == 3
    for it in bpy.context.scene.outliner_items:
        it.is_selected = it.item_id in {d.item_id for d in domain_rows}
    bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name="P3")
    puppet = next(it for it in bpy.context.scene.outliner_items
                  if it.item_type == "PUPPET" and it.name == "P3")
    assert len(puppet.puppet_memberships.split(',')) == 3

    # Collapse three domains into two: the third is genuinely deleted.
    kept = sorted(((did, d) for did, d in mol.domains.items()
                   if d.name.startswith("Piece")),
                  key=lambda kv: kv[1].start)
    doomed_id = kept[2][0]

    row = _row_by_id(row_id)
    _apply(row, [("Piece 1", kept[0][1].start, kept[0][1].end, kept[0][0]),
                 ("Piece 2", kept[1][1].start, high, kept[1][0])])
    _build_outliner()

    assert doomed_id not in mol.domains
    puppet = next((it for it in bpy.context.scene.outliner_items
                   if it.item_type == "PUPPET" and it.name == "P3"), None)
    assert puppet is not None
    remaining = set(puppet.puppet_memberships.split(','))
    assert doomed_id not in remaining, "deleted domain left a dangling member id"
    assert {kept[0][0], kept[1][0]} <= remaining


# --------------------------------------------------------------------------
# The viewport preview must always be undone
# --------------------------------------------------------------------------

def _domain_tree(obj):
    """The domain's geometry-node tree, straight off its modifier."""
    return next(m.node_group for m in obj.modifiers
                if m.type == 'NODES' and m.node_group)


def _shown_range(obj):
    """The residue span a domain object is currently displaying."""
    _mod, node = ds._range_node(obj)
    return (node.inputs["Min"].default_value, node.inputs["Max"].default_value)


def _style_material(obj):
    """The material the domain is shaded with, read from the node graph.

    Deliberately not domain_splitter's own accessor: an assertion that reads
    state through the code under test would move with a bug in that code
    instead of catching it.
    """
    tree = _domain_tree(obj)
    style = next(n for n in tree.nodes if n.type == 'GROUP' and n.node_tree
                 and 'Style' in n.node_tree.name)
    return style.inputs["Material"].default_value


def _style_material_name(obj):
    material = _style_material(obj)
    return material.name if material else ""


def _shader_alpha(material):
    """The Principled BSDF alpha a material shades with, or None."""
    return next((n.inputs['Alpha'].default_value
                 for n in material.node_tree.nodes
                 if n.type == 'BSDF_PRINCIPLED'), None)


def _shader_shape(material):
    """The material's node types and links, as a comparable fingerprint."""
    nodes = sorted(n.type for n in material.node_tree.nodes)
    links = sorted((l.from_node.type, l.from_socket.name,
                    l.to_node.type, l.to_socket.name)
                   for l in material.node_tree.links)
    return nodes, links


def _domain_color(obj):
    """The domain's colour, read from the node graph rather than the model."""
    return tuple(_domain_tree(obj).nodes["Color Common"].inputs["Carbon"]
                 .default_value)


def _spec(entry, start, end):
    return domain_layout.DomainSpec(name=entry.name, start=start, end=end,
                                    domain_id=entry.domain_id)


def _split_in_two(mid):
    """A chain of 4hhb divided into two domains, ready to preview."""
    mol = H.sm().molecules[mid]
    row = _chain_rows(mid)[0]
    token = row.chain_id
    low, high = domain_layout.chain_residue_range(mol, token)
    pieces = domain_layout.even_split(low, high, 2)
    _apply(row, [(f"Piece {i}", s, e, None)
                 for i, (s, e) in enumerate(pieces, start=1)])
    _build_outliner()

    layout = domain_layout.current_layout(mol, token)
    assert len(layout) == 2, "expected the chain to be split in two"
    return mol, token, low, high, layout


@pytest.mark.integration
def test_preview_isolates_the_chain_and_restores_everything_afterwards(scene):
    """Sizing a domain isolates its chain, and closing the dialog puts it back.

    The chain being edited stays whole - the domain under the cursor plus its
    neighbours for context - while everything else in the scene is hidden. This
    is the one piece of the dialog that touches the scene *before* the user
    confirms, so a leak is highly visible: the user would be left looking at a
    scene missing most of its contents with no idea why. Ground truth is the
    visibility flags and node ranges captured before isolating, so the
    assertions cannot move with a bug in the restore code.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol, token, low, high, layout = _split_in_two(mid)

    geometry = [o for o in bpy.data.objects if o.type in ds._ISOLATABLE_TYPES]
    assert len(geometry) > 3, "need several objects for isolation to mean anything"
    before_hidden = {o.name: o.hide_viewport for o in geometry}

    first_obj = mol.domains[layout[0].domain_id].object
    second_obj = mol.domains[layout[1].domain_id].object
    chain_objects = {first_obj.name, second_obj.name}
    assert chain_objects < set(before_hidden), (
        "the scene holds nothing outside the edited chain to hide")
    before_range = {o.name: _shown_range(o) for o in (first_obj, second_obj)}

    # Size the FIRST domain. Its chain stays whole; nothing else survives.
    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low + 5, low + 25),
                       _spec(layout[1], low + 26, high)], 0)
    visible = {o.name for o in bpy.data.objects
               if o.type in ds._ISOLATABLE_TYPES and not o.hide_viewport}
    assert visible == chain_objects, (
        f"isolation should leave exactly the edited chain visible, left {visible}")
    assert _shown_range(first_obj) == (low + 5, low + 25)
    assert _shown_range(second_obj) == (low + 26, high), (
        "the rest of the chain is not showing the layout the user is heading to")

    # Dragging further must not re-capture the previewed state as "original".
    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low + 5, low + 40),
                       _spec(layout[1], low + 41, high)], 0)
    assert _shown_range(first_obj) == (low + 5, low + 40)

    # Moving to the SECOND domain sizes that one instead. Both stay visible:
    # the chain is the context, only which domain is the subject changes.
    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low, low + 49),
                       _spec(layout[1], low + 50, low + 60)], 1)
    visible = {o.name for o in bpy.data.objects
               if o.type in ds._ISOLATABLE_TYPES and not o.hide_viewport}
    assert visible == chain_objects, (
        f"switching domains changed what is visible: {visible}")
    assert bpy.context.scene[ds._PREVIEW_OBJECT] == second_obj.name

    ds.restore_preview(bpy.context)

    after_hidden = {o.name: o.hide_viewport for o in bpy.data.objects
                    if o.type in ds._ISOLATABLE_TYPES}
    assert after_hidden == before_hidden, (
        "the preview did not restore the original visibility")
    # Every driven object gets its own range back, not just the last one.
    for obj in (first_obj, second_obj):
        assert _shown_range(obj) == before_range[obj.name], (
            f"the preview left {obj.name} showing a preview range")
    assert ds._PREVIEW_OBJECT not in bpy.context.scene, (
        "preview bookkeeping was left on the scene")


@pytest.mark.integration
def test_preview_ghosts_the_chain_and_highlights_the_domain_being_sized(scene):
    """The edited domain is picked out of its chain, and both revert on close.

    Context is only useful if the subject still reads as the subject, so the
    domain under the cursor is drawn solid and in the highlight colour while
    its neighbours drop to the ghost material. Both are borrowed, not owned:
    the domain's real colour and material have to come back, or the dialog
    silently repaints the user's molecule.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol, token, low, high, layout = _split_in_two(mid)

    first_obj = mol.domains[layout[0].domain_id].object
    second_obj = mol.domains[layout[1].domain_id].object
    before_material = {o.name: _style_material_name(o)
                       for o in (first_obj, second_obj)}
    before_color = {o.name: _domain_color(o) for o in (first_obj, second_obj)}
    assert before_color[first_obj.name] != before_color[second_obj.name], (
        "the fixture gave both domains the same colour, so a highlight that "
        "leaked to the neighbour would go unnoticed")

    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low, low + 40),
                       _spec(layout[1], low + 41, high)], 0)

    assert _style_material_name(first_obj) == before_material[first_obj.name], (
        "the domain being sized should stay solid, in its own material")
    assert _style_material_name(second_obj) == (
        before_material[second_obj.name] + ds._GHOST_SUFFIX), (
        "the rest of the chain should be ghosted for context")
    assert _domain_color(first_obj) == pytest.approx(ds.HIGHLIGHT_COLOR, abs=1e-4), (
        "the domain being sized was not highlighted")
    assert _domain_color(second_obj) == pytest.approx(
        before_color[second_obj.name], abs=1e-4), (
        "highlighting one domain repainted its neighbour")

    # Sizing the other domain swaps which one is the subject, both ways round.
    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low, low + 40),
                       _spec(layout[1], low + 41, high)], 1)
    assert _style_material_name(first_obj) == (
        before_material[first_obj.name] + ds._GHOST_SUFFIX)
    assert _style_material_name(second_obj) == before_material[second_obj.name]
    assert _domain_color(second_obj) == pytest.approx(ds.HIGHLIGHT_COLOR, abs=1e-4)
    assert _domain_color(first_obj) == pytest.approx(
        before_color[first_obj.name], abs=1e-4), (
        "the domain we stopped sizing kept the highlight colour")

    ds.restore_preview(bpy.context)

    for obj in (first_obj, second_obj):
        assert _style_material_name(obj) == before_material[obj.name], (
            f"{obj.name} was left wearing the preview's material")
        assert _domain_color(obj) == pytest.approx(before_color[obj.name],
                                                   abs=1e-4), (
            f"{obj.name} was left wearing the preview's colour")
    assert [m.name for m in bpy.data.materials
            if m.name.endswith(ds._GHOST_SUFFIX)] == [], (
        "the preview left its ghost materials in the file")


@pytest.mark.integration
def test_a_chain_that_was_never_split_still_gets_ghosted_context(scene):
    """The ordinary way in, where almost every row is intent rather than object.

    A chain imports as a *single* domain, so opening the splitter and asking
    for three gives one row backed by a real object and two backed by nothing
    at all - the domains a layout describes are created when the user presses
    OK, long after the preview has to draw them. Previewing only the rows that
    already had objects meant this, the common path, showed one solid domain
    and an otherwise empty viewport with nothing ghosted whatsoever.

    Every other test in this file splits the chain up front, which hands the
    preview a full set of objects and hides the case entirely. That is what let
    the feature ship looking, to its author, like it worked.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]
    row = _chain_rows(mid)[0]
    token = row.chain_id
    low, high = domain_layout.chain_residue_range(mol, token)

    layout = domain_layout.current_layout(mol, token)
    assert len(layout) == 1, "the chain should import as a single domain"
    real = mol.domains[layout[0].domain_id].object
    real_range = _shown_range(real)

    # What the dialog holds after the user sets the count to three: the first
    # row inherits the existing domain, the rest are pure intent.
    thirds = domain_layout.even_split(low, high, 3)
    specs = [domain_layout.DomainSpec(
                name=f"New {i}", start=start, end=end,
                domain_id=layout[0].domain_id if i == 0 else None)
             for i, (start, end) in enumerate(thirds)]

    # Size the middle row - the one with no object of its own.
    ds.preview_layout(bpy.context, mol, token, specs, 1)

    visible = [o for o in bpy.data.objects
               if o.type in ds._ISOLATABLE_TYPES and not o.hide_viewport]
    assert len(visible) == 3, (
        f"every row should be drawn, but only these are: "
        f"{[o.name for o in visible]}")
    assert sorted(_shown_range(o) for o in visible) == sorted(
        (s.start, s.end) for s in specs), (
        "what is on screen does not tile the chain the layout describes")

    ghosted = [o for o in visible
               if _style_material_name(o).endswith(ds._GHOST_SUFFIX)]
    solid = [o for o in visible if o not in ghosted]
    assert len(solid) == 1, (
        f"exactly one domain should be solid, got {[o.name for o in solid]}")
    assert len(ghosted) == 2, "the rest of the chain should be ghosted"
    assert _shown_range(solid[0]) == (specs[1].start, specs[1].end), (
        "the solid domain is not the one being sized")
    assert _domain_color(solid[0]) == pytest.approx(ds.HIGHLIGHT_COLOR, abs=1e-4), (
        "the stand-in for a brand-new domain was not highlighted - its colour "
        "group is probably still shared with the object it was copied from")

    ds.restore_preview(bpy.context)

    assert [o.name for o in bpy.data.objects
            if o.name.startswith(ds._TEMP_PREFIX)] == [], (
        "the preview left its stand-in objects in the scene")
    assert _shown_range(real) == real_range, (
        "the real domain was left showing a preview range")


@pytest.mark.integration
def test_the_ghost_is_a_copy_of_the_domains_own_material(scene):
    """The ghost must differ from the real material in opacity and nothing else.

    This is the shape of the feature, not an implementation detail. A ghost
    built from scratch - a plain Attribute node into a fresh Principled BSDF -
    reproduces the domain's colours and so looks correct in a node graph, but
    MolecularNodes shades through its own group reading the *instancer*, and
    the stand-in renders effectively opaque in the Material Preview viewport
    however low its alpha is set. That failure is invisible to any assertion
    about colour or about which material is assigned; only "the ghost shades
    the same way the real material does" catches it.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol, token, low, high, layout = _split_in_two(mid)

    first_obj = mol.domains[layout[0].domain_id].object
    second_obj = mol.domains[layout[1].domain_id].object
    real = _style_material(second_obj)
    real_shape = _shader_shape(real)
    assert _shader_alpha(real) == 1.0, "the fixture's material is already faded"

    ds.preview_layout(bpy.context, mol, token,
                      [_spec(layout[0], low, low + 40),
                       _spec(layout[1], low + 41, high)], 0)

    ghost = _style_material(second_obj)
    assert ghost != real, "the ghost shares the real material, so alpha would leak"
    assert _shader_shape(ghost) == real_shape, (
        "the ghost does not shade the way the domain does - it is a stand-in, "
        "not a copy, and will not render translucent")
    assert _shader_alpha(ghost) == pytest.approx(ds.GHOST_ALPHA), (
        "the ghost is not actually transparent")
    assert ghost.surface_render_method == 'BLENDED', (
        "dithered transparency renders the ghost as a stipple, not a wash")
    # The one that silently undoes the whole effect. A space-filling chain
    # stacks ~20 sphere surfaces per view ray; with the far side drawn, each
    # blends again and the chain returns to near-opaque however low the alpha
    # is set - measured at 68% of opaque brightness versus 25% with it off.
    # Nothing about the assignment, the colour or the alpha value catches this.
    assert ghost.show_transparent_back is False, (
        "the ghost draws its far side, so alpha compounds back to near-opaque")
    # The domain being sized is untouched: its material must still be the real
    # one, at full opacity, or the subject fades along with its context.
    assert _style_material(first_obj) == real
    assert _shader_alpha(_style_material(first_obj)) == 1.0

    ds.restore_preview(bpy.context)
    assert _style_material(second_obj) == real
    assert _shader_alpha(real) == 1.0, "the preview faded the real material"


@pytest.mark.integration
def test_a_new_row_gets_its_own_stand_in_and_leaves_the_real_domains_alone(scene):
    """A row with no object is drawn by a stand-in, not by taking a sibling's.

    An earlier version lent the new row an existing domain's object. That domain
    then had nothing left to draw itself with, so adding a row silently blanked
    a real one from the context it was supposed to be providing - and the lender
    had to be handed its own range back on the way out or it would sit there
    showing the wrong stretch of the chain.
    """
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol, token, low, high, layout = _split_in_two(mid)

    first_obj = mol.domains[layout[0].domain_id].object
    second_obj = mol.domains[layout[1].domain_id].object
    before_range = {o.name: _shown_range(o) for o in (first_obj, second_obj)}
    before_color = {o.name: _domain_color(o) for o in (first_obj, second_obj)}

    # A third row the user has just added: no domain_id, so no object of its own.
    brand_new = domain_layout.DomainSpec(name="New", start=low, end=low + 20,
                                         domain_id=None)
    ds.preview_layout(bpy.context, mol, token,
                      [brand_new, _spec(layout[0], low + 21, low + 60),
                       _spec(layout[1], low + 61, high)], 0)

    drawn = bpy.data.objects[bpy.context.scene[ds._PREVIEW_OBJECT]]
    assert drawn.name.startswith(ds._TEMP_PREFIX), (
        f"the new row took a real domain's object ({drawn.name}) instead of "
        "being given a stand-in")
    assert _shown_range(drawn) == (low, low + 20)
    # Both real domains keep drawing themselves, which is the whole point.
    assert _shown_range(first_obj) == (low + 21, low + 60)
    assert _shown_range(second_obj) == (low + 61, high)

    ds.restore_preview(bpy.context)

    for obj in (first_obj, second_obj):
        assert _shown_range(obj) == before_range[obj.name]
        assert _domain_color(obj) == pytest.approx(before_color[obj.name],
                                                   abs=1e-4)
    assert [o.name for o in bpy.data.objects
            if o.name.startswith(ds._TEMP_PREFIX)] == [], (
        "the preview left its stand-in objects in the scene")


@pytest.mark.integration
def test_restoring_a_preview_that_was_never_started_is_harmless(scene):
    """A stale-preview teardown on a clean scene must be a no-op, not a crash."""
    H.import_local("1ubq.pdb", "1ubq")
    _build_outliner()
    before = {o.name: o.hide_viewport for o in bpy.data.objects}

    ds.restore_preview(bpy.context)

    assert {o.name: o.hide_viewport for o in bpy.data.objects} == before


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_layout_edit_is_mirrored_into_the_persisted_collection(scene):
    """The edit reaches MoleculeListItem.domains, which is what save/undo read."""
    mid, chain_row, (pdb_min, pdb_max), letter = _single_chain_setup()
    mol = H.sm().molecules[mid]
    low = max(1, pdb_min)
    midpoint = (low + pdb_max) // 2

    _apply(chain_row, [("Head", low, midpoint, None),
                       ("Tail", midpoint + 1, pdb_max, None)])

    persisted = {(pg.domain_id, pg.start, pg.end) for pg in H.list_item(mid).domains}
    runtime = {(did, d.start, d.end)
               for did, d in _domains_on_chain(mol, letter).items()}
    assert persisted == runtime

    head_id = next(did for did, d in mol.domains.items() if d.name == "Head")
    chain_row = _row_by_id(chain_row.item_id)
    _apply(chain_row, [("Head", low, midpoint - 4, head_id),
                       ("Tail", midpoint + 1, pdb_max, None)])

    persisted = {pg.domain_id: (pg.start, pg.end) for pg in H.list_item(mid).domains}
    assert persisted[head_id] == (low, midpoint - 4), (
        "the range edit never reached the persisted collection, so it would be "
        "lost on save or undo")


@pytest.mark.integration
def test_chain_rename_through_the_splitter_persists(scene):
    """The dialog's chain-name field writes the same store the rename op uses."""
    mid, chain_row, _bounds, _letter = _single_chain_setup()
    row_id = chain_row.item_id

    # An empty layout is rejected, and the rename must not be applied either.
    # Reporting an ERROR from an operator makes bpy.ops raise, so the rejection
    # surfaces as RuntimeError rather than a returned {'CANCELLED'}.
    with pytest.raises(RuntimeError):
        bpy.ops.proteinblender.edit_chain_domains(
            'EXEC_DEFAULT', item_id=row_id, chain_name="Catalytic core",
            layout_json=json.dumps([]))
    assert "Catalytic core" not in (H.list_item(mid).chain_custom_names or ""), (
        "a rejected layout must not apply the chain rename either")

    mol = H.sm().molecules[mid]
    low, high = domain_layout.chain_residue_range(mol, _row_by_id(row_id).chain_id)
    payload = json.dumps([{"name": "Whole", "start": low, "end": high,
                           "domain_id": ""}])
    assert bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=row_id, chain_name="Catalytic core",
        layout_json=payload) == {'FINISHED'}

    stored = json.loads(H.list_item(mid).chain_custom_names or "{}")
    assert "Catalytic core" in stored.values()
    _build_outliner()
    assert _row_by_id(row_id).name == "Catalytic core"
