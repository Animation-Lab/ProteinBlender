"""Bending a helical filament - by moving the subunits, not deforming them.

A generated helix (``symmetry_builder.helical``) puts subunit *k* at ``rise·k``
along a straight axis, spun ``twist·k`` about it. Real filaments are not
straight: actin curves, microtubules flex, amyloid twists through a field of
view. This module replaces the straight axis with a curve the user shapes, and
re-derives the same operators against it.

**Why the copies move rather than the model deforming.** Two reasons, and
either one alone would decide it.

The physical one: a filament of globular protein subunits bends by changing
the relative orientation of neighbouring subunits, which stay rigid. Shearing
each subunit's own atoms along a curve would be a picture of something that
does not happen. (DNA is the opposite case - a double helix genuinely bends
along its length - which is why ``dna_builder/bender.py`` hands its curve to a
Curve modifier instead. Same rig, opposite use.)

The practical one: it is the only thing that works. The copies are
geometry-nodes instances, and a deform modifier never sees them. Appending a
Curve modifier after the MolecularNodes modifier on a built filament was
measured moving all eight copies by exactly 0.0, with the evaluated mesh at
zero vertices. Deforming would first mean realizing every copy into real
geometry, which throws away the instancing that makes a long filament cheap.

**How a bent operator is built.** For subunit *k*, at arc length ``rise·k``
along the curve:

* ``p``, ``T``, ``N`` - the curve's position, tangent and normal there.
* ``F`` - the rotation taking the filament's own axis onto ``T`` and its
  reference perpendicular onto ``N``.
* ``R = F · rot(axis, twist·k)`` - spin the subunit about its own axis first,
  then stand it up on the path.
* ``t = p - R·centre`` - so the subunit's reference point lands on the curve.

With a straight curve running from the centre along the axis this reduces
*exactly* to ``symmetry_builder.helical``: ``T`` is the axis, ``F`` is the
identity, and ``t`` is ``axis·rise·k``. That is the property the tests pin,
because it means bending adds a degree of freedom without moving anything that
was already right.

Everything past this point is the ordinary operator path, so a bent filament
still animates with the assemble factor, trims, cuts away, realizes and draws
its axes like any other build.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import bend_rig

logger = logging.getLogger(__name__)

Operator = Tuple[np.ndarray, np.ndarray]

#: MolecularNodes stores structures at 1/100 scale, so an Angstrom of rise is
#: 0.01 Blender units of arc length along the bend curve.
WORLD_SCALE = 0.01

#: Custom properties naming the rig, and the names its objects take. Kept
#: distinct from the DNA rig's so neither feature's orphan sweep can reach the
#: other's objects.
CURVE_PROP = "pb_filament_bend_curve"
NODES_PROP = "pb_filament_bend_nodes"
CURVE_SUFFIX = "_FilamentBend"

SPEC = bend_rig.BendRigSpec(
    kind="filament",
    curve_prop=CURVE_PROP,
    nodes_prop=NODES_PROP,
    curve_suffix=CURVE_SUFFIX,
    node_label="Filament Node",
    hook_prefix="Hook_FB",
    curve_bevel=0.01,
    node_display_size=0.06,
    node_display_type="SPHERE",
)


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------

def owner_object(molecule):
    """The object a filament's bend rig hangs off: the molecule itself.

    Not a domain object. The bend describes where the whole filament goes, and
    a molecule always has exactly one of these even when its domains have been
    deleted or renamed.
    """
    try:
        return molecule.object
    except (AttributeError, ReferenceError):
        return None


def has_bend(molecule) -> bool:
    return get_bend_curve(molecule) is not None


def get_bend_curve(molecule):
    return bend_rig.get_curve(SPEC, owner_object(molecule))


def get_bend_nodes(molecule):
    return bend_rig.get_nodes(SPEC, owner_object(molecule))


def molecule_for_node(node_obj, scene_molecules):
    """Which molecule owns this control node, given the live registry."""
    owner = bend_rig.owner_of_node(SPEC, node_obj)
    if owner is None:
        return None
    for molecule in scene_molecules.values():
        if owner_object(molecule) == owner:
            return molecule
    return None


def filament_length(count: int, rise: float) -> float:
    """How long the straight filament would be, in Blender units.

    ``count - 1`` gaps, not ``count``: the first subunit sits at the start.
    """
    return max(int(count) - 1, 1) * abs(float(rise)) * WORLD_SCALE


def add_bend(molecule, count: int, rise: float, axis=(0.0, 0.0, 1.0),
             n_points: int = bend_rig.RES_DEFAULT):
    """Build the curve and its control nodes along the filament's own axis.

    The curve starts at the molecule's origin and runs the length the current
    subunit count and rise describe, so adding a bend changes nothing until a
    node is actually dragged.
    """
    owner = owner_object(molecule)
    if owner is None:
        return None

    # Sweep before building, at a deterministic moment rather than from a
    # handler - see core.bend_rig.cleanup_orphans.
    bend_rig.cleanup_orphans(SPEC)

    length = filament_length(count, rise)
    if length <= 0:
        logger.warning("filament has no length; nothing to bend along")
        return None

    curve_obj = bend_rig.create_curve(
        SPEC, owner, f"{owner.name}{CURVE_SUFFIX}",
        bend_rig.straight_points(length, n=n_points, direction=axis))
    bend_rig.create_nodes(SPEC, owner, curve_obj, n_points)
    _scale_node_handles(molecule, length)
    return curve_obj


def set_node_count(molecule, n_points: int) -> bool:
    """Change how many handles shape the path, keeping the shape itself."""
    owner = owner_object(molecule)
    if owner is None or bend_rig.get_curve(SPEC, owner) is None:
        return False
    bend_rig.rebuild_nodes(SPEC, owner, n_points)
    _scale_node_handles(molecule, bend_rig.curve_length(
        bend_rig.get_curve(SPEC, owner)))
    return True


def apply_preset(molecule, preset: str, count: int, rise: float,
                 axis=(0.0, 0.0, 1.0)) -> bool:
    """Overwrite the path with a starting shape, keeping the handle count."""
    owner = owner_object(molecule)
    if owner is None:
        return False
    length = filament_length(count, rise)
    if length <= 0:
        return False
    ok = bend_rig.apply_preset(SPEC, owner, preset, length, direction=axis)
    if ok:
        _scale_node_handles(molecule, length)
    return ok


def remove_bend(molecule) -> bool:
    """Take the rig away. The filament goes back to straight on the next build."""
    owner = owner_object(molecule)
    if owner is None or bend_rig.get_curve(SPEC, owner) is None:
        return False
    bend_rig.remove_rig(SPEC, owner)
    return True


def _scale_node_handles(molecule, length: float) -> None:
    """Size the control spheres to the filament they shape.

    A fixed size is wrong at both ends: invisible against a long microtubule,
    and swallowing a short one. A fortieth of the path reads the same at any
    length, bounded so a one-subunit filament still gets something clickable.
    """
    if length <= 0:
        return
    size = min(max(length / 40.0, 0.02), 0.25)
    for node in get_bend_nodes(molecule):
        node.empty_display_size = size


# ---------------------------------------------------------------------------
# The operators
# ---------------------------------------------------------------------------

def _unit(vector) -> np.ndarray:
    array = np.array(vector, dtype=float)
    length = float(np.linalg.norm(array))
    if length < 1e-12:
        return np.array([0.0, 0.0, 1.0])
    return array / length


def _orthogonalise(vector: np.ndarray, against: np.ndarray) -> np.ndarray:
    """The part of *vector* square to *against*, or any perpendicular if none."""
    residual = vector - against * float(np.dot(vector, against))
    if float(np.linalg.norm(residual)) < 1e-9:
        fallback = np.eye(3)[int(np.argmin(np.abs(against)))]
        residual = np.cross(against, fallback)
    return _unit(residual)


def _basis(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """A right-handed orthonormal basis as columns, from two directions."""
    e1 = _unit(first)
    e2 = _orthogonalise(_unit(second), e1)
    e3 = np.cross(e1, e2)
    return np.column_stack([e1, e2, e3])


def _rotation_about(axis, angle: float) -> np.ndarray:
    a = _unit(axis)
    cross = np.array([[0.0, -a[2], a[1]],
                      [a[2], 0.0, -a[0]],
                      [-a[1], a[0], 0.0]])
    return (np.eye(3)
            + math.sin(angle) * cross
            + (1.0 - math.cos(angle)) * (cross @ cross))


def bent_helical_operators(molecule, count: int, rise: float, twist: float,
                           axis=(0.0, 0.0, 1.0),
                           centre=(0.0, 0.0, 0.0)) -> List[Operator]:
    """A helix of ``count`` subunits laid along the molecule's bend curve.

    Falls back to the straight helix whenever there is no curve to follow, so
    callers never have to ask which they are getting.
    """
    from . import symmetry_builder

    count = max(int(count), 1)
    owner = owner_object(molecule)
    curve_obj = bend_rig.get_curve(SPEC, owner)
    if owner is None or curve_obj is None:
        return symmetry_builder.helical(count, rise, twist, axis, centre)

    arcs = [abs(float(rise)) * k * WORLD_SCALE for k in range(count)]
    samples = bend_rig.sample_along(curve_obj, arcs)
    if len(samples) != count:
        logger.warning("bend curve gave %d of %d samples; using a straight helix",
                       len(samples), count)
        return symmetry_builder.helical(count, rise, twist, axis, centre)

    # Operators act on the molecule's mesh coordinates, upstream of its object
    # transform, so the curve has to be read in the same space rather than in
    # world space.
    to_local = owner.matrix_world.inverted()
    to_local_rotation = to_local.to_3x3()

    positions, tangents, normals = [], [], []
    for world_position, world_tangent, world_normal in samples:
        local = to_local @ world_position
        positions.append(np.array(local) / WORLD_SCALE)
        tangents.append(_unit(np.array(to_local_rotation @ world_tangent)))
        normals.append(_unit(np.array(to_local_rotation @ world_normal)))

    # The frame the subunit starts in. Taking the reference perpendicular from
    # the curve's own first normal is what makes a straight curve along the
    # axis produce the identity at k = 0 - i.e. adding a bend and dragging
    # nothing leaves the filament exactly where it was.
    filament_axis = _unit(axis)
    source = _basis(filament_axis, _orthogonalise(normals[0], filament_axis))

    reference = np.array(centre, dtype=float)
    step = math.radians(float(twist))

    operators: List[Operator] = []
    for k in range(count):
        frame = _basis(tangents[k], normals[k]) @ source.T
        rotation = frame @ _rotation_about(filament_axis, step * k)
        translation = positions[k] - rotation @ reference
        operators.append((rotation, translation))

    return _anchored_on_the_original(operators)


def _anchored_on_the_original(operators: List[Operator]) -> List[Operator]:
    """Re-express the filament in the frame of the subunit already on screen.

    Copy zero is not a copy: it is the structure the user imported, sitting
    where the import left it. Everything around it assumes so - the trim
    filters never drop the identity, Realize Copies skips it rather than
    duplicating what is already there, and the assemble slider at 0 puts every
    copy back onto it.

    A curve does not respect that on its own. Dragging a middle control node
    tilts the path's starting tangent very slightly, which was enough to swing
    subunit zero off its own position by about an Angstrom and to stop it
    reading as the identity - so Realize made a copy of the original and
    stacked it on top of itself.

    Composing every operator with the inverse of the first fixes it exactly and
    for any curve: ``op0`` becomes the identity by construction, and the
    relative geometry between subunits is untouched, because left-composing a
    rigid motion onto all of them is just a change of frame. The filament ends
    up anchored to the original and bending away from it, which is also the
    more intelligible thing to watch.

    A straight curve leaves this a no-op: ``op0`` is already the identity.
    """
    if not operators:
        return operators

    first_rotation, first_translation = operators[0]
    inverse_rotation = np.asarray(first_rotation, dtype=float).T
    origin = np.asarray(first_translation, dtype=float)

    return [(inverse_rotation @ np.asarray(rotation, dtype=float),
             inverse_rotation @ (np.asarray(translation, dtype=float) - origin))
            for rotation, translation in operators]


def build_operators(molecule, kind: str, **settings) -> List[Operator]:
    """The generated operators for *molecule*, bent if it has a bend curve.

    The one entry point the panel, the build operator and the cutaway/axes
    readers all go through, so a bent filament can never be built one way and
    measured another.
    """
    from . import symmetry_builder

    kind = (kind or "C").upper()
    if kind != "H" or not has_bend(molecule):
        return symmetry_builder.build_operators(kind, **settings)

    return bent_helical_operators(
        molecule,
        count=settings.get("count", 10),
        rise=settings.get("rise", 0.0),
        twist=settings.get("twist", 0.0),
        axis=settings.get("axis", (0.0, 0.0, 1.0)),
        centre=settings.get("centre", (0.0, 0.0, 0.0)),
    )


def bend_departure(molecule, count: int, rise: float, twist: float,
                   axis=(0.0, 0.0, 1.0)) -> float:
    """How far the bent filament's last subunit sits from where straight put it.

    In Angstrom. Used to tell "there is a bend rig" apart from "the rig is
    actually bending something", which is what the panel wants to report.
    """
    from . import symmetry_builder

    if not has_bend(molecule):
        return 0.0
    bent = bent_helical_operators(molecule, count, rise, twist, axis)
    straight = symmetry_builder.helical(count, rise, twist, axis)
    if not bent or not straight:
        return 0.0
    return float(np.linalg.norm(bent[-1][1] - straight[-1][1]))
