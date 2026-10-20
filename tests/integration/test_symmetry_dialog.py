"""The Symmetry Builder dialog: changes show live, OK commits, Cancel puts back.

Every change to the dialog's settings is shown at once, and there are two ways
out of it that mean different things. The tests here are about those differences, not about
the generator underneath - what a C7 *is* is settled in
``test_symmetry_builder.py`` against trigonometry.

Ground truth is the number of copies actually instanced in the depsgraph, not
the tag on the assembly node and not the settings dict that produced them. A
C7 ring has seven subunits because that is what seven-fold means; asserting
against ``built_assembly_id`` or ``built_build_params`` would pass whatever
those happened to return, including the wrong thing.
"""

import json
from types import SimpleNamespace

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
         axis=(0.0, 0.0, 1.0)):
    """Put the dialog's controls where a user would have dragged them."""
    scene = bpy.context.scene
    scene.pb_symmetry_kind = kind
    scene.pb_symmetry_order = order
    scene.pb_symmetry_count = count
    scene.pb_symmetry_rise = rise
    scene.pb_symmetry_twist = twist
    scene.pb_symmetry_axis = axis


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


def _open(molecule, source='GENERATED', assembly_id=''):
    """What the dialog's invoke does last: start showing changes live.

    Popups do not exist headless, so the session is begun directly; from
    then on the dialog's settings are written exactly as its fields write
    them, and the scene's own update callbacks do the rest.
    """
    _dialog().start_live(bpy.context.scene, molecule.identifier, source,
                         assembly_id)


def _pick(molecule, source='GENERATED', assembly_id=''):
    """What changing the dialog's protein or source picker does."""
    _dialog().follow_dialog(
        SimpleNamespace(target_id=molecule.identifier, source=source,
                        assembly_id=assembly_id), bpy.context)


def _cancel():
    """What the dialog's cancel() does, minus the redraw.

    ``cancel`` is called by Blender when a popup is dismissed, and popups do
    not exist headless. The work it delegates to is module functions
    precisely so it can be reached from here.
    """
    _dialog().stop_live()
    return _dialog().discard_previews()


@pytest.fixture(autouse=True)
def _no_previews_leak_between_tests():
    """Previews are module state, which the scene scrub does not reach."""
    _dialog().stop_live()
    _dialog().discard_previews()
    yield
    _dialog().stop_live()
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


def test_ok_puts_symmetry_beneath_its_source_protein():
    molecule = _import()
    _set(kind="C", order=5)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier) == {'FINISHED'}
    row = _symmetry_rows()[0]
    assert row.indent_level == 1
    assert row.parent_id == molecule.identifier
    assert "C5" in row.name
    protein = _row(molecule.identifier)
    assert protein.parent_id == ""
    assert protein.indent_level == 0
    assert _first_chain(molecule.identifier).indent_level == 1


def test_clearing_symmetry_preserves_the_source_hierarchy():
    molecule = _import()
    _set(kind="C", order=5)
    bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', target_id=molecule.identifier)
    bpy.ops.molecule.clear_assembly('EXEC_DEFAULT', molecule_id=molecule.identifier)
    assert _row(molecule.identifier).indent_level == 0
    assert _first_chain(molecule.identifier).indent_level == 1
    assert not _symmetry_rows()


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


def test_biological_assembly_has_a_child_row():
    mol_id = H.import_local("4ins.pdb", "4ins")
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=mol_id, source='BIOLOGICAL', assembly_id='3') == {'FINISHED'}
    row = _symmetry_rows()[0]
    assert row.parent_id == mol_id
    assert "Biological" in row.name
    assert _copies(H.sm().molecules[mol_id]) == 3


@pytest.mark.parametrize("scope", ["CHAIN", "DOMAIN"])
def test_symmetry_repeats_only_its_chosen_chain_or_domain(scope):
    mid = H.import_local("4hhb.pdb", "hb")
    chain_id = _first_chain(mid).item_id
    bpy.ops.proteinblender.edit_chain_domains(item_id=chain_id, layout_json=_split_payload(chain_id, 2))
    scene = bpy.context.scene
    target = (chain_id if scope == "CHAIN" else next(
        r.item_id for r in scene.outliner_items if r.item_type == 'DOMAIN'))
    from proteinblender.operators.pivot_operators import row_objects
    target_objects = {o.name for o in row_objects(bpy.context, _row(target))}
    _set(kind='C', order=3)
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=target) == {'FINISHED'}
    row = _symmetry_rows()[0]
    assert row.parent_id == target
    parent_depth = next(r.indent_level for r in scene.outliner_items if r.item_id == target)
    assert row.indent_level == parent_depth + 1
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    for domain in H.sm().molecules[mid].domains.values():
        name = domain.object.name
        copies = sum(i.is_instance and i.parent is not None
                     and i.parent.original.name == name for i in graph.object_instances)
        assert copies == (3 if name in target_objects else 1), name


