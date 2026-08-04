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
