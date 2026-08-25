"""The Symmetry Builder dialog: Apply previews, OK commits, Cancel puts back.

Three ways out of one dialog, and the whole point of the feature is that they
mean different things. The tests here are about those differences, not about
the generator underneath - what a C7 *is* is settled in
``test_symmetry_builder.py`` against trigonometry.

Ground truth is the number of copies actually instanced in the depsgraph, not
the tag on the assembly node and not the settings dict that produced them. A
C7 ring has seven subunits because that is what seven-fold means; asserting
against ``built_assembly_id`` or ``built_build_params`` would pass whatever
those happened to return, including the wrong thing.
"""

import bpy
import pytest

import helpers as H

FIXTURE = "1ubq.pdb"           # a monomer: no deposited symmetry to confuse things

#: What :func:`_copies` reads for a protein with no assembly built. Not zero:
#: MolecularNodes draws the structure as a single geometry-nodes instance
#: whether or not anything repeats it, so "nothing built" is one copy - the
#: asymmetric unit on its own. A build of n operators reads as n.
UNBUILT = 1


def _dialog():
    from proteinblender.operators import symmetry_dialog
    return symmetry_dialog


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _import(ident="ubq"):
    mol_id = H.import_local(FIXTURE, ident)
    bpy.context.view_layer.update()
    return H.sm().molecules.get(mol_id)


def _a_domain_object(molecule):
    return next(d.object for d in molecule.domains.values())


def _copies(molecule):
    """How many copies are on screen, counted off the depsgraph.

    One instance per operator, parented to a domain object. This is what the
    user sees, and it is independent of every record the add-on keeps about
    what it thinks it built.
    """
    obj_name = _a_domain_object(molecule).name
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return len([i for i in depsgraph.object_instances
                if i.is_instance and i.parent is not None
                and i.parent.original.name == obj_name])


def _set(kind="C", order=3, count=10, rise=0.0, twist=0.0,
         axis=(0.0, 0.0, 1.0), range_limit=0.0, contact=0.0):
    """Put the dialog's controls where a user would have dragged them."""
    scene = bpy.context.scene
    scene.pb_symmetry_kind = kind
    scene.pb_symmetry_order = order
    scene.pb_symmetry_count = count
    scene.pb_symmetry_rise = rise
    scene.pb_symmetry_twist = twist
    scene.pb_symmetry_axis = axis
    scene.pb_symmetry_range = range_limit
    scene.pb_symmetry_contact = contact


def _symmetry_rows():
    return [item for item in bpy.context.scene.outliner_items
            if item.item_type == 'SYMMETRY']


def _rebuild_outliner():
    from proteinblender.utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(bpy.context)


def _row(item_id):
    """The outliner row for an id, rebuilt from the live scene first."""
    _rebuild_outliner()
    return next(r for r in bpy.context.scene.outliner_items
                if r.item_id == item_id)


def _first_chain(molecule_id):
    return next(r for r in bpy.context.scene.outliner_items
                if r.item_type == 'CHAIN' and r.parent_id == molecule_id)


def _cancel():
    """What the dialog's cancel() does, minus the redraw.

    ``cancel`` is called by Blender when a popup is dismissed, and popups do
    not exist headless. The work it delegates to is a module function
    precisely so it can be reached from here.
    """
    return _dialog().discard_previews()


@pytest.fixture(autouse=True)
def _no_previews_leak_between_tests():
    """Previews are module state, which the scene scrub does not reach."""
    _dialog().discard_previews()
    yield
    _dialog().discard_previews()


# --------------------------------------------------------------------------
# OK - build and commit
# --------------------------------------------------------------------------

def test_ok_builds_what_the_dialog_was_showing():
    """Running the dialog is its OK: it builds, with the settings on screen."""
    molecule = _import()
    assert _copies(molecule) == UNBUILT, "nothing should be built before the dialog"

    _set(kind="C", order=7)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier) == {'FINISHED'}

    # Seven, because seven-fold symmetry has seven subunits.
    assert _copies(molecule) == 7


def test_ok_puts_a_symmetry_object_in_the_outliner():
    """A built symmetry is an object, not a note on the protein.

    It takes the top-level row; the protein it repeats moves *inside* it.
    """
    molecule = _import()
    _set(kind="C", order=5)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier) == {'FINISHED'}

    rows = _symmetry_rows()
    assert len(rows) == 1, "one build, one Symmetry object"
    row = rows[0]
    assert row.indent_level == 0, "a Symmetry is top-level, like a membrane"
    assert row.parent_id == "", "it belongs to the scene, not to a protein"
    assert "C5" in row.name, f"the row should name what was built, got {row.name!r}"


