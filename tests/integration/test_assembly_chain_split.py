"""Splitting a chain of a deposited assembly cuts every copy of it.

Ann (2026-11-10, Alpha 1.2.5, Blender 5.2.3), on 1STM's complete icosahedral
assembly: "after I clicked OK, only one copy of Chain B was split; the other
copies in the assembly were unaffected. The resulting domains also overlap
each other and don't update when I change the cutting point." And: "once I
realized all the chains, only the second domains were kept. The first domains
disappeared in all the Chain B. I also lost the colors I applied."

Ground truth is the file and what Blender draws. The fixture notes
(``tests/data/assembly-fixtures.md``) say assembly 1 places chain B 12 times,
and the mmCIF itself lists chain B's C-alpha residues (17-157). So every one
of those residues must be drawn exactly 12 times, at 12 different places,
whatever the domains are: fewer is a lost copy, more is two pieces drawing
the same atoms (an overlap). The drawn atoms are read off the evaluated
depsgraph, never asked of the assembly or domain code.
"""

import gzip
import json

import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration

#: Chain B's placements in 1STM assembly 1 (tests/data/assembly-fixtures.md).
COPIES = 12
# Chain B's amino acids run 17-157 in 1stm; its waters (66 of them, up to
# 223) are not chain residues.
CHAIN_B_END = 157
FIRST_CUT = 100
SECOND_CUT = 150


def _file_alpha_residues(chain="B"):
    """Author residue numbers of the chain's C-alpha atoms, read from the mmCIF."""
    header, rows = [], []
    with gzip.open(H.data_path("1stm.cif.gz"), "rt") as handle:
        for line in handle:
            if line.startswith("_atom_site."):
                header.append(line.split(".", 1)[1].strip())
            elif header and line.startswith("ATOM"):
                rows.append(line.split())
    column = {name: i for i, name in enumerate(header)}
    return sorted({int(row[column["auth_seq_id"]]) for row in rows
                   if row[column["auth_asym_id"]] == chain
                   and row[column["label_atom_id"]] == "CA"})


def _capsid():
    mid = H.import_local("1stm.cif.gz", "1STM")
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=mid, source="BIOLOGICAL", assembly_id="1") == {"FINISHED"}
    return H.sm().molecules[mid]


def _chain_row(molecule, name="Chain B"):
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    return next(item for item in bpy.context.scene.outliner_items
                if item.item_type == "CHAIN" and item.parent_id == molecule.identifier
                and item.name == name)


def _pieces(molecule, chain="B"):
    return sorted((d for d in molecule.domains.values() if str(d.chain_id) == chain),
                  key=lambda d: d.start)


def _piece_ids(molecule, chain="B"):
    """The keys the molecule files its chain's domains under, in residue order."""
    return [key for key, d in sorted(molecule.domains.items(), key=lambda kv: kv[1].start)
            if str(d.chain_id) == chain]


def _splitter(molecule, ranges, domain_ids=None):
    row = _chain_row(molecule)
    domain_ids = domain_ids or [""] * len(ranges)
    layout = json.dumps([{"name": "", "start": start, "end": end, "domain_id": did}
                         for (start, end), did in zip(ranges, domain_ids)])
    return bpy.ops.proteinblender.edit_chain_domains(
        "EXEC_DEFAULT", item_id=row.item_id, layout_json=layout, chain_name=row.name)


def _as_spheres():
    """Draw every protein object as atoms, so its C-alpha atoms are points."""
    from proteinblender.core import visual_style

    for molecule in H.sm().molecules.values():
        for domain in molecule.domains.values():
            if domain.object is not None:
                visual_style.apply_style_to_object(domain.object, "spheres",
                                                   sync_morphsets=False)
    bpy.context.view_layer.update()


