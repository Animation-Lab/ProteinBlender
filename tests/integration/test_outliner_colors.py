"""The colour swatches on the Protein Outliner's rows.

Every protein, chain and domain row carries a ``row_color`` swatch: it shows
the colour the item currently renders with, and editing it recolours the item
on the spot. These tests pin both directions of that binding.

Ground truth is kept independent of the code under test (see CLAUDE.md): the
colour an object "renders with" is read straight off its geometry-node graph -
whichever node feeds the Set Color group's Color input - never through the
addon's own ``get_object_color`` / ``seed_from_objects`` helpers, which are
exactly the code the swatches go through.
"""

import json

import bpy
import pytest

import helpers as H

from proteinblender.core import domain_layout


# --------------------------------------------------------------------------
# Independent colour read
# --------------------------------------------------------------------------

def _rendered_rgb(obj):
    """The RGB an object's node graph feeds into Set Color.

    Handles both wirings: the import path drives it from the "Color Common"
    group (RGBA "Carbon" socket), a recolour relinks it to a "Custom Combine
    Color" node (three float channels). Read raw, not via the addon helpers.
    """
    tree = next(m.node_group for m in obj.modifiers
                if m.type == 'NODES' and m.node_group)
    set_color = tree.nodes["Set Color"]
    color_input = next(s for s in set_color.inputs if "Color" in s.name)
    driver = next(l.from_node for l in tree.links if l.to_socket == color_input)
    if driver.name == "Custom Combine Color":
        return tuple(driver.inputs[c].default_value
                     for c in ("Red", "Green", "Blue"))
    return tuple(driver.inputs["Carbon"].default_value)[:3]


def _build_outliner():
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)


def _rows(item_type, parent_id=None):
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == item_type
            and (parent_id is None or it.parent_id == parent_id)
            and "_ref_" not in it.item_id]


def _chain_objects(mol, chain_row):
    from proteinblender.utils.chain_utils import get_chain_objects
    return get_chain_objects(mol, chain_row)


def _split_first_chain(mid, pieces=2):
    """Split a chain via the splitter's scripted path; returns the chain row id."""
    row = _rows("CHAIN", parent_id=mid)[0]
    row_id = row.item_id
    mol = H.sm().molecules[mid]
    low, high = domain_layout.chain_residue_range(mol, row.chain_id)
    spans = domain_layout.even_split(low, high, pieces)
    payload = json.dumps([{"name": f"Piece {i}", "start": a, "end": b,
                           "domain_id": ""}
                          for i, (a, b) in enumerate(spans, start=1)])
    assert bpy.ops.proteinblender.edit_chain_domains(
        'EXEC_DEFAULT', item_id=row_id, layout_json=payload) == {'FINISHED'}
    _build_outliner()
    return row_id


# --------------------------------------------------------------------------
# Seeding: the swatch shows what the item looks like
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_chain_swatches_seed_from_what_each_chain_renders_with(scene):
    """Each chain row's swatch matches its own objects' node-graph colour."""
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]

    chain_rows = _rows("CHAIN", parent_id=mid)
    assert len(chain_rows) >= 2

    seeded = 0
    for row in chain_rows:
        objects = _chain_objects(mol, row)
        if not objects:
            continue
        expected = _rendered_rgb(objects[0])
        assert tuple(row.row_color)[:3] == pytest.approx(expected, abs=1e-3), (
            f"chain {row.name}'s swatch does not show the chain's colour")
        seeded += 1
    assert seeded >= 2, "no chain swatch was actually checked"