def test_the_protein_moves_inside_the_symmetry_that_repeats_it():
    """The containment, and the indents that draw it.

    The protein stops being top-level and its chains follow it down a level,
    so the tree reads Symmetry > protein > chain rather than leaving the
    protein sitting beside the object that contains it.
    """
    molecule = _import()
    identifier = molecule.identifier

    before = _row(identifier)
    assert before.indent_level == 0, "an unsymmetrised protein is top-level"
    assert before.parent_id == ""
    chain_before = _first_chain(identifier)
    assert chain_before.indent_level == 1

    _set(kind="C", order=5)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=identifier) == {'FINISHED'}

    symmetry = _symmetry_rows()[0]
    protein = _row(identifier)
    assert protein.parent_id == symmetry.item_id, (
        "the protein is not inside the Symmetry that repeats it")
    assert protein.indent_level == 1, "the protein did not move down a level"
    assert _first_chain(identifier).indent_level == 2, (
        "the chains did not follow the protein down")

    top_level = [r.item_id for r in bpy.context.scene.outliner_items
                 if r.indent_level == 0]
    assert identifier not in top_level, (
        "the protein is still top-level as well as inside the Symmetry")


def test_clearing_the_symmetry_returns_the_protein_to_the_top_level():
    """Deleting the object gives back exactly what was there before it."""
    molecule = _import()
    identifier = molecule.identifier

    _set(kind="C", order=5)
    bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', target_id=identifier)
    assert _row(identifier).indent_level == 1

    bpy.ops.molecule.clear_assembly('EXEC_DEFAULT', molecule_id=identifier)
    from proteinblender.utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(bpy.context)

    protein = _row(identifier)
    assert protein.indent_level == 0, "the protein stayed indented with no parent"
    assert protein.parent_id == "", "the protein still points at a row that is gone"
    assert _first_chain(identifier).indent_level == 1


def test_the_outliner_row_goes_when_the_assembly_is_cleared():
    """The row is derived from what is built, so clearing takes it away.

    This is the property that makes the row trustworthy: there is no second
    copy of the fact to leave behind.
    """
    molecule = _import()
    _set(kind="C", order=4)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    assert _symmetry_rows()

    assert bpy.ops.molecule.clear_assembly(
        'EXEC_DEFAULT', molecule_id=molecule.identifier) == {'FINISHED'}
    from proteinblender.utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(bpy.context)

    assert _copies(molecule) == UNBUILT
    assert not _symmetry_rows(), "the row outlived the build it described"


def test_a_deposited_assembly_gets_no_symmetry_row():
    """The row is for generated symmetry, which is what its pencil can edit."""
    from proteinblender.core import assembly as assembly_core
    from proteinblender.utils.scene_manager import build_outliner_hierarchy

    mol_id = H.import_local("4ins.pdb", "4ins")
    molecule = H.sm().molecules[mol_id]
    assert assembly_core.build_assembly(molecule, "3"), "assembly 3 failed to build"
    build_outliner_hierarchy(bpy.context)

    assert _copies(molecule) > 1, "the deposited assembly should be on screen"
    assert not _symmetry_rows(), (
        "a deposited assembly has no generator settings, so the dialog's "
        "pencil would open on nothing")


# --------------------------------------------------------------------------
# Apply - build without committing
# --------------------------------------------------------------------------

def test_apply_builds_the_same_thing_ok_would():
    """Apply is a preview, not a different builder.

    Both go through one path, so what the viewport shows during the dialog is
    what stays there when it closes. Built twice over, once each way, and the
    copy counts compared.
    """
    first = _import("ubq_apply")
    _set(kind="D", order=3)
    assert bpy.ops.molecule.symmetry_preview(
        'EXEC_DEFAULT', molecule_id=first.identifier) == {'FINISHED'}
    previewed = _copies(first)

    # A D3 is two rings of three - six copies, by definition of dihedral.
    assert previewed == 6

    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=first.identifier) == {'FINISHED'}
    assert _copies(first) == previewed


# --------------------------------------------------------------------------
# Cancel - put back what was there
# --------------------------------------------------------------------------

def test_cancel_after_a_preview_leaves_nothing_built():
    """The dialog opened on an unbuilt protein, so Cancel must leave it so."""
    molecule = _import()
    before = _copies(molecule)
    assert before == UNBUILT

    _set(kind="C", order=6)
    bpy.ops.molecule.symmetry_preview(
        'EXEC_DEFAULT', molecule_id=molecule.identifier)
    assert _copies(molecule) == 6, "the preview did not build"

    _cancel()
    assert _copies(molecule) == before, "Cancel left the rejected preview behind"


