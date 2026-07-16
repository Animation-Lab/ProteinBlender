"""Integration tests for PROTEIN-level operations.

Drives the real ProteinBlender operators against a headless Blender scene and
asserts observable outcomes (scene manager singleton, bpy.data objects,
MoleculeListItem UI rows).

Every test is self-contained: the autouse ``_clean_scene`` fixture (conftest)
hands each test an empty scene, and the ``single_chain`` / ``multi_chain``
fixtures re-import a fresh protein per test.
"""

import bpy
import pytest

import helpers as H

# Actual valid style enum values, read from the addon's single source of truth
# so this test tracks the real list rather than a hard-coded copy.
from proteinblender.utils.molecularnodes.style import STYLE_ITEMS

STYLE_VALUES = [item[0] for item in STYLE_ITEMS]


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_import_single_chain_registers(scene, sm):
    """Offline single-chain import registers a wrapper, a Blender object and a
    UI list item."""
    mol_id = H.import_local("1ubq.pdb", "1ubq")

    assert mol_id in sm.molecules
    mol = sm.molecules[mol_id]
    assert mol.object is not None
    assert mol.object.name in bpy.data.objects
    assert H.list_item(mol_id) is not None


@pytest.mark.integration
def test_import_multi_chain_auto_creates_four_domains(scene, sm, multi_chain):
    """4hhb has four chains, so import auto-creates one domain per chain."""
    mol = sm.molecules[multi_chain]
    assert len(mol.domains) == 4

    # The auto-created domains are also mirrored into the persistent
    # MoleculeListItem.domains collection (survives save/load).
    li = H.list_item(multi_chain)
    assert li is not None
    assert len(li.domains) == 4


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("style", STYLE_VALUES)
def test_change_style_updates_list_item(scene, sm, single_chain, style):
    """Setting scene.molecule_style for the selected molecule re-styles it and
    mirrors the new style into the persistent list item, for EVERY valid enum
    value."""
    scene.selected_molecule_id = single_chain

    # Blender only fires the property update callback on an actual value
    # change, so step through a sentinel first to guarantee a transition into
    # `style` (otherwise a target equal to the current value would no-op and
    # the list item would never be mirrored).
    sentinel = "cartoon" if style != "cartoon" else "spheres"
    scene.molecule_style = sentinel
    scene.molecule_style = style

    li = H.list_item(single_chain)
    assert li is not None
    assert li.style == style


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_domain_color_property_sticks(scene, sm, multi_chain):
    """Setting a domain object's `domain_color` (the live colour path used by
    the UI) takes effect and reads back."""
    mol = sm.molecules[multi_chain]
    did = sorted(mol.domains.keys())[0]
    dom = mol.domains[did]
    assert dom.object is not None

    dom.object.domain_color = (1.0, 0.2, 0.2, 1.0)

    assert abs(dom.object.domain_color[0] - 1.0) < 0.01
    assert abs(dom.object.domain_color[1] - 0.2) < 0.01


# --------------------------------------------------------------------------
# Duplicate
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_duplicate_protein_adds_one_molecule(scene, sm, single_chain):
    """Duplicating a protein registers exactly one new molecule in the scene
    manager."""
    before = set(sm.molecules.keys())

    res = bpy.ops.molecule.duplicate_protein(molecule_id=single_chain)
    assert res == {'FINISHED'}

    after = set(sm.molecules.keys())
    new = after - before
    assert len(new) == 1
    # The duplicate must have its own Blender object.
    new_id = new.pop()
    assert sm.molecules[new_id].object is not None


# --------------------------------------------------------------------------
# Visibility
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_toggle_visibility_flips_hide_flag(scene, sm, single_chain):
    obj = sm.molecules[single_chain].object
    assert obj is not None
    before = obj.hide_viewport

    res = bpy.ops.molecule.toggle_visibility(molecule_id=single_chain)
    assert res == {'FINISHED'}
    assert obj.hide_viewport != before

    # Toggling again restores the original state.
    bpy.ops.molecule.toggle_visibility(molecule_id=single_chain)
    assert obj.hide_viewport == before


