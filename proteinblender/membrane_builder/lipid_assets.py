"""Lipid variant assets for the Membrane Builder.

Two render styles, each in its own collection — the user picks one in the
panel and the GN modifier re-points its ``Lipid Collection`` input.

* ``STYLIZED`` (4 assets)
    One head sphere + two bent tail chains following the carbon
    backbones of each PDB conformation. Built by walking the bond graph
    to identify the two acyl tails per PX4 lipid, then drawing each tail
    as a chain of thin cylinder segments with small joint spheres at
    every carbon. Different PDB poses → visibly different tail bends —
    the variety the user asked for, without the per-atom detail.

* ``BALL_AND_STICK`` (4 assets)
    Real PDB conformations as icosphere atoms + cylinder bonds. The four
    PX4 variants live in ``data/lipid_{1..4}.pdb``; they're parsed,
    oriented head-up, and baked once per session.

Every asset is parked unlinked-from-scene and gathered into its render-
style collection. ``GeometryNodeCollectionInfo`` reads the collection
just fine without it being part of the scene hierarchy.

Orientation: every lipid is rotated so the head→tail axis aligns with
-Z and the P atom sits at z ≈ +4 Å. Both styles share this anchor, so
swapping styles doesn't shift where the lipid lands.
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Matrix, Vector
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Render styles
# ---------------------------------------------------------------------------

STYLE_STYLIZED = "STYLIZED"
STYLE_BALL_AND_STICK = "BALL_AND_STICK"

RENDER_STYLE_ITEMS = (
    (STYLE_STYLIZED, "Stylized",
     "Abstract head sphere + two tail chains that follow each PDB pose"),
    (STYLE_BALL_AND_STICK, "Ball and Stick",
     "Real PX4 conformations: atoms as spheres, bonds as cylinders"),
)

DEFAULT_STYLE = STYLE_BALL_AND_STICK

_COLLECTION_NAMES: Dict[str, str] = {
    STYLE_STYLIZED: "PB_Membrane_Lipid_Variants_Stylized",
    STYLE_BALL_AND_STICK: "PB_Membrane_Lipid_Variants_BallStick",
}

RENDER_STYLE_VARIANT_COUNT: Dict[str, int] = {
    STYLE_STYLIZED: 4,
    STYLE_BALL_AND_STICK: 4,
}


# ---------------------------------------------------------------------------
# Bundled PDB sources
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent / "data"
LIPID_PDB_NAMES: Tuple[str, ...] = (
    "lipid_1.pdb",
    "lipid_2.pdb",
    "lipid_3.pdb",
    "lipid_4.pdb",
)
NUM_LIPID_VARIANTS: int = len(LIPID_PDB_NAMES)

LIPID_COLLECTION_NAME = _COLLECTION_NAMES[STYLE_BALL_AND_STICK]


# ---------------------------------------------------------------------------
# Geometry constants
# ---------------------------------------------------------------------------

# 1 Å = 0.01 BU (matches MN_SCALE = 0.01).
_ANG_TO_BU = 0.01

# ---- Ball-and-stick sizing (matches the original head-sphere mass) ----
_BS_RADIUS_BU = {
    "P": 0.038,
    "O": 0.030,
    "N": 0.032,
    "C": 0.026,
    "H": 0.012,
}
_BS_DEFAULT_RADIUS_BU = 0.025
_BS_BOND_RADIUS_BU = 0.011
_BS_SUBDIV = 2

# ---- Stylized sizing ----
_STYLIZED_HEAD_RADIUS_BU = 0.04   # ~4 Å head sphere (matches v5 procedural)
_STYLIZED_TAIL_RADIUS_BU = 0.012  # tube radius (bevel_depth on the Bezier)
# Bezier tube resolution per control-point segment (samples along length)
# and around the circumference. 6 / 4 keeps the per-lipid poly count modest
# (~1.5k polys per tail) while reading as a smooth bent tube at this scale.
_STYLIZED_TUBE_RES_U = 6
_STYLIZED_TUBE_RES_BEVEL = 4
_STYLIZED_FALLBACK_TAIL_LENGTH_BU = 0.18
_STYLIZED_FALLBACK_TAIL_OFFSET_X_BU = 0.018

# Bond inference cutoff in Å — covers C-C / C-O / C-N / C-P bonds in PX4.
_BOND_CUTOFF_ANG = 1.85

# Atoms treated as "head group" (slot 0) vs tail (slot 1) for ball-and-
# stick colouring. Element-based — matches standard B&S convention.
_HEAD_ELEMENTS = frozenset({"P", "N", "O"})


# ---------------------------------------------------------------------------
# PDB parsing
# ---------------------------------------------------------------------------

def _parse_pdb(path: Path) -> List[Tuple[str, Vector]]:
    """Return ``[(element, position_in_Ang), ...]`` from a PDB file."""
    atoms: List[Tuple[str, Vector]] = []
    with open(path, "r") as f:
        for line in f:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
            except (ValueError, IndexError):
                continue
            element = line[76:78].strip().upper() if len(line) >= 78 else ""
            if not element:
                name = line[12:16].strip()
                element = "".join(c for c in name if c.isalpha())[:1].upper()
            atoms.append((element, Vector((x, y, z))))
    return atoms


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

def _orient_to_zaxis(atoms: List[Tuple[str, Vector]]) -> List[Tuple[str, Vector]]:
    """Rotate atoms so head→tail axis aligns with -Z, place P atom at z ≈ +4 Å."""
    import numpy as np

    head_pts = np.array(
        [list(p) for el, p in atoms if el in _HEAD_ELEMENTS], dtype=float)
    tail_pts = np.array(
        [list(p) for el, p in atoms if el == "C"], dtype=float)
    all_pts = np.array([list(p) for _, p in atoms], dtype=float)

    if len(head_pts) == 0 or len(tail_pts) == 0:
        return atoms

    axis = tail_pts.mean(axis=0) - head_pts.mean(axis=0)
    n = np.linalg.norm(axis)
    if n < 1e-6:
        return atoms
    axis /= n

    rot = _rotation_aligning(axis, np.array([0.0, 0.0, -1.0]))
    rotated = (all_pts - all_pts.mean(axis=0)) @ rot.T

    p_indices = [i for i, (el, _) in enumerate(atoms) if el == "P"]
    if p_indices:
        p_idx = p_indices[0]
        rotated[:, 0] -= rotated[p_idx, 0]
        rotated[:, 1] -= rotated[p_idx, 1]
        rotated[:, 2] += 4.0 - rotated[p_idx, 2]

    return [(el, Vector(rotated[i].tolist())) for i, (el, _) in enumerate(atoms)]


def _rotation_aligning(from_vec, to_vec):
    """Return the 3×3 rotation matrix that aligns ``from_vec`` onto ``to_vec``.

    Pure numpy — no scipy dependency. Uses the trig-free form of
    Rodrigues' formula: ``R = I + [v]× + [v]×² / (1 + c)`` where
    ``v = a × b`` and ``c = a · b`` (both inputs first normalised).
    The 180° edge case (``c ≈ -1``) is handled separately because the
    formula has a 1/(1+c) singularity there.

    Apply to a batch of row-vector points with ``points @ R.T``.
    """
    import numpy as np

    a = np.asarray(from_vec, dtype=float)
    b = np.asarray(to_vec, dtype=float)
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = float(np.linalg.norm(v))

    if s < 1e-8:
        if c > 0.0:
            return np.eye(3)
        # 180° flip: rotate around any axis perpendicular to ``a``.
        perp = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, np.array([0.0, 1.0, 0.0]))
        perp = perp / np.linalg.norm(perp)
        # R = 2·(perp⊗perp) − I  is a 180° rotation about ``perp``.
        return 2.0 * np.outer(perp, perp) - np.eye(3)

    K = np.array([
        [0.0,  -v[2],  v[1]],
        [v[2],   0.0, -v[0]],
        [-v[1], v[0],   0.0],
    ])
    return np.eye(3) + K + (K @ K) / (1.0 + c)


# ---------------------------------------------------------------------------
# Bond inference + tail finding
# ---------------------------------------------------------------------------

def _infer_bonds(atoms: List[Tuple[str, Vector]]) -> List[Tuple[int, int]]:
    """Pairwise distance cutoff — anything closer than _BOND_CUTOFF_ANG is bonded."""
    cutoff_sq = _BOND_CUTOFF_ANG ** 2
    bonds: List[Tuple[int, int]] = []
    n = len(atoms)
    for i in range(n):
        _, pi = atoms[i]
        for j in range(i + 1, n):
            _, pj = atoms[j]
            if (pi - pj).length_squared < cutoff_sq:
                bonds.append((i, j))
    return bonds


def _find_acyl_tails(
        atoms: List[Tuple[str, Vector]],
        bonds: List[Tuple[int, int]],
) -> Optional[List[List[int]]]:
    """Walk the bond graph to extract the two acyl tails as ordered carbon
    chains, starting at each tail's carbonyl carbon.

    Method: drop all non-carbon atoms from the graph, take connected
    components, keep the two largest (= the two fatty-acyl chains; the
    smaller components are choline ethyl, choline methyls, and glycerol).
    For each chain, the carbonyl carbon is the one whose FULL-graph
    neighbours include an oxygen — start there and walk the chain.

    Returns ``None`` if the topology doesn't yield two clean tails (caller
    falls back to straight cylinders for that variant).
    """
    n = len(atoms)
    elements = [el for el, _ in atoms]
    adj: Dict[int, List[int]] = {i: [] for i in range(n)}
    for i, j in bonds:
        adj[i].append(j)
        adj[j].append(i)

    # Connected components, restricted to C atoms.
    visited: set = set()
    components: List[List[int]] = []
    for seed in range(n):
        if elements[seed] != "C" or seed in visited:
            continue
        comp: List[int] = []
        stack = [seed]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            comp.append(cur)
            for nb in adj[cur]:
                if elements[nb] == "C" and nb not in visited:
                    stack.append(nb)
        components.append(comp)

    components.sort(key=len, reverse=True)
    if len(components) < 2 or len(components[1]) < 4:
        # Not enough structure — only one big chain, or the second "chain"
        # is just a glycerol fragment. Fall back to straight tails.
        return None

    tails: List[List[int]] = []
    for comp in components[:2]:
        comp_set = set(comp)
        # Carbonyl C: the only carbon in the component that's bonded to
        # an oxygen in the full graph.
        start = next(
            (i for i in comp if any(elements[nb] == "O" for nb in adj[i])),
            None,
        )
        if start is None:
            return None  # malformed — fall back

        # Linear walk down the chain. Fatty acyls don't branch; if any
        # bookkeeping issue produced a branch, prefer the longest continuation.
        ordered = [start]
        prev: Optional[int] = None
        cur = start
        while True:
            nxts = [nb for nb in adj[cur]
                    if elements[nb] == "C" and nb in comp_set and nb != prev]
            if not nxts:
                break
            prev = cur
            cur = nxts[0]
            if cur in ordered:
                break  # cycle guard (shouldn't happen for acyl chains)
            ordered.append(cur)
        tails.append(ordered)

    return tails


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

HEAD_MATERIAL_NAME = "PB_Membrane_Head"
TAIL_MATERIAL_NAME = "PB_Membrane_Tail"


def _ensure_material(name, color, roughness=0.4):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = color
    return mat


def _ensure_head_tail_materials():
    head_mat = _ensure_material(HEAD_MATERIAL_NAME, (0.92, 0.30, 0.55, 1.0), 0.35)
    tail_mat = _ensure_material(TAIL_MATERIAL_NAME, (0.98, 0.82, 0.30, 1.0), 0.55)
    return head_mat, tail_mat


def _attach_head_tail_materials(mesh):
    head_mat, tail_mat = _ensure_head_tail_materials()
    if not mesh.materials:
        mesh.materials.append(head_mat)
        mesh.materials.append(tail_mat)


# ---------------------------------------------------------------------------
# Mesh-build helpers
# ---------------------------------------------------------------------------

def _add_icosphere(bm, pos_bu: Vector, radius: float, subdivisions: int,
                   material_index: int) -> None:
    n_before = len(bm.faces)
    bmesh.ops.create_icosphere(
        bm,
        subdivisions=subdivisions,
        radius=radius,
        matrix=Matrix.Translation(pos_bu),
    )
    bm.faces.ensure_lookup_table()
    for f in bm.faces[n_before:]:
        f.material_index = material_index


def _add_bond_cylinder(bm, a: Vector, b: Vector, radius: float,
                        segments: int, material_index: int) -> None:
    vec = b - a
    length = vec.length
    if length < 1e-6:
        return
    z_axis = Vector((0.0, 0.0, 1.0))
    mid = (a + b) * 0.5
    rot = z_axis.rotation_difference(vec.normalized()).to_matrix().to_4x4()
    n_before = len(bm.faces)
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=length,
        matrix=Matrix.Translation(mid) @ rot,
    )
    bm.faces.ensure_lookup_table()
    for f in bm.faces[n_before:]:
        f.material_index = material_index


def _tube_mesh_through(points: List[Vector], radius: float) -> bpy.types.Mesh:
    """Build a smooth bent-tube mesh that passes through ``points``.

    Uses a Bezier curve with AUTO handles + ``bevel_depth = radius`` so the
    tube is C¹-smooth between control points (no visible kinks). The
    intermediate curve / object datablocks are deleted before returning;
    callers ``bm.from_mesh(...)`` the result and then ``bpy.data.meshes
    .remove(...)`` it.
    """
    curve = bpy.data.curves.new("_pb_lipid_tube_tmp", type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = _STYLIZED_TUBE_RES_BEVEL
    curve.use_fill_caps = True
    curve.resolution_u = _STYLIZED_TUBE_RES_U

    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.bezier_points[i].co = p
    for bp in spline.bezier_points:
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"

    tmp_obj = bpy.data.objects.new("_pb_lipid_tube_tmp_obj", curve)
    try:
        mesh = bpy.data.meshes.new_from_object(tmp_obj)
    finally:
        bpy.data.objects.remove(tmp_obj, do_unlink=True)
        bpy.data.curves.remove(curve)
    return mesh


def _absorb_mesh(bm, src_mesh: bpy.types.Mesh, material_index: int) -> None:
    """Append ``src_mesh`` into the bmesh and tag its new faces."""
    n_before = len(bm.faces)
    bm.from_mesh(src_mesh)
    bm.faces.ensure_lookup_table()
    for f in bm.faces[n_before:]:
        f.material_index = material_index


def _finalize_mesh(bm, name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    _attach_head_tail_materials(mesh)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return bpy.data.objects.new(name, mesh)


# ---------------------------------------------------------------------------
# Style: BALL_AND_STICK
# ---------------------------------------------------------------------------

def _build_ball_and_stick(pdb_path: Path, name: str) -> bpy.types.Object:
    atoms = _orient_to_zaxis(_parse_pdb(pdb_path))
    bonds = _infer_bonds(atoms)
    bm = bmesh.new()

    for el, pos_ang in atoms:
        pos_bu = pos_ang * _ANG_TO_BU
        radius = _BS_RADIUS_BU.get(el, _BS_DEFAULT_RADIUS_BU)
        mat_idx = 0 if el in _HEAD_ELEMENTS else 1
        _add_icosphere(bm, pos_bu, radius, _BS_SUBDIV, mat_idx)

    for i, j in bonds:
        el_i, pi = atoms[i]
        el_j, pj = atoms[j]
        both_head = (el_i in _HEAD_ELEMENTS) and (el_j in _HEAD_ELEMENTS)
        mat_idx = 0 if both_head else 1
        _add_bond_cylinder(bm, pi * _ANG_TO_BU, pj * _ANG_TO_BU,
                           _BS_BOND_RADIUS_BU, 8, mat_idx)

    return _finalize_mesh(bm, name)


# ---------------------------------------------------------------------------
# Style: STYLIZED (bent tails, per-PDB)
# ---------------------------------------------------------------------------

def _build_stylized(pdb_path: Path, name: str) -> bpy.types.Object:
    """Head sphere at the P position + two smooth bent tubes that follow
    the carbon backbones of this PDB pose.

    Each tail is rendered as a single Bezier-curve tube passing through
    the head P + every carbon of the tail — so the tube is C¹-smooth
    between control points and reads as one continuous bent leg, not a
    chain of joints. The head sphere covers the tube's entry at the P.

    Falls back to two straight cylinders if the bond-graph walk can't
    cleanly identify two acyl chains.
    """
    atoms = _orient_to_zaxis(_parse_pdb(pdb_path))
    bonds = _infer_bonds(atoms)
    p_idx = next((i for i, (el, _) in enumerate(atoms) if el == "P"), None)
    tails = _find_acyl_tails(atoms, bonds) if p_idx is not None else None

    bm = bmesh.new()

    if p_idx is not None:
        p_pos_bu = atoms[p_idx][1] * _ANG_TO_BU
    else:
        p_pos_bu = Vector((0.0, 0.0, _STYLIZED_HEAD_RADIUS_BU))

    # Head sphere centred on the phosphate (or origin fallback).
    _add_icosphere(bm, p_pos_bu, _STYLIZED_HEAD_RADIUS_BU,
                   subdivisions=2, material_index=0)

    if tails is None or p_idx is None:
        # Fallback: classic two straight cylinders pointing -Z, attached
        # under the head sphere.
        z_axis = Vector((0.0, 0.0, 1.0))
        down = Vector((0.0, 0.0, -1.0))
        rot_down = z_axis.rotation_difference(down).to_matrix().to_4x4()
        for sign_x in (-1.0, 1.0):
            mid = Vector((
                p_pos_bu.x + sign_x * _STYLIZED_FALLBACK_TAIL_OFFSET_X_BU,
                p_pos_bu.y,
                p_pos_bu.z - _STYLIZED_HEAD_RADIUS_BU
                    - _STYLIZED_FALLBACK_TAIL_LENGTH_BU / 2.0,
            ))
            n_before = len(bm.faces)
            bmesh.ops.create_cone(
                bm,
                cap_ends=True,
                cap_tris=False,
                segments=8,
                radius1=_STYLIZED_TAIL_RADIUS_BU,
                radius2=_STYLIZED_TAIL_RADIUS_BU,
                depth=_STYLIZED_FALLBACK_TAIL_LENGTH_BU,
                matrix=Matrix.Translation(mid) @ rot_down,
            )
            bm.faces.ensure_lookup_table()
            for f in bm.faces[n_before:]:
                f.material_index = 1
        return _finalize_mesh(bm, name)

    # Bent tails: one smooth Bezier tube per tail, threaded through P →
    # carbonyl C → … → tail tip. Including P as the first control point
    # makes the tube enter the head sphere cleanly with no visible seam.
    for tail in tails:
        path = [p_pos_bu] + [atoms[i][1] * _ANG_TO_BU for i in tail]
        tube_mesh = _tube_mesh_through(path, _STYLIZED_TAIL_RADIUS_BU)
        try:
            _absorb_mesh(bm, tube_mesh, material_index=1)
        finally:
            bpy.data.meshes.remove(tube_mesh)

    return _finalize_mesh(bm, name)


# ---------------------------------------------------------------------------
# Collection assembly
# ---------------------------------------------------------------------------

# Suffix per style — included in the asset name so style transitions and
# any future builder revisions don't collide with stale objects.
_STYLE_ASSET_SUFFIX = {
    STYLE_STYLIZED: "StylizedBent",
    STYLE_BALL_AND_STICK: "BallStick",
}


def _style_asset_name(style: str, i: int) -> str:
    return f"PB_Membrane_Lipid_{_STYLE_ASSET_SUFFIX[style]}_{i}"


def get_or_build_lipid_collection(style: str = DEFAULT_STYLE) -> bpy.types.Collection:
    """Build (or fetch) the collection holding the variants for ``style``.

    Both styles produce 4 variants (one per bundled PDB pose). The
    collection is unlinked from any scene — ``GeometryNodeCollectionInfo``
    reads it just fine, and the user's outliner stays clean.

    Any objects already in the collection whose names don't match the
    current style's naming scheme are unlinked, so swapping in a new
    builder revision doesn't leave stale assets behind.
    """
    if style not in _COLLECTION_NAMES:
        style = DEFAULT_STYLE

    coll_name = _COLLECTION_NAMES[style]
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)

    builder = {
        STYLE_STYLIZED: _build_stylized,
        STYLE_BALL_AND_STICK: _build_ball_and_stick,
    }[style]
    count = RENDER_STYLE_VARIANT_COUNT[style]
    expected = {_style_asset_name(style, i) for i in range(1, count + 1)}

    # Drop anything stale (e.g. the old v6 single ``Stylized_1`` asset)
    # so the random Instance Index only picks from current variants.
    for obj in list(coll.objects):
        if obj.name not in expected:
            try:
                coll.objects.unlink(obj)
            except Exception:
                pass

    for i, pdb_name in enumerate(LIPID_PDB_NAMES, start=1):
        asset_name = _style_asset_name(style, i)
        obj = bpy.data.objects.get(asset_name)
        if obj is None:
            pdb_path = _DATA_DIR / pdb_name
            if not pdb_path.is_file():
                # Bundled PDB missing — skip; the GN tree picks from
                # whatever variants ARE in the collection.
                continue
            obj = builder(pdb_path, asset_name)
        if obj.name not in coll.objects:
            coll.objects.link(obj)

    return coll


def variant_count_for_style(style: str) -> int:
    """Number of variants in ``style``'s collection — drives the random
    Instance Index max on the GN modifier."""
    return RENDER_STYLE_VARIANT_COUNT.get(style, 1)


# ---------------------------------------------------------------------------
# Legacy cleanup
# ---------------------------------------------------------------------------

def cleanup_legacy_lipid_asset() -> None:
    """Remove orphaned datablocks from past versions. Called by the
    GN-tree upgrade path so users don't accumulate dead meshes."""
    legacy_object_names = (
        "PB_Membrane_Lipid_Asset",        # v5 single procedural lipid
        "PB_Membrane_Lipid_Asset_1",      # v6 ball-and-stick (pre-rename)
        "PB_Membrane_Lipid_Asset_2",
        "PB_Membrane_Lipid_Asset_3",
        "PB_Membrane_Lipid_Asset_4",
        "PB_Membrane_Lipid_Stylized_1",   # v7 stylized single asset
        "PB_Membrane_Lipid_Surface_1",    # removed Surface style
        "PB_Membrane_Lipid_Surface_2",
        "PB_Membrane_Lipid_Surface_3",
        "PB_Membrane_Lipid_Surface_4",
    )
    for name in legacy_object_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.users != 0:
            continue
        mesh = obj.data
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            continue
        if (mesh is not None and isinstance(mesh, bpy.types.Mesh)
                and mesh.users == 0):
            try:
                bpy.data.meshes.remove(mesh)
            except Exception:
                pass

    legacy_collection_names = (
        "PB_Membrane_Lipid_Variants",          # pre-style-split (v6)
        "PB_Membrane_Lipid_Variants_Surface",  # removed Surface style
    )
    for cname in legacy_collection_names:
        coll = bpy.data.collections.get(cname)
        if coll is None:
            continue
        if len(coll.objects) == 0:
            try:
                bpy.data.collections.remove(coll)
            except Exception:
                pass