def test_cancel_puts_back_the_symmetry_that_was_already_built():
    """Editing a C4 and cancelling must leave a C4, not the C9 being tried.

    This is the case a naive "Cancel clears it" would get wrong, and the one
    that proves the settings really do travel with the build: the C4 is
    rebuilt from what was recorded on its own node, long after the scene's
    sliders moved on to 9.
    """
    molecule = _import()

    _set(kind="C", order=4)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    assert _copies(molecule) == 4

    _set(kind="C", order=9)
    bpy.ops.molecule.symmetry_preview(
        'EXEC_DEFAULT', molecule_id=molecule.identifier)
    assert _copies(molecule) == 9, "the preview did not replace the build"

    _cancel()
    assert _copies(molecule) == 4, "Cancel did not put the original C4 back"


def test_cancel_puts_back_a_deposited_assembly():
    """A generated preview over a deposited build must not eat the deposit."""
    from proteinblender.core import assembly as assembly_core

    mol_id = H.import_local("4ins.pdb", "4ins_cancel")
    molecule = H.sm().molecules[mol_id]
    assert assembly_core.build_assembly(molecule, "3")
    deposited = _copies(molecule)
    assert deposited > 1

    _set(kind="C", order=8)
    bpy.ops.molecule.symmetry_preview(
        'EXEC_DEFAULT', molecule_id=molecule.identifier)
    assert _copies(molecule) == 8

    _cancel()
    assert _copies(molecule) == deposited, (
        "Cancel did not restore the deposited assembly")
    assert assembly_core.built_assembly_id(molecule) == "3"


def test_repeated_previews_still_cancel_back_to_the_original():
    """Cancel must undo to what the dialog opened on, not to the last preview.

    The trap: recording "what to put back" on every Apply means the second
    Apply records the *first preview* as the thing to restore, and Cancel
    leaves the user with a C5 they never asked to keep.
    """
    molecule = _import()
    _set(kind="C", order=3)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    assert _copies(molecule) == 3

    for order in (5, 8, 11):
        _set(kind="C", order=order)
        bpy.ops.molecule.symmetry_preview(
            'EXEC_DEFAULT', molecule_id=molecule.identifier)
        assert _copies(molecule) == order

    _cancel()
    assert _copies(molecule) == 3, (
        "Cancel put back a preview rather than the build the dialog opened on")


def test_ok_keeps_the_committed_protein_and_puts_the_other_one_back():
    """The picker can move after an Apply, and only one build is committed.

    Preview A, change the picker to B, OK on B: B keeps its symmetry and A -
    which was only ever previewed - goes back to having none.
    """
    first = _import("first_ok")
    second = _import("second_ok")

    _set(kind="C", order=6)
    bpy.ops.molecule.symmetry_preview(
        'EXEC_DEFAULT', molecule_id=first.identifier)
    assert _copies(first) == 6

    _set(kind="C", order=4)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=second.identifier) == {'FINISHED'}

    assert _copies(second) == 4, "the protein that was OK'd lost its build"
    assert _copies(first) == UNBUILT, (
        "a protein that was only previewed kept its preview after OK")


# --------------------------------------------------------------------------
# The record the build carries
# --------------------------------------------------------------------------

def test_the_build_remembers_its_settings_after_the_sliders_move_on():
    """Why the record exists at all.

    The pb_symmetry_* controls are one set of sliders standing in for
    whichever protein is active. Building a second protein moves them, and
    the first protein's Edit pencil must still open on *its* C7.
    """
    first = _import("first")
    _set(kind="C", order=7)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=first.identifier)

    second = _import("second")
    _set(kind="C", order=3)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=second.identifier)

    assert bpy.context.scene.pb_symmetry_order == 3, "the sliders moved on"

    stored = _assembly_core().built_build_params(first)
    assert stored is not None, "the first build kept no record of its settings"
    assert stored["order"] == 7, (
        f"the first protein's build should still say 7, said {stored['order']}")
    assert _copies(first) == 7, "and it should still be a seven-fold ring"


def test_clearing_the_assembly_takes_the_record_with_it():
    molecule = _import()
    _set(kind="C", order=5)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    assert _assembly_core().built_build_params(molecule) is not None

    bpy.ops.molecule.clear_assembly(
        'EXEC_DEFAULT', molecule_id=molecule.identifier)
    assert _assembly_core().built_build_params(molecule) is None, (
        "the settings outlived the build they described")


