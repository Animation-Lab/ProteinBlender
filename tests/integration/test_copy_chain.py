"""Copying a chain from the Protein Outliner.

Regression guard for: copying a chain that had been split into domains copied
only its *first* domain. The outliner's chain row handed the chain's primary
domain id to ``molecule.copy_domain``, so "copy chain A" produced a partial
copy - and, because that copy no longer spanned the whole chain, it was
auto-parented to the original and shown as an extra domain row *inside* chain
A rather than as a chain copy.

Ground truth for what "the entire chain" covers is parsed straight out of
``tests/data/4hhb.pdb``, never from the add-on's own chain bookkeeping: an
expectation derived from ``chain_residue_ranges`` would move together with the
code under test and pass whatever the copy did.
"""

import bpy
import pytest

import helpers as H

CHAIN_LETTER = "A"


# --------------------------------------------------------------------------
# Independent ground truth + small readers
# --------------------------------------------------------------------------

def _pdb_chain_residue_range(filename, chain_letter):
    """(min, max) author residue number of a chain, read from the PDB text.

    Columns are the fixed PDB record layout: 22 is chainID, 23-26 resSeq.
    Both ATOM and HETATM count - a chain's range in this add-on spans its
    hetero residues too (4hhb chain A: 141 amino acids, HEM 142, waters to
    198).
    """
    residues = set()
    with open(H.data_path(filename)) as handle:
        for line in handle:
            if line.startswith(("ATOM", "HETATM")) and line[21] == chain_letter:
                residues.add(int(line[22:26]))
    if not residues:
        raise AssertionError(f"no chain {chain_letter} records in {filename}")
    return min(residues), max(residues)


def _rebuild_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _chain_row(mid, name):
    _rebuild_outliner()
    return next(it for it in bpy.context.scene.outliner_items
                if it.item_type == "CHAIN" and it.parent_id == mid
                and it.name == name)


def _rows_under(parent_id, item_type="DOMAIN"):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == item_type and it.parent_id == parent_id]


def _chain_token(mid, row):
    """The chain identifier the outliner row hands to a chain-level operator."""
    from proteinblender.utils.chain_utils import chain_token_from_item
    return chain_token_from_item(row)


def _domains_of(mol, chain_letter, copies=False):
    return {did: (d.start, d.end) for did, d in mol.domains.items()
            if str(d.chain_id) == chain_letter
            and bool(getattr(d, "is_copy", False)) is copies}


def _covered_residues(mol, domain_ids):
    return {res for did in domain_ids
            for res in range(mol.domains[did].start, mol.domains[did].end + 1)}


def _split_chain_in_two(scene, mol, mid, chain_letter):
    """Split the chain's whole-chain domain in half through the outliner's
    splitter, and return the resulting {domain_id: (start, end)}."""
    did, dom = next((d, x) for d, x in sorted(mol.domains.items())
                    if str(x.chain_id) == chain_letter)
    half = dom.start + (dom.end - dom.start) // 2
    scene.active_splitting_domain_id = ""
    assert H.split_domain_from_outliner(
        mid, dom.chain_id, dom.start, half, domain_id=did) == {'FINISHED'}
    pieces = _domains_of(mol, chain_letter)
    assert len(pieces) == 2, f"split should leave two domains, left {pieces}"
    return pieces


# --------------------------------------------------------------------------
# Copying a split chain
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_copy_split_chain_copies_every_domain(scene, sm, multi_chain):
    """The copy covers the whole chain, not just its first domain."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    chain_min, chain_max = _pdb_chain_residue_range("4hhb.pdb", CHAIN_LETTER)
    pieces = _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)

    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    before = set(mol.domains)
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    new = sorted(set(mol.domains) - before)
    assert sorted(mol.domains[d].start for d in new) == \
        sorted(s for s, _e in pieces.values())
    assert _covered_residues(mol, new) == set(range(chain_min, chain_max + 1)), \
        "the chain copy does not cover every residue of the chain"

    # Every piece is marked a copy, and they hang together as one chain copy.
    groups = {getattr(mol.domains[d], "copy_group_id", "") for d in new}
    assert all(mol.domains[d].is_copy for d in new)
    assert len(groups) == 1 and groups != {""}


@pytest.mark.integration
def test_copy_split_chain_keeps_each_domain_distinct(scene, sm, multi_chain):
    """Each domain is copied into its own object, so the copy stays split."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)
    originals = _domains_of(mol, CHAIN_LETTER)
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    before = set(mol.domains)
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    new = sorted(set(mol.domains) - before)
    original_objects = {mol.domains[d].object.name for d in originals}
    copy_objects = {mol.domains[d].object.name for d in new}
    assert len(copy_objects) == len(new), "copied domains share an object"
    assert not (copy_objects & original_objects), \
        "a copied domain reuses the original's object"

    # The copies mirror the originals' ranges one for one.
    assert sorted((mol.domains[d].start, mol.domains[d].end) for d in new) == \
        sorted(originals.values())