# --------------------------------------------------------------------------
# Edit - the dialog opened on an assembly is also where it is worked on
# --------------------------------------------------------------------------

def _filament(molecule):
    """Five copies marching 20 A apart along -Y, a cutaway's default side."""
    _set(kind="H", count=5, rise=20.0, twist=30.0, axis=(0.0, -1.0, 0.0))
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=molecule.identifier, source='GENERATED') == {'FINISHED'}
    assert _copies(molecule) == 5


def _opened_on(molecule, source='GENERATED', assembly_id=''):
    """What the dialog notes down when a row's pencil opens it."""
    from types import SimpleNamespace
    return _dialog().dialog_signature(
        SimpleNamespace(target_id=molecule.identifier, source=source,
                        assembly_id=assembly_id),
        bpy.context.scene)


def _ok(molecule, opened_on):
    return bpy.ops.molecule.symmetry_dialog(
        target_id=molecule.identifier, source='GENERATED', opened_on=opened_on)


def test_ok_with_nothing_changed_keeps_a_cutaway():
    """OK builds what was asked for, and nothing new was asked for.

    The cutaway is made from inside the dialog, so the OK that closes it must
    not be what puts the cut copies back.
    """
    molecule = _import()
    _filament(molecule)
    opened_on = _opened_on(molecule)

    # Copies sit 0, 20, 40, 60 and 80 A out; a plane at 50 A takes the last two.
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=50) == {'FINISHED'}
    assert _copies(molecule) == 3

    assert _ok(molecule, opened_on) == {'CANCELLED'}
    assert _copies(molecule) == 3


def test_ok_with_a_changed_setting_rebuilds_the_assembly_whole():
    molecule = _import()
    _filament(molecule)
    opened_on = _opened_on(molecule)
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=50) == {'FINISHED'}

    bpy.context.scene.pb_symmetry_count = 4

    assert _ok(molecule, opened_on) == {'FINISHED'}
    assert _copies(molecule) == 4


def test_ok_does_not_build_over_realized_copies():
    """Realize Copies ends the assembly; OK must not start another on top."""
    molecule = _import()
    _filament(molecule)
    opened_on = _opened_on(molecule)
    before = set(bpy.data.objects.keys())

    assert bpy.ops.molecule.realize_copies(
        molecule_id=molecule.identifier) == {'FINISHED'}
    realized = set(bpy.data.objects.keys()) - before
    assert realized

    assert _ok(molecule, opened_on) == {'CANCELLED'}
    assert _copies(molecule) == UNBUILT
    assert set(bpy.data.objects.keys()) - before == realized


def test_ok_builds_when_a_preview_is_outstanding():
    """Settings put back by hand are not the same as nothing having happened.

    Something else was shown in between, and OK is what keeps the result.
    """
    molecule = _import()
    _filament(molecule)
    opened_on = _opened_on(molecule)
    _open(molecule)

    bpy.context.scene.pb_symmetry_count = 7
    assert _copies(molecule) == 7
    bpy.context.scene.pb_symmetry_count = 5
    assert _copies(molecule) == 5

    assert _ok(molecule, opened_on) == {'FINISHED'}
    assert _copies(molecule) == 5


def test_a_scripted_call_builds_whatever_is_already_there():
    """Only a dialog opened on an assembly has anything to leave alone."""
    molecule = _import()
    _filament(molecule)
    assert bpy.ops.molecule.cutaway(
        molecule_id=molecule.identifier, normal=(0, -1, 0), offset=50) == {'FINISHED'}
    assert _copies(molecule) == 3

    assert bpy.ops.molecule.symmetry_dialog(
        target_id=molecule.identifier, source='GENERATED') == {'FINISHED'}
    assert _copies(molecule) == 5


# --------------------------------------------------------------------------
# Live - every change shown as it is made
# --------------------------------------------------------------------------