def _drawn_alpha_carbons(chain_index):
    """(res_id, x, y, z, r, g, b) for every drawn C-alpha of one chain, in the scene.

    Read from every evaluated point cloud - instanced copies and real objects
    alike - with each entry's own world matrix. Positions in Angstrom.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    rows = []
    for entry in depsgraph.object_instances:
        if entry.object.type != "POINTCLOUD":
            continue
        data = entry.object.data
        attrs = data.attributes
        if not all(name in attrs for name in ("res_id", "is_alpha_carbon", "chain_id")):
            continue
        count = len(data.points)
        position = np.empty(count * 3)
        alpha = np.empty(count, dtype=bool)
        residue = np.empty(count, dtype=np.int32)
        chain = np.empty(count, dtype=np.int32)
        attrs["position"].data.foreach_get("vector", position)
        attrs["is_alpha_carbon"].data.foreach_get("value", alpha)
        attrs["res_id"].data.foreach_get("value", residue)
        attrs["chain_id"].data.foreach_get("value", chain)
        color = np.zeros(count * 4)
        if "Color" in attrs:
            attrs["Color"].data.foreach_get("color", color)
        color = color.reshape(-1, 4)
        matrix = np.array(entry.matrix_world)
        world = position.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        keep = alpha & (chain == chain_index)
        for r, xyz, rgba in zip(residue[keep], world[keep] / 0.01, color[keep]):
            rows.append((int(r), *xyz, *rgba[:3]))
    return np.array(rows).reshape(-1, 7)


def _chain_index(molecule, letter="B"):
    return next(int(index) for index, author in molecule.chain_mapping.items()
                if str(author) == letter)


def _assert_every_residue_drawn_once_per_copy(molecule, residues):
    drawn = _drawn_alpha_carbons(_chain_index(molecule))
    counts = {r: int((drawn[:, 0] == r).sum()) for r in residues}
    wrong = {r: n for r, n in counts.items() if n != COPIES}
    assert not wrong, (
        f"each chain B residue should be drawn {COPIES} times (once per copy); "
        f"these are not: {dict(list(wrong.items())[:8])} ({len(wrong)} residues)")
    extra = sorted(set(drawn[:, 0].astype(int)) - set(residues))
    assert not extra, f"chain B residues drawn that the file has no C-alpha for: {extra[:8]}"
    for r in (residues[0], residues[-1]):
        spots = drawn[drawn[:, 0] == r][:, 1:4]
        gaps = np.linalg.norm(spots[:, None] - spots[None], axis=2) + np.eye(len(spots)) * 1e9
        assert gaps.min() > 1.0, f"residue {r}: two copies drawn on top of each other"
    return drawn


def test_the_file_places_chain_b_in_every_copy():
    """The ground truth this module stands on, checked against the fixture."""
    residues = _file_alpha_residues()
    assert residues[0] == 17 and residues[-1] == 157 and len(residues) == 141


def test_splitting_chain_b_cuts_all_twelve_copies(scene):
    molecule = _capsid()
    residues = _file_alpha_residues()
    _as_spheres()
    _assert_every_residue_drawn_once_per_copy(molecule, residues)

    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    _as_spheres()
    assert [(d.start, d.end) for d in _pieces(molecule)] == [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]
    _assert_every_residue_drawn_once_per_copy(molecule, residues)


def test_moving_the_cut_keeps_every_copy_of_both_pieces(scene):
    """Ann's "don't update when I change the cutting point"."""
    molecule = _capsid()
    residues = _file_alpha_residues()
    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    ids = _piece_ids(molecule)

    assert _splitter(molecule, [(17, SECOND_CUT), (SECOND_CUT + 1, CHAIN_B_END)], ids) == {"FINISHED"}
    pieces = _pieces(molecule)
    assert [(d.start, d.end) for d in pieces] == [(17, SECOND_CUT), (SECOND_CUT + 1, CHAIN_B_END)]
    assert _piece_ids(molecule) == ids, "re-cutting replaced the domains"
    _as_spheres()
    _assert_every_residue_drawn_once_per_copy(molecule, residues)


def _paint(molecule, domain_id, rgba):
    """Color a domain as the user does: its swatch on the PB Outliner row."""
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    row = next(item for item in bpy.context.scene.outliner_items
               if item.item_type == "DOMAIN" and item.item_id == domain_id)
    row.row_color = rgba


def _realize(molecule):
    from proteinblender.operators.assembly_realize import realize_assembly
    result = realize_assembly(bpy.context, molecule)
    assert result, "nothing was realized"
    return result


RED, BLUE = (1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)


