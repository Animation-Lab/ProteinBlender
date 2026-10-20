"""Keyframing a filament: where it is, how it bends, and its numbers.

A filament is keyed from Animate Scene's Create Keyframe like a membrane: one
row, and ticking it keys the molecule's transform, its bend control nodes and
every number it is built from (``core.filament_animation``). The copies then
follow the keys on every frame change - in the viewport and in an animation
render, which evaluates into a depsgraph of its own.

Ground truth is what Blender draws: copies counted on the depsgraph, subunit
centres read from drawn atoms, pixels in a rendered frame. Expected values
come from the keys themselves and Bezier arithmetic done here: a key at frame
1 and another at frame 41, both with Blender's default easing, meet at their
average at frame 21.
"""

import math

import bpy
import numpy as np
import pytest
from mathutils import Vector

import filament_checks as F
import helpers as H

WORLD_SCALE = 0.01
ACTIN_RISE = 27.5


def _anim():
    from proteinblender.core import filament_animation
    return filament_animation


def _assembly_core():
    from proteinblender.core import assembly
    return assembly


def _bend():
    from proteinblender.core import symmetry_bend
    return symmetry_bend


def _build(length=27.5, preset='ACTIN'):
    before = set(H.sm().molecules)
    assert bpy.ops.molecule.build_filament(
        'EXEC_DEFAULT', preset=preset, length=length) == {'FINISHED'}
    (new,) = set(H.sm().molecules) - before
    return H.sm().molecules[new]


def _copies(molecule):
    obj_name = next(iter(molecule.domains.values())).object.name
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    return len([i for i in depsgraph.object_instances
                if i.is_instance and i.parent is not None
                and i.parent.original.name == obj_name])


def _key(molecule, frame):
    """Tick the filament's row in Create Keyframe and press OK."""
    obj = molecule.object
    return bpy.ops.proteinblender.create_keyframe(
        'EXEC_DEFAULT', frame_number=frame,
        puppet_items=[{
            "name": molecule.identifier,
            "puppet_id": molecule.identifier,
            "puppet_name": molecule.identifier,
            "controller_object_name": obj.name,
            "item_kind": "FILAMENT",
            "use_puppet": True,
            "keyframe_location": True,
            "keyframe_rotation": True,
            "keyframe_scale": True,
            "keyframe_pose": False,
            "keyframe_color": False,
            "brownian_enabled": False,
        }])


def _edit(molecule, **changes):
    """Reopen Edit Assembly on the filament, change settings, and OK."""
    from proteinblender.operators.assembly_operators import (
        apply_symmetry_settings,
    )
    scene = bpy.context.scene
    apply_symmetry_settings(scene, _assembly_core().built_build_params(molecule))
    for prop, value in changes.items():
        setattr(scene, f"pb_symmetry_{prop}", value)
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id=molecule.identifier,
        source='GENERATED') == {'FINISHED'}


def _twist_between_neighbours(molecule):
    """Degrees round the axis from one drawn subunit to the next.

    The axis is the straight bend path, read off its first and last nodes.
    """
    preset = F.presets().get("ACTIN")
    centres = F.chain_centres(molecule, preset)
    nodes = [np.array(n.matrix_world.translation) / WORLD_SCALE
             for n in _bend().get_bend_nodes(molecule)]
    start, axis = nodes[0], nodes[-1] - nodes[0]
    axis /= np.linalg.norm(axis)
    along = (centres - start) @ axis
    order = np.argsort(along)
    side = np.cross(axis, [1.0, 0.0, 0.0])
    side /= np.linalg.norm(side)
    other = np.cross(axis, side)
    radial = centres[order] - start - np.outer(along[order], axis)
    angles = np.degrees(np.arctan2(radial @ other, radial @ side))
    steps = (np.diff(angles) + 180.0) % 360.0 - 180.0
    return float(np.median(steps))


# --------------------------------------------------------------------------
# Offered for keyframing
# --------------------------------------------------------------------------

def test_a_filament_is_offered_for_keyframing_by_its_name():
    from proteinblender.operators.keyframe_operators import get_keyframe_targets

    molecule = _build()
    filaments = [t for t in get_keyframe_targets(bpy.context) if t[2] == 'FILAMENT']
    assert len(filaments) == 1
    label, obj, _kind, item_id = filaments[0]
    assert obj == molecule.object and item_id == molecule.identifier
    assert label == F.presets().get("ACTIN").label


def test_a_protein_with_no_helix_is_not_offered():
    from proteinblender.operators.keyframe_operators import get_keyframe_targets

    H.import_local("1ubq.pdb", "ubq")
    scene = bpy.context.scene
    scene.pb_symmetry_kind = "C"
    scene.pb_symmetry_order = 3
    assert bpy.ops.molecule.symmetry_dialog(
        'EXEC_DEFAULT', target_id="ubq") == {'FINISHED'}
    assert not [t for t in get_keyframe_targets(bpy.context) if t[2] == 'FILAMENT']