def test_a_deposited_assembly_carries_no_generator_settings():
    from proteinblender.core import assembly as assembly_core

    mol_id = H.import_local("4ins.pdb", "4ins_params")
    molecule = H.sm().molecules[mol_id]
    assert assembly_core.build_assembly(molecule, "3")

    assert assembly_core.built_build_params(molecule) is None, (
        "a deposited assembly has no generator settings to record")


def test_the_trim_limits_travel_with_the_build():
    """Trim moved into the dialog, so it is part of what a build is made of."""
    molecule = _import()
    _set(kind="C", order=12, range_limit=0.0)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    untrimmed = _copies(molecule)
    assert untrimmed == 12

    _set(kind="C", order=12, range_limit=20.0)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    trimmed = _copies(molecule)

    assert trimmed < untrimmed, (
        f"a 20 A range limit kept all {untrimmed} copies of a 12-fold ring")
    stored = _assembly_core().built_build_params(molecule)
    assert stored["range_limit"] == pytest.approx(20.0)


# --------------------------------------------------------------------------
# Which protein the dialog opens on
# --------------------------------------------------------------------------

def _forget_the_active_molecule():
    """The state a user is in after deleting a protein, or an undo.

    Clears all three sources ``resolve_active_molecule_id`` consults, so
    nothing is active while proteins are still loaded.
    """
    bpy.context.scene.selected_molecule_id = ""
    bpy.context.scene.molecule_list_index = -1
    H.sm().active_molecule = None


def test_the_dialog_opens_on_a_loaded_protein_when_nothing_is_active():
    """Create New Symmetry is always enabled, so it gets clicked cold.

    Refusing a scene that has a protein in it merely because none is selected
    is the bug this covers: the dialog has a picker, and there is something
    to pick.
    """
    molecule = _import()
    _forget_the_active_molecule()

    assert _dialog().resolve_target(bpy.context) == molecule.identifier, (
        "the dialog would have refused a scene with a protein in it")


def test_an_explicit_request_wins_over_whatever_is_active():
    first = _import("target_first")
    second = _import("target_second")
    bpy.context.scene.selected_molecule_id = second.identifier

    assert _dialog().resolve_target(
        bpy.context, first.identifier) == first.identifier


def test_a_stale_request_falls_back_rather_than_refusing():
    """The outliner's pencil can carry an id whose protein has since gone."""
    molecule = _import()
    assert _dialog().resolve_target(
        bpy.context, "a_protein_that_was_deleted") == molecule.identifier


def test_only_an_empty_scene_leaves_the_dialog_with_nothing():
    """The one case it genuinely cannot proceed from."""
    assert not H.sm().molecules, "the scrub should have left an empty scene"
    assert _dialog().resolve_target(bpy.context) == ""


def test_an_empty_scene_is_told_what_to_do_not_what_is_missing():
    """The message a user meets on a fresh file.

    It used to read "No protein selected", which sent people looking for a
    selection that would not have helped. Nothing was selectable: a symmetry
    repeats a protein, so there has to be one first.
    """
    assert not H.sm().molecules
    with pytest.raises(RuntimeError, match="Import a protein first"):
        bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT')


# --------------------------------------------------------------------------
# Seeding the dialog
# --------------------------------------------------------------------------

def test_reopening_seeds_the_controls_from_the_build():
    """What the Edit pencil relies on: invoke's seed step, run directly.

    ``invoke`` needs a window, so the seeding it does is exercised here
    through the same two calls it makes. The UI lane drives the real dialog.
    """
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    molecule = _import()
    _set(kind="H", count=8, rise=25.0, twist=40.0)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)

    # The user wanders off and sets up a completely different symmetry.
    _set(kind="C", order=2)

    stored = _assembly_core().built_build_params(molecule)
    apply_symmetry_settings(bpy.context.scene, stored)

    scene = bpy.context.scene
    assert scene.pb_symmetry_kind == "H"
    assert scene.pb_symmetry_count == 8
    assert scene.pb_symmetry_rise == pytest.approx(25.0)
    assert scene.pb_symmetry_twist == pytest.approx(40.0)


def test_seeding_survives_a_stored_value_its_property_will_not_take():
    """One bad field must not abort the whole seed.

    A settings blob is read back from a .blend that may be older than the
    property it feeds. Seeding field by field means a renamed enum or an
    out-of-range count costs that one control, not the dialog.
    """
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )

    _import()
    _set(kind="C", order=3)
    apply_symmetry_settings(bpy.context.scene, {
        "kind": "NOT_A_REAL_KIND",       # refused by the enum
        "order": 6,                      # must still land
    })

    assert bpy.context.scene.pb_symmetry_order == 6, (
        "a rejected field stopped the rest of the seed")
