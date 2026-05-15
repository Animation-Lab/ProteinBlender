"""Canonical nucleotide templates for LADDER mode.

LADDER mode is a stylised representation — flat rungs perpendicular to
the helix axis. Using 1BNA-extracted residues for LADDER carries a
residual ring buckle (the crystal bases aren't perfectly planar), which
MN's Style Cartoon node picks up and turns into a visible radial tilt
of the rendered rung blocks.

This module builds idealised templates from scratch with every base
ring atom placed exactly in the z=0 plane. The cartoon node then
computes a normal of exactly +Z from any three ring atoms it samples,
so every rung renders flat by construction.

Two flavours, picked by the ``realistic`` flag:

* ``realistic=False`` (stylised): every atom — base AND backbone — at
  z=0. Each residue is a flat 2D sheet. Clean geometric ladder.
* ``realistic=True``: base ring atoms at z=0; sugar/phosphate backbone
  keeps a natural 3D extent so ball-and-stick still reads as a real
  nucleotide. Bases are still perfectly flat, so cartoon remains clean.

Template space convention (matches what ``sequence_builder`` expects):

* C1' at origin (0, 0, 0).
* Base ring centroid lies on the -X axis (so the base faces inward
  toward the helix axis after the residue is placed at world ±X).
* Glycosidic atom (N1 for pyrimidine, N9 for purine) on the -X axis
  between C1' and the ring centroid, at distance ``_GLYC_BOND_LEN``
  from C1'.
* All base ring atoms lie in the z=0 plane.

LADDER mode picks anti up by X-axis-flipping a sense template (y→-y,
z→-z), which produces an antiparallel-backbone partner. Because base
atoms are at z=0, the flip leaves them at z=0 — paired bases on the
two strands land at identical world Z and the cartoon node renders
them as one continuous flat rung.
"""

from __future__ import annotations

import math

import numpy as np
import biotite.structure as struc


# ---------------------------------------------------------------------------
# Geometric constants
# ---------------------------------------------------------------------------

# C1' helix radius for ladder mode (matches 1BNA average, used by
# sequence_builder to place each strand at ±LADDER_RADIUS on X).
LADDER_RADIUS = 5.9  # Angstroms

# Aromatic ring bond length (uniform for all our regular polygons).
_RING_BOND_LEN = 1.4

# Glycosidic bond: C1' to N1 (pyrimidines) or N9 (purines).
_GLYC_BOND_LEN = 1.47

# Single-bond lengths for "extra" substituents off the ring.
_C_O_DBL = 1.24
_C_N_SGL = 1.34
_C_C_SGL = 1.50

# Hexagon circumradius (= side length for a regular hexagon).
_HEX_R = _RING_BOND_LEN

# Pentagon circumradius for a regular pentagon with given side length.
_PENT_R = _RING_BOND_LEN / (2.0 * math.sin(math.pi / 5.0))

# Hexagon apothem (centre to edge midpoint).
_HEX_APOTHEM = _RING_BOND_LEN * math.sqrt(3.0) / 2.0


# ---------------------------------------------------------------------------
# Base ring positions (all at z=0)
# ---------------------------------------------------------------------------


def _pyrimidine_ring() -> dict[str, tuple[float, float, float]]:
    """Regular hexagon for the pyrimidine 6-ring.

    N1 (glycosidic) is the +X vertex closest to C1' at origin. Going CW
    (decreasing y for second atom) around the ring: N1, C2, N3, C4, C5, C6.
    """
    # Centroid: distance _GLYC_BOND_LEN + _HEX_R from C1' along -X.
    cx = -(_GLYC_BOND_LEN + _HEX_R)
    cy = 0.0

    # Vertex 0 (N1) at angle 0° from centroid (i.e., +X direction).
    # Subsequent vertices step by -60° (CW).
    order = ["N1", "C2", "N3", "C4", "C5", "C6"]
    out: dict[str, tuple[float, float, float]] = {}
    for i, name in enumerate(order):
        ang = math.radians(-60.0 * i)
        out[name] = (cx + _HEX_R * math.cos(ang),
                     cy + _HEX_R * math.sin(ang),
                     0.0)
    return out