@pytest.mark.integration
def test_protein_swatch_shows_neutral_grey_when_its_chains_disagree(scene):
    """A protein whose chains wear different colours cannot honestly show one.

    The swatch falls back to the same neutral grey the Visual Set-up dialogs
    use for "mixed" - showing one chain's colour as if it spoke for the rest
    is a lie the user would then commit by re-picking it.
    """
    from proteinblender.operators.visual_edit import MIXED_COLOR

    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]

    colors = {_rendered_rgb(d.object) for d in mol.domains.values() if d.object}
    assert len(colors) > 1, (
        "the fixture painted every chain alike, so 'mixed' cannot be observed")

    protein_row = next(it for it in bpy.context.scene.outliner_items
                       if it.item_type == "PROTEIN" and it.item_id == mid)
    assert tuple(protein_row.row_color)[:3] == pytest.approx(
        MIXED_COLOR[:3], abs=1e-4), (
        "a mixed-colour protein row should show the neutral 'mixed' grey")


# --------------------------------------------------------------------------
# Applying: editing a swatch recolours the item
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_editing_a_chain_swatch_recolors_every_object_of_the_chain(scene):
    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]

    chain_rows = _rows("CHAIN", parent_id=mid)
    target, other = chain_rows[0], chain_rows[1]
    other_before = _rendered_rgb(_chain_objects(mol, other)[0])

    picked = (0.9, 0.15, 0.1, 1.0)
    target.row_color = picked

    for obj in _chain_objects(mol, target):
        assert _rendered_rgb(obj) == pytest.approx(picked[:3], abs=1e-4), (
            f"{obj.name} did not take the colour picked on its chain row")
    assert _rendered_rgb(_chain_objects(mol, other)[0]) == pytest.approx(
        other_before, abs=1e-4), (
        "recolouring one chain repainted a different chain")
    # The swatch keeps showing what was picked (the re-seed agrees with it).
    target = next(it for it in bpy.context.scene.outliner_items
                  if it.item_id == target.item_id)
    assert tuple(target.row_color)[:3] == pytest.approx(picked[:3], abs=1e-3)


@pytest.mark.integration
def test_editing_the_protein_swatch_recolors_the_whole_protein(scene):
    """A pick on a mixed protein row resolves the mix - and un-greys itself."""
    from proteinblender.operators.visual_edit import MIXED_COLOR

    mid = H.import_local("4hhb.pdb", "4hhb")
    _build_outliner()
    mol = H.sm().molecules[mid]

    protein_row = next(it for it in bpy.context.scene.outliner_items
                       if it.item_type == "PROTEIN" and it.item_id == mid)
    assert tuple(protein_row.row_color)[:3] == pytest.approx(
        MIXED_COLOR[:3], abs=1e-4), "expected a mixed protein to start grey"

    picked = (0.1, 0.3, 0.85, 1.0)
    protein_row.row_color = picked

    for domain in mol.domains.values():
        if domain.object:
            assert _rendered_rgb(domain.object) == pytest.approx(
                picked[:3], abs=1e-4), (
                f"{domain.name} did not take the protein-wide colour")

    protein_row = next(it for it in bpy.context.scene.outliner_items
                       if it.item_type == "PROTEIN" and it.item_id == mid)
    assert tuple(protein_row.row_color)[:3] == pytest.approx(
        picked[:3], abs=1e-3), (
        "after resolving the mix the swatch should show the picked colour, "
        "not the grey placeholder")


@pytest.mark.integration
def test_editing_a_domain_swatch_recolors_only_that_domain(scene):
    mid = H.import_local("1ubq.pdb", "1ubq")
    _build_outliner()
    chain_row_id = _split_first_chain(mid, pieces=2)
    mol = H.sm().molecules[mid]

    domain_rows = _rows("DOMAIN", parent_id=chain_row_id)
    assert len(domain_rows) == 2
    target, sibling = domain_rows
    sibling_obj = bpy.data.objects[sibling.object_name]
    sibling_before = _rendered_rgb(sibling_obj)

    picked = (0.2, 0.8, 0.3, 1.0)
    target.row_color = picked

    assert _rendered_rgb(bpy.data.objects[target.object_name]) == pytest.approx(
        picked[:3], abs=1e-4), "the domain did not take its picked colour"
    assert _rendered_rgb(sibling_obj) == pytest.approx(sibling_before,
                                                       abs=1e-4), (
        "recolouring one domain repainted its sibling")
