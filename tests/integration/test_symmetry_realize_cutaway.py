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

def _realize(molecule, force=False):
    from proteinblender.operators.assembly_realize import realize_assembly
    return realize_assembly(bpy.context, molecule, force=force)


def _chain_objects(molecule_id):
    return [d.object for d in H.sm().molecules[molecule_id].domains.values()]


def test_realizing_creates_one_protein_per_extra_copy(scene, sm):
    """A C4 leaves the original plus three proteins of their own."""
    builder = _builder()
    molecule = _import()

    assert builder.apply_symmetry(molecule, "C", order=4)
    before = set(sm.molecules)

    created = _realize(molecule)

    assert created, "nothing was realized"
    # 3 extra copies (the identity is the structure already there).
    assert len(created.proteins) == 3
    assert set(sm.molecules) - before == set(created.proteins)


def test_realized_copies_are_selectable_on_their_own(scene, sm):
    """The point of realizing: per-copy identity that instances cannot give."""
    builder = _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=3)
    first, second = [_chain_objects(mid)[0] for mid in _realize(molecule).proteins]

    for obj in bpy.data.objects:
        obj.select_set(False)
    first.select_set(True)

    selected = [o.name for o in bpy.data.objects if o.select_get()]
    assert first.name in selected
    assert second.name not in selected, (
        "selecting one copy selected another - they are not independent")


def test_deleting_one_realized_copy_leaves_the_others_drawn(scene, sm):
    """Each copy is a protein in its own right, not a view onto a shared one."""
    builder = _builder()
    molecule = _import()
    atoms = len(H.evaluated_atom_positions(_chain_objects(molecule.identifier)))
    assert atoms > 0

    builder.apply_symmetry(molecule, "C", order=3)
    doomed, kept = _realize(molecule).proteins

    assert bpy.ops.molecule.delete(molecule_id=doomed) == {'FINISHED'}
    bpy.context.view_layer.update()

    assert doomed not in H.sm().molecules
    for molecule_id in (molecule.identifier, kept):
        drawn = H.evaluated_atom_positions(_chain_objects(molecule_id))
        assert len(drawn) == atoms, molecule_id


def test_realized_copies_land_where_the_instances_were(scene, sm):
    """Realizing must not move anything.

    The copy positions are captured from the depsgraph before realizing and
    compared with the real objects' own origins afterwards.
    """
    builder = _builder()
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

    created = _realize(molecule)
    bpy.context.view_layer.update()

    chains = [domain] + [_chain_objects(mid)[0] for mid in created.proteins]
    after = sorted(
        tuple(np.round(np.array(o.matrix_world.translation), 5)) for o in chains)

    assert len(after) == len(before)
    for got, want in zip(after, before):
        assert np.allclose(got, want, atol=1e-4), (
            f"a copy moved when it was realized: {got} vs {want}")


def test_realizing_clears_the_instanced_assembly(scene, sm):
    """Otherwise every copy would be drawn twice."""
    core, builder = _core(), _builder()
    molecule = _import()

    builder.apply_symmetry(molecule, "C", order=3)
    _realize(molecule)

    assert core.built_assembly_id(molecule) is None
    assert _placed(molecule) <= 1


def test_a_big_assembly_is_refused_unless_forced(scene, sm):
    """ChimeraX's rule: above the threshold, copies stay clones by default.

    A capsid's worth of real proteins is rarely what anyone wanted, so it has
    to be asked for rather than happened upon.
    """
    core, builder = _core(), _builder()
    molecule = _import()

    order = core.REALIZE_THRESHOLD + 2
    builder.apply_symmetry(molecule, "C", order=order)

    assert _realize(molecule) is None, (
        f"{order} copies should be refused without force")
    assert core.built_assembly_id(molecule) is not None, (
        "a refusal must leave the assembly alone")
    assert len(sm.molecules) == 1

    created = _realize(molecule, force=True)
    assert len(created.proteins) == order - 1, (
        "force should realize regardless of the count")


def test_realizing_nothing_is_harmless(scene, sm):
    molecule = _import()
    assert not _realize(molecule)
    assert len(sm.molecules) == 1


