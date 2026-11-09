"""Render Animation draws each linker where its frame puts it.

Found 2026-11-09 while checking linkers between Morphset chains: during
Render > Render Animation every linker stayed where it was on the frame the
scene was left at, for plain chains as well as morphing ones. Linkers are
rebuilt from a frame-change handler, and that handler read the original
objects (their ``matrix_world``, a morph's shape-key values), which only the
viewport keeps in step with the frame. A render evaluates the frames in its
own depsgraph and leaves the originals where they were.

Ground truth is the rendered image: a still render after jumping to a frame is
the established, working path (the viewport updates the originals), so
Render Animation's image of the same frame must match it. Workbench renders
are deterministic, and the two paths draw the molecules identically, so any
difference is the linker.
"""

import numpy as np
import pytest
import bpy
from mathutils import Vector

from test_linkers import _setup_puppet_two_chains, _add_linker
from test_morph_linkers import morph_ab, _add_morph_linker, _linker_ends  # noqa: F401

pytestmark = pytest.mark.integration

SIZE = 96
LAST = 49   # frame_start 1, step 24: frames 1, 25, 49


def _camera_over(points):
    scene = bpy.context.scene
    points = np.array(points)
    low, high = points.min(axis=0), points.max(axis=0)
    cam = bpy.data.objects.new('LinkerCam', bpy.data.cameras.new('LinkerCam'))
    scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = float(max(high - low)) * 1.6 + 0.2
    cam.location = Vector(((low + high) / 2)) + Vector((0, 0, 10))
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.frame_start, scene.frame_end, scene.frame_step = 1, LAST, 24


def _pixels(path):
    image = bpy.data.images.load(str(path))
    try:
        data = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(data)
    finally:
        bpy.data.images.remove(image)
    return data.reshape(-1, 4)


def _still(tmp_path, frame):
    scene = bpy.context.scene
    scene.frame_set(frame)
    path = tmp_path / f'still_{frame}.png'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return _pixels(path)


def _animation(tmp_path, frame):
    scene = bpy.context.scene
    scene.frame_set(1)
    scene.render.filepath = str(tmp_path / 'anim_')
    bpy.ops.render.render(animation=True)
    return _pixels(tmp_path / f'anim_{frame:04d}.png')


def _differing(a, b):
    return int((np.abs(a - b).max(axis=1) > 2 / 255).sum())


def _check(tmp_path, linker):
    ends = []
    for frame in (1, LAST):
        bpy.context.scene.frame_set(frame)
        ends.extend(_linker_ends(linker))
    _camera_over(ends)
    first, last = _still(tmp_path, 1), _still(tmp_path, LAST)
    assert _differing(first, last) > 20, "precondition: the linker moves between frames"
    rendered = _animation(tmp_path, LAST)
    assert _differing(rendered, last) == 0, (
        f"Render Animation drew frame {LAST} differently from a still render of it "
        f"({_differing(rendered, last)} pixels; {_differing(rendered, first)} differ from frame 1)")


def test_linker_between_keyed_chains_moves_in_render_animation(scene, tmp_path):
    _mid, puppet, chains = _setup_puppet_two_chains()
    linker = _add_linker(puppet, chains[0], chains[1], length_residues=400)
    row = next(r for r in scene.outliner_items if r.item_id == chains[0].item_id)
    obj = bpy.data.objects[row.object_name]
    scene.frame_set(1)
    obj.keyframe_insert('location', frame=1)
    obj.location.x += 0.5
    obj.keyframe_insert('location', frame=LAST)
    _check(tmp_path, linker)


def test_linker_between_morphing_chains_morphs_in_render_animation(morph_ab, tmp_path):
    linker, *_ = _add_morph_linker(morph_ab)
    _check(tmp_path, linker)
