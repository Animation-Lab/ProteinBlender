#!/usr/bin/env python3
"""Cut one subunit out of a deposited filament and stand it on the filament's axis.

The helical builder turns copies about the Z axis through the origin of the
structure it is given. A deposited filament is not in that frame: a cryo-EM
model sits wherever its map put it, with the axis running through the middle
of the box and, as often as not, a few degrees off Z. Built from such a file,
the copies ring the wrong line and the filament comes out with whatever radius
the box happened to give it.

This script writes the subunits the filament presets ship
(``proteinblender/data/filaments``): one repeat unit of each filament, moved
rigidly so the axis is +Z through the origin, the unit sits out along +X and
its centre is at z = 0. Nothing is refined, idealised or rebuilt - every atom
keeps its deposited position relative to every other.

Where the axis is comes from the deposit itself. Superposing one chain onto
its neighbour along the filament gives a rotation and a translation, and a
rotation plus a translation is a screw about one particular line; that line is
the filament's axis. Several neighbouring pairs are averaged.

It also writes the ground truth the tests check the presets against
(``tests/data/filaments``): where a handful of C-alpha atoms of the unit's
*neighbours* sit in the same frame, straight from the deposit. A preset is
right if building its lattice from the shipped unit lands copies on those.

Run it only to regenerate the data. It needs the network (or ``--cache`` with
the mmCIF files already in it) and a Python with biotite and numpy::

    python scripts/make_filament_subunits.py --cache /tmp/filament-cif

PDB entries are in the public domain (CC0), so the cut-down files can ship.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DIR = ROOT / "proteinblender" / "data" / "filaments"
TRUTH_DIR = ROOT / "tests" / "data" / "filaments"

#: C-alpha atoms recorded per neighbouring chain. Enough, spread along the
#: chain, that a copy cannot sit on them with the wrong orientation.
LANDMARKS_PER_CHAIN = 8


@dataclass(frozen=True)
class Source:
    """One filament to cut a unit from."""

    name: str
    pdb_id: str
    #: Chains of the deposit that make up one repeat unit, and what each is
    #: called in the file that ships.
    unit_chains: Dict[str, str]
    #: Pairs of equivalent chains one lattice step apart round the axis. Each
    #: must be related by a real rotation: a pair one step *along* a straight
    #: protofilament is a pure translation and says nothing about where the
    #: axis is.
    axis_pairs: Sequence[Tuple[str, str]]
    #: Deposited chains to record as ground truth, as ``deposit chain ->
    #: the unit chain it is a copy of``.
    neighbours: Dict[str, str]


SOURCES = (
    Source(
        name="actin",
        pdb_id="8A2T",
        unit_chains={"C": "A"},
        axis_pairs=(("C", "D"), ("B", "C"), ("A", "B"), ("D", "E")),
        neighbours={"A": "C", "B": "C", "D": "C", "E": "C"},
    ),
    Source(
        name="tubulin",
        pdb_id="7SJ7",
        # A is alpha-tubulin and B the beta above it in the same protofilament.
        unit_chains={"A": "A", "B": "B"},
        axis_pairs=(("A", "C"), ("E", "A"), ("K", "L"), ("J", "K")),
        # The next protofilament round (C alpha, D beta), the next dimer up the
        # same protofilament (K), and the two together (L). The protofilament
        # on the other side is left out on purpose: in a closed 13-strand tube
        # it is across the seam, where an alpha sits beside a beta.
        neighbours={"C": "A", "D": "B", "K": "A", "L": "A"},
    ),
)


def _rotation_about(axis, degrees: float) -> np.ndarray:
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    t = np.radians(degrees)
    cross = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) + np.sin(t) * cross + (1.0 - np.cos(t)) * (cross @ cross)


def _superpose(start: np.ndarray, end: np.ndarray):
    """``R, T`` with ``end ~= start @ R.T + T`` (Kabsch)."""
    start_centre, end_centre = start.mean(axis=0), end.mean(axis=0)
    covariance = (start - start_centre).T @ (end - end_centre)
    u, _s, vt = np.linalg.svd(covariance)
    handed = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag([1.0, 1.0, handed]) @ u.T
    return rotation, end_centre - rotation @ start_centre


def _screw_axis(rotation: np.ndarray, translation: np.ndarray):
    """The line a rigid motion screws about: ``(direction, point on it)``."""
    values, vectors = np.linalg.eig(rotation)
    direction = np.real(vectors[:, int(np.argmin(np.abs(values - 1.0)))])
    direction = direction / np.linalg.norm(direction)
    along = float(translation @ direction)
    # (I - R) c = the part of the translation square to the axis.
    point = np.linalg.lstsq(np.eye(3) - rotation,
                            translation - along * direction, rcond=None)[0]
    return direction, point - direction * float(point @ direction)


def _fetch(pdb_id: str, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{pdb_id}.cif"
    if not path.exists():
        url = f"https://files.rcsb.org/download/{pdb_id}.cif"
        print(f"  downloading {url}")
        urllib.request.urlretrieve(url, path)
    return path


def _alpha_carbons(atoms, chain: str):
    return atoms[(atoms.chain_id == chain) & (atoms.atom_name == "CA")
                 & ~atoms.hetero]


def _paired(atoms, first: str, second: str):
    """C-alpha coordinates of the residues two chains have in common."""
    a, b = _alpha_carbons(atoms, first), _alpha_carbons(atoms, second)
    common = np.intersect1d(a.res_id, b.res_id)
    return (a[np.isin(a.res_id, common)].coord,
            b[np.isin(b.res_id, common)].coord, common)


def make(source: Source, cache: Path) -> None:
    import biotite.structure.io.pdb as pdb
    import biotite.structure.io.pdbx as pdbx

    print(f"{source.name} (PDB {source.pdb_id})")
    atoms = pdbx.get_structure(
        pdbx.CIFFile.read(str(_fetch(source.pdb_id, cache))), model=1)

    directions, points = [], []
    for first, second in source.axis_pairs:
        start, end, _common = _paired(atoms, first, second)
        direction, point = _screw_axis(*_superpose(start, end))
        if direction[2] < 0.0:
            direction = -direction
        directions.append(direction)
        points.append(point)
    axis = np.mean(directions, axis=0)
    axis = axis / np.linalg.norm(axis)
    on_axis = np.mean([p - axis * float(p @ axis) for p in points], axis=0)
    spread = max(float(np.linalg.norm(p - axis * float(p @ axis) - on_axis))
                 for p in points)
    print(f"  axis {np.round(axis, 4)} through {np.round(on_axis, 2)} "
          f"(pairs agree to {spread:.2f} A)")

    # Stand the axis up on +Z ...
    tilt_about = np.cross(axis, [0.0, 0.0, 1.0])
    tilt = float(np.linalg.norm(tilt_about))
    upright = (np.eye(3) if tilt < 1e-9 else
               _rotation_about(tilt_about, np.degrees(np.arcsin(tilt))))

    unit = atoms[np.isin(atoms.chain_id, list(source.unit_chains))
                 & (atoms.res_name != "HOH")]
    backbone = (unit.atom_name == "CA") & ~unit.hetero
    centre = ((unit.coord - on_axis) @ upright.T)[backbone].mean(axis=0)
    # ... then turn the unit out along +X and drop its centre to z = 0.
    spin = _rotation_about([0.0, 0.0, 1.0],
                           -np.degrees(np.arctan2(centre[1], centre[0])))

    def framed(coord: np.ndarray) -> np.ndarray:
        return ((coord - on_axis) @ upright.T) @ spin.T - [0.0, 0.0, centre[2]]

    truth = {
        "source": f"PDB {source.pdb_id}",
        "note": ("C-alpha positions of the unit's neighbours, in Angstrom, in "
                 "the frame of the shipped unit. From the deposit by a rigid "
                 "move only - see scripts/make_filament_subunits.py."),
        "neighbours": [],
    }
    for deposit_chain, unit_chain in source.neighbours.items():
        _start, end, common = _paired(atoms, unit_chain, deposit_chain)
        picks = np.linspace(0, len(common) - 1, LANDMARKS_PER_CHAIN).astype(int)
        placed = framed(end)
        truth["neighbours"].append({
            "deposit_chain": deposit_chain,
            "copy_of_chain": source.unit_chains[unit_chain],
            "landmarks": {str(int(common[i])): [round(float(v), 3)
                                                for v in placed[i]]
                          for i in picks},
        })

    unit.coord = framed(unit.coord).astype(np.float32)
    unit.chain_id = np.array([source.unit_chains[c] for c in unit.chain_id],
                             dtype=unit.chain_id.dtype)

    PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    out = PRODUCT_DIR / f"{source.name}_{source.pdb_id.lower()}.pdb"
    file = pdb.PDBFile()
    file.set_structure(unit)
    file.write(str(out))
    truth_path = TRUTH_DIR / f"{source.name}_{source.pdb_id.lower()}_neighbours.json"
    truth_path.write_text(json.dumps(truth, indent=1) + "\n", encoding="utf-8")

    radius = float(np.hypot(*unit.coord[backbone].mean(axis=0)[:2]))
    print(f"  {out.relative_to(ROOT)}: {unit.array_length()} atoms, "
          f"{radius:.1f} A from the axis")
    print(f"  {truth_path.relative_to(ROOT)}: "
          f"{len(truth['neighbours'])} neighbouring chains")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path,
                        default=Path(tempfile.gettempdir()) / "filament-cif",
                        help="where downloaded mmCIF files are kept")
    args = parser.parse_args(argv)
    for source in SOURCES:
        make(source, args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