@pytest.mark.parametrize("recut", [False, True], ids=["split", "split-and-recut"])
def test_realizing_a_split_chain_keeps_both_pieces_and_their_colors(scene, recut):
    """Ann's "only the second domains were kept ... I also lost the colors"."""
    molecule = _capsid()
    residues = _file_alpha_residues()
    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    cut = FIRST_CUT
    if recut:
        ids = _piece_ids(molecule)
        assert _splitter(molecule, [(17, SECOND_CUT), (SECOND_CUT + 1, CHAIN_B_END)], ids) == {"FINISHED"}
        cut = SECOND_CUT
    first, second = _piece_ids(molecule)
    _paint(molecule, first, RED)
    _paint(molecule, second, BLUE)
    _as_spheres()
    before = {letter: _drawn_alpha_carbons(_chain_index(molecule, letter))[:, :4]
              for letter in "ABCDE"}

    _realize(molecule)
    _as_spheres()
    drawn = _assert_every_residue_drawn_once_per_copy(molecule, residues)
    # Realizing turns drawn copies into real ones where they stood: no atom moves.
    for letter, was in before.items():
        now = _drawn_alpha_carbons(_chain_index(molecule, letter))[:, :4]
        assert now.shape == was.shape, (letter, was.shape, now.shape)
        for residue in (17, 100, 157):
            a = was[was[:, 0] == residue][:, 1:]
            b = now[now[:, 0] == residue][:, 1:]
            gaps = np.linalg.norm(a[:, None] - b[None], axis=2).min(axis=1)
            assert gaps.max() < 0.5, (
                f"chain {letter} residue {residue}: a copy moved {gaps.max():.1f} A when realized")

    # Every copy of chain B is two pieces, each in the color it was painted.
    low = drawn[drawn[:, 0] <= cut][:, 4:7]
    high = drawn[drawn[:, 0] > cut][:, 4:7]
    assert np.allclose(low, RED[:3], atol=0.02), "a first piece lost its color"
    assert np.allclose(high, BLUE[:3], atol=0.02), "a second piece lost its color"
    assert len(H.sm().molecules) == COPIES, "the capsid should realize as one protein per copy"
    for copy in H.sm().molecules.values():
        assert [(d.start, d.end) for d in _pieces(copy)] == [(17, cut), (cut + 1, CHAIN_B_END)], (
            f"{copy.identifier} does not have both pieces of chain B")
        # Ann: "the domain split options are only available for the first set
        # of chains". Each copy is a protein of its own, so every chain row is
        # a real chain the Domain Splitter edits, not a chain copy.
        assert not any(getattr(d, "is_copy", False) for d in copy.domains.values()), (
            f"{copy.identifier} came out as chain copies, which cannot be split")


def _drawn_residues(molecule, letter="B"):
    _as_spheres()
    return _drawn_alpha_carbons(_chain_index(molecule, letter))[:, 0].astype(int)


def _delete(molecule, domain_id):
    return bpy.ops.molecule.delete_domain(
        "EXEC_DEFAULT", domain_id=domain_id, molecule_id=molecule.identifier)


@pytest.mark.parametrize("built", [False, True], ids=["protein", "assembly"])
def test_deleting_a_piece_takes_its_atoms_off_the_screen(scene, built):
    """Ann's "if I deleted the two domains, entire Chain B will be removed from
    the list, although they still appear in the viewport".

    A deleted domain's atoms fell back to the protein's own object, which
    draws whatever no domain covers, so they stayed on screen with no row.
    """
    molecule = _capsid() if built else H.sm().molecules[H.import_local("1stm.cif.gz", "1STM")]
    copies = COPIES if built else 1
    residues = _file_alpha_residues()
    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    first, second = _piece_ids(molecule)

    assert _delete(molecule, first) == {"FINISHED"}
    drawn = _drawn_residues(molecule)
    assert not (drawn <= FIRST_CUT).any(), "the deleted piece is still drawn"
    kept = [r for r in residues if r > FIRST_CUT]
    assert all((drawn == r).sum() == copies for r in kept), "the other piece is not drawn as before"

    assert _delete(molecule, second) == {"FINISHED"}
    assert len(_drawn_residues(molecule)) == 0, "chain B is still drawn with no row left for it"
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    assert not [item for item in bpy.context.scene.outliner_items
                if item.parent_id == molecule.identifier and item.name == "Chain B"]
    # The rest of the protein is untouched.
    for letter in "ACDE":
        assert len(_drawn_residues(molecule, letter)) == 141 * copies, f"chain {letter}"