def test_a_change_shows_the_same_thing_ok_keeps():
    """What the viewport shows during the dialog is what stays when it closes."""
    first = _import("ubq_live")
    _open(first)
    _set(kind="D", order=3)

    # A D3 is two rings of three - six copies, by definition of dihedral.
    assert _copies(first) == 6

    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=first.identifier) == {'FINISHED'}
    assert _copies(first) == 6


def test_every_number_shows_as_it_changes():
    """No button in between: each setting written is drawn at once."""
    molecule = _import()
    _set(kind="H", count=4, rise=20.0, twist=30.0)
    _open(molecule)

    scene = bpy.context.scene
    scene.pb_symmetry_count = 6
    assert _copies(molecule) == 6
    scene.pb_symmetry_length = 4.0          # 40 A at 20 A a subunit: two of them
    assert _copies(molecule) == 2
    scene.pb_symmetry_strands = 3
    assert _copies(molecule) == 6
    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 5
    assert _copies(molecule) == 5


def test_opening_the_dialog_builds_nothing():
    """Only a change is shown: opening on an unbuilt protein leaves it so."""
    molecule = _import()
    _set(kind="C", order=4)
    _open(molecule)
    assert _copies(molecule) == UNBUILT

    # Written again with what it already says - not a change.
    bpy.context.scene.pb_symmetry_order = 4
    assert _copies(molecule) == UNBUILT
    assert not _dialog().pending_previews()


def test_with_no_dialog_open_the_settings_build_nothing():
    """The settings are the dialog's controls; a script writing them is not it."""
    molecule = _import()
    _set(kind="C", order=6)
    assert _copies(molecule) == UNBUILT


def test_after_ok_or_cancel_the_settings_build_nothing_more():
    molecule = _import()
    _open(molecule)
    _set(kind="C", order=6)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier) == {'FINISHED'}
    _set(kind="C", order=8)
    assert _copies(molecule) == 6

    _open(molecule)
    _set(kind="C", order=3)
    _cancel()
    _set(kind="C", order=9)
    assert _copies(molecule) == 6


def test_a_change_re_places_the_copies_it_already_has():
    """A drag must keep up, and must not lose what is keyed on the assembly.

    The same kind of build on the same protein is written into the point
    clouds it already has - no object made or removed - so a factor keyed on
    the assembly node keeps its animation.
    """
    core = _assembly_core()
    molecule = _import()
    _set(kind="C", order=4)
    bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', target_id=molecule.identifier)
    assert core.keyframe_assembly(molecule, frame=1) > 0

    before = {o.name: o.as_pointer() for o in bpy.data.objects}
    _open(molecule)
    bpy.context.scene.pb_symmetry_order = 9
    assert _copies(molecule) == 9
    assert {o.name: o.as_pointer() for o in bpy.data.objects} == before

    group = next(m for m in _a_domain_object(molecule).modifiers
                 if m.type == 'NODES').node_group
    assert group.animation_data and group.animation_data.action, (
        "the keyed assemble factor was lost")


def test_copies_re_placed_at_a_new_count_sit_at_the_origin():
    """Resized point clouds hold real positions, not whatever memory held.

    The node tree places copies from attributes, and the points themselves
    sit at the origin; a NaN left there gave the cloud a NaN bounding box.
    """
    import numpy as np

    core = _assembly_core()
    molecule = _import()
    _set(kind="C", order=4)
    bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', target_id=molecule.identifier)
    _open(molecule)
    bpy.context.scene.pb_symmetry_order = 23
    assert _copies(molecule) == 23

    clouds = [points for _group, node in core._assembly_nodes(molecule)
              for points, _chain in core._point_clouds(node.node_tree)]
    assert clouds
    for points in clouds:
        co = np.empty(len(points.data.vertices) * 3)
        points.data.vertices.foreach_get("co", co)
        assert len(co) == 23 * 3 and np.all(co == 0.0), points.name


def test_picking_another_source_shows_it_at_once():
    """The source and the deposited assembly are settings like the numbers."""
    from proteinblender.core import assembly as assembly_core

    mol_id = H.import_local("4ins.pdb", "4ins_live")
    molecule = H.sm().molecules[mol_id]
    _set(kind="C", order=5)
    _open(molecule)
    bpy.context.scene.pb_symmetry_order = 7
    assert _copies(molecule) == 7

    deposited = len(assembly_core._operators_for(molecule, "3"))
    _pick(molecule, source='BIOLOGICAL', assembly_id="3")
    assert assembly_core.built_assembly_id(molecule) == "3"
    assert _copies(molecule) == deposited


