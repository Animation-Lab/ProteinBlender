"""Generative symmetry - building an assembly the file does not describe.

Deposited assemblies (``core.assembly``) cover structures whose symmetry the
depositor recorded. This module covers everything else: a designed assembly, a
structure whose deposited operators are absent or wrong, and filaments the PDB
does not describe as such.

The vocabulary follows ChimeraX's ``sym`` command, which is the reference
implementation most structural biologists already have in their fingers:

* **Cyclic (Cn)** - n copies evenly spaced about one axis. Rings, pores,
  most homo-oligomers.
* **Dihedral (Dn)** - a Cn stacked with a perpendicular two-fold, giving 2n
  copies. Back-to-back rings.
* **Helical (H)** - a rise along the axis and a twist about it, repeated.
  Actin, microtubules, amyloid, pili.

An operator here is the same ``(3x3 rotation, 3-vector translation in
Angstrom)`` pair a BIOMT record parses to, so generated symmetry goes through
exactly the same placement path as a deposited assembly - and inherits the
assemble/disassemble animation for free.

Rotating about an axis that does not pass through the origin is expressed by
folding the centre into the translation: a point ``p`` maps to
``R @ (p - c) + c``, which is ``R @ p + (c - R @ c)``.

The cubic groups (tetrahedral, octahedral, icosahedral) are deliberately not
here yet. They need an explicit orientation convention - ChimeraX offers 222,
2n5, n25 and 2n3 for icosahedral alone - and picking one silently would put
every capsid subunit in the wrong place.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

Operator = Tuple[np.ndarray, np.ndarray]

#: Symmetry kinds this module can generate, as (id, label, description).
SYMMETRY_KINDS = (
    ("C", "Cyclic (Cn)", "n copies evenly spaced around one axis - a ring"),
    ("D", "Dihedral (Dn)",
     "a ring of n plus a perpendicular two-fold, giving 2n copies"),
    ("H", "Helical",
     "a rise along the axis and a twist about it, repeated - a filament"),
)

DEFAULT_AXIS = (0.0, 0.0, 1.0)


def _unit(axis: Sequence[float]) -> np.ndarray:
    vector = np.array(axis, dtype=float)
    length = float(np.linalg.norm(vector))
    if length < 1e-9:
        logger.warning("symmetry axis has no direction; falling back to Z")
        return np.array(DEFAULT_AXIS, dtype=float)
    return vector / length


def rotation_about(axis: Sequence[float], angle: float) -> np.ndarray:
    """A 3x3 rotation of ``angle`` radians about ``axis`` (Rodrigues)."""
    a = _unit(axis)
    cross = np.array([
        [0.0, -a[2], a[1]],
        [a[2], 0.0, -a[0]],
        [-a[1], a[0], 0.0],
    ])
    return (np.eye(3)
            + math.sin(angle) * cross
            + (1.0 - math.cos(angle)) * (cross @ cross))


def _with_centre(rotation: np.ndarray, centre: Sequence[float]) -> Operator:
    """Fold a rotation centre into the operator's translation."""
    c = np.array(centre, dtype=float)
    return rotation, c - rotation @ c


def _perpendicular_to(axis: Sequence[float]) -> np.ndarray:
    """Any unit vector at right angles to ``axis``."""
    a = _unit(axis)
    # Cross with whichever cardinal direction a is least aligned to, so the
    # result never degenerates.
    fallback = np.eye(3)[int(np.argmin(np.abs(a)))]
    perpendicular = np.cross(a, fallback)
    return perpendicular / float(np.linalg.norm(perpendicular))


def cyclic(order: int, axis=DEFAULT_AXIS, centre=(0.0, 0.0, 0.0)) -> List[Operator]:
    """Cn: ``order`` copies at 360/order degree intervals about ``axis``."""
    order = max(int(order), 1)
    return [
        _with_centre(rotation_about(axis, 2.0 * math.pi * k / order), centre)
        for k in range(order)
    ]


