"""Realizing copies into real objects, and cutting a shell open.

Phase 4, remaining slices. Realize follows ChimeraX's `sym copies` rule:
full copies below a threshold, graphical clones above it unless forced.
Cutaway removes whole copies on one side of a plane, which is what the
published capsid figures do.
"""

import bpy
import numpy as np
import pytest

import helpers as H

WORLD_SCALE = 0.01


def _core():
    from proteinblender.core import assembly
    return assembly


def _builder():
    from proteinblender.core import symmetry_builder
    return symmetry_builder


def _import(fixture="1ubq.pdb", ident="ubq"):
    mol_id = H.import_local(fixture, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _placed(molecule):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    domain = next(iter(molecule.domains.values())).object
    return sum(1 for i in depsgraph.object_instances
               if i.is_instance and i.parent is not None
               and i.parent.original.name == domain.name)


# --------------------------------------------------------------------------
# Realize
# --------------------------------------------------------------------------

def test_realizing_creates_one_object_per_extra_copy(scene, sm):
    """A C4 leaves the original plus three real copies, per source object."""
    core, builder = _core(), _builder()
    molecule = _import()

    assert builder.apply_symmetry(molecule, "C", order=4)
    sources = len(core._target_objects(molecule))

    before = set(bpy.data.objects.keys())
    created = core.realize_copies(molecule)
    after = set(bpy.data.objects.keys())

    assert created, "nothing was realized"
    # 3 extra copies (the identity is the structure already there).
    assert len(created) == 3 * sources
    assert len(after - before) == len(created)


def test_realized_copies_are_selectable_on_their_own(scene, sm):
    """The point of realizing: per-copy identity that instances cannot give."""
    core, builder = _core(), _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=3)
    created = core.realize_copies(molecule)

    for obj in created:
        obj.select_set(False)
    created[0].select_set(True)

    selected = [o for o in bpy.data.objects if o.select_get()]
    assert created[0].name in [o.name for o in selected]
    assert created[1].name not in [o.name for o in selected], (
        "selecting one copy selected another - they are not independent")


def test_realized_copies_share_their_atoms(scene, sm):
    """Real objects, but not real duplicate atom data."""
    core, builder = _core(), _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=3)
    created = core.realize_copies(molecule)

    meshes = {o.data.name for o in created}
    assert len(meshes) <= len(core._target_objects(molecule)), (
        "realizing duplicated the atom data instead of sharing it")


def test_realized_copies_land_where_the_instances_were(scene, sm):
    """Realizing must not move anything.

    The copy positions are captured from the depsgraph before realizing and
    compared with the real objects' own origins afterwards.
    """
    core, builder = _core(), _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=4)

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    domain = next(iter(molecule.domains.values())).object
    before = sorted(
        tuple(np.round(np.array(i.matrix_world.translation), 5))
        for i in depsgraph.object_instances
        if i.is_instance and i.parent is not None
        and i.parent.original.name == domain.name)

    created = core.realize_copies(molecule)
    bpy.context.view_layer.update()

    from_this_domain = [o for o in created if o.name.startswith(domain.name)]
    after = sorted(
        tuple(np.round(np.array(o.matrix_world.translation), 5))
        for o in from_this_domain + [domain])

    assert len(after) == len(before)
    for got, want in zip(after, before):
        assert np.allclose(got, want, atol=1e-4), (
            f"a copy moved when it was realized: {got} vs {want}")


def test_realizing_clears_the_instanced_assembly(scene, sm):
    """Otherwise every copy would be drawn twice."""
    core, builder = _core(), _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=3)
    core.realize_copies(molecule)

    assert core.built_assembly_id(molecule) is None
    assert _placed(molecule) <= 1


def test_a_big_assembly_is_refused_unless_forced(scene, sm):
    """ChimeraX's rule: above the threshold, copies stay clones by default.

    A capsid's worth of real objects is rarely what anyone wanted, so it has
    to be asked for rather than happened upon.
    """
    core, builder = _core(), _builder()
    molecule = _import()

    order = core.REALIZE_THRESHOLD + 4
    builder.apply_symmetry(molecule, "C", order=order)

    assert core.realize_copies(molecule) is None, (
        f"{order} copies should be refused without force")
    assert core.built_assembly_id(molecule) is not None, (
        "a refusal must leave the assembly alone")

    created = core.realize_copies(molecule, force=True)
    assert created, "force should realize regardless of the count"


def test_realizing_nothing_is_harmless(scene, sm):
    core = _core()
    molecule = _import()
    assert core.realize_copies(molecule) == []


# --------------------------------------------------------------------------
# Cutaway
# --------------------------------------------------------------------------

def test_a_cutaway_removes_the_copies_in_front_of_the_plane(scene, sm):
    """Which copies go is arithmetic on the ring, computed here."""
    core, builder = _core(), _builder()
    molecule = _import()

    order = 8
    operators = builder.cyclic(order)

    atoms = core._atom_cloud(molecule)
    centre = atoms.mean(axis=0)
    normal = np.array([0.0, -1.0, 0.0])

    expected = sum(
        1 for rotation, translation in operators
        if float(np.dot((rotation @ centre
                         + np.asarray(translation) * WORLD_SCALE) - centre,
                        normal)) <= 0.0)

    kept = core.cutaway_operators(molecule, operators, normal=normal, offset=0.0)

    assert len(kept) == expected
    assert 0 < len(kept) < order, (
        "a cut through the centre should remove some copies but not all")