def test_an_original_that_was_cut_away_becomes_the_first_copy_left(scene, sm):
    """Two copies left on screen are two proteins, not two and a hidden one."""
    molecule = _import()
    alone = H.evaluated_atom_positions(_chain_objects(molecule.identifier))
    centre = float(alone[:, 1].mean())

    # Copies at 0, 20, 40 and 60 A down Y.
    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = 4
    scene.pb_symmetry_rise = 20.0
    scene.pb_symmetry_twist = 0.0
    scene.pb_symmetry_axis = (0.0, -1.0, 0.0)
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=molecule.identifier, source='GENERATED') == {'FINISHED'}
    # Take away everything above a plane 30 A down: the original and copy 1.
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, 1, 0), offset=-30) == {'FINISHED'}
    assert _placed(molecule) == 2

    assert bpy.ops.molecule.realize_copies(
        molecule_id=molecule.identifier) == {'FINISHED'}

    assert len(sm.molecules) == 2
    heights = []
    for molecule_id in sm.molecules:
        objects = _chain_objects(molecule_id)
        assert not any(o.hide_get() for o in objects)
        bpy.context.view_layer.update()
        heights.append(float(H.evaluated_atom_positions(objects)[:, 1].mean()))
    assert np.allclose(sorted(heights, reverse=True),
                       [centre - 0.4, centre - 0.6], atol=1e-3), heights


def test_a_ring_of_one_chain_realizes_as_copies_of_that_chain(scene, sm):
    """An assembly made from one chain repeats that chain, not the protein.

    Its copies belong beside it, as the chain row's own Copy button would
    put them, with the other chains left as they were.
    """
    mid = H.import_local("4hhb.pdb", "hb")
    bpy.context.view_layer.update()
    molecule = H.sm().molecules[mid]
    chains = lambda: [r for r in scene.outliner_items
                      if r.item_type == 'CHAIN' and r.parent_id == mid]
    assert len(chains()) == 4
    target = chains()[0]

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 3
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    assert bpy.ops.molecule.symmetry_dialog(target_id=target.item_id) == {'FINISHED'}

    assert bpy.ops.molecule.realize_copies(molecule_id=mid) == {'FINISHED'}

    assert list(sm.molecules) == [mid]
    # The four chains it had, and the two more a three-fold ring adds.
    assert len(chains()) == 6
    assert not any(r.item_type == 'SYMMETRY' for r in scene.outliner_items)
    copies = [d for d in molecule.domains.values() if getattr(d, 'is_copy', False)]
    assert len(copies) == 2
    assert _core().built_assembly_id(molecule) is None


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

    assert not _realize(molecule)

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

    created = _realize(molecule)
    if created:
        assert core.built_assembly_id(molecule) is None
        assert len(sm.molecules) == survivors
    else:
        assert core.built_assembly_id(molecule) == "cut", (
            "nothing was realized, so the cutaway should still be on screen")


def test_cutaway_popup_parameters_and_built_settings_override_scene_defaults(scene, sm):
    molecule = _import()
    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 8
    bpy.ops.molecule.build_symmetry(molecule_id=molecule.identifier)
    whole = _placed(molecule)
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=0) == {'FINISHED'}
    expected = _placed(molecule)
    assert 0 < expected < whole
    bpy.ops.molecule.build_symmetry(molecule_id=molecule.identifier)
    # Another builder's defaults must not alter this assembly's copies.
    scene.pb_symmetry_order = 2
    scene.pb_cutaway_offset = -1000.0
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=0) == {'FINISHED'}
    assert _placed(molecule) == expected


def _instances_of(obj):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return sum(1 for i in depsgraph.object_instances
               if i.is_instance and i.parent is not None
               and i.parent.original.name == obj.name)


def test_a_cutaway_keeps_the_settings_the_assembly_was_built_with(scene, sm):
    """Cutting away is a change to a build, not a new build.

    The build's settings ride on its assembly node, and the cut used to
    rebuild that node from nothing. A cut generated ring then had no settings
    left, so its edit dialog reopened as a deposited assembly and a second cut
    measured against whatever the scene sliders happened to say.
    """
    core = _core()
    molecule = _import()
    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 8
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=molecule.identifier, source='GENERATED') == {'FINISHED'}
    whole = _placed(molecule)
    assert whole == 8

    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=0) == {'FINISHED'}
    assert 0 < _placed(molecule) < whole

    # The ring that was asked for above, not anything read back from a build.
    kept = core.built_build_params(molecule)
    assert kept is not None, "the cut threw the build's settings away"
    assert (kept["kind"], kept["order"]) == ("C", 8)
    assert kept["source_item_id"] == molecule.identifier