def _purine_rings() -> dict[str, tuple[float, float, float]]:
    """Regular pentagon (5-ring) + regular hexagon (6-ring) fused at C4-C5.

    N9 is the glycosidic attachment, the +X vertex of the pentagon
    closest to C1' at origin. 5-ring CW order from N9: N9, C4, C5, N7, C8.
    The fused C4-C5 edge faces the upper-left; the 6-ring is anchored
    there. 6-ring CW order from C5: C5, C6, N1, C2, N3, C4.

    Layout choices are arbitrary stylistic conventions — what matters is
    that every atom ends up at z=0 and the inter-ring topology is correct.
    """
    out: dict[str, tuple[float, float, float]] = {}

    # ---- Pentagon (5-ring) ----
    pent_cx = -(_GLYC_BOND_LEN + _PENT_R)
    pent_cy = 0.0
    # CW from N9 (at angle 0°): N9, C4, C5, N7, C8
    # step = -72° per atom.
    pent_order = ["N9", "C4", "C5", "N7", "C8"]
    for i, name in enumerate(pent_order):
        ang = math.radians(-72.0 * i)
        out[name] = (pent_cx + _PENT_R * math.cos(ang),
                     pent_cy + _PENT_R * math.sin(ang),
                     0.0)

    # ---- Hexagon (6-ring) ----
    # Anchor at the C4-C5 edge. C4 and C5 are already placed.
    c4 = np.array(out["C4"][:2])
    c5 = np.array(out["C5"][:2])
    mid = (c4 + c5) / 2.0
    n9 = np.array(out["N9"][:2])
    # 6-ring extends away from N9.
    away = mid - n9
    away_unit = away / np.linalg.norm(away)
    hex_cx, hex_cy = (mid + away_unit * _HEX_APOTHEM)

    # Identify the angular position of C4 and C5 viewed from the hex centre.
    ang_c4 = math.atan2(c4[1] - hex_cy, c4[0] - hex_cx)
    ang_c5 = math.atan2(c5[1] - hex_cy, c5[0] - hex_cx)
    # They differ by ±60° on the hexagon. Pick the angular step that
    # moves from C4 *away* from C5 (i.e., into the unshared part of
    # the ring). If C5 sits at ang_c4 - 60° then "away" is +60°.
    step = +60.0 if _ang_diff(ang_c5, ang_c4 - math.radians(60.0)) < math.radians(1.0) \
                else -60.0

    # 6-ring atoms going from C4 away from C5: C4 → N3 → C2 → N1 → C6 → C5.
    hex_order_from_c4 = ["N3", "C2", "N1", "C6"]
    cur = ang_c4
    for name in hex_order_from_c4:
        cur += math.radians(step)
        out[name] = (hex_cx + _HEX_R * math.cos(cur),
                     hex_cy + _HEX_R * math.sin(cur),
                     0.0)

    # Stash the hex centre — handy for placing the exocyclic atoms.
    out["_hex_center"] = (hex_cx, hex_cy, 0.0)
    return out


def _ang_diff(a: float, b: float) -> float:
    """Smallest angular distance |a-b| in [0, π]."""
    d = (a - b) % (2.0 * math.pi)
    if d > math.pi:
        d = 2.0 * math.pi - d
    return d


def _bond_outward(atom_xy: tuple[float, float],
                  ring_centre_xy: tuple[float, float],
                  bond_len: float) -> tuple[float, float, float]:
    """Place an exocyclic atom in the z=0 plane, bonded to *atom_xy* and
    pointing away from *ring_centre_xy* by *bond_len* Å."""
    direction = np.array(atom_xy) - np.array(ring_centre_xy)
    norm = np.linalg.norm(direction)
    if norm < 1e-9:
        return (atom_xy[0], atom_xy[1], 0.0)
    unit = direction / norm
    pos = np.array(atom_xy) + unit * bond_len
    return (float(pos[0]), float(pos[1]), 0.0)


