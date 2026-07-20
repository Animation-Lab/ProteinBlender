"""Integration tests for PROTEIN-level operations.

Drives the real ProteinBlender operators against a headless Blender scene and
asserts observable outcomes (scene manager singleton, bpy.data objects,
MoleculeListItem UI rows).

Every test is self-contained: the autouse ``_clean_scene`` fixture (conftest)
hands each test an empty scene, and the ``single_chain`` / ``multi_chain``
fixtures re-import a fresh protein per test.
"""

import contextlib
import logging

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

def _attr_store_owner():
    """The class in databpy's MRO that actually defines store_named_attribute.

    Patching the defining class rather than ``BlenderObject`` keeps monkeypatch's
    teardown from leaving a shadowing override behind on the subclass.
    """
    import databpy

    return next(c for c in databpy.BlenderObject.__mro__
                if "store_named_attribute" in c.__dict__)


class _RecordCatcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def _capture_addon_logs():
    """Capture log records emitted under the ``proteinblender`` logger.

    pytest's ``caplog`` attaches to the ROOT logger and only sees records that
    propagate there. The addon deliberately sets ``proteinblender.propagate =
    False`` and installs its own stderr handler (so Blender's console shows add-
    on logs exactly once), which means caplog captures NOTHING the add-on logs —
    a test relying on caplog for add-on warnings is a false negative, green or
    red for the wrong reason. Attach directly to the ``proteinblender`` logger
    instead, which is where the add-on actually emits, regardless of
    propagation.
    """
    logger = logging.getLogger("proteinblender")
    catcher = _RecordCatcher()
    prev_level = logger.level
    if prev_level > logging.WARNING or prev_level == logging.NOTSET:
        logger.setLevel(logging.WARNING)
    logger.addHandler(catcher)
    try:
        yield catcher
    finally:
        logger.removeHandler(catcher)
        logger.setLevel(prev_level)


def _break_attribute(monkeypatch, attr):
    """Make writing ``attr`` raise, leaving every other attribute alone."""
    owner = _attr_store_owner()
    original = owner.store_named_attribute

    def exploding(self, data, name, *args, **kwargs):
        if name == attr:
            raise ValueError(f"induced failure writing {name}")
        return original(self, data, name, *args, **kwargs)

    monkeypatch.setattr(owner, "store_named_attribute", exploding)


@pytest.mark.integration
@pytest.mark.parametrize("attr", ["chain_id", "res_id", "is_alpha_carbon"])
def test_import_aborts_when_a_critical_attribute_cannot_be_written(
        scene, sm, monkeypatch, capsys, attr):
    """A critical attribute that fails to write must abort the import.

    Domains select on chain_id + res_id in geometry nodes and pivots resolve
    alpha carbons through is_alpha_carbon. Missing one of these does not make the
    add-on fail - it masks nothing, or renders the wrong geometry, which is far
    harder to diagnose. A half-built molecule must never reach the registry.

    These used to be swallowed whole: the writer caught every exception and,
    under the default verbose=False, discarded it with no warning and no log.
    """
    _break_attribute(monkeypatch, attr)

    before = set(sm.molecules.keys())
    with pytest.raises(RuntimeError):
        H.import_local("1ubq.pdb", "1ubq_broken")

    assert set(sm.molecules.keys()) == before, (
        "a molecule missing a critical attribute was registered anyway")
    assert not any(o.name.startswith("1ubq_broken") for o in bpy.data.objects), (
        "a half-built molecule object was left behind in the scene")
    # The attribute that failed must be named somewhere the user can see it.
    assert attr in capsys.readouterr().out


@pytest.mark.integration
def test_import_survives_a_non_critical_attribute_failure(
        scene, sm, monkeypatch):
    """A non-critical attribute failure degrades the render, so it logs and
    continues rather than aborting - but it must never be silent.

    Captures on the ``proteinblender`` logger (not caplog/root): the add-on
    sets ``propagate=False``, so its warnings never reach the root logger caplog
    watches. Asserting via caplog here failed even though the warning WAS
    emitted - a false negative that hid nothing but wasted a red."""
    _break_attribute(monkeypatch, "b_factor")

    with _capture_addon_logs() as caught:
        mol_id = H.import_local("1ubq.pdb", "1ubq_partial")

    assert mol_id in sm.molecules, "a lost b_factor should not abort the import"
    warnings = [r for r in caught.records if r.levelno >= logging.WARNING]
    assert any("b_factor" in r.getMessage() for r in warnings), (
        "the failure was swallowed: no WARNING mentioning b_factor was logged")


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
# Duplicate must not share node groups with its source (regression)
# --------------------------------------------------------------------------

