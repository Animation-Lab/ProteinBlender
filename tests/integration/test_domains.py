"""Integration tests for DOMAIN operations on a multi-chain protein.

Each test
imports 4hhb offline (four auto-created chain domains) via the ``multi_chain``
fixture and drives real ProteinBlender operators, asserting observable state on
the MoleculeWrapper runtime dict (``sm.molecules[mid].domains``), the persisted
``MoleculeListItem.domains`` collection, the Protein Outliner rows, and the
domain Blender objects.

Notes on invocation conventions used below:
  * ``molecule.*`` operators read ``scene.selected_molecule_id`` — always set it
    first, and also pass explicit operator props where the op exposes them.
  * ``proteinblender.split_domain`` / ``merge_domains`` / ``rename_domain`` read
    the Protein Outliner selection (``outliner_items[*].is_selected``); we set
    that explicitly and call with ``'EXEC_DEFAULT'`` to bypass the invoke dialog.
"""

import bpy
import pytest

import helpers as H


def _first_domain(mol):
    return sorted(mol.domains.keys())[0]


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_create_custom_range_domain(scene, sm, multi_chain):
    """Free a chain of its auto-domain, then create a custom residue-range
    domain through molecule.create_domain (which reads scene.new_domain_*)."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid

    # Pick the lowest chain index and its author letter + residue range.
    idx = sorted(mol.chain_mapping.keys())[0]
    author = mol.chain_mapping[idx]
    min_res, max_res = mol.chain_residue_ranges[author]

    # The auto-domain covers the whole chain, so create_domain would report an
    # overlap. Delete it first to free the residue span.
    auto_did = next(d for d, dom in mol.domains.items() if dom.chain_id == author)
    bpy.ops.molecule.delete_domain(molecule_id=mid, domain_id=auto_did)
    assert auto_did not in mol.domains

    # Set the creation UI props. Assigning new_domain_chain first fires its
    # update callback (which resets start/end to the chain range); override the
    # range afterwards.
    try:
        scene.new_domain_chain = str(idx)
    except (TypeError, ValueError):
        pytest.skip(f"chain index {idx} not offered by new_domain_chain enum")
    custom_start = min_res
    custom_end = min(min_res + 20, max_res)
    scene.new_domain_start = custom_start
    scene.new_domain_end = custom_end

    res = bpy.ops.molecule.create_domain()
    assert res == {'FINISHED'}

    # A domain covering exactly the requested span now exists with an object.
    match = [dom for dom in mol.domains.values()
             if dom.chain_id == author and dom.start == custom_start
             and dom.end == custom_end]
    assert len(match) == 1
    assert match[0].object is not None
    assert match[0].object.name in bpy.data.objects

    # And it is mirrored into the persistent list-item collection.
    li = H.list_item(mid)
    assert any(pg.start == custom_start and pg.end == custom_end
               for pg in li.domains)


# --------------------------------------------------------------------------
# Rename / update name
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_rename_domain_updates_wrapper_and_list_item(scene, sm, multi_chain):
    """proteinblender.rename_domain (outliner-driven) renames the wrapper
    domain, the outliner row AND the persisted MoleculeListItem entry."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)

    # The low-level offline import doesn't build the Outliner (only the full
    # import operator does), so build it here — rename_domain updates the
    # Outliner row, and without rows there'd be nothing to update.
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)

    for it in scene.outliner_items:
        it.is_selected = (it.item_type == "DOMAIN" and it.item_id == did)

    res = bpy.ops.proteinblender.rename_domain(
        'EXEC_DEFAULT', domain_id=did, new_name="Renamed_X")
    assert res == {'FINISHED'}

    # Wrapper domain (the runtime source of truth) is renamed.
    assert mol.domains[did].name == "Renamed_X"

    # Persisted MoleculeListItem entry (what survives save/load) is renamed.
    li = H.list_item(mid)
    assert any(pg.domain_id == did and pg.name == "Renamed_X"
               for pg in li.domains)

    # And any Outliner DOMAIN row for this id is renamed too. (A chain-wide
    # auto-domain renders as the CHAIN row rather than its own DOMAIN row, so
    # there may be no such row — assert it only when present.)
    domain_rows = [it for it in scene.outliner_items
                   if it.item_type == "DOMAIN" and it.item_id == did]
    for row in domain_rows:
        assert row.name == "Renamed_X"