def test_a_cutaway_stays_on_the_chain_the_assembly_was_built_from(scene, sm):
    """A ring made from one chain must not spread to the others when cut."""
    from proteinblender.operators.pivot_operators import row_objects

    mid = H.import_local("4hhb.pdb", "hb")
    bpy.context.view_layer.update()
    molecule = H.sm().molecules[mid]
    chain = next(r for r in scene.outliner_items
                 if r.item_type == 'CHAIN' and r.parent_id == mid)
    repeated = {o.name for o in row_objects(bpy.context, chain)}
    objects = [d.object for d in molecule.domains.values()]
    assert repeated and len(repeated) < len(objects)

    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 3
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    assert bpy.ops.molecule.symmetry_dialog(target_id=chain.item_id) == {'FINISHED'}

    # A plane 1000 A out removes nothing, so the only thing that can change
    # a count here is the cut reaching objects the ring was never built on.
    assert bpy.ops.molecule.cutaway(
        molecule_id=mid, normal=(0, -1, 0), offset=1000) == {'FINISHED'}

    for obj in objects:
        assert _instances_of(obj) == (3 if obj.name in repeated else 1), obj.name


# --------------------------------------------------------------------------
# Realized copies are proteins the PB Outliner knows about
# --------------------------------------------------------------------------

def _drawn_atoms(molecule):
    bpy.context.view_layer.update()
    objects = [molecule.object] + [d.object for d in molecule.domains.values()]
    return H.evaluated_atom_positions(objects)


def _row_types(scene, molecule_id):
    return sorted(r.item_type for r in scene.outliner_items if r.parent_id == molecule_id)


def test_realized_copies_are_proteins_in_the_outliner(scene, sm):
    """Realize Copies exists so each copy can be selected, coloured and hidden.

    All of that is done from PB Outliner rows, so a copy the outliner does not
    list is a copy nothing can be done to. Each one has to arrive as a protein
    of its own, standing where its instance was drawn.
    """
    molecule = _import()
    source_id = molecule.identifier
    # Four copies 20 A apart along -Y with no twist: copy k is the original
    # moved 0.2 k Blender units down Y, which can be checked by hand.
    scene.pb_symmetry_kind = "H"
    scene.pb_symmetry_count = 4
    scene.pb_symmetry_rise = 20.0
    scene.pb_symmetry_twist = 0.0
    scene.pb_symmetry_axis = (0.0, -1.0, 0.0)
    scene.pb_symmetry_range = 0.0
    scene.pb_symmetry_contact = 0.0
    alone = _drawn_atoms(molecule)
    atoms, centre = len(alone), float(alone[:, 1].mean())
    source_rows = _row_types(scene, source_id)
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=source_id, source='GENERATED') == {'FINISHED'}
    assert len(_drawn_atoms(molecule)) == 4 * atoms

    assert bpy.ops.molecule.realize_copies(molecule_id=source_id) == {'FINISHED'}

    assert len(H.sm().molecules) == 4
    proteins = [r for r in scene.outliner_items if r.item_type == 'PROTEIN']
    assert len(proteins) == 4
    assert not any(r.item_type == 'SYMMETRY' for r in scene.outliner_items)

    heights = []
    for row in proteins:
        copy = H.sm().molecules[row.item_id]
        assert _core().built_assembly_id(copy) is None
        # Every copy is the whole protein: the same rows beneath it.
        assert _row_types(scene, row.item_id) == source_rows, row.item_id
        drawn = _drawn_atoms(copy)
        assert len(drawn) == atoms, (row.item_id, len(drawn))
        heights.append(float(drawn[:, 1].mean()))
    assert np.allclose(sorted(heights, reverse=True),
                       [centre - 0.2 * k for k in range(4)], atol=1e-3), heights

    # Nothing realized is left outside the registry for the outliner to miss.
    known = set()
    for item in H.sm().molecules.values():
        known.add(item.object.name)
        known.update(d.object.name for d in item.domains.values())
    stray = [o.name for o in bpy.data.objects
             if o.name not in known and o.type in {'MESH', 'POINTCLOUD'}]
    assert not stray, stray