@pytest.mark.integration
def test_copy_split_chain_shows_as_one_chain_row(scene, sm, multi_chain):
    """The copy is a chain row of its own with the copied domains under it -
    it does not land inside the chain it was copied from."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    source_row_id = row.item_id
    chain_rows_before = len(_rows_under(mid, "CHAIN"))

    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    _rebuild_outliner()
    chain_rows = _rows_under(mid, "CHAIN")
    assert len(chain_rows) == chain_rows_before + 1, \
        "the chain copy should add exactly one chain row"

    # The source chain still shows its own two domains and nothing else.
    assert len(_rows_under(source_row_id)) == 2, \
        "the copy leaked into the chain it was copied from"

    # A real chain's row is "<molecule>_chain_<index>"; a copy's is its own
    # primary domain id.
    copy_row = next(it for it in chain_rows
                    if not it.item_id.startswith(f"{mid}_chain_"))
    assert copy_row.has_domains, "a split chain's copy is still split"
    copy_row.is_expanded = True
    _rebuild_outliner()
    copy_row = next(it for it in bpy.context.scene.outliner_items
                    if it.item_id == copy_row.item_id)
    assert len(_rows_under(copy_row.item_id)) == 2, \
        "the chain copy should list both copied domains"


@pytest.mark.integration
def test_copy_of_split_chain_renders_the_whole_chain(scene, sm, multi_chain,
                                                    tmp_path):
    """Pixel proof, independent of the add-on's own bookkeeping.

    The copy sits exactly where the chain it was copied from sits, so it must
    put the same amount of protein on screen. Half a chain covers visibly
    less - which is what the bug produced.
    """
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    originals = sorted(_split_chain_in_two(scene, mol, mid, CHAIN_LETTER))
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    before = set(mol.domains)
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}
    copies = sorted(set(mol.domains) - before)

    def coverage(domain_ids):
        for obj in bpy.data.objects:
            obj.hide_render = True
        for did in domain_ids:
            mol.domains[did].object.hide_render = False
        bpy.context.view_layer.update()
        return int(H.render_coverage(tmp_path).sum())

    whole_chain = coverage(originals)
    first_domain_only = coverage(originals[:1])
    the_copy = coverage(copies)

    assert whole_chain > 0, "the chain rendered nothing - test setup is broken"
    assert first_domain_only < whole_chain * 0.95, \
        "one domain covers as much as the chain; this fixture cannot show the bug"
    assert the_copy == pytest.approx(whole_chain, rel=0.05), \
        "the chain copy renders a different amount of protein than the chain"


# --------------------------------------------------------------------------
# Copying an unsplit chain (the behaviour that already worked)
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_copy_unsplit_chain_still_copies_the_whole_chain(scene, sm, multi_chain):
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    chain_min, chain_max = _pdb_chain_residue_range("4hhb.pdb", "B")
    row = _chain_row(mid, "Chain B")
    before = set(mol.domains)
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    new = sorted(set(mol.domains) - before)
    assert len(new) == 1
    assert (mol.domains[new[0]].start, mol.domains[new[0]].end) == \
        (chain_min, chain_max)

    _rebuild_outliner()
    copy_row = next(it for it in _rows_under(mid, "CHAIN")
                    if it.item_id == new[0])
    assert not copy_row.has_domains, \
        "an unsplit chain's copy is a single domain, so it has no children"


@pytest.mark.integration
def test_copying_a_chain_copy_copies_all_of_it(scene, sm, multi_chain):
    """Copy the copy: the second copy is as complete as the first."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    chain_min, chain_max = _pdb_chain_residue_range("4hhb.pdb", CHAIN_LETTER)
    _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    first_copy = sorted(_domains_of(mol, CHAIN_LETTER, copies=True))
    before = set(mol.domains)
    _rebuild_outliner()
    copy_row = next(it for it in _rows_under(mid, "CHAIN")
                    if it.item_id in first_copy)
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, copy_row)) == {'FINISHED'}

    second_copy = sorted(set(mol.domains) - before)
    assert len(second_copy) == len(first_copy)
    # Copy numbers do not stack: the copy of "Chain A 1" is "Chain A 2".
    assert mol.domains[first_copy[0]].copy_group_name == f"Chain {CHAIN_LETTER} 1"
    assert mol.domains[second_copy[0]].copy_group_name == f"Chain {CHAIN_LETTER} 2"
    assert _covered_residues(mol, second_copy) == \
        set(range(chain_min, chain_max + 1))
    # It is a copy OF THE COPY, not a second copy of the source chain.
    assert {mol.domains[d].original_domain_id for d in second_copy} == \
        set(first_copy)
    assert len({mol.domains[d].copy_group_id for d in second_copy}) == 1
    assert mol.domains[second_copy[0]].copy_group_id != \
        mol.domains[first_copy[0]].copy_group_id