# --------------------------------------------------------------------------
# The numbers
# --------------------------------------------------------------------------

def test_a_keyed_length_plays_back_as_a_growing_filament():
    """Ten subunits at frame 1, forty at frame 41: twenty-five at frame 21."""
    scene = bpy.context.scene
    molecule = _build(27.5)
    assert _copies(molecule) == 10

    scene.frame_set(1)
    assert _key(molecule, 1) == {'FINISHED'}
    scene.frame_set(41)
    _edit(molecule, length=110.0)
    assert _copies(molecule) == 40
    assert _key(molecule, 41) == {'FINISHED'}

    scene.frame_set(21)
    assert _copies(molecule) == 25
    # Edit Assembly opens on what is on screen.
    assert _assembly_core().built_build_params(molecule)["count"] == 25
    scene.frame_set(1)
    assert _copies(molecule) == 10
    scene.frame_set(41)
    assert _copies(molecule) == 40


def test_a_keyed_twist_plays_back():
    """Actin's -166.7 degrees at frame 1, -150 at 41: half way at frame 21."""
    scene = bpy.context.scene
    molecule = _build(27.5)
    scene.frame_set(1)
    _key(molecule, 1)
    assert _twist_between_neighbours(molecule) == pytest.approx(-166.7, abs=0.5)

    scene.frame_set(41)
    _edit(molecule, twist=-150.0)
    _key(molecule, 41)
    assert _twist_between_neighbours(molecule) == pytest.approx(-150.0, abs=0.5)

    scene.frame_set(21)
    assert _twist_between_neighbours(molecule) == pytest.approx(
        (-166.7 - 150.0) / 2, abs=0.5)


def test_a_keyed_microtubule_keeps_its_strands_while_it_grows():
    scene = bpy.context.scene
    molecule = _build(16.3, 'MICROTUBULE')            # two dimers a strand
    assert _copies(molecule) == 2 * 13
    scene.frame_set(1)
    _key(molecule, 1)
    scene.frame_set(11)
    _edit(molecule, count=6)
    _key(molecule, 11)

    scene.frame_set(6)
    assert _copies(molecule) == 4 * 13
    preset = F.presets().get("MICROTUBULE")
    for neighbour in F.truth(preset.id)["neighbours"]:
        assert F.worst_miss(molecule, preset, neighbour) < 1.0


def test_keying_a_frame_other_than_the_one_on_screen_keys_what_is_on_screen():
    """The dialog's Frame field can name another frame; the build goes there."""
    scene = bpy.context.scene
    molecule = _build(27.5)
    scene.frame_set(1)
    _key(molecule, 1)
    _edit(molecule, length=55.0)                      # twenty, not yet keyed
    assert _key(molecule, 30) == {'FINISHED'}

    scene.frame_set(30)
    assert _copies(molecule) == 20
    scene.frame_set(1)
    assert _copies(molecule) == 10


def test_deleting_the_keyframe_takes_the_numbers_with_it():
    scene = bpy.context.scene
    molecule = _build(27.5)
    scene.frame_set(1)
    _key(molecule, 1)
    scene.frame_set(41)
    _edit(molecule, length=110.0)
    _key(molecule, 41)

    assert bpy.ops.proteinblender.delete_keyframe(frame=41) == {'FINISHED'}
    curves = _anim().parameter_fcurves(molecule.object)
    assert curves, "the frame 1 keys went too"
    assert all(len(fc.keyframe_points) == 1 for fc in curves.values())
    scene.frame_set(21)
    assert _copies(molecule) == 10


def test_keyframes_list_shows_the_filament_frames():
    from proteinblender.operators.keyframe_operators import get_keyframe_frames

    scene = bpy.context.scene
    molecule = _build(27.5)
    _key(molecule, 5)
    scene.frame_set(17)
    _edit(molecule, length=55.0)
    _key(molecule, 17)
    assert {5, 17} <= set(get_keyframe_frames(bpy.context))


# --------------------------------------------------------------------------
# Where it stands, and how it bends
# --------------------------------------------------------------------------

def test_a_keyed_bend_plays_back():
    """A node pulled 200 A sideways by frame 41 is 100 A out at frame 21."""
    scene = bpy.context.scene
    molecule = _build(55.0)
    scene.frame_set(1)
    _key(molecule, 1)
    straight = F.chain_centres(molecule, F.presets().get("ACTIN"))

    scene.frame_set(41)
    node = _bend().get_bend_nodes(molecule)[1]
    node.location = node.location + Vector((200.0 * WORLD_SCALE, 0.0, 0.0))
    bpy.context.view_layer.update()
    _key(molecule, 41)
    bent = F.chain_centres(molecule, F.presets().get("ACTIN"))
    full = np.linalg.norm(bent - straight, axis=1).max()
    assert full > 50.0, "the drag did not bend the filament"

    scene.frame_set(21)
    half = np.linalg.norm(
        F.chain_centres(molecule, F.presets().get("ACTIN")) - straight, axis=1).max()
    assert 0.3 * full < half < 0.7 * full, (half, full)

    scene.frame_set(1)
    back = np.linalg.norm(
        F.chain_centres(molecule, F.presets().get("ACTIN")) - straight, axis=1).max()
    assert back < 1.0