def test_the_cutaway_offset_moves_the_plane(scene, sm):
    """A more generous offset takes less away."""
    core, builder = _core(), _builder()
    molecule = _import()

    operators = builder.cyclic(12)
    normal = (0.0, -1.0, 0.0)

    shallow = core.cutaway_operators(molecule, operators, normal=normal, offset=1000.0)
    deep = core.cutaway_operators(molecule, operators, normal=normal, offset=-1000.0)

    assert len(shallow) == len(operators), "a far plane should remove nothing"
    assert len(deep) == 0, "a plane beyond the far side should remove everything"


def test_the_cutaway_does_not_privilege_the_original(scene, sm):
    """Unlike range and contact, a cutaway is about the shell as a whole.

    Exempting the identity would leave one subunit floating in the opening.
    """
    core, builder = _core(), _builder()
    molecule = _import()

    operators = builder.cyclic(6)
    kept = core.cutaway_operators(molecule, operators,
                                  normal=(0.0, -1.0, 0.0), offset=-1000.0)

    assert kept == [], "the original should be cut away like any other copy"


def test_a_cutaway_reaches_the_scene(scene, sm):
    core, builder = _core(), _builder()
    molecule = _import()

    operators = builder.cyclic(8)
    kept = core.cutaway_operators(molecule, operators, normal=(0.0, -1.0, 0.0))
    assert core.apply_operators(molecule, kept, "cutaway")

    assert _placed(molecule) == len(kept)


def test_a_degenerate_normal_keeps_everything(scene, sm):
    core, builder = _core(), _builder()
    molecule = _import()

    operators = builder.cyclic(5)
    kept = core.cutaway_operators(molecule, operators, normal=(0.0, 0.0, 0.0))

    assert len(kept) == len(operators)


# --------------------------------------------------------------------------
# Through the operators the panel drives
# --------------------------------------------------------------------------

def test_the_realize_operator_respects_the_threshold(scene, sm):
    core, builder = _core(), _builder()
    molecule = _import()

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = core.REALIZE_THRESHOLD + 3
    bpy.ops.molecule.build_symmetry("EXEC_DEFAULT", molecule_id=molecule.identifier)

    assert bpy.ops.molecule.realize_copies(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"CANCELLED"}
    assert core.built_assembly_id(molecule) is not None

    assert bpy.ops.molecule.realize_copies(
        "EXEC_DEFAULT", molecule_id=molecule.identifier, force=True) == {"FINISHED"}


def test_the_cutaway_operator_reads_the_panel(scene, sm):
    core = _core()
    molecule = _import()

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 8
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    bpy.ops.molecule.build_symmetry("EXEC_DEFAULT", molecule_id=molecule.identifier)
    whole = _placed(molecule)

    scene.pb_cutaway_normal = (0.0, -1.0, 0.0)
    scene.pb_cutaway_offset = 0.0
    assert bpy.ops.molecule.cutaway(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"FINISHED"}

    assert 0 < _placed(molecule) < whole


def test_cutting_away_everything_is_refused(scene, sm):
    molecule = _import()
    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 6
    bpy.ops.molecule.build_symmetry("EXEC_DEFAULT", molecule_id=molecule.identifier)

    scene.pb_cutaway_offset = -1000.0
    assert bpy.ops.molecule.cutaway(
        "EXEC_DEFAULT", molecule_id=molecule.identifier) == {"CANCELLED"}
    scene.pb_cutaway_offset = 0.0


def test_realizing_nothing_leaves_the_assembly_alone(scene, sm):
    """A realize that creates nothing must not destroy what was built.

    Reachable from the UI in one step: cut an assembly down until only the
    original is left, then press Realize Copies. There is nothing to realize,
    the operator reports as much and cancels - and clearing the assembly on the
    way out would silently throw away the build still on screen. A cancelled
    operator must leave the scene as it found it.
    """
    core = _core()
    molecule = _import()

    identity = [(np.eye(3), np.zeros(3))]
    assert core.apply_operators(molecule, identity, "solo")
    assert core.built_assembly_id(molecule) == "solo"

    assert core.realize_copies(molecule) == []

    assert core.built_assembly_id(molecule) == "solo", (
        "a realize that created nothing cleared the assembly anyway")


def test_a_cutaway_then_realize_keeps_the_survivors(scene, sm):
    """The exact sequence that surfaced the bug, end to end."""
    core, builder = _core(), _builder()
    molecule = _import()

    assert builder.apply_symmetry(molecule, "C", order=6)
    kept = core.cutaway_operators(
        molecule, builder.cyclic(6), normal=(0.0, -1.0, 0.0), offset=0.0)
    assert core.apply_operators(molecule, kept, "cut")

    survivors = _placed(molecule)
    assert survivors >= 1

    created = core.realize_copies(molecule)
    if created:
        assert core.built_assembly_id(molecule) is None
    else:
        assert core.built_assembly_id(molecule) == "cut", (
            "nothing was realized, so the cutaway should still be on screen")