# --------------------------------------------------------------------------
# Centre
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_center_protein_moves_to_origin(scene, sm, single_chain):
    obj = sm.molecules[single_chain].object
    assert obj is not None
    obj.location = (5.0, 3.0, 1.0)
    bpy.context.view_layer.update()

    res = bpy.ops.molecule.center_protein(molecule_id=single_chain)
    assert res == {'FINISHED'}

    assert max(abs(v) for v in obj.location) < 1.0


# --------------------------------------------------------------------------
# Delete
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_delete_protein_removes_everything(scene, sm, single_chain):
    """Deleting a protein removes the wrapper, its Blender object and the UI
    list item."""
    obj_name = sm.molecules[single_chain].object.name
    assert single_chain in sm.molecules

    res = bpy.ops.molecule.delete(molecule_id=single_chain)
    assert res == {'FINISHED'}

    assert single_chain not in sm.molecules
    assert bpy.data.objects.get(obj_name) is None
    assert H.list_item(single_chain) is None


@pytest.mark.integration
def test_delete_chain_removes_only_that_chain(scene, sm, multi_chain):
    """Deleting one chain of a 4-chain protein removes that chain's domain(s)
    and leaves the other three chains intact."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    assert len(mol.domains) == 4

    # Drive the deletion from a real Protein Outliner CHAIN row.
    chain_item = next(it for it in scene.outliner_items
                      if it.item_type == "CHAIN" and it.parent_id == mid)
    chain_index = chain_item.chain_id
    # Resolve the author letter this outliner index maps to, so we can assert
    # the right domain disappeared (index vs. letter bridge).
    author = mol.chain_mapping.get(
        int(chain_index) if str(chain_index).isdigit() else chain_index,
        str(chain_index))

    res = bpy.ops.molecule.delete_chain(chain_id=chain_index, molecule_id=mid)
    assert res == {'FINISHED'}

    assert len(mol.domains) == 3
    # No surviving domain belongs to the deleted chain.
    assert all(dom.chain_id != author for dom in mol.domains.values())


# --------------------------------------------------------------------------
# Duplicate must copy the domain structure exactly (regression)
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_duplicate_preserves_domain_structure(scene, sm):
    """Duplicating a freshly imported protein must replicate its domains
    exactly — it must NOT auto-fill spurious degenerate (0-0) domains that
    read as "Chain A split into two domains".

    Regression: importing 1atn and clicking Copy in the PB Outliner produced a
    copy whose Chain A had an extra 0-0 domain alongside the real 1-375 one,
    because the duplicate path called create_domain() (auto_fill_chain=True) to
    copy each domain instead of replicating it verbatim.
    """
    from collections import Counter

    mid = H.import_local("1atn.pdb", "1atn")
    orig = sm.molecules[mid]
    orig_counts = Counter(d.chain_id for d in orig.domains.values())
    # Sanity: a fresh import gives exactly one domain per chain.
    assert all(n == 1 for n in orig_counts.values()), \
        f"unexpected starting structure: {dict(orig_counts)}"

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=mid)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]
    copy = sm.molecules[copy_id]

    # No degenerate / zero-length domain was fabricated on the copy.
    degenerate = [(d.chain_id, d.start, d.end) for d in copy.domains.values()
                  if (d.start == 0 and d.end == 0) or d.end < d.start]
    assert not degenerate, f"copy has spurious degenerate domains: {degenerate}"

    # The copy replicates the source's per-chain domain structure exactly.
    copy_counts = Counter(d.chain_id for d in copy.domains.values())
    assert copy_counts == orig_counts, (
        f"copy domain structure differs from source: "
        f"orig={dict(orig_counts)} copy={dict(copy_counts)}")

    # And the copy did not mutate the original.
    assert Counter(d.chain_id for d in orig.domains.values()) == orig_counts


# --------------------------------------------------------------------------
# Network import (RCSB fetch) — only runs when explicitly selected.
# --------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.network
def test_import_pdb_network(scene, sm):
    mol_id = H.import_pdb("1aki")
    assert mol_id in sm.molecules
    assert sm.molecules[mol_id].object is not None
    assert H.list_item(mol_id) is not None