def test_a_keyed_position_moves_the_whole_filament():
    scene = bpy.context.scene
    molecule = _build(27.5)
    scene.frame_set(1)
    _key(molecule, 1)
    before = F.chain_centres(molecule, F.presets().get("ACTIN"))
    scene.frame_set(41)
    molecule.object.location.x += 3.0
    _key(molecule, 41)
    after = F.chain_centres(molecule, F.presets().get("ACTIN"))
    shift = (after - before).mean(axis=0)
    assert shift == pytest.approx([300.0, 0.0, 0.0], abs=1.0)


def test_keys_on_the_filament_alone_leave_its_nodes_free():
    """Its numbers and transform are not the rig: the Nodes field still works."""
    from proteinblender.core import bend_rig
    from proteinblender.operators import symmetry_dialog

    molecule = _build(27.5)
    assert _anim().keyframe_parameters(molecule, 1) == 6
    molecule.object.keyframe_insert("location", frame=1)
    assert not bend_rig.has_keyframes(_bend().SPEC, molecule.object,
                                      include_owner=False)

    class Dialog:
        molecule_id_to_update = molecule.identifier
    symmetry_dialog._set_bend_nodes(Dialog(), 5)
    assert len(_bend().get_bend_nodes(molecule)) == 5


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _render_frames(tmp_path, molecule, frames, ortho=8.0, lift=2.7):
    """Render an animation from the side; return each frame's covered pixels."""
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("anim_cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("anim_cam", cam_data)
    scene.collection.objects.link(cam)
    centre = molecule.object.matrix_world.translation
    cam.location = (centre.x, centre.y - 30.0, centre.z + lift)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(tmp_path / "frame_")
    scene.frame_start, scene.frame_end = min(frames), max(frames)
    assert bpy.ops.render.render(animation=True) == {'FINISHED'}

    covered = {}
    for frame in frames:
        img = bpy.data.images.load(str(tmp_path / f"frame_{frame:04d}.png"))
        try:
            px = np.array(img.pixels[:], dtype=np.float32).reshape(64, 64, 4)
            covered[frame] = px[:, :, 3] > 0.01
        finally:
            bpy.data.images.remove(img)
    return covered


@pytest.mark.slow
def test_an_animation_render_draws_the_filament_at_each_frame(tmp_path):
    """Rendered frames follow the keys, not whatever the viewport last showed.

    An animation render evaluates every frame into a depsgraph of its own, so
    this is the case a handler reading the objects' own values gets wrong.
    Two subunits at frame 1 and twenty at frame 3, rendered from the side: the
    filament covers far more of frame 3 than of frame 1.
    """
    scene = bpy.context.scene
    molecule = _build(5.5)                            # two subunits
    scene.frame_set(1)
    _key(molecule, 1)
    scene.frame_set(3)
    _edit(molecule, count=20)
    _key(molecule, 3)
    scene.frame_set(1)                                # the viewport at frame 1

    covered = _render_frames(tmp_path, molecule, (1, 3))
    first, last = int(covered[1].sum()), int(covered[3].sum())
    assert first > 0, "nothing was rendered at frame 1"
    assert last > 4 * first, (first, last)


@pytest.mark.slow
def test_an_animation_render_draws_the_bend_at_each_frame(tmp_path):
    """A bend keyed at frame 3 is rendered bent at frame 3.

    The node positions of a frame being rendered exist only in the render's
    depsgraph. Read from the objects instead, frame 3 would be drawn with
    the viewport's straight frame-1 path.
    """
    scene = bpy.context.scene
    molecule = _build(55.0)
    scene.frame_set(1)
    _key(molecule, 1)
    scene.frame_set(3)
    node = _bend().get_bend_nodes(molecule)[1]
    node.location = node.location + Vector((300.0 * WORLD_SCALE, 0.0, 0.0))
    bpy.context.view_layer.update()
    _key(molecule, 3)
    scene.frame_set(1)

    covered = _render_frames(tmp_path, molecule, (1, 3), ortho=10.0, lift=2.6)

    def width(mask):
        columns = np.flatnonzero(mask.any(axis=0))
        return int(columns.max() - columns.min() + 1)

    assert width(covered[3]) > width(covered[1]) + 6, (
        width(covered[1]), width(covered[3]))