# ---------------------------------------------------------------------------
# Per-base atom tables
# ---------------------------------------------------------------------------


def _atoms_for_DA() -> dict[str, tuple[float, float, float]]:
    pos = _purine_rings()
    hex_c = pos["_hex_center"]
    pos["N6"] = _bond_outward(pos["C6"][:2], hex_c[:2], _C_N_SGL)
    pos.pop("_hex_center", None)
    return pos


def _atoms_for_DG() -> dict[str, tuple[float, float, float]]:
    pos = _purine_rings()
    hex_c = pos["_hex_center"]
    pos["O6"] = _bond_outward(pos["C6"][:2], hex_c[:2], _C_O_DBL)
    pos["N2"] = _bond_outward(pos["C2"][:2], hex_c[:2], _C_N_SGL)
    pos.pop("_hex_center", None)
    return pos


def _atoms_for_DC() -> dict[str, tuple[float, float, float]]:
    pos = _pyrimidine_ring()
    centre = (-(_GLYC_BOND_LEN + _HEX_R), 0.0)
    pos["O2"] = _bond_outward(pos["C2"][:2], centre, _C_O_DBL)
    pos["N4"] = _bond_outward(pos["C4"][:2], centre, _C_N_SGL)
    return pos


def _atoms_for_DT() -> dict[str, tuple[float, float, float]]:
    pos = _pyrimidine_ring()
    centre = (-(_GLYC_BOND_LEN + _HEX_R), 0.0)
    pos["O2"] = _bond_outward(pos["C2"][:2], centre, _C_O_DBL)
    pos["O4"] = _bond_outward(pos["C4"][:2], centre, _C_O_DBL)
    pos["C7"] = _bond_outward(pos["C5"][:2], centre, _C_C_SGL)
    return pos


_BASE_BUILDERS = {
    "DA": _atoms_for_DA,
    "DG": _atoms_for_DG,
    "DC": _atoms_for_DC,
    "DT": _atoms_for_DT,
}


# ---------------------------------------------------------------------------
# Backbone positions (sugar + phosphate)
# ---------------------------------------------------------------------------
#
# Canonical B-DNA-like positions for the sugar-phosphate backbone,
# parameterised so the sense template runs 5'→3' upward (P at low Z,
# O3' at high Z). The X-axis flip applied to anti by sequence_builder
# inverts these Z signs, giving an antiparallel partner with O3'(i)
# right next to P(i+1) — the inter-residue gap closes cleanly even
# though we skip the explicit O3'→P bond in ladder mode.
#
# For the stylised template every backbone atom is forced to z=0 so the
# whole residue is a flat 2D sheet. For the realistic template the
# canonical z values are kept.

# Distance from C1' (template origin) at which the phosphate sits, picked
# so |z_P| + |z_O3'| ≈ rise (3.38 Å) — that's what makes the antiparallel
# backbone connect smoothly when anti is X-flipped.
_BACKBONE_REALISTIC: dict[str, tuple[float, float, float]] = {
    # C1' anchors the template at the origin.
    "C1'": (0.00, 0.00, 0.00),
    # Sugar ring (deoxyribose). z values modest (~1 Å) so the sugar
    # sits just behind the base from the helix axis view.
    "C2'": (1.20, 0.00, -0.40),
    "C3'": (1.55, 1.30, 0.00),
    "C4'": (0.45, 2.10, 0.50),
    "O4'": (-0.50, 1.05, 0.30),
    # 3' side (downstream in 5'→3' direction): O3' ABOVE C1'.
    "O3'": (2.20, 1.40, 1.30),
    # 5' side (upstream): O5', C5', and the phosphate group BELOW C1'.
    "C5'": (0.65, 2.85, -0.50),
    "O5'": (1.60, 2.40, -1.45),
    "P":   (1.60, 1.50, -1.85),
    "OP1": (0.40, 0.95, -2.45),
    "OP2": (2.70, 0.65, -2.25),
}