def dihedral(order: int, axis=DEFAULT_AXIS, centre=(0.0, 0.0, 0.0)) -> List[Operator]:
    """Dn: a Cn, plus the same ring flipped by a perpendicular two-fold.

    2n copies in total - two rings back to back, which is what most dihedral
    oligomers look like.
    """
    order = max(int(order), 1)
    flip = rotation_about(_perpendicular_to(axis), math.pi)

    operators = []
    for rotation, _translation in cyclic(order, axis, centre):
        operators.append(_with_centre(rotation, centre))
    for rotation, _translation in cyclic(order, axis, centre):
        operators.append(_with_centre(rotation @ flip, centre))
    return operators


def helical(count: int, rise: float, twist: float, axis=DEFAULT_AXIS,
            centre=(0.0, 0.0, 0.0)) -> List[Operator]:
    """A filament: ``count`` subunits, each ``rise`` A and ``twist`` deg on.

    ``rise`` is in Angstrom along the axis and ``twist`` in degrees about it,
    which is how helical parameters are quoted in the literature - actin is
    about 27.5 A and -166.7 degrees per subunit.
    """
    count = max(int(count), 1)
    direction = _unit(axis)
    step = math.radians(twist)

    operators = []
    for k in range(count):
        rotation = rotation_about(direction, step * k)
        _r, translation = _with_centre(rotation, centre)
        operators.append((rotation, translation + direction * (rise * k)))
    return operators


def build_operators(kind: str, order: int = 3, count: int = 10,
                    rise: float = 0.0, twist: float = 0.0,
                    axis=DEFAULT_AXIS,
                    centre=(0.0, 0.0, 0.0)) -> List[Operator]:
    """Operators for one of :data:`SYMMETRY_KINDS`."""
    kind = (kind or "C").upper()
    if kind == "C":
        return cyclic(order, axis, centre)
    if kind == "D":
        return dihedral(order, axis, centre)
    if kind == "H":
        return helical(count, rise, twist, axis, centre)
    logger.warning("unknown symmetry kind %r", kind)
    return []


def describe(kind: str, order: int = 3, count: int = 10,
             rise: float = 0.0, twist: float = 0.0) -> str:
    """A short human label for what a given setting will build."""
    kind = (kind or "C").upper()
    if kind == "C":
        return f"C{int(order)} - {int(order)} copies around one axis"
    if kind == "D":
        return f"D{int(order)} - {2 * int(order)} copies, two rings"
    if kind == "H":
        return (f"Helix - {int(count)} subunits, {rise:g} A rise, "
                f"{twist:g}° twist")
    return kind


def short_label(kind: str, order: int = 3, count: int = 10,
                rise: float = 0.0, twist: float = 0.0) -> str:
    """A compact name for a built symmetry.

    :func:`describe` is written for a panel's summary line, where there is
    room to explain what the setting will do. An outliner row has none: it
    sits in a column of names beside chains and domains, so it wants the
    name alone and leaves the explanation to the tooltip.
    """
    kind = (kind or "C").upper()
    if kind in {"C", "D"}:
        return f"{kind}{int(order)}"
    if kind == "H":
        return f"Helix ({int(count)})"
    return kind


def apply_symmetry(molecule, kind: str, **settings) -> bool:
    """Generate a symmetry and place the copies.

    Goes through the same operator path as a deposited assembly, so the result
    animates with the same factor and clears the same way.
    """
    from . import assembly as assembly_core

    operators = build_operators(kind, **settings)
    if not operators:
        return False

    return assembly_core.apply_operators(
        molecule, operators, f"generated:{(kind or 'C').upper()}")


def built_symmetry_kind(molecule) -> Optional[str]:
    """The generated symmetry currently built, if any."""
    from . import assembly as assembly_core

    tag = assembly_core.built_assembly_id(molecule)
    if tag and str(tag).startswith("generated:"):
        return str(tag).split(":", 1)[1]
    return None
