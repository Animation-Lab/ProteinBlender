"""Building a deposited biological assembly inside ProteinBlender.

Phase 1 of symmetry support: reading which assemblies a structure offers,
deciding which are worth showing, and wiring the copies into the objects that
are actually on screen.

The trap this file exists to guard is that a ProteinBlender import creates one
object per domain on top of the molecule object, and the molecule object draws
only the atoms no domain covers - nothing at all after a normal import. An
assembly built into the molecule object alone is therefore invisible while
looking entirely correct in the node graph, so the assertions here are about
*instances the depsgraph actually places* and pixels rendered, never about the
node tree's own account of itself.

Ground truth is the fixture's `REMARK 350` text, read by the independent
parser in ``test_biological_assembly``.
"""

import bpy
import pytest

import helpers as H
from test_biological_assembly import _remark_350_transforms

FIXTURE = "4ins.pdb"

# From tests/data/4ins.pdb REMARK 350, read by eye: assemblies 1, 2 and 7 hold
# a single identity transform (the asymmetric unit relabelled), while 3, 4 and
# 5 hold an identity plus two thirds of a three-fold, and 6 holds an identity
# on chains A,B and a three-fold on C,D.
IDENTITY_ONLY = {"1", "2", "7"}
WITH_SYMMETRY = {"3", "4", "5", "6"}


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _import(fixture=FIXTURE, ident="4ins"):
    mol_id = H.import_local(fixture, ident)
    bpy.context.scene.selected_molecule_id = mol_id
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _instances_by_object():
    """How many instances the depsgraph places for each originating object.

    The only measure that reflects what is drawn. Keyed by object name because
    bpy returns a fresh wrapper on every attribute access, so identity
    comparison between structs is meaningless.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    counts = {}
    for instance in depsgraph.object_instances:
        if not instance.is_instance or instance.parent is None:
            continue
        name = instance.parent.original.name
        counts[name] = counts.get(name, 0) + 1
    return counts


def _domain_object_names(molecule):
    names = []
    for domain in molecule.domains.values():
        obj = domain.object
        if obj is not None:
            names.append(obj.name)
    return names


# --------------------------------------------------------------------------
# What the file offers
# --------------------------------------------------------------------------

def test_available_assemblies_match_the_file(scene, sm):
    """Every assembly in REMARK 350, with the right transform count."""
    molecule = _import()
    truth = _remark_350_transforms(FIXTURE)

    infos = {i.assembly_id: i for i in _assembly_core().available_assemblies(molecule)}

    assert sorted(infos) == sorted(truth)
    for assembly_id, expected in truth.items():
        assert infos[assembly_id].transform_count == len(expected), (
            f"assembly {assembly_id}: reported "
            f"{infos[assembly_id].transform_count} copies, REMARK 350 declares "
            f"{len(expected)}")


def test_identity_only_assemblies_are_not_offered(scene, sm):
    """An assembly that is purely the identity would build nothing visible.

    Every deposited structure carries an assembly record; for a monomer it is
    one identity transform. Offering it would be a button that does nothing.
    """
    molecule = _import()

    buildable = {i.assembly_id for i in _assembly_core().buildable_assemblies(molecule)}

    assert buildable == WITH_SYMMETRY
    assert not (buildable & IDENTITY_ONLY)


@pytest.mark.parametrize("fixture,ident,expected", [
    ("4ins.pdb", "4ins", True),
    ("1ubq.pdb", "1ubq", False),
    ("1aki.pdb", "1aki", False),
    ("4hhb.pdb", "4hhb", False),
])
def test_symmetry_is_detected_only_where_it_exists(scene, sm, fixture, ident, expected):
    """The gate the Symmetry panel polls on."""
    molecule = _import(fixture, ident)
    assert _assembly_core().has_buildable_symmetry(molecule) is expected


@pytest.mark.parametrize("fixture,ident,expected", [
    ("4ins.pdb", "4ins", True),
    ("1ubq.pdb", "1ubq", False),
])
def test_panel_polls_itself_away_without_symmetry(scene, sm, fixture, ident, expected):
    """The meeting's requirement: no symmetry in the file, no panel."""
    from proteinblender.panels.symmetry_panel import PROTEINBLENDER_PT_symmetry

    _import(fixture, ident)
    assert PROTEINBLENDER_PT_symmetry.poll(bpy.context) is expected


# --------------------------------------------------------------------------
# Building - measured on screen, not in the node graph
# --------------------------------------------------------------------------