@pytest.mark.integration
def test_copying_one_piece_of_a_copy_stays_in_that_copy(scene, sm, multi_chain):
    """A domain copied from inside a chain copy joins that copy, rather than
    surfacing under the chain the copy came from."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    piece = sorted(_domains_of(mol, CHAIN_LETTER, copies=True))[0]
    group = mol.domains[piece].copy_group_id
    before = set(mol.domains)
    # The Copy button on a DOMAIN row.
    assert bpy.ops.molecule.copy_domain(domain_id=piece) == {'FINISHED'}
    new = (set(mol.domains) - before).pop()

    assert mol.domains[new].copy_group_id == group
    _rebuild_outliner()
    copy_row = next(it for it in _rows_under(mid, "CHAIN")
                    if it.item_id in _domains_of(mol, CHAIN_LETTER, copies=True))
    copy_row.is_expanded = True
    _rebuild_outliner()
    assert new in {it.item_id for it in _rows_under(copy_row.item_id)}, \
        "the copied piece did not land under the chain copy it came from"


# --------------------------------------------------------------------------
# Naming a chain copy
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_renaming_a_chain_copy_renames_the_copy_only(scene, sm, multi_chain):
    """The copy's edit pencil names the copy.

    A chain copy's row reports the chain_id of the chain it came from, so a
    rename written to the molecule's chain-name map would land on (or beside)
    the original. It belongs on the copy group.
    """
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    _split_chain_in_two(scene, mol, mid, CHAIN_LETTER)
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}

    _rebuild_outliner()
    copies = _domains_of(mol, CHAIN_LETTER, copies=True)
    copy_row = next(it for it in _rows_under(mid, "CHAIN") if it.item_id in copies)
    assert bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', target_item_id=copy_row.item_id, item_type='CHAIN',
        new_name="Second Alpha") == {'FINISHED'}

    _rebuild_outliner()
    names = {it.item_id: it.name for it in _rows_under(mid, "CHAIN")}
    assert names[copy_row.item_id] == "Second Alpha"
    assert names[f"{mid}_chain_0"] == f"Chain {CHAIN_LETTER}", \
        "renaming the copy renamed the chain it was copied from"


# --------------------------------------------------------------------------
# Deleting a chain copy
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_deleting_a_chain_copy_removes_all_of_it(scene, sm, multi_chain):
    """The copy's Delete button removes the whole copy and leaves the
    original chain untouched."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    originals = set(_split_chain_in_two(scene, mol, mid, CHAIN_LETTER))
    row = _chain_row(mid, f"Chain {CHAIN_LETTER}")
    assert bpy.ops.molecule.copy_chain(
        molecule_id=mid, chain_id=_chain_token(mid, row)) == {'FINISHED'}
    copies = set(_domains_of(mol, CHAIN_LETTER, copies=True))
    assert len(copies) == 2

    _rebuild_outliner()
    copy_row = next(it for it in _rows_under(mid, "CHAIN")
                    if it.item_id in copies)
    assert bpy.ops.molecule.delete_chain(
        'EXEC_DEFAULT', molecule_id=mid,
        chain_id=_chain_token(mid, copy_row)) == {'FINISHED'}

    assert set(_domains_of(mol, CHAIN_LETTER, copies=True)) == set()
    assert set(_domains_of(mol, CHAIN_LETTER)) == originals, \
        "deleting the copy disturbed the chain it was copied from"