def _backbone_positions(realistic: bool) -> dict[str, tuple[float, float, float]]:
    """Return sugar+phosphate atom positions for the residue template.

    realistic=True keeps the canonical 3D z extents. realistic=False
    snaps everything to z=0 so the whole residue is a flat 2D sheet.
    """
    if realistic:
        return dict(_BACKBONE_REALISTIC)
    return {name: (x, y, 0.0) for name, (x, y, _z) in _BACKBONE_REALISTIC.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_BASE_NAME_FOR_TEMPLATE = {
    "DA": "DA", "DG": "DG", "DC": "DC", "DT": "DT",
}

# MN's cartoon style for nucleotides samples a specific "far endpoint" ring
# atom to build the base block's long axis: N1 for purine, N3 for pyrimidine
# (see .Sample Nucleic Base Values in MN_data_file_*.blend — atom codes 62/64).
# After build the template is rotated about C1' (the origin) so that this
# endpoint lands on the -X axis. This guarantees MN's `base_position - base_pivot`
# vector is purely radial, so the cartoon rung renders as a flat horizontal
# bar in top-down view instead of a tilted parallelogram.
_FAR_ENDPOINT = {"DA": "N1", "DG": "N1", "DC": "N3", "DT": "N3"}

# Uniform Rungs mode forces every residue's res_name to DT, so MN's Cartoon
# treats every base as pyrimidine and samples N3 (atom 64) as the far endpoint
# even on residues whose actual atoms are purine. Aligning purines by their
# own N1 (as above) leaves N3 off-axis — the inner edge of the rung block
# tilts. To keep rungs flat in uniform mode we align purine templates by N3
# too, so the cartoon's pyrimidine sampling lands on -X for every residue.
_FAR_ENDPOINT_UNIFORM = {"DA": "N3", "DG": "N3", "DC": "N3", "DT": "N3"}


# Fixed backbone rotation used in every template. Aligning the rail this way
# (instead of per-base) keeps C3'/C4'/P at identical positions across all four
# bases, so MN's Cartoon rail tangent (sampled from those atoms) gives a
# straight side profile instead of zig-zagging when consecutive residues are
# different bases. The angle was picked midway between the per-base alignment
# angles that put N1 (purine) or N3 (pyrimidine) on -X — close enough that the
# glycosidic bond still points roughly toward the helix axis in every base.
_BACKBONE_ROT_RAD = math.radians(-20.0)


def _align_far_endpoint_to_neg_x(
    base_atoms: dict[str, tuple[float, float, float]],
    backbone_atoms: dict[str, tuple[float, float, float]],
    template_key: str,
    schematic: bool = False,
) -> None:
    """Align the base ring (per base type) and the backbone (uniform).

    The base ring rotates by whatever angle puts the cartoon's far-endpoint
    atom on the -X axis (N1 for purines / N3 for pyrimidines, or N3 for all
    in ``schematic`` mode). MN's Cartoon block uses C1'→far-endpoint for the
    rung's long axis, so this keeps every rung pointing radially.

    The backbone rotates by a single fixed angle (``_BACKBONE_ROT_RAD``) for
    every base type. That gives MN's Cartoon a rail with identical
    C3'/C4'/P positions across consecutive residues, so the side profile
    reads as a straight bar and the block ends sit at consistent Z values.
    Rotating the backbone by the per-base angle (the previous behaviour)
    drifted those atoms a couple of degrees apart and produced both a wavy
    rail in side view and tilted blocks that visibly overlapped in close
    perspective.

    C1' stays at the origin in both dicts (rotation pivots about it), so the
    glycosidic bond endpoint lands close to the X axis but with a small
    chi-angle offset — invisible in cartoon style.
    """
    endpoints = _FAR_ENDPOINT_UNIFORM if schematic else _FAR_ENDPOINT
    endpoint_name = endpoints[template_key]
    ex, ey, _ = base_atoms[endpoint_name]
    r = math.hypot(ex, ey)
    if r < 1e-9:
        return
    # Per-base rotation that maps the far-endpoint direction onto (-1, 0).
    base_rot = math.pi - math.atan2(ey, ex)
    cos_b, sin_b = math.cos(base_rot), math.sin(base_rot)
    for name, (x, y, z) in base_atoms.items():
        base_atoms[name] = (x * cos_b - y * sin_b, x * sin_b + y * cos_b, z)

    # Backbone uses one fixed rotation, identical for every template.
    cos_k, sin_k = math.cos(_BACKBONE_ROT_RAD), math.sin(_BACKBONE_ROT_RAD)
    for name, (x, y, z) in backbone_atoms.items():
        backbone_atoms[name] = (x * cos_k - y * sin_k, x * sin_k + y * cos_k, z)


def build_canonical_template(
    template_key: str, realistic: bool, schematic: bool = False
) -> struc.AtomArray:
    """Build an idealised template AtomArray for one base type.

    Parameters
    ----------
    template_key : str
        ``'DA'``, ``'DG'``, ``'DC'``, or ``'DT'``. RNA uses the DNA
        templates too; sequence_builder swaps res_name and strips C7
        when emitting RNA uracil.
    realistic : bool
        Backbone z extent. True = 3D backbone (recognisable nucleotide
        in ball-and-stick). False = backbone collapsed to z=0 (clean
        geometric ladder).
    schematic : bool
        Uniform Rungs mode. When True, align every template by its N3 atom
        (the pyrimidine far endpoint MN's Cartoon samples once every
        residue's res_name is forced to DT). Defaults to False for the
        normal per-base purine/pyrimidine alignment.
    """
    if template_key not in _BASE_BUILDERS:
        raise ValueError(f"Unknown template_key: {template_key!r}")

    base_atoms = _BASE_BUILDERS[template_key]()
    backbone_atoms = _backbone_positions(realistic)
    _align_far_endpoint_to_neg_x(
        base_atoms, backbone_atoms, template_key, schematic=schematic
    )

    # Assemble: backbone first (so atom_id ordering reads 5'→3' sugar
    # then base), then base atoms.
    names: list[str] = []
    coords: list[tuple[float, float, float]] = []
    for name, pos in backbone_atoms.items():
        names.append(name)
        coords.append(pos)
    for name, pos in base_atoms.items():
        names.append(name)
        coords.append(pos)

    n = len(names)
    arr = struc.AtomArray(n)
    arr.coord = np.array(coords, dtype=np.float32)
    arr.atom_name = np.array(names, dtype="<U6")
    arr.element = np.array([_element_for(name) for name in names], dtype="<U2")
    arr.chain_id = np.array(["A"] * n, dtype="<U4")
    arr.res_id = np.zeros(n, dtype=np.int32)
    arr.res_name = np.array([template_key] * n, dtype="<U5")
    arr.hetero = np.zeros(n, dtype=bool)
    # atom_id is a custom annotation that _place_nucleotide overwrites; it
    # must exist on the template (assigning to a missing annotation creates
    # an instance attribute, not a real annotation).
    arr.set_annotation("atom_id", np.arange(1, n + 1, dtype=np.int32))
    return arr


def _element_for(atom_name: str) -> str:
    """Map atom name → element symbol.

    Nucleotide atom names start with the element letter for our atoms:
    N1/N3/N6/..., C1'/C2/.../C7, O2/O4/O3'/..., P. The only quirk is
    the prime symbol on sugar atoms.
    """
    first = atom_name[0]
    return first


def get_canonical_templates(
    realistic: bool, schematic: bool = False
) -> dict[str, struc.AtomArray]:
    """Return {DA, DT, DG, DC} as idealised LADDER templates."""
    return {
        key: build_canonical_template(key, realistic=realistic, schematic=schematic)
        for key in ("DA", "DT", "DG", "DC")
    }