def test_deleted_atoms_stay_gone_after_reopening_and_in_a_duplicate(scene, tmp_path):
    molecule = H.sm().molecules[H.import_local("1stm.cif.gz", "1STM")]
    mid = molecule.identifier
    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    assert _delete(molecule, _piece_ids(molecule)[0]) == {"FINISHED"}

    path = str(tmp_path / "deleted-piece.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    H.scene_manager_module()._deferred_reconstruct_on_load()
    molecule = H.sm().molecules[mid]
    drawn = _drawn_residues(molecule)
    assert len(drawn) and not (drawn <= FIRST_CUT).any(), "reopening brought the deleted piece back"

    assert bpy.ops.molecule.duplicate_protein("EXEC_DEFAULT", molecule_id=mid) == {"FINISHED"}
    assert len(H.sm().molecules) == 2
    for copy in H.sm().molecules.values():
        drawn = _drawn_residues(copy)
        # Both proteins draw chain B residue 101 on, once each, and nothing before.
        assert not (drawn <= FIRST_CUT).any(), f"{copy.identifier} draws the deleted piece"
    both = _drawn_residues(molecule)
    assert (both == FIRST_CUT + 1).sum() == 2


def test_a_duplicate_of_a_split_protein_stands_exactly_on_it(scene):
    """Duplicate makes the copy where its source is, every atom on its twin.

    A split gives each piece a pivot of its own, and the copy's pieces were
    made with the default pivot instead while keeping the source's transform,
    so each copied piece was drawn off by the difference - ~30 A here. That is
    also why Realize Copies scattered a split chain across the capsid.
    """
    molecule = H.sm().molecules[H.import_local("1stm.cif.gz", "1STM")]
    assert _splitter(molecule, [(17, FIRST_CUT), (FIRST_CUT + 1, CHAIN_B_END)]) == {"FINISHED"}
    _as_spheres()
    source = {letter: _drawn_alpha_carbons(_chain_index(molecule, letter))[:, :4]
              for letter in "AB"}

    assert bpy.ops.molecule.duplicate_protein(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}
    _as_spheres()
    for letter, alone in source.items():
        both = _drawn_alpha_carbons(_chain_index(molecule, letter))[:, :4]
        assert len(both) == 2 * len(alone), letter
        for residue in (17, FIRST_CUT, FIRST_CUT + 1, 157):
            spots = both[both[:, 0] == residue][:, 1:]
            assert len(spots) == 2
            gap = float(np.linalg.norm(spots[0] - spots[1]))
            assert gap < 0.01, f"chain {letter} residue {residue}: the copy is {gap:.1f} A off"


def test_realizing_part_of_a_protein_keeps_a_split_chain_in_place_and_color(scene):
    """1STM assembly 4 repeats chain A three times and the rest once, so
    realizing makes chain copies inside the protein instead of proteins
    (``_realize_within_the_protein``). Split and painted, chain A's copies
    must stand where they were drawn, in the pieces' colors."""
    mid = H.import_local("1stm.cif.gz", "1STM")
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=mid, source="BIOLOGICAL", assembly_id="4") == {"FINISHED"}
    molecule = H.sm().molecules[mid]
    row = _chain_row(molecule, "Chain A")
    layout = json.dumps([{"name": "", "start": 17, "end": FIRST_CUT, "domain_id": ""},
                         {"name": "", "start": FIRST_CUT + 1, "end": CHAIN_B_END, "domain_id": ""}])
    assert bpy.ops.proteinblender.edit_chain_domains(
        "EXEC_DEFAULT", item_id=row.item_id, layout_json=layout,
        chain_name=row.name) == {"FINISHED"}
    first, second = _piece_ids(molecule, "A")
    _paint(molecule, first, RED)
    _paint(molecule, second, BLUE)
    _as_spheres()
    index = _chain_index(molecule, "A")
    before = _drawn_alpha_carbons(index)
    assert (before[:, 0] == 17).sum() == 3, "assembly 4 places chain A three times"

    result = _realize(molecule)
    assert not result.proteins and result.domains, "expected chain copies inside the protein"
    _as_spheres()
    after = _drawn_alpha_carbons(index)
    assert after.shape == before.shape
    for residue in (17, FIRST_CUT, FIRST_CUT + 1, 157):
        a = before[before[:, 0] == residue][:, 1:4]
        b = after[after[:, 0] == residue][:, 1:4]
        gaps = np.linalg.norm(a[:, None] - b[None], axis=2).min(axis=1)
        assert gaps.max() < 0.5, f"residue {residue}: a copy moved {gaps.max():.1f} A"
    assert np.allclose(after[after[:, 0] <= FIRST_CUT][:, 4:7], RED[:3], atol=0.02), \
        "a copy of the first piece lost its color"
    assert np.allclose(after[after[:, 0] > FIRST_CUT][:, 4:7], BLUE[:3], atol=0.02), \
        "a copy of the second piece lost its color"