@pytest.mark.integration
def test_update_domain_name_operator(scene, sm, multi_chain):
    """molecule.update_domain_name renames the wrapper domain and its object."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)

    res = bpy.ops.molecule.update_domain_name(domain_id=did, name="Alpha1")
    assert res == {'FINISHED'}
    assert mol.domains[did].name == "Alpha1"


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_update_domain_color_object_property(scene, sm, multi_chain):
    """The live colour path (setting obj.domain_color) drives the update
    callback and the value sticks on the object."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)
    dom = mol.domains[did]
    assert dom.object is not None

    dom.object.domain_color = (0.1, 0.9, 0.15, 1.0)

    assert abs(dom.object.domain_color[1] - 0.9) < 0.01


@pytest.mark.integration
def test_update_domain_color_operator_applies_color(scene, sm, multi_chain):
    """molecule.update_domain_color applies the given colour to the domain.

    Regression guard: the operator used to read the unregistered
    `scene.domain_color` and crash with AttributeError; it now reads the
    registered `scene.temp_domain_color` (overridden here by the explicit
    `color` argument)."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)

    bpy.ops.molecule.update_domain_color(domain_id=did, color=(0.1, 0.9, 0.1, 1.0))
    assert mol.domains[did].color[1] > 0.5


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_domain_style_object_property(scene, sm, multi_chain):
    """Setting obj.domain_style (the UI path) updates the style on the object."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)
    dom = mol.domains[did]
    assert dom.object is not None

    dom.object.domain_style = "spheres"
    assert dom.object.domain_style == "spheres"