def test_ok_keeps_what_is_shown_without_building_it_again(monkeypatch):
    """OK on a change already on screen keeps that build as it is."""
    molecule = _import()
    _open(molecule)
    _set(kind="C", order=7)
    assert _copies(molecule) == 7

    builds = []
    real = _dialog().build_dialog_symmetry
    monkeypatch.setattr(_dialog(), "build_dialog_symmetry",
                        lambda *a, **k: builds.append(a) or real(*a, **k))
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier) == {'FINISHED'}
    assert not builds, "OK built again what was already on screen"
    assert _copies(molecule) == 7


# --------------------------------------------------------------------------
# Cancel - put back what was there
# --------------------------------------------------------------------------

def test_cancel_after_a_preview_leaves_nothing_built():
    """The dialog opened on an unbuilt protein, so Cancel must leave it so."""
    molecule = _import()
    before = _copies(molecule)
    assert before == UNBUILT

    _open(molecule)
    _set(kind="C", order=6)
    assert _copies(molecule) == 6, "the change was not shown"

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

    _open(molecule)
    _set(kind="C", order=9)
    assert _copies(molecule) == 9, "the change did not replace the build"

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

    _open(molecule)
    _set(kind="C", order=8)
    assert _copies(molecule) == 8

    _cancel()
    assert _copies(molecule) == deposited, (
        "Cancel did not restore the deposited assembly")
    assert assembly_core.built_assembly_id(molecule) == "3"


def test_repeated_previews_still_cancel_back_to_the_original():
    """Cancel must undo to what the dialog opened on, not to the last preview.

    The trap: recording "what to put back" on every change means the second
    change records the *first preview* as the thing to restore, and Cancel
    leaves the user with a C5 they never asked to keep.
    """
    molecule = _import()
    _set(kind="C", order=3)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    assert _copies(molecule) == 3

    _open(molecule)
    for order in (5, 8, 11):
        _set(kind="C", order=order)
        assert _copies(molecule) == order

    _cancel()
    assert _copies(molecule) == 3, (
        "Cancel put back a preview rather than the build the dialog opened on")


def test_ok_keeps_the_committed_protein_and_puts_the_other_one_back():
    """The picker can move after a change is shown, and only one build is kept.

    Show A, change the picker to B, OK on B: B keeps its symmetry and A -
    which was only ever previewed - goes back to having none.
    """
    first = _import("first_ok")
    second = _import("second_ok")

    _open(first)
    _set(kind="C", order=6)
    assert _copies(first) == 6

    _pick(second)
    assert _copies(second) == 6
    _set(kind="C", order=4)
    assert _copies(second) == 4
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


def test_there_is_no_trimming_any_more():
    """Trim Copies is gone: no controls for it, and nothing a build records.

    A build made before it went may still carry a range limit in its record;
    rebuilt from that record, it is whole - every copy the settings make.
    """
    from proteinblender.operators.assembly_operators import (
        build_generated_symmetry,
    )

    scene = bpy.context.scene
    assert not hasattr(scene, "pb_symmetry_range")
    assert not hasattr(scene, "pb_symmetry_contact")

    molecule = _import()
    _set(kind="C", order=12)
    bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier)
    stored = _assembly_core().built_build_params(molecule)
    assert "range_limit" not in stored and "contact" not in stored

    # 2 r sin(pi / 12) puts neighbours of a ring this size well over 1 A
    # apart, so a 1 A range would have kept the original alone.
    ok, _message = build_generated_symmetry(
        molecule, dict(stored, range_limit=1.0, contact=1.0))
    assert ok
    assert _copies(molecule) == 12


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


def test_an_empty_scene_is_told_what_to_do_not_what_is_missing(monkeypatch):
    """The message a user meets on a fresh file.

    It used to read "No protein selected", which sent people looking for a
    selection that would not have helped. Nothing was selectable: a symmetry
    repeats a protein, so there has to be one first. With nothing typed into
    the dialog's Protein block there is nothing to fetch either.
    """
    assert not H.sm().molecules
    _refuse_downloads(monkeypatch)
    assert not bpy.context.scene.protein_props.pdb_id
    with pytest.raises(RuntimeError, match="Import a protein first"):
        bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT')


