"""A puppet's poses carry its filament's bend and its subunit count.

Janet (2026-10-30) animated an actin filament the way she animates proteins:
"I tried making a puppet of the actin filament, then made two poses (straight
and bent) ... pose didn't record the movement of the bend controller", and
"I tried making the filament into a puppet and making the changes to monomer
number, but it didn't seem to be recorded."

A pose kept only the puppet's chain transforms. A filament's shape is its bend
rig (a curve and its control nodes) and the numbers its copies are placed from,
none of which are chain transforms. Now a pose keeps both, Apply Pose puts both
back, and keying the puppet keys both.

Ground truth is the drawn scene: copies counted from the evaluated instances,
and the bend read off where Blender draws the middle subunits.
"""
import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration

STRAIGHT_COUNT = 10      # 27.5 nm of actin
LONG_COUNT = 14


def _build_actin():
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset='ACTIN', length=27.5) == {'FINISHED'}
    (new,) = set(H.sm().molecules) - before
    return H.sm().molecules[new]


def _copies(molecule):
    names = {d.object.name for d in molecule.domains.values() if d.object}
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    per_object = {}
    for inst in depsgraph.object_instances:
        if inst.is_instance and inst.parent is not None and inst.parent.original.name in names:
            per_object[inst.parent.original.name] = per_object.get(inst.parent.original.name, 0) + 1
    counts = set(per_object.values())
    assert len(counts) == 1, per_object
    return counts.pop()


def _copy_centres(molecule):
    """Where each drawn copy of the chain stands, in Blender units, sorted."""
    names = {d.object.name for d in molecule.domains.values() if d.object}
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    centres = [tuple(np.round(np.array(inst.matrix_world.translation), 4))
               for inst in depsgraph.object_instances
               if inst.is_instance and inst.parent is not None
               and inst.parent.original.name in names]
    return np.array(sorted(centres))


def _straightness(molecule):
    """How far the copies stray from the line through the first and last.

    0 for a straight filament (its copies spiral about the line by the same
    small radius all along, which the median removes); grows as it bends.
    """
    c = _copy_centres(molecule)
    order = np.argsort(c[:, 2] if np.ptp(c[:, 2]) > np.ptp(c[:, 0]) else c[:, 0])
    c = c[order]
    a, b = c[0], c[-1]
    axis = (b - a) / np.linalg.norm(b - a)
    rel = c - a
    off = np.linalg.norm(rel - np.outer(rel @ axis, axis), axis=1)
    return float(off.max() - np.median(off))


def _puppet_of(molecule, name="Filament Puppet"):
    scene = bpy.context.scene
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    chains = [it for it in scene.outliner_items
              if it.item_type == "CHAIN" and it.parent_id == molecule.identifier]
    for it in scene.outliner_items:
        it.is_selected = it.item_id in {c.item_id for c in chains}
    assert bpy.ops.proteinblender.create_puppet('EXEC_DEFAULT', puppet_name=name) == {'FINISHED'}
    return next(p for p in scene.outliner_items
                if p.item_type == "PUPPET" and p.name == name)


