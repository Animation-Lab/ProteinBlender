"""B-factor motion must not break a ribbon apart.

Janet (2026-10-30): "When I test B factor on 1atn, chain A looks pretty weird
in ribbon mode, though it looks okay in cartoon mode." Her screenshot shows
the actin ribbon as short, blobby tube fragments.

The ribbon decides where the backbone has a real gap by the distance between
neighbouring C-alpha atoms. Measured on the jiggling atoms, neighbours drift
across that cutoff and the ribbon is cut into pieces that come and go frame by
frame. The cartoon was fixed for this on 2026-09-23 (``core.cartoon_motion``);
the ribbon was not.

Ground truth is the evaluated mesh Blender draws: at rest (motion off) the
ribbon has some topology, and with motion on every frame must keep it - the
atoms move, the ribbon does not tear.
"""
import bpy
import numpy as np
import pytest

import helpers as H

pytestmark = pytest.mark.integration


def _ribbon(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        points = np.empty((len(mesh.vertices), 3))
        mesh.vertices.foreach_get('co', points.ravel())
        return points, (len(mesh.vertices), len(mesh.edges), len(mesh.polygons))
    finally:
        evaluated.to_mesh_clear()


def _chain_object(molecule, chain_letter):
    return next(d.object for d in molecule.domains.values()
                if str(d.chain_id) == chain_letter)


@pytest.mark.parametrize('intensity', [1.0, 5.0])
def test_ribbon_keeps_its_shape_through_b_factor_motion(scene, intensity):
    mid = H.import_local('1atn.pdb', 'Actin')
    molecule = H.sm().molecules[mid]
    obj = _chain_object(molecule, 'A')
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, vs_style='ribbon') == {'FINISHED'}
    reference, rest = _ribbon(obj)
    assert rest[0] > 1000, f"chain A drew almost no ribbon at rest: {rest}"

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, bfactor_motion=True, bfactor_intensity=intensity) == {'FINISHED'}
    seen = {}
    moved = 0.0
    for frame in range(1, 49):
        scene.frame_set(frame)
        points, topology = _ribbon(obj)
        seen[frame] = topology
        if topology == rest:
            moved = max(moved, float(np.abs(points - reference).max()))
    torn = {f: t for f, t in seen.items() if t != rest}
    assert not torn, (
        f"B-factor motion tears the ribbon: at rest {rest}, "
        f"{len(torn)} of 48 frames differ, e.g. {dict(list(torn.items())[:4])}")
    assert moved > 1e-4, "the ribbon did not move at all"


def test_switching_to_ribbon_with_motion_on_keeps_it_whole(scene):
    """The other order: motion turned on in cartoon, then the style changed."""
    mid = H.import_local('1atn.pdb', 'Actin')
    molecule = H.sm().molecules[mid]
    obj = _chain_object(molecule, 'A')
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, vs_style='ribbon') == {'FINISHED'}
    _, rest = _ribbon(obj)
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, vs_style='cartoon', bfactor_motion=True,
        bfactor_intensity=3.0) == {'FINISHED'}
    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=mid, vs_style='ribbon') == {'FINISHED'}
    torn = []
    for frame in range(1, 25):
        scene.frame_set(frame)
        topology = _ribbon(obj)[1]
        if topology != rest:
            torn.append((frame, topology))
    assert not torn, f"at rest {rest}, torn on {torn[:4]}"
