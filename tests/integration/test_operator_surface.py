"""Coverage for public operators that previously had no direct regression test."""

import bpy
import pytest

import helpers as H


@pytest.mark.integration
def test_import_local_public_operator_uses_real_filepath(scene, sm):
    result = bpy.ops.molecule.import_local("EXEC_DEFAULT", filepath=H.data_path("1ubq.pdb"))
    assert result == {"FINISHED"}
    assert len(sm.molecules) == 1
    assert next(iter(sm.molecules)).startswith("1ubq")


@pytest.mark.integration
def test_update_identifier_rekeys_runtime_and_persistent_state(scene, sm, single_chain):
    scene.selected_molecule_id = single_chain
    scene.edit_molecule_identifier = "renamed_ubiquitin"
    assert bpy.ops.molecule.update_identifier() == {"FINISHED"}
    assert single_chain not in sm.molecules
    assert "renamed_ubiquitin" in sm.molecules
    assert H.list_item("renamed_ubiquitin") is not None
    assert scene.selected_molecule_id == "renamed_ubiquitin"


@pytest.mark.integration
def test_select_object_selects_parent_and_domain(scene, sm, single_chain):
    molecule = sm.molecules[single_chain]
    scene.selected_molecule_id = single_chain
    assert bpy.ops.molecule.select_object(object_id=single_chain, is_domain=False) == {"FINISHED"}
    assert bpy.context.active_object == molecule.object
    domain_id, domain = next(iter(molecule.domains.items()))
    assert bpy.ops.molecule.select_object(object_id=domain_id, is_domain=True) == {"FINISHED"}
    assert bpy.context.active_object == domain.object


@pytest.mark.integration
def test_snap_parent_pivot_center_is_finite(scene, sm, single_chain):
    import math
    from proteinblender.core import domain_space

    molecule = sm.molecules[single_chain]
    assert bpy.ops.molecule.snap_protein_pivot_center(
        molecule_id=single_chain) == {"FINISHED"}
    after = domain_space.get_pivot(molecule.object)
    assert all(math.isfinite(value) for value in after)


@pytest.mark.integration
def test_snap_parent_pivot_center_lands_inside_the_molecule(scene, sm,
                                                            single_chain):
    """A "centre" outside the thing it centres is wrong however it was reached.

    Ground truth is Blender's own evaluated geometry - the point-cloud atoms it
    drew, mapped by each instance's ``matrix_world`` - so nothing here shares a
    code path with the operator. That matters: the operator averaged
    ``obj.matrix_world @ corner`` over ``obj.bound_box``, and ``bound_box`` is
    the *raw* mesh's bounds, which have not been through the geometry-nodes
    pivot. The two errors compose into a centre displaced by exactly the pivot,
    and asserting only that the result is finite never noticed.
    """
    import numpy as np

    molecule = sm.molecules[single_chain]
    objects = [molecule.object] + [d.object for d in molecule.domains.values()
                                   if d.object]

    assert bpy.ops.molecule.snap_protein_pivot_center(
        molecule_id=single_chain) == {"FINISHED"}
    bpy.context.view_layer.update()

    atoms = H.evaluated_atom_positions(objects)
    assert len(atoms) > 0, "the molecule evaluated to no drawable atoms"

    low, high = atoms.min(axis=0), atoms.max(axis=0)
    centre = np.array(molecule.object.matrix_world.translation)
    for axis in range(3):
        assert low[axis] <= centre[axis] <= high[axis], (
            f"the 'centre' pivot fell outside the molecule on axis {axis}: "
            f"{centre[axis]} is not within [{low[axis]}, {high[axis]}]")


@pytest.mark.integration
def test_initialize_domain_temp_name_is_observable(scene, sm, single_chain):
    molecule = sm.molecules[single_chain]
    domain_id, domain = next(iter(molecule.domains.items()))
    scene.selected_molecule_id = single_chain
    domain.object.temp_domain_name = ""
    assert bpy.ops.molecule.initialize_domain_temp_name(domain_id=domain_id) == {"FINISHED"}
    assert domain.object.temp_domain_name == domain.name


@pytest.mark.integration
def test_missing_targets_cancel_instead_of_crashing():
    # Blender promotes operator report({'ERROR'}, ...) into RuntimeError for
    # scripted callers; that is a clean refusal, not an internal traceback.
    with pytest.raises(RuntimeError, match="Molecule 'missing' not found"):
        bpy.ops.molecule.select_object(object_id="missing", is_domain=False)
    with pytest.raises(RuntimeError, match="Molecule object not found"):
        bpy.ops.molecule.snap_protein_pivot_center(molecule_id="missing")
    with pytest.raises(RuntimeError, match="File not found"):
        bpy.ops.molecule.import_local(
            "EXEC_DEFAULT", filepath="/definitely/not/a/protein.pdb")


@pytest.mark.integration
def test_panel_animation_operator_surface_handles_valid_and_invalid_frames(scene):
    scene.frame_set(1)
    assert bpy.ops.proteinblender.edit_keyframe(
        frame=17, skip_dialog=True) == {"FINISHED"}
    assert scene.frame_current == 17
    assert bpy.ops.proteinblender.edit_keyframe(
        frame=-1, skip_dialog=True) == {"CANCELLED"}
    # With no keyframed targets, deletion is still a clean idempotent action.
    assert bpy.ops.proteinblender.delete_keyframe(frame=17) == {"FINISHED"}


@pytest.mark.integration
def test_panel_internal_actions_fail_cleanly_without_dialog_state():
    with pytest.raises(RuntimeError, match="Invalid pose index"):
        bpy.ops.proteinblender.capture_pose(pose_index=999)
    assert bpy.ops.proteinblender.toggle_puppet_selection(
        puppet_id="missing", operator_instance_id="missing") == {"CANCELLED"}
    assert bpy.ops.pb2.show_help_popup(
        "EXEC_DEFAULT", title="Test", message="Help text") == {"FINISHED"}
