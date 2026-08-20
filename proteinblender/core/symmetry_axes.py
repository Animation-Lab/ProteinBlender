"""Symmetry axes as real, renderable objects.

Mol* draws an assembly's symmetry axes over the structure, and it is the
single clearest way to show *why* an assembly looks the way it does - a
five-fold through the vertex of a capsid, a two-fold between two subunits.

Recovering the axes needs no extra input. Every rotation has an axis, and the
distinct axes of an assembly's operators are its symmetry axes; the smallest
rotation about each one gives its fold. That works identically for a deposited
assembly and for a generated symmetry, because by this point both are just
lists of operators.

The axes are built as thin cylinders rather than empties. An empty is a
viewport gizmo that never reaches a render, and the whole point of putting
these in Blender is to have them in the figure.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import bpy
import numpy as np

logger = logging.getLogger(__name__)

#: Prefix for every axis object, so they can be found and removed again.
AXIS_PREFIX = ".pb_symmetry_axis_"

#: Two axes closer than this (radians) are treated as the same axis.
_AXIS_TOLERANCE = 1e-3

#: Rotations smaller than this are the identity for our purposes.
_MIN_ANGLE = 1e-6


@dataclass(frozen=True)
class SymmetryAxis:
    """One symmetry axis of an assembly."""

    direction: tuple      # unit vector
    fold: int             # 2 for a two-fold, 5 for a five-fold, ...
    angles: tuple         # every rotation angle found about this axis

    @property
    def label(self) -> str:
        return f"C{self.fold}"


def _axis_and_angle(rotation) -> Optional[tuple]:
    """The axis and angle of a 3x3 rotation, or None if it is the identity."""
    from mathutils import Matrix as BlenderMatrix

    quaternion = BlenderMatrix(np.asarray(rotation, dtype=float).tolist()).to_quaternion()
    angle = float(quaternion.angle)
    if abs(angle) < _MIN_ANGLE or abs(angle - 2.0 * math.pi) < _MIN_ANGLE:
        return None

    axis = np.array(tuple(quaternion.axis), dtype=float)
    norm = float(np.linalg.norm(axis))
    if norm < _MIN_ANGLE:
        return None
    axis = axis / norm

    # An axis and its negative describe the same line, so canonicalise the sign
    # or a five-fold shows up as two different axes.
    for component in axis:
        if abs(component) > 1e-9:
            if component < 0:
                axis, angle = -axis, 2.0 * math.pi - angle
            break

    return axis, angle


def axes_of(operators) -> List[SymmetryAxis]:
    """The distinct symmetry axes of a set of operators, with their folds.

    The fold comes from the *smallest* rotation about each axis: a C5 carries
    rotations of 72, 144, 216 and 288 degrees, and 360/72 is what makes it a
    five-fold.
    """
    grouped = []   # [(axis vector, [angles])]

    for rotation, _translation in operators:
        found = _axis_and_angle(rotation)
        if found is None:
            continue
        axis, angle = found

        for existing_axis, angles in grouped:
            if float(np.linalg.norm(existing_axis - axis)) < _AXIS_TOLERANCE:
                angles.append(angle)
                break
        else:
            grouped.append((axis, [angle]))

    axes = []
    for axis, angles in grouped:
        smallest = min(angles)
        fold = int(round(2.0 * math.pi / smallest)) if smallest > _MIN_ANGLE else 0
        axes.append(SymmetryAxis(direction=tuple(axis), fold=max(fold, 2),
                                 angles=tuple(sorted(angles))))

    # Highest-order axis first: that is the one a viewer reads as "the" axis.
    axes.sort(key=lambda a: -a.fold)
    return axes


# --------------------------------------------------------------------------
# Drawing them
# --------------------------------------------------------------------------

def _cylinder_mesh(name, length, radius, segments=12):
    """A thin cylinder along Z, centred on the origin."""
    verts, faces = [], []
    half = length / 2.0

    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        x, y = radius * math.cos(theta), radius * math.sin(theta)
        verts.append((x, y, -half))
        verts.append((x, y, half))

    for i in range(segments):
        a = 2 * i
        b = 2 * ((i + 1) % segments)
        faces.append((a, b, b + 1, a + 1))

    # Cap both ends so the axis reads as a solid rod in a render.
    faces.append(tuple(range(0, 2 * segments, 2)))
    faces.append(tuple(range(1, 2 * segments, 2))[::-1])

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _structure_extent(molecule) -> float:
    """A length that comfortably spans the assembly, in Blender units."""
    from . import assembly as assembly_core

    atoms = assembly_core._atom_cloud(molecule)
    if atoms is None or not len(atoms):
        return 1.0
    span = float(np.linalg.norm(np.ptp(atoms, axis=0)))
    return max(span * 2.5, 0.1)


def clear_symmetry_axes(molecule) -> int:
    """Remove the axis objects belonging to this molecule."""
    prefix = f"{AXIS_PREFIX}{molecule.identifier}_"
    removed = 0
    for obj in [o for o in bpy.data.objects if o.name.startswith(prefix)]:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)
        removed += 1
    return removed


def show_symmetry_axes(molecule, operators, centre=(0.0, 0.0, 0.0)) -> List[bpy.types.Object]:
    """Build one object per symmetry axis. Replaces any already present."""
    from mathutils import Vector

    clear_symmetry_axes(molecule)

    axes = axes_of(operators)
    if not axes:
        return []

    length = _structure_extent(molecule)
    radius = max(length * 0.004, 0.002)
    collection = _collection_for(molecule)

    created = []
    for index, axis in enumerate(axes):
        name = f"{AXIS_PREFIX}{molecule.identifier}_{axis.label}_{index}"
        mesh = _cylinder_mesh(name, length, radius)
        obj = bpy.data.objects.new(name, mesh)

        # The cylinder is built along Z, so rotate Z onto the axis.
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(
            Vector(axis.direction))
        obj.location = Vector(centre)
        obj["pb_symmetry_fold"] = axis.fold

        collection.objects.link(obj)
        created.append(obj)

    return created


def _collection_for(molecule):
    obj = getattr(molecule, "object", None)
    if obj is not None:
        for collection in obj.users_collection:
            return collection
    return bpy.context.scene.collection


def symmetry_axis_objects(molecule) -> List[bpy.types.Object]:
    prefix = f"{AXIS_PREFIX}{molecule.identifier}_"
    return [o for o in bpy.data.objects if o.name.startswith(prefix)]