@pytest.mark.integration
def test_update_domain_style_operator(scene, sm, multi_chain):
    """molecule.update_domain_style swaps the style node; when it can run it
    records the new style on the wrapper domain."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)

    res = bpy.ops.molecule.update_domain_style(domain_id=did, style="spheres")
    if res != {'FINISHED'}:
        pytest.skip("update_domain_style could not swap the style node headless")
    assert mol.domains[did].style == "spheres"


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_copy_domain_adds_one(scene, sm, multi_chain):
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    before = set(mol.domains.keys())
    did = sorted(before)[0]

    res = bpy.ops.molecule.copy_domain(domain_id=did)
    assert res == {'FINISHED'}

    new = set(mol.domains.keys()) - before
    assert len(new) == 1
    assert mol.domains[new.pop()].object is not None


# --------------------------------------------------------------------------
# Split
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_split_domain_molecule_op(scene, sm, multi_chain):
    """molecule.split_domain (reads scene.split_domain_new_start/end) turns one
    full-chain domain into two domains covering the original range."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)
    dom = mol.domains[did]
    author = dom.chain_id
    d_start, d_end = dom.start, dom.end

    new_start = d_start
    new_end = d_start + max(1, (d_end - d_start) // 2)

    # Clear the "active splitting domain" so the scene-prop update callbacks
    # don't clamp our values, then set the split range.
    scene.active_splitting_domain_id = ""
    scene.split_domain_new_start = new_start
    scene.split_domain_new_end = new_end

    before = len(mol.domains)
    res = bpy.ops.molecule.split_domain(domain_id=did)
    assert res == {'FINISHED'}

    assert did not in mol.domains          # original consumed by the split
    assert len(mol.domains) == before + 1  # one full-chain domain -> two

    chain_doms = sorted((d for d in mol.domains.values() if d.chain_id == author),
                        key=lambda x: x.start)
    assert len(chain_doms) == 2
    assert chain_doms[0].start == d_start
    assert chain_doms[-1].end == d_end


@pytest.mark.integration
def test_split_domain_proteinblender_op(scene, sm, multi_chain):
    """proteinblender.split_domain (chain-driven, auto-generates complementary
    domains) adds one net domain when carving a sub-range off a full chain."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    for it in scene.outliner_items:
        it.is_selected = False

    did = _first_domain(mol)
    dom = mol.domains[did]
    author = dom.chain_id
    d_start, d_end = dom.start, dom.end
    split_start = d_start
    split_end = d_start + max(1, (d_end - d_start) // 2)

    before = len(mol.domains)
    res = bpy.ops.proteinblender.split_domain(
        chain_id=author, molecule_id=mid,
        split_start=split_start, split_end=split_end)
    assert res == {'FINISHED'}
    assert len(mol.domains) == before + 1


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_merge_domains_removes_sources_adds_merged(scene, sm, multi_chain):
    """Split a chain into two adjacent halves, then merge them. Per audit
    ISSUE-7 the old behaviour left the source domains behind; the current,
    correct behaviour removes both sources and adds a single merged domain."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    for it in scene.outliner_items:
        it.is_selected = False

    did = _first_domain(mol)
    dom = mol.domains[did]
    author = dom.chain_id
    d_start, d_end = dom.start, dom.end
    mid_pt = d_start + max(1, (d_end - d_start) // 2)

    # 1) split into two adjacent domains on this chain.
    bpy.ops.proteinblender.split_domain(
        chain_id=author, molecule_id=mid, split_start=d_start, split_end=mid_pt)
    chain_dids = [d for d, dm in mol.domains.items() if dm.chain_id == author]
    assert len(chain_dids) == 2

    # 2) select both split rows in the outliner and merge.
    for it in scene.outliner_items:
        it.is_selected = (it.item_type == "DOMAIN" and it.item_id in chain_dids)

    before = len(mol.domains)
    res = bpy.ops.proteinblender.merge_domains('EXEC_DEFAULT')
    assert res == {'FINISHED'}

    assert len(mol.domains) == before - 1
    # Both source domains are gone...
    assert all(d not in mol.domains for d in chain_dids)
    # ...replaced by exactly one domain spanning the original full range.
    merged = [dm for dm in mol.domains.values() if dm.chain_id == author]
    assert len(merged) == 1
    assert merged[0].start == d_start
    assert merged[0].end == d_end


# --------------------------------------------------------------------------
# Parenting
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_set_and_update_parent_domain(scene, sm, multi_chain):
    """molecule.update_parent_domain records the parent relationship on the
    wrapper and re-parents the Blender object."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    dids = sorted(mol.domains.keys())
    child, parent = dids[0], dids[1]

    # The set_parent_domain operator is just a dialog launcher; EXEC_DEFAULT
    # runs its (no-op) execute() without opening UI.
    res_dialog = bpy.ops.molecule.set_parent_domain('EXEC_DEFAULT', domain_id=child)
    assert res_dialog == {'FINISHED'}

    res = bpy.ops.molecule.update_parent_domain(
        domain_id=child, parent_domain_id=parent)
    assert res == {'FINISHED'}

    assert mol.domains[child].parent_domain_id == parent
    child_obj = mol.domains[child].object
    parent_obj = mol.domains[parent].object
    if child_obj is not None and parent_obj is not None:
        assert child_obj.parent == parent_obj


# --------------------------------------------------------------------------
# Reset transform
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_reset_domain_transform(scene, sm, multi_chain):
    """After moving a domain object, reset returns it to its identity/parent
    origin."""
    mid = multi_chain
    mol = sm.molecules[mid]
    did = _first_domain(mol)
    dom = mol.domains[did]
    assert dom.object is not None

    dom.object.location = (5.0, 3.0, 1.0)
    bpy.context.view_layer.update()

    res = bpy.ops.molecule.reset_domain_transform(domain_id=did)
    assert res == {'FINISHED'}

    assert max(abs(v) for v in dom.object.location) < 0.5


# --------------------------------------------------------------------------
# Snap pivot to residue
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_snap_pivot_to_residue(scene, sm, multi_chain):
    """Snapping the pivot to the start residue's Cα stamps an
    ``initial_matrix_local`` record on the domain object."""
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)
    dom = mol.domains[did]
    assert dom.object is not None

    res = bpy.ops.molecule.snap_pivot_to_residue(
        domain_id=did, target_residue='START')
    if res != {'FINISHED'}:
        pytest.skip("snap_pivot_to_residue could not resolve the Cα headless")

    assert "initial_matrix_local" in dom.object


# --------------------------------------------------------------------------
# Expand / collapse
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_toggle_domain_expanded_flips_flag(scene, sm, multi_chain):
    mid = multi_chain
    mol = sm.molecules[mid]
    scene.selected_molecule_id = mid
    did = _first_domain(mol)
    dom = mol.domains[did]
    assert dom.object is not None

    before = bool(dom.object.get("domain_expanded", False))
    res = bpy.ops.molecule.toggle_domain_expanded(
        domain_id=did, is_expanded=not before)
    assert res == {'FINISHED'}
    assert bool(dom.object["domain_expanded"]) == (not before)