# --------------------------------------------------------------------------
# OK on an empty scene, with an id typed into the dialog's own Protein block
# --------------------------------------------------------------------------

def _serve_downloads_from(monkeypatch, fixture):
    """Answer the add-on's structure download from a bundled file, offline.

    Only the HTTP call is replaced. The text it returns goes through the real
    stream, parser, import and finalisation, exactly as a Download does.
    """
    import gzip
    from proteinblender.utils.molecularnodes import download
    served = gzip.open(H.data_path(fixture), 'rt', encoding='utf-8').read()
    requested = []

    class Response:
        status_code = 200

        def __init__(self):
            self.text = served
            self.content = served.encode('utf-8')

    def answer(url, *args, **kwargs):
        requested.append(url)
        return True, Response()

    monkeypatch.setattr(download, '_download_with_retry', answer)
    return requested


def _refuse_downloads(monkeypatch):
    from proteinblender.utils.molecularnodes import download

    def refused(url, *args, **kwargs):
        raise AssertionError(f'no download should be attempted, but {url} was')

    monkeypatch.setattr(download, '_download_with_retry', refused)


def test_ok_with_a_typed_id_imports_it_and_builds_its_deposited_assembly(scene, monkeypatch):
    """Reported: Create New Assembly on an empty scene, type 1atn, OK, and the
    answer was "Import a protein first - a symmetry repeats one".

    The id was sitting in the dialog's own Protein block. OK has to do with it
    what Download would have done, and then build - in the default format,
    with the molecule named as a download names it.
    """
    assert not H.sm().molecules
    requested = _serve_downloads_from(monkeypatch, '1atn.cif.gz')
    props = scene.protein_props
    props.pdb_id = '1atn'  # exactly the property write the Info log recorded
    assert (props.import_method, props.remote_format) == ('PDB', 'cif')

    assert bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', source='BIOLOGICAL') == {'FINISHED'}

    assert len(requested) == 1, requested
    assert '1atn' in requested[0].lower() and requested[0].endswith('.cif'), requested
    molecules = H.sm().molecules
    assert list(molecules) == ['1atn_001'], 'OK must import the typed structure'
    molecule = molecules['1atn_001']
    # 1ATN deposits one assembly, id 1 (the identity over every chain).
    assert _assembly_core().built_assembly_id(molecule) == '1'
    assert any(r.item_type == 'SYMMETRY' for r in scene.outliner_items), [
        (r.item_type, r.name) for r in scene.outliner_items]


def test_ok_with_an_id_that_will_not_download_says_which_id_failed(scene, monkeypatch):
    """A typo or an offline machine must not fall back to the generic message."""
    from proteinblender.utils.molecularnodes import download
    monkeypatch.setattr(download, '_download_with_retry',
                        lambda url, *args, **kwargs: (False, f'File not found (404): {url}'))
    scene.protein_props.pdb_id = 'xxxx'
    with pytest.raises(RuntimeError, match='Could not import xxxx'):
        bpy.ops.molecule.symmetry_dialog('EXEC_DEFAULT', source='BIOLOGICAL')
    assert not H.sm().molecules


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


def _split_payload(chain_id, count):
    row = next(r for r in bpy.context.scene.outliner_items if r.item_id == chain_id)
    low, high = row.chain_start, row.chain_end
    size = high - low + 1
    return json.dumps([dict(name=f"Piece {i+1}",
        start=low + size*i//count, end=low + size*(i+1)//count - 1)
        for i in range(count)])


@pytest.mark.parametrize("filename, expected", [
    ("4ins.pdb", {"1", "2", "3", "4", "5", "6", "7"}),
    ("1ubq.pdb", {"1"}),
])
def test_deposited_picker_includes_identity_and_chain_subset_assemblies(filename, expected):
    from types import SimpleNamespace

    mid = H.import_local(filename, "picker")
    items = _dialog().biological_enum_items(SimpleNamespace(target_id=mid), bpy.context)
    assert {item[0] for item in items} == expected


def test_deposited_assembly_can_be_built_for_the_second_loaded_protein():
    H.import_local('1ubq.pdb', 'first_monomer')
    mid = H.import_local('4ins.pdb', 'second_insulin')
    assert bpy.ops.molecule.symmetry_dialog(
        target_id=mid, source='BIOLOGICAL', assembly_id='3') == {'FINISHED'}
    assert _copies(H.sm().molecules[mid]) == 3
    assert _copies(H.sm().molecules['first_monomer']) == 1