def test_building_places_one_copy_per_deposited_operator(scene, sm):
    """Each domain object must be instanced once per operator for its chain.

    The count comes from REMARK 350, not from the assembly code: assembly 3
    applies three transforms to chains A, B, C and D, so every chain's domain
    object should be placed three times.
    """
    molecule = _import()
    truth = _remark_350_transforms(FIXTURE)

    expected_per_chain = {}
    for chain_ids, _matrix in truth["3"]:
        for chain in chain_ids:
            expected_per_chain[chain] = expected_per_chain.get(chain, 0) + 1
    assert set(expected_per_chain.values()) == {3}, (
        "fixture changed - assembly 3 no longer applies 3 operators per chain")

    assert _assembly_core().build_assembly(molecule, "3")

    counts = _instances_by_object()
    for domain in molecule.domains.values():
        obj = domain.object
        assert obj is not None
        expected = expected_per_chain.get(str(domain.chain_id))
        if expected is None:
            continue
        assert counts.get(obj.name, 0) == expected, (
            f"{obj.name} (chain {domain.chain_id}) was placed "
            f"{counts.get(obj.name, 0)} times, REMARK 350 declares {expected}")


def test_building_puts_the_copies_on_screen(scene, sm, tmp_path):
    """The copies must actually render.

    An assembly wired only into the molecule object passes every node-graph
    check and still shows nothing, because that object draws only the atoms no
    domain covers - none, after a normal import.
    """
    molecule = _import()

    before = int(H.render_coverage(tmp_path).sum())
    assert before > 0, "the protein rendered nothing before the assembly was built"

    assert _assembly_core().build_assembly(molecule, "3")
    bpy.context.view_layer.update()
    after = int(H.render_coverage(tmp_path).sum())

    assert after > before, (
        f"building the assembly changed nothing on screen ({before} -> {after} "
        "px) - the copies are probably on the invisible molecule object")


def test_clearing_restores_the_asymmetric_unit(scene, sm):
    """Build then clear must land exactly back where it started."""
    molecule = _import()
    baseline = _instances_by_object()

    assert _assembly_core().build_assembly(molecule, "3")
    assert _instances_by_object() != baseline

    assert _assembly_core().clear_assembly(molecule)
    assert _instances_by_object() == baseline
    assert _assembly_core().built_assembly_id(molecule) is None


def test_rebuilding_does_not_stack_copies(scene, sm):
    """Building twice replaces, never accumulates."""
    molecule = _import()

    assert _assembly_core().build_assembly(molecule, "3")
    once = _instances_by_object()

    assert _assembly_core().build_assembly(molecule, "3")
    assert _instances_by_object() == once

    # And switching assemblies replaces rather than adding a second node.
    assert _assembly_core().build_assembly(molecule, "4")
    assert _assembly_core().built_assembly_id(molecule) == "4"


def test_built_assembly_id_reads_back_what_was_built(scene, sm):
    molecule = _import()
    assert _assembly_core().built_assembly_id(molecule) is None

    assert _assembly_core().build_assembly(molecule, "5")
    assert _assembly_core().built_assembly_id(molecule) == "5"


def test_unknown_assembly_is_refused(scene, sm):
    molecule = _import()
    assert _assembly_core().build_assembly(molecule, "99") is False
    assert _assembly_core().built_assembly_id(molecule) is None


# --------------------------------------------------------------------------
# Through the operators the panel actually calls
# --------------------------------------------------------------------------

def test_build_operator_builds(scene, sm):
    molecule = _import()

    result = bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    assert result == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) == "3"


def test_clear_operator_clears(scene, sm):
    molecule = _import()
    bpy.ops.molecule.build_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, assembly_id="3")

    result = bpy.ops.molecule.clear_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)

    assert result == {"FINISHED"}
    assert _assembly_core().built_assembly_id(molecule) is None


def test_clear_operator_on_nothing_is_cancelled(scene, sm):
    molecule = _import()
    result = bpy.ops.molecule.clear_assembly(
        "EXEC_DEFAULT", molecule_id=molecule.identifier)
    assert result == {"CANCELLED"}


def test_assembly_enum_offers_only_symmetric_assemblies(scene, sm):
    """The picker must not list the identity-only assemblies either."""
    from proteinblender.operators.assembly_operators import assembly_enum_items

    _import()
    identifiers = {item[0] for item in assembly_enum_items(None, bpy.context)}

    assert identifiers == WITH_SYMMETRY