def _mn_node_group(mol):
    """The parent MolecularNodes GN tree backing a molecule wrapper."""
    mod = mol.object.modifiers.get("MolecularNodes")
    return mod.node_group if mod else None


@pytest.mark.integration
def test_duplicate_gives_copy_its_own_node_group(scene, sm):
    """A duplicated protein must own a private copy of the parent MolecularNodes
    tree, not share the source's datablock.

    The duplicate operator copies modifiers by assigning every non-readonly RNA
    property, and `node_group` is a *pointer* — so the copy's modifier ends up
    aimed at the source's tree. Both molecules then write their domain masking
    into one shared tree.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    orig = sm.molecules[mid]
    orig_tree = _mn_node_group(orig)
    assert orig_tree is not None

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=mid)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]
    copy_tree = _mn_node_group(sm.molecules[copy_id])

    assert copy_tree is not None
    assert copy_tree is not orig_tree, (
        "duplicate shares the source's MolecularNodes tree "
        f"({orig_tree.name}) — domain edits and deletion of either molecule "
        "will corrupt the other")


@pytest.mark.integration
def test_duplicate_does_not_inherit_source_domain_masks(scene, sm):
    """The copy's tree must carry masking nodes for its OWN domains only.

    The duplicate re-creates every source domain explicitly, so any mask node
    inherited from the source is cruft: it stays wired into the copy's boolean
    join, so it keeps hiding that residue range out of the copy's parent mesh
    even after the user deletes the domain that should own it — and it burns
    join input slots, forcing premature overflow joins.
    """
    mid = H.import_local("1atn.pdb", "1atn")

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=mid)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]

    tree = _mn_node_group(sm.molecules[copy_id])
    masks = [n.name for n in tree.nodes
             if n.name.startswith(("Domain_Chain_Select_", "Domain_Res_Select_"))]
    assert masks, "copy has no domain masks at all"

    # Every mask in the copy's tree must belong to one of the copy's domains.
    own = set(sm.molecules[copy_id].domains.keys())
    stale = [m for m in masks
             if not any(m.endswith(domain_id) for domain_id in own)]
    assert not stale, (
        f"copy's tree carries {len(stale)} mask node(s) inherited from the "
        f"source's domains: {stale}")


@pytest.mark.integration
def test_delete_copy_leaves_original_domain_masking_intact(scene, sm):
    """Deleting a duplicate must not strip the *original's* domain masking.

    Reported: import 1atn, Copy it, delete the copy — the original then renders
    its full atom mesh on top of its per-domain objects (reads as "the copy
    didn't get deleted", with heavy clipping between the two overlapping
    surfaces).

    Root cause: the copy shares the source's GN tree, so the copy's cleanup()
    removes Domain_Boolean_Join / Domain_Final_Not — the nodes that mask the
    parent's geometry out from under the domain objects — from the tree the
    original is still rendering through.
    """
    mid = H.import_local("1atn.pdb", "1atn")
    orig = sm.molecules[mid]
    orig_tree = _mn_node_group(orig)
    assert orig_tree.nodes.get("Domain_Boolean_Join") is not None
    assert orig_tree.nodes.get("Domain_Final_Not") is not None

    before = set(sm.molecules.keys())
    bpy.ops.molecule.duplicate_protein(molecule_id=mid)
    copy_id = sorted(set(sm.molecules.keys()) - before)[-1]

    bpy.ops.molecule.delete(molecule_id=copy_id)
    assert copy_id not in sm.molecules

    # The original survives, still owns its tree, and that tree still masks.
    assert mid in sm.molecules
    tree = _mn_node_group(sm.molecules[mid])
    assert tree is not None, "original lost its MolecularNodes node group"
    assert tree.nodes.get("Domain_Boolean_Join") is not None, (
        "deleting the copy removed the original's Domain_Boolean_Join — the "
        "parent mesh is no longer masked out from under its domain objects")
    assert tree.nodes.get("Domain_Final_Not") is not None, (
        "deleting the copy removed the original's Domain_Final_Not")

    # The masking must still be *wired into* the style node, not just present.
    style_node = sm.molecules[mid].get_main_style_node()
    assert style_node is not None
    assert style_node.inputs["Selection"].links, (
        "original's style node lost its Selection input link — the parent "
        "renders every atom, overlapping the domain objects")


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