def _bend_and_lengthen(molecule):
    from proteinblender.core import assembly, symmetry_bend
    from proteinblender.operators.assembly_operators import build_generated_symmetry

    nodes = symmetry_bend.get_bend_nodes(molecule)
    nodes[len(nodes) // 2].location.x += 0.6
    bpy.context.view_layer.update()
    settings = dict(assembly.built_build_params(molecule))
    settings["count"] = LONG_COUNT
    ok, message = build_generated_symmetry(molecule, settings)
    assert ok, message


def _create_pose(name, puppet):
    assert bpy.ops.proteinblender.create_pose(
        'EXEC_DEFAULT', pose_name=name, puppet_ids=puppet.item_id) == {'FINISHED'}
    return len(bpy.context.scene.pose_library) - 1


def _key_puppet(puppet, frame):
    controller = bpy.data.objects[puppet.controller_object_name]
    return bpy.ops.proteinblender.create_keyframe(
        'EXEC_DEFAULT', frame_number=frame,
        puppet_items=[{
            "name": puppet.name,
            "puppet_id": puppet.item_id,
            "puppet_name": puppet.name,
            "controller_object_name": controller.name,
            "item_kind": "PUPPET",
            "use_puppet": True,
            "keyframe_location": True,
            "keyframe_rotation": True,
            "keyframe_scale": True,
            "keyframe_pose": True,
            "keyframe_color": False,
            "brownian_enabled": False,
        }])


def test_a_pose_restores_a_filament_bend_and_subunit_count():
    molecule = _build_actin()
    puppet = _puppet_of(molecule)
    straight = _create_pose("Straight", puppet)
    assert _copies(molecule) == STRAIGHT_COUNT
    flat = _straightness(molecule)

    _bend_and_lengthen(molecule)
    bent = _create_pose("Bent", puppet)
    assert _copies(molecule) == LONG_COUNT
    curved = _straightness(molecule)
    assert curved > flat + 0.05, "the drag did not bend the filament"

    assert bpy.ops.proteinblender.apply_pose(pose_index=straight) == {'FINISHED'}
    assert _copies(molecule) == STRAIGHT_COUNT, "Apply Pose left the subunit count"
    assert _straightness(molecule) == pytest.approx(flat, abs=0.01), (
        "Apply Pose left the bend")

    assert bpy.ops.proteinblender.apply_pose(pose_index=bent) == {'FINISHED'}
    assert _copies(molecule) == LONG_COUNT
    assert _straightness(molecule) == pytest.approx(curved, abs=0.01)


def test_capture_pose_updates_the_filament_shape_too():
    molecule = _build_actin()
    puppet = _puppet_of(molecule)
    index = _create_pose("Shape", puppet)
    _bend_and_lengthen(molecule)
    assert bpy.ops.proteinblender.capture_pose(pose_index=index) == {'FINISHED'}

    # Undo the shape by hand, then let the pose put it back.
    from proteinblender.core import assembly
    from proteinblender.operators.assembly_operators import build_generated_symmetry
    settings = dict(assembly.built_build_params(molecule))
    settings["count"] = STRAIGHT_COUNT
    assert build_generated_symmetry(molecule, settings)[0]
    assert _copies(molecule) == STRAIGHT_COUNT

    assert bpy.ops.proteinblender.apply_pose(pose_index=index) == {'FINISHED'}
    assert _copies(molecule) == LONG_COUNT


def test_keying_a_puppet_after_each_pose_animates_its_filament():
    """Janet's workflow: apply a pose, key the puppet, at two frames; play it."""
    scene = bpy.context.scene
    molecule = _build_actin()
    puppet = _puppet_of(molecule)
    straight = _create_pose("Straight", puppet)
    flat = _straightness(molecule)
    _bend_and_lengthen(molecule)
    bent = _create_pose("Bent", puppet)
    curved = _straightness(molecule)

    scene.frame_set(1)
    assert bpy.ops.proteinblender.apply_pose(pose_index=straight) == {'FINISHED'}
    assert _key_puppet(puppet, 1) == {'FINISHED'}
    scene.frame_set(40)
    assert bpy.ops.proteinblender.apply_pose(pose_index=bent) == {'FINISHED'}
    assert _key_puppet(puppet, 40) == {'FINISHED'}

    scene.frame_set(1)
    assert _copies(molecule) == STRAIGHT_COUNT
    assert _straightness(molecule) == pytest.approx(flat, abs=0.01)
    scene.frame_set(40)
    assert _copies(molecule) == LONG_COUNT
    assert _straightness(molecule) == pytest.approx(curved, abs=0.01)
    scene.frame_set(20)
    assert STRAIGHT_COUNT <= _copies(molecule) <= LONG_COUNT
