"""A cytoskeleton filament's representation can be changed after it is built.

Reported 2026-11-03 (Dillon's notes): "make it so actin style is updatable
too". A new filament is drawn as Surface; its row's pencil is the protein
Visual Set-up dialog, and choosing another style there must restyle every
subunit - plain copies and copies that carry their own colour alike.

Observed from the evaluated scene: Surface draws each copy as a mesh, Spheres
as a point cloud of atoms. That is Blender's output, not the add-on's record
of what style it set.
"""

from collections import Counter

import bpy
import pytest

from filament_checks import build as _build

pytestmark = pytest.mark.integration


def _drawn_kinds(molecule):
    """How many non-empty meshes and point clouds the filament draws."""
    names = {d.object.name for d in molecule.domains.values() if d.object}
    bpy.context.view_layer.update()
    kinds = Counter()
    for entry in bpy.context.evaluated_depsgraph_get().object_instances:
        owner = (entry.parent.original if entry.is_instance
                 else entry.object.original)
        if owner.name not in names:
            continue
        data = entry.object.data
        if entry.object.type == 'MESH' and len(data.vertices):
            kinds['MESH'] += 1
        elif entry.object.type == 'POINTCLOUD' and len(data.points):
            kinds['POINTCLOUD'] += 1
    return kinds


def _paint(molecule, names):
    from proteinblender.core import subunit_colors
    subunit_colors.sync_roster(molecule)
    for row in molecule.object.pb_filament.subunits:
        row.select = row.name in names
    bpy.context.scene.pb_subunit_color = (1.0, 0.0, 0.0)
    assert bpy.ops.molecule.color_subunits(
        'EXEC_DEFAULT', molecule_id=molecule.identifier) == {'FINISHED'}


@pytest.mark.parametrize('painted', [False, True])
def test_a_filament_can_be_restyled_from_its_pencil(scene, painted):
    molecule = _build("ACTIN", 27.5)
    if painted:
        _paint(molecule, ["3:A"])
    built = _drawn_kinds(molecule)
    assert built['MESH'] and not built['POINTCLOUD'], (
        f"a new filament should be drawn as Surface meshes, got {dict(built)}")

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=molecule.identifier, vs_style='spheres') == {'FINISHED'}
    spheres = _drawn_kinds(molecule)
    assert spheres['POINTCLOUD'] and not spheres['MESH'], (
        f"after choosing Spheres the filament still draws {dict(spheres)}")

    assert bpy.ops.proteinblender.edit_protein_visuals(
        item_id=molecule.identifier, vs_style='surface') == {'FINISHED'}
    back = _drawn_kinds(molecule)
    assert back['MESH'] and not back['POINTCLOUD'], (
        f"after choosing Surface again the filament draws {dict(back)}")
