"""Membrane geometry construction.

Builds:
- The lipid asset mesh (head sphere + two tail cylinders, one per leaflet).
- The Geometry Nodes tree that distributes lipid instances across the
  membrane surface with random Y-rotation, a 6-axis pseudo-random "mosh pit"
  jostle animation (bob / sway / lean / twist), and animatable circular holes.

The membrane object itself is a flat ``GeometryNodeMeshGrid``-style mesh
that lives at the controller's local origin and gets shaped by a Lattice
modifier (for deformation) before the GN modifier instances lipids onto it.

All sizes are in Blender units. We use a fixed conversion factor
``NM_PER_BU = 10`` (1 BU = 10 nm = 100 Å, matching MN_SCALE = 0.01).
"""

from __future__ import annotations

import math
import bpy
from typing import Tuple, List, Optional
from mathutils import Vector


# 1 BU = 10 nm. The MN convention is 1 BU = 100 Å.
NM_PER_BU = 10.0
MAX_HOLES = 8

# Geometry Nodes group / asset names — kept stable so we can find them again
# across rebuilds.
GN_TREE_NAME = "ProteinBlender_Membrane_GN"
LIPID_ASSET_NAME = "PB_Membrane_Lipid_Asset"
HEAD_MATERIAL_NAME = "PB_Membrane_Head"
TAIL_MATERIAL_NAME = "PB_Membrane_Tail"

# Bump whenever _build_membrane_gn_tree's node structure changes. Membranes
# saved with an older tree are detected via this tag and rebuilt on load.
#   v2: six-axis per-lipid mosh-pit motion
#   v3: holes redistribute lipids (radial push) instead of deleting them
#   v4: Poisson-disk lipid distribution + realistic default density
GN_TREE_VERSION = 4


# ===========================================================================
# Material helpers
# ===========================================================================

def _ensure_material(name: str, color: Tuple[float, float, float, float],
                     roughness: float = 0.4) -> bpy.types.Material:
    """Get-or-create a Principled BSDF material with the given diffuse colour."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    # Re-color if it already exists.
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
    # Also store the diffuse color on the material itself (used by some viewport modes).
    mat.diffuse_color = color
    return mat


def set_membrane_colors(membrane_obj: bpy.types.Object,
                         color_head: Tuple[float, float, float, float],
                         color_tail: Tuple[float, float, float, float]) -> None:
    """Re-color the shared lipid head/tail materials."""
    _ensure_material(HEAD_MATERIAL_NAME, color_head, roughness=0.35)
    _ensure_material(TAIL_MATERIAL_NAME, color_tail, roughness=0.55)


# ===========================================================================
# Lipid asset mesh
# ===========================================================================

def _build_lipid_mesh() -> bpy.types.Object:
    """Build the lipid asset object (a head sphere + two tails) once.

    The lipid is oriented with the head at +Z and tails extending toward -Z.
    Origin sits at the head/tail junction so that "position on surface" maps
    cleanly to "head sphere centre at +half_thickness, tails reaching into
    the bilayer interior".

    Returns the existing asset if it already exists.
    """
    existing = bpy.data.objects.get(LIPID_ASSET_NAME)
    if existing is not None:
        return existing

    head_mat = _ensure_material(HEAD_MATERIAL_NAME, (0.92, 0.30, 0.55, 1.0), 0.35)
    tail_mat = _ensure_material(TAIL_MATERIAL_NAME, (0.98, 0.82, 0.30, 1.0), 0.55)

    # Hidden building collection — we'll create the parts there, join into one
    # mesh, then move the result to the asset stash.
    import bmesh

    # --- Head -----------------------------------------------------------
    HEAD_RADIUS = 0.04  # ~4 Å
    bm = bmesh.new()
    bmesh.ops.create_icosphere(
        bm,
        subdivisions=2,
        radius=HEAD_RADIUS,
    )
    # Position head at +Z = +HEAD_RADIUS so the sphere sits *above* the
    # tail junction.
    for v in bm.verts:
        v.co.z += HEAD_RADIUS

    mesh = bpy.data.meshes.new(LIPID_ASSET_NAME + "_mesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(LIPID_ASSET_NAME, mesh)

    # --- Materials: head first (slot 0), tail second (slot 1) ----------
    mesh.materials.append(head_mat)
    mesh.materials.append(tail_mat)
    # Initial verts (head sphere) belong to material 0 (head) — already correct
    # since polys default to material 0.

    # --- Tails (two cylinders extending downward) ----------------------
    TAIL_RADIUS = 0.012
    TAIL_LENGTH = 0.18  # tails extend 0.18 BU = 18 Å into the bilayer
    TAIL_OFFSET_X = 0.018  # split slightly so two tails are visible

    for sign_x in (-1.0, 1.0):
        bm = bmesh.new()
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=8,
            radius1=TAIL_RADIUS,
            radius2=TAIL_RADIUS,
            depth=TAIL_LENGTH,
        )
        # Default cylinder is centered on origin along z. Shift so its top
        # sits at z=0 (tail extends from z=0 to z=-TAIL_LENGTH).
        for v in bm.verts:
            v.co.z -= TAIL_LENGTH / 2.0
            v.co.x += sign_x * TAIL_OFFSET_X

        tmp_mesh = bpy.data.meshes.new("_tail_tmp")
        bm.to_mesh(tmp_mesh)
        bm.free()

        # Join tmp_mesh into the main mesh using a temp object + mesh join.
        # Simpler: use bmesh to merge directly.
        bm_main = bmesh.new()
        bm_main.from_mesh(mesh)
        bm_tail = bmesh.new()
        bm_tail.from_mesh(tmp_mesh)

        # The faces from bm_tail need material_index = 1 (tail).
        tail_face_offset = len(bm_main.faces)
        for f in bm_tail.faces:
            f.material_index = 1

        # Append tail geometry into main bmesh.
        bm_main_verts = []
        for v in bm_tail.verts:
            new_v = bm_main.verts.new(v.co.copy())
            bm_main_verts.append(new_v)
        bm_main.verts.ensure_lookup_table()
        for f in bm_tail.faces:
            try:
                bm_main.faces.new([bm_main_verts[v.index] for v in f.verts])
            except ValueError:
                # Duplicate face — skip.
                pass
        # Assign material_index = 1 to the appended tail faces.
        bm_main.faces.ensure_lookup_table()
        for i, f in enumerate(bm_main.faces):
            if i >= tail_face_offset:
                f.material_index = 1

        bm_main.to_mesh(mesh)
        bm_main.free()
        bm_tail.free()
        bpy.data.meshes.remove(tmp_mesh)

    mesh.update()

    # Smooth-shade the asset for nicer renders. Per-face smoothing in
    # Blender 5 requires the shade_smooth flag on each polygon.
    for poly in mesh.polygons:
        poly.use_smooth = True

    # Park the asset object outside the scene by *not* linking it to any
    # collection. It can be referenced via bpy.data.objects.get(...) and used
    # as a GN Object Info input without appearing in the outliner.
    # However, Object Info nodes need the object to exist as a Blender obj
    # but not necessarily in a scene. So we leave it unlinked.
    return obj


def get_or_build_lipid_asset() -> bpy.types.Object:
    """Public accessor for the shared lipid asset object."""
    return _build_lipid_mesh()


# ===========================================================================
# Geometry Nodes tree
# ===========================================================================

def _new_input(tree, name, socket_type, default=None, min_val=None, max_val=None):
    """Helper: add an input socket to a GN tree's interface."""
    sock = tree.interface.new_socket(
        name=name, in_out="INPUT", socket_type=socket_type
    )
    if default is not None:
        try:
            sock.default_value = default
        except Exception:
            pass
    if min_val is not None:
        try:
            sock.min_value = min_val
        except Exception:
            pass
    if max_val is not None:
        try:
            sock.max_value = max_val
        except Exception:
            pass
    return sock


def _build_membrane_gn_tree() -> bpy.types.GeometryNodeTree:
    """Build the membrane Geometry Nodes tree, replacing any existing one.

    Returns the tree.
    """
    # Drop the old tree if present — we rebuild fresh every Blender session.
    existing = bpy.data.node_groups.get(GN_TREE_NAME)
    if existing is not None:
        bpy.data.node_groups.remove(existing, do_unlink=True)

    tree = bpy.data.node_groups.new(GN_TREE_NAME, "GeometryNodeTree")

    # ------------------------------------------------------------------
    # Interface (inputs + output)
    # ------------------------------------------------------------------
    tree.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    tree.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )

    _new_input(tree, "Lipid Asset", "NodeSocketObject")
    _new_input(tree, "Density (per nm²)", "NodeSocketFloat",
               default=1.5, min_val=0.05, max_val=5.0)
    _new_input(tree, "Bilayer Thickness (nm)", "NodeSocketFloat",
               default=4.0, min_val=1.0, max_val=15.0)
    _new_input(tree, "Lipid Scale", "NodeSocketFloat",
               default=1.0, min_val=0.3, max_val=3.0)
    _new_input(tree, "Random Rotation", "NodeSocketBool", default=True)
    _new_input(tree, "Animate Bob", "NodeSocketBool", default=False)
    _new_input(tree, "Bob Amplitude (nm)", "NodeSocketFloat",
               default=0.3, min_val=0.0, max_val=3.0)
    _new_input(tree, "Bob Speed", "NodeSocketFloat",
               default=0.6, min_val=0.05, max_val=5.0)
    _new_input(tree, "Random Seed", "NodeSocketInt", default=0)

    # Hole controllers — 8 fixed slots. Each has an "Enabled" bool that gates
    # the slot so unassigned slots don't carve a phantom hole at the origin.
    for i in range(1, MAX_HOLES + 1):
        _new_input(tree, f"Hole {i} Enabled", "NodeSocketBool", default=False)
        _new_input(tree, f"Hole {i}", "NodeSocketObject")

    nodes = tree.nodes
    links = tree.links

    # Convenience helpers ------------------------------------------------
    def get_in(socket_name):
        return group_in.outputs[socket_name]

    def new(node_type, name=None, **kwargs):
        n = nodes.new(node_type)
        if name:
            n.name = name
            n.label = name
        for k, v in kwargs.items():
            setattr(n, k, v)
        return n

    # ------------------------------------------------------------------
    # Layout: group input on the left, output on the right.
    # ------------------------------------------------------------------
    group_in = new("NodeGroupInput")
    group_in.location = (-2800, 0)
    group_out = new("NodeGroupOutput")
    group_out.location = (2400, 0)

    # ------------------------------------------------------------------
    # 1. Density handling. The user's "Density" is in lipids/nm²; the
    #    Distribute Points node works in lipids/BU² (NM_PER_BU = 10, so
    #    1 nm² = 0.01 BU² → ×100).
    #
    #    For POISSON-disk distribution the achieved density is governed by
    #    Distance Min (the minimum spacing in the *result*), NOT Density Max
    #    — so Distance Min is what we drive from the user's density: denser
    #    membrane → smaller spacing. DistanceMin = sqrt(0.0042 / density)
    #    was calibrated in Blender so the achieved lipids/nm² matches the
    #    requested value (within a few %). Density Max only sizes the
    #    candidate pool; kept 3× above the target so the blue-noise
    #    elimination has enough samples to choose from.
    # ------------------------------------------------------------------
    density_bu2 = new("ShaderNodeMath", name="Density nm²→BU²")
    density_bu2.operation = "MULTIPLY"
    density_bu2.inputs[1].default_value = NM_PER_BU * NM_PER_BU  # 100
    density_bu2.location = (-2700, 650)
    links.new(get_in("Density (per nm²)"), density_bu2.inputs[0])

    # Density Max — Poisson candidate pool, 3× the target for clean blue noise.
    density_max = new("ShaderNodeMath", name="Density Max (pool)")
    density_max.operation = "MULTIPLY"
    density_max.inputs[1].default_value = 3.0
    density_max.location = (-2500, 650)
    links.new(density_bu2.outputs[0], density_max.inputs[0])

    # Distance Min = sqrt(0.0042 / density_per_nm²)
    dmin_inv = new("ShaderNodeMath", name="DistMin div")
    dmin_inv.operation = "DIVIDE"
    dmin_inv.inputs[0].default_value = 0.0042
    dmin_inv.location = (-2700, 450)
    links.new(get_in("Density (per nm²)"), dmin_inv.inputs[1])

    dmin = new("ShaderNodeMath", name="DistMin sqrt")
    dmin.operation = "SQRT"
    dmin.location = (-2500, 450)
    links.new(dmin_inv.outputs[0], dmin.inputs[0])

    # ------------------------------------------------------------------
    # 2. Distribute Points on Faces — produces one point per future lipid.
    #    Used twice: once for upper leaflet, once for lower leaflet, with
    #    different seeds so the two leaflets don't perfectly mirror.
    #
    #    POISSON (blue-noise) distribution, not RANDOM: a real bilayer is a
    #    gap-free mosaic of lipids packed shoulder-to-shoulder. Pure random
    #    placement clumps and leaves holes (Poisson-process clustering), so it
    #    reads as a sparse scatter. Poisson-disk sampling spaces the lipids
    #    evenly, which is what makes the sheet look like a membrane.
    # ------------------------------------------------------------------
    def make_leaflet(leaflet_index: int, y_pos: float):
        """Build a leaflet sub-graph at vertical layout y position."""
        is_upper = leaflet_index == 0
        seed_off = 0 if is_upper else 9173

        # Distribute points
        dist = new("GeometryNodeDistributePointsOnFaces",
                   name=f"Distribute {('Upper' if is_upper else 'Lower')}")
        dist.distribute_method = "POISSON"
        dist.location = (-2200, y_pos)
        links.new(get_in("Geometry"), dist.inputs["Mesh"])
        links.new(density_max.outputs[0], dist.inputs["Density Max"])
        links.new(dmin.outputs[0], dist.inputs["Distance Min"])

        # Add seed offset so the two leaflets have different point sets
        seed_add = new("ShaderNodeMath", name=f"Seed {leaflet_index}")
        seed_add.operation = "ADD"
        seed_add.inputs[1].default_value = float(seed_off)
        seed_add.location = (-2400, y_pos + 200)
        links.new(get_in("Random Seed"), seed_add.inputs[0])
        links.new(seed_add.outputs[0], dist.inputs["Seed"])

        # Capture Normal at each point (so deformed grids tilt lipids correctly).
        # Use Distribute's *own* Normal output — InputNormal reads from the
        # geometry's normal attribute, which a point cloud doesn't have
        # (it would return (0,0,0) and silently disable the half-thickness
        # offset, the bob offset, and the lipid tilt).
        #
        # We capture the normal as a Float Vector attribute on the points so
        # it's accessible downstream of SetPos / Delete / etc., where the
        # source Distribute node isn't directly reachable per-point.
        capture_n = new("GeometryNodeCaptureAttribute",
                        name=f"CaptureNormal {leaflet_index}")
        capture_n.domain = "POINT"
        capture_n.location = (-2050, y_pos)
        capture_n.capture_items.new("VECTOR", "captured_normal")
        links.new(dist.outputs["Points"], capture_n.inputs["Geometry"])
        # Inputs: [Geometry, captured_normal (Value)]. Outputs: [Geometry, captured_normal (Attribute)].
        links.new(dist.outputs["Normal"], capture_n.inputs[1])

        # Get current point position via Input Position.
        pos = new("GeometryNodeInputPosition", name=f"Pos {leaflet_index}")
        pos.location = (-2000, y_pos - 250)

        # Normal is read from the captured attribute output (second output).
        class _NormalProxy:
            """Shim so the rest of the code can use ``normal.outputs[0]``."""
            def __init__(self, sock):
                self.outputs = [sock]
        normal = _NormalProxy(capture_n.outputs[1])

        # Half thickness (in BU)
        half_thick = new("ShaderNodeMath", name=f"HalfThick {leaflet_index}")
        half_thick.operation = "MULTIPLY"
        # convert nm → BU (÷10) and halve (÷2) → ÷20
        half_thick.inputs[1].default_value = 1.0 / (NM_PER_BU * 2.0)
        half_thick.location = (-2000, y_pos + 100)
        links.new(get_in("Bilayer Thickness (nm)"), half_thick.inputs[0])

        # If lower leaflet, negate offset
        signed_half = new("ShaderNodeMath", name=f"SignedHalf {leaflet_index}")
        signed_half.operation = "MULTIPLY"
        signed_half.inputs[1].default_value = 1.0 if is_upper else -1.0
        signed_half.location = (-1800, y_pos + 100)
        links.new(half_thick.outputs[0], signed_half.inputs[0])

        # Offset = normal * signed_half
        offset_vec = new("ShaderNodeVectorMath", name=f"OffsetVec {leaflet_index}")
        offset_vec.operation = "SCALE"
        offset_vec.location = (-1600, y_pos - 200)
        links.new(normal.outputs[0], offset_vec.inputs[0])
        links.new(signed_half.outputs[0], offset_vec.inputs["Scale"])

        # New position = pos + half_thickness_offset (bob offset is added later in
        # the same Position vector — Blender's Set Position resets Position to
        # (0,0,0) when the Position input is left unlinked, so combining
        # everything into one Position write is the only way to chain it
        # without losing the half-thickness shift).
        new_pos = new("ShaderNodeVectorMath", name=f"PosOffset {leaflet_index}")
        new_pos.operation = "ADD"
        new_pos.location = (-1400, y_pos - 100)
        links.new(pos.outputs[0], new_pos.inputs[0])
        links.new(offset_vec.outputs[0], new_pos.inputs[1])

        # Set Position: writes new_pos. The bob offset is folded into this
        # later (see further down — we re-link Position with new_pos + bob_vec).
        # Note we feed from capture_n.outputs["Geometry"] (not dist directly)
        # so the captured normal attribute travels with the points.
        set_pos = new("GeometryNodeSetPosition", name=f"SetPos {leaflet_index}")
        set_pos.location = (-1200, y_pos)
        links.new(capture_n.outputs["Geometry"], set_pos.inputs["Geometry"])
        # Position input is *re-linked* below once bob_vec is known.

        # ---- Compute hole redistribution displacement --------------------
        # Holes do NOT delete lipids — they shove them aside, the way a real
        # membrane parts around a pore. Each hole applies a radial, area-
        # preserving displacement in the XY plane:
        #
        #   * A point at radius d from the hole centre is remapped to
        #     d' = sqrt(d² + R²)  (R = hole radius). This exact map sends the
        #     whole disk of radius R out into the annulus beyond R, conserving
        #     lipid count — the hole interior empties, nothing vanishes.
        #   * Beyond R the push tapers smoothly to zero at R · HOLE_INFLUENCE,
        #     so lipids bunch into a compressed ring around the rim — they
        #     "feel" the hole and redistribute, affecting their neighbours.
        #
        # Every hole's displacement is summed. Because Object Info reads the
        # empty live, animating a hole's scale or location makes the lipids
        # flow in real time (grow the hole → lipids stream outward; shrink it
        # → the membrane heals closed).
        HOLE_INFLUENCE = 3.0   # disturbance reaches 3× the hole radius
        hole_disp = None       # accumulates a Vector socket (total push)
        for h in range(1, MAX_HOLES + 1):
            enabled = get_in(f"Hole {h} Enabled")
            obj_in = get_in(f"Hole {h}")
            hy = y_pos - 600 - h * 260

            oi = new("GeometryNodeObjectInfo", name=f"OI H{h} L{leaflet_index}")
            oi.transform_space = "RELATIVE"
            oi.location = (-1750, hy)
            links.new(obj_in, oi.inputs["Object"])

            # delta = point.xy - hole.xy  (Z flattened so the hole is a
            # vertical column regardless of where the empty sits in Z).
            sub_vec = new("ShaderNodeVectorMath", name=f"SubH{h} L{leaflet_index}")
            sub_vec.operation = "SUBTRACT"
            sub_vec.location = (-1560, hy)
            links.new(pos.outputs[0], sub_vec.inputs[0])
            links.new(oi.outputs["Location"], sub_vec.inputs[1])

            flat_xy = new("ShaderNodeVectorMath", name=f"FlatH{h} L{leaflet_index}")
            flat_xy.operation = "MULTIPLY"
            flat_xy.inputs[1].default_value = (1.0, 1.0, 0.0)
            flat_xy.location = (-1380, hy)
            links.new(sub_vec.outputs[0], flat_xy.inputs[0])

            # d = |delta_xy|
            dist = new("ShaderNodeVectorMath", name=f"LenH{h} L{leaflet_index}")
            dist.operation = "LENGTH"
            dist.location = (-1200, hy)
            links.new(flat_xy.outputs[0], dist.inputs[0])

            # dir = normalize(delta_xy) — radial outward direction
            direction = new("ShaderNodeVectorMath", name=f"DirH{h} L{leaflet_index}")
            direction.operation = "NORMALIZE"
            direction.location = (-1200, hy - 130)
            links.new(flat_xy.outputs[0], direction.inputs[0])

            # R = hole radius = Scale.X (uniform scale) of the empty
            scale_sep = new("ShaderNodeSeparateXYZ",
                            name=f"ScaleH{h} L{leaflet_index}")
            scale_sep.location = (-1560, hy - 170)
            links.new(oi.outputs["Scale"], scale_sep.inputs[0])
            radius = scale_sep.outputs["X"]

            # area-preserving pushed radius: sqrt(d² + R²) == length(d, R, 0)
            dR = new("ShaderNodeCombineXYZ", name=f"dRH{h} L{leaflet_index}")
            dR.location = (-1000, hy)
            links.new(dist.outputs["Value"], dR.inputs[0])
            links.new(radius, dR.inputs[1])
            dR.inputs[2].default_value = 0.0

            pushed_r = new("ShaderNodeVectorMath",
                           name=f"PushedRH{h} L{leaflet_index}")
            pushed_r.operation = "LENGTH"
            pushed_r.location = (-820, hy)
            links.new(dR.outputs[0], pushed_r.inputs[0])

            # raw push distance = d' - d  (always >= 0)
            raw_push = new("ShaderNodeMath", name=f"RawPushH{h} L{leaflet_index}")
            raw_push.operation = "SUBTRACT"
            raw_push.location = (-640, hy)
            links.new(pushed_r.outputs["Value"], raw_push.inputs[0])
            links.new(dist.outputs["Value"], raw_push.inputs[1])

            # influence radius = R · HOLE_INFLUENCE
            r_inf = new("ShaderNodeMath", name=f"RInfH{h} L{leaflet_index}")
            r_inf.operation = "MULTIPLY"
            r_inf.inputs[1].default_value = HOLE_INFLUENCE
            r_inf.location = (-820, hy - 170)
            links.new(radius, r_inf.inputs[0])

            # falloff: 1 for d <= R, smoothstep down to 0 at d >= R·INFLUENCE.
            # Holding it at 1 inside R guarantees the hole interior fully
            # clears (the exact area-preserving map applies there).
            falloff = new("ShaderNodeMapRange",
                          name=f"FalloffH{h} L{leaflet_index}")
            falloff.interpolation_type = "SMOOTHSTEP"
            falloff.clamp = True
            falloff.location = (-640, hy - 170)
            links.new(dist.outputs["Value"], falloff.inputs["Value"])
            links.new(radius, falloff.inputs["From Min"])
            links.new(r_inf.outputs[0], falloff.inputs["From Max"])
            falloff.inputs["To Min"].default_value = 1.0
            falloff.inputs["To Max"].default_value = 0.0

            push_dist = new("ShaderNodeMath", name=f"PushH{h} L{leaflet_index}")
            push_dist.operation = "MULTIPLY"
            push_dist.location = (-440, hy)
            links.new(raw_push.outputs[0], push_dist.inputs[0])
            links.new(falloff.outputs["Result"], push_dist.inputs[1])

            # displacement vector = dir · push_dist
            disp = new("ShaderNodeVectorMath", name=f"DispH{h} L{leaflet_index}")
            disp.operation = "SCALE"
            disp.location = (-260, hy)
            links.new(direction.outputs[0], disp.inputs[0])
            links.new(push_dist.outputs[0], disp.inputs["Scale"])

            # gate by Enabled — an unassigned slot must contribute nothing
            # (Object Info on a None object reports Scale (1,1,1), which
            # would otherwise carve a phantom hole at the origin).
            gate = new("GeometryNodeSwitch", name=f"GateH{h} L{leaflet_index}")
            gate.input_type = "VECTOR"
            gate.location = (-80, hy)
            gate.inputs["False"].default_value = (0.0, 0.0, 0.0)
            links.new(enabled, gate.inputs["Switch"])
            links.new(disp.outputs[0], gate.inputs["True"])

            if hole_disp is None:
                hole_disp = gate.outputs[0]
            else:
                acc = new("ShaderNodeVectorMath", name=f"AccH{h} L{leaflet_index}")
                acc.operation = "ADD"
                acc.location = (100, hy)
                links.new(hole_disp, acc.inputs[0])
                links.new(gate.outputs[0], acc.inputs[1])
                hole_disp = acc.outputs[0]

        # ==================================================================
        # MOSH-PIT MOTION
        # ------------------------------------------------------------------
        # Lipids in a real bilayer are packed shoulder-to-shoulder and
        # constantly jostling their neighbours. To capture that churn each
        # lipid is driven by SIX independent wobble channels:
        #   * bob        — up / down along the surface normal
        #   * sway T / B — lateral slosh in the surface tangent plane
        #   * tilt T / B — leaning, by perturbing the alignment normal
        #   * twist      — oscillating spin about the lipid's long axis
        # Every channel's phase, frequency AND amplitude are randomised
        # per-lipid (seeded by the point index), so no two lipids move alike
        # and the whole sheet churns unpredictably — a mosh pit, not a
        # marching band. It stays deterministic (index-seeded, not random
        # state) so the animation plays back identically every time.
        # ==================================================================
        idx = new("GeometryNodeInputIndex", name=f"Idx {leaflet_index}")
        idx.location = (-200, y_pos - 350)

        scene_time = new("GeometryNodeInputSceneTime", name=f"Time {leaflet_index}")
        scene_time.location = (-200, y_pos - 500)

        # ---- Master gate: Bob Amplitude when Animate Bob is on, else 0 ----
        # Everything below scales off this, so flipping Animate Bob off
        # zeroes all six channels at once.
        anim_amp = new("GeometryNodeSwitch", name=f"AnimGate {leaflet_index}")
        anim_amp.input_type = "FLOAT"
        anim_amp.location = (0, y_pos - 650)
        anim_amp.inputs["False"].default_value = 0.0
        links.new(get_in("Animate Bob"), anim_amp.inputs[0])
        links.new(get_in("Bob Amplitude (nm)"), anim_amp.inputs["True"])

        # Per-family base amplitudes derived from the master amplitude.
        amp_bu = new("ShaderNodeMath", name=f"AmpBU {leaflet_index}")
        amp_bu.operation = "MULTIPLY"
        amp_bu.inputs[1].default_value = 1.0 / NM_PER_BU   # nm → BU
        amp_bu.location = (200, y_pos - 650)
        links.new(anim_amp.outputs[0], amp_bu.inputs[0])

        sway_base = new("ShaderNodeMath", name=f"SwayBase {leaflet_index}")
        sway_base.operation = "MULTIPLY"
        sway_base.inputs[1].default_value = 0.8   # lateral slosh ≈ 80% of bob
        sway_base.location = (400, y_pos - 650)
        links.new(amp_bu.outputs[0], sway_base.inputs[0])

        tilt_base = new("ShaderNodeMath", name=f"TiltBase {leaflet_index}")
        tilt_base.operation = "MULTIPLY"
        tilt_base.inputs[1].default_value = 0.5   # normal-perturb magnitude
        tilt_base.location = (200, y_pos - 800)
        links.new(anim_amp.outputs[0], tilt_base.inputs[0])

        twist_base = new("ShaderNodeMath", name=f"TwistBase {leaflet_index}")
        twist_base.operation = "MULTIPLY"
        twist_base.inputs[1].default_value = 0.45  # radians of spin wobble
        twist_base.location = (400, y_pos - 800)
        links.new(anim_amp.outputs[0], twist_base.inputs[0])

        # ---- Per-lipid random helper -------------------------------------
        # ID = point index (per-element variation); Seed = a constant unique
        # to each channel so the channels are statistically independent.
        def rand_float(seed_int, lo, hi, loc):
            rv = new("FunctionNodeRandomValue",
                     name=f"Rnd{seed_int} L{leaflet_index}")
            rv.data_type = "FLOAT"
            rv.location = loc
            rv.inputs[2].default_value = lo            # Min (float)
            rv.inputs[3].default_value = hi            # Max (float)
            rv.inputs["Seed"].default_value = seed_int + leaflet_index * 10000
            links.new(idx.outputs[0], rv.inputs["ID"])
            return rv.outputs[1]                       # FLOAT "Value" output

        # ---- Wobble channel ----------------------------------------------
        # value = sin(t · BobSpeed · freqMul · 2π + phase) · baseAmp · ampMul
        # freqMul / ampMul / phase are all randomised per lipid.
        def wobble(seed, base_amp_socket, label, lx, ly):
            phase = rand_float(seed + 0, 0.0, math.tau, (lx, ly))
            fmul = rand_float(seed + 1, 0.55, 1.5, (lx, ly - 150))
            amul = rand_float(seed + 2, 0.4, 1.6, (lx, ly - 300))

            freq = new("ShaderNodeMath", name=f"{label} freq L{leaflet_index}")
            freq.operation = "MULTIPLY"
            freq.location = (lx + 200, ly)
            links.new(get_in("Bob Speed"), freq.inputs[0])
            links.new(fmul, freq.inputs[1])

            tf = new("ShaderNodeMath", name=f"{label} t-f L{leaflet_index}")
            tf.operation = "MULTIPLY"
            tf.location = (lx + 380, ly)
            links.new(scene_time.outputs["Seconds"], tf.inputs[0])
            links.new(freq.outputs[0], tf.inputs[1])

            ang = new("ShaderNodeMath", name=f"{label} 2pi L{leaflet_index}")
            ang.operation = "MULTIPLY"
            ang.inputs[1].default_value = math.tau
            ang.location = (lx + 560, ly)
            links.new(tf.outputs[0], ang.inputs[0])

            ang2 = new("ShaderNodeMath", name=f"{label} phase L{leaflet_index}")
            ang2.operation = "ADD"
            ang2.location = (lx + 740, ly)
            links.new(ang.outputs[0], ang2.inputs[0])
            links.new(phase, ang2.inputs[1])

            s = new("ShaderNodeMath", name=f"{label} sin L{leaflet_index}")
            s.operation = "SINE"
            s.location = (lx + 920, ly)
            links.new(ang2.outputs[0], s.inputs[0])

            amp = new("ShaderNodeMath", name=f"{label} amp L{leaflet_index}")
            amp.operation = "MULTIPLY"
            amp.location = (lx + 740, ly - 150)
            links.new(base_amp_socket, amp.inputs[0])
            links.new(amul, amp.inputs[1])

            out = new("ShaderNodeMath", name=f"{label} val L{leaflet_index}")
            out.operation = "MULTIPLY"
            out.location = (lx + 1100, ly)
            links.new(s.outputs[0], out.inputs[0])
            links.new(amp.outputs[0], out.inputs[1])
            return out.outputs[0]

        bob_ch = wobble(100, amp_bu.outputs[0], "bob", 600, y_pos - 1000)
        swayT_ch = wobble(200, sway_base.outputs[0], "swayT", 600, y_pos - 1500)
        swayB_ch = wobble(300, sway_base.outputs[0], "swayB", 600, y_pos - 2000)
        tiltT_ch = wobble(400, tilt_base.outputs[0], "tiltT", 600, y_pos - 2500)
        tiltB_ch = wobble(500, tilt_base.outputs[0], "tiltB", 600, y_pos - 3000)
        twist_ch = wobble(600, twist_base.outputs[0], "twist", 600, y_pos - 3500)

        # ---- Surface tangent frame (T, B perpendicular to the normal) ----
        # cross(N, worldX) is a stable tangent: the membrane normal is always
        # close to world Z, so it is never parallel to X.
        worldX = new("FunctionNodeInputVector", name=f"WorldX {leaflet_index}")
        worldX.vector = (1.0, 0.0, 0.0)
        worldX.location = (-200, y_pos - 700)

        tan_raw = new("ShaderNodeVectorMath", name=f"TanRaw {leaflet_index}")
        tan_raw.operation = "CROSS_PRODUCT"
        tan_raw.location = (0, y_pos - 250)
        links.new(normal.outputs[0], tan_raw.inputs[0])
        links.new(worldX.outputs[0], tan_raw.inputs[1])

        tan = new("ShaderNodeVectorMath", name=f"Tan {leaflet_index}")
        tan.operation = "NORMALIZE"
        tan.location = (200, y_pos - 250)
        links.new(tan_raw.outputs[0], tan.inputs[0])

        bit_raw = new("ShaderNodeVectorMath", name=f"BitRaw {leaflet_index}")
        bit_raw.operation = "CROSS_PRODUCT"
        bit_raw.location = (400, y_pos - 250)
        links.new(normal.outputs[0], bit_raw.inputs[0])
        links.new(tan.outputs[0], bit_raw.inputs[1])

        bit = new("ShaderNodeVectorMath", name=f"Bit {leaflet_index}")
        bit.operation = "NORMALIZE"
        bit.location = (600, y_pos - 250)
        links.new(bit_raw.outputs[0], bit.inputs[0])

        # ---- Positional mosh offset: N·bob + T·swayT + B·swayB -----------
        bob_vec = new("ShaderNodeVectorMath", name=f"BobVec {leaflet_index}")
        bob_vec.operation = "SCALE"
        bob_vec.location = (1850, y_pos - 1000)
        links.new(normal.outputs[0], bob_vec.inputs[0])
        links.new(bob_ch, bob_vec.inputs["Scale"])

        swayT_vec = new("ShaderNodeVectorMath", name=f"SwayTVec {leaflet_index}")
        swayT_vec.operation = "SCALE"
        swayT_vec.location = (1850, y_pos - 1500)
        links.new(tan.outputs[0], swayT_vec.inputs[0])
        links.new(swayT_ch, swayT_vec.inputs["Scale"])

        swayB_vec = new("ShaderNodeVectorMath", name=f"SwayBVec {leaflet_index}")
        swayB_vec.operation = "SCALE"
        swayB_vec.location = (1850, y_pos - 2000)
        links.new(bit.outputs[0], swayB_vec.inputs[0])
        links.new(swayB_ch, swayB_vec.inputs["Scale"])

        mosh_a = new("ShaderNodeVectorMath", name=f"MoshAdd1 {leaflet_index}")
        mosh_a.operation = "ADD"
        mosh_a.location = (2050, y_pos - 1250)
        links.new(bob_vec.outputs[0], mosh_a.inputs[0])
        links.new(swayT_vec.outputs[0], mosh_a.inputs[1])

        mosh_offset = new("ShaderNodeVectorMath", name=f"MoshAdd2 {leaflet_index}")
        mosh_offset.operation = "ADD"
        mosh_offset.location = (2250, y_pos - 1500)
        links.new(mosh_a.outputs[0], mosh_offset.inputs[0])
        links.new(swayB_vec.outputs[0], mosh_offset.inputs[1])

        # Total motion offset = mosh jostling + hole redistribution push.
        motion_sum = new("ShaderNodeVectorMath", name=f"MotionSum {leaflet_index}")
        motion_sum.operation = "ADD"
        motion_sum.location = (-1500, y_pos + 200)
        links.new(mosh_offset.outputs[0], motion_sum.inputs[0])
        links.new(hole_disp, motion_sum.inputs[1])

        # Fold the motion offset + half-thickness offset into the single
        # SetPos Position write (a chained Set Position would reset position
        # to (0,0,0) because it writes its Position input even when unlinked).
        final_pos = new("ShaderNodeVectorMath", name=f"FinalPos {leaflet_index}")
        final_pos.operation = "ADD"
        final_pos.location = (-1300, y_pos)
        links.new(new_pos.outputs[0], final_pos.inputs[0])
        links.new(motion_sum.outputs[0], final_pos.inputs[1])
        links.new(final_pos.outputs[0], set_pos.inputs["Position"])

        # Holes redistribute lipids rather than deleting them, so there is no
        # Delete node — instancing reads straight from Set Position.
        bob_set = set_pos  # alias so subsequent code reads .outputs["Geometry"]

        # ---- Compute per-instance rotation -------------------------------
        # Align lipid +Z to the surface normal (-normal for the lower
        # leaflet), then perturb that vector by the two tilt channels so
        # each lipid leans and rocks over time. Normalising the perturbed
        # vector keeps the lean angle bounded.
        if is_upper:
            align_base = normal.outputs[0]
        else:
            neg = new("ShaderNodeVectorMath", name=f"NegN {leaflet_index}")
            neg.operation = "SCALE"
            neg.inputs["Scale"].default_value = -1.0
            neg.location = (2400, y_pos - 250)
            links.new(normal.outputs[0], neg.inputs[0])
            align_base = neg.outputs[0]

        tiltT_vec = new("ShaderNodeVectorMath", name=f"TiltTVec {leaflet_index}")
        tiltT_vec.operation = "SCALE"
        tiltT_vec.location = (1850, y_pos - 2500)
        links.new(tan.outputs[0], tiltT_vec.inputs[0])
        links.new(tiltT_ch, tiltT_vec.inputs["Scale"])

        tiltB_vec = new("ShaderNodeVectorMath", name=f"TiltBVec {leaflet_index}")
        tiltB_vec.operation = "SCALE"
        tiltB_vec.location = (1850, y_pos - 3000)
        links.new(bit.outputs[0], tiltB_vec.inputs[0])
        links.new(tiltB_ch, tiltB_vec.inputs["Scale"])

        tilt_a = new("ShaderNodeVectorMath", name=f"TiltAdd1 {leaflet_index}")
        tilt_a.operation = "ADD"
        tilt_a.location = (2600, y_pos - 2750)
        links.new(align_base, tilt_a.inputs[0])
        links.new(tiltT_vec.outputs[0], tilt_a.inputs[1])

        tilt_b = new("ShaderNodeVectorMath", name=f"TiltAdd2 {leaflet_index}")
        tilt_b.operation = "ADD"
        tilt_b.location = (2800, y_pos - 2750)
        links.new(tilt_a.outputs[0], tilt_b.inputs[0])
        links.new(tiltB_vec.outputs[0], tilt_b.inputs[1])

        align_normal = new("ShaderNodeVectorMath", name=f"AlignNorm {leaflet_index}")
        align_normal.operation = "NORMALIZE"
        align_normal.location = (3000, y_pos - 2750)
        links.new(tilt_b.outputs[0], align_normal.inputs[0])

        align = new("FunctionNodeAlignRotationToVector",
                   name=f"AlignRot {leaflet_index}")
        align.axis = "Z"
        align.pivot_axis = "AUTO"
        align.location = (3200, y_pos - 150)
        links.new(align_normal.outputs[0], align.inputs["Vector"])
        base_rot = align.outputs["Rotation"]

        # ---- Instance lipid on points ------------------------------------
        scale_to_vec = new("ShaderNodeCombineXYZ", name=f"ScaleVec {leaflet_index}")
        scale_to_vec.location = (3200, y_pos - 350)
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[0])
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[1])
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[2])

        oi_lipid = new("GeometryNodeObjectInfo", name=f"OI Lipid {leaflet_index}")
        oi_lipid.transform_space = "ORIGINAL"
        oi_lipid.location = (3200, y_pos - 500)
        links.new(get_in("Lipid Asset"), oi_lipid.inputs["Object"])

        iop = new("GeometryNodeInstanceOnPoints", name=f"IoP {leaflet_index}")
        iop.location = (3450, y_pos)
        links.new(bob_set.outputs["Geometry"], iop.inputs["Points"])
        links.new(oi_lipid.outputs["Geometry"], iop.inputs["Instance"])
        links.new(base_rot, iop.inputs["Rotation"])
        links.new(scale_to_vec.outputs[0], iop.inputs["Scale"])

        # ---- Per-instance spin about the lipid's long axis ---------------
        # Static random Y-rotation (gated by Random Rotation, so the top view
        # isn't uniform) PLUS the time-varying twist channel (gated by
        # Animate Bob). They're independent: one is the resting orientation,
        # the other is mosh-pit twisting.
        rand_yrot = rand_float(700, 0.0, math.tau, (3200, y_pos - 700))

        rot_switch = new("GeometryNodeSwitch", name=f"RotSwitch {leaflet_index}")
        rot_switch.input_type = "FLOAT"
        rot_switch.location = (3450, y_pos - 700)
        rot_switch.inputs["False"].default_value = 0.0
        links.new(get_in("Random Rotation"), rot_switch.inputs[0])
        links.new(rand_yrot, rot_switch.inputs["True"])

        spin = new("ShaderNodeMath", name=f"Spin {leaflet_index}")
        spin.operation = "ADD"
        spin.location = (3650, y_pos - 700)
        links.new(rot_switch.outputs[0], spin.inputs[0])
        links.new(twist_ch, spin.inputs[1])

        # Euler vector (0, 0, spin) — rotation in the INSTANCE's local space
        # (Rotate Instances has Local Space enabled below).
        rot_vec = new("ShaderNodeCombineXYZ", name=f"RotVec {leaflet_index}")
        rot_vec.location = (3850, y_pos - 700)
        rot_vec.inputs[0].default_value = 0.0
        rot_vec.inputs[1].default_value = 0.0
        links.new(spin.outputs[0], rot_vec.inputs[2])

        rotate_inst = new("GeometryNodeRotateInstances",
                         name=f"RotInst {leaflet_index}")
        rotate_inst.location = (4050, y_pos)
        rotate_inst.inputs["Local Space"].default_value = True
        links.new(iop.outputs["Instances"], rotate_inst.inputs["Instances"])
        links.new(rot_vec.outputs[0], rotate_inst.inputs["Rotation"])

        return rotate_inst.outputs["Instances"]

    upper_out = make_leaflet(0, 800)
    lower_out = make_leaflet(1, -2200)

    # Join both leaflets
    join = new("GeometryNodeJoinGeometry", name="Join Leaflets")
    join.location = (2300, 0)
    links.new(upper_out, join.inputs[0])
    links.new(lower_out, join.inputs[0])

    links.new(join.outputs[0], group_out.inputs["Geometry"])

    tree["pb_gn_version"] = GN_TREE_VERSION
    return tree


def get_or_build_membrane_gn_tree() -> bpy.types.GeometryNodeTree:
    """Return the membrane GN tree, building it if missing or out of date.

    When an out-of-date tree is found (a membrane built with an older addon
    version), it is rebuilt and every existing membrane is re-linked to the
    fresh tree and has its stored settings re-applied — so old membranes pick
    up new motion features without the user having to recreate them.
    """
    tree = bpy.data.node_groups.get(GN_TREE_NAME)
    if tree is not None and tree.get("pb_gn_version", 0) == GN_TREE_VERSION:
        return tree

    was_stale = tree is not None
    tree = _build_membrane_gn_tree()  # removes the old datablock, builds fresh

    if was_stale:
        # _build_membrane_gn_tree removed the old tree, so any membrane
        # modifier that referenced it now has node_group == None. Re-link
        # each one and re-push its stored settings + hole assignments.
        from . import membrane_operators as ops
        for obj in bpy.data.objects:
            if not obj.get("pb_is_membrane", False):
                continue
            for mod in obj.modifiers:
                if mod.type == "NODES" and mod.name == ops.GN_MOD_NAME:
                    mod.node_group = tree
            try:
                ops.reapply_membrane_settings(obj)
            except Exception:
                pass
    return tree


# ===========================================================================
# Base grid mesh
# ===========================================================================

def _build_grid_mesh(width_nm: float, height_nm: float,
                     subdivisions_per_nm: float = 0.5) -> bpy.types.Mesh:
    """Build a subdivided plane mesh for the membrane base.

    The subdivisions give the lattice + distribute-points enough resolution
    to look smooth when deformed. We aim for at least 0.5 subdivisions/nm.
    """
    import bmesh

    width_bu = width_nm / NM_PER_BU
    height_bu = height_nm / NM_PER_BU

    # Subdivisions: clamp to a sensible range
    x_subs = max(8, int(width_nm * subdivisions_per_nm))
    y_subs = max(8, int(height_nm * subdivisions_per_nm))

    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm,
        x_segments=x_subs,
        y_segments=y_subs,
        size=1.0,  # will scale separately
    )
    # create_grid creates a unit square. Scale to the desired size.
    sx = width_bu / 2.0
    sy = height_bu / 2.0
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy

    mesh = bpy.data.meshes.new("PB_Membrane_Grid")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def update_grid_mesh(mesh: bpy.types.Mesh, width_nm: float,
                     height_nm: float) -> None:
    """Rebuild the given grid mesh in place to the new size.

    Used by the resize operator when the user changes width/height. We keep
    the existing mesh datablock so modifier references (Lattice, GN) stay
    valid — just replace its geometry.
    """
    new_mesh_data = _build_grid_mesh(width_nm, height_nm)
    bpy_verts = [v.co.copy() for v in new_mesh_data.vertices]
    bpy_edges = [tuple(e.vertices) for e in new_mesh_data.edges]
    bpy_faces = [tuple(p.vertices) for p in new_mesh_data.polygons]
    mesh.clear_geometry()
    mesh.from_pydata(bpy_verts, bpy_edges, bpy_faces)
    mesh.update()
    bpy.data.meshes.remove(new_mesh_data)


# ===========================================================================
# Lattice (deformation)
# ===========================================================================

def build_membrane_lattice(width_nm: float, height_nm: float,
                            resolution: int = 5) -> bpy.types.Object:
    """Create a Lattice object sized to fit the membrane, returns the object.

    The lattice is created at the scene origin and *not* linked to any
    collection — callers should link it themselves.
    """
    lattice_data = bpy.data.lattices.new("PB_Membrane_Lattice")
    obj = bpy.data.objects.new("PB_Membrane_Lattice", lattice_data)

    # Lattice default size is 1x1x1; the lattice's dimensions = scale of obj.
    width_bu = width_nm / NM_PER_BU
    height_bu = height_nm / NM_PER_BU
    obj.scale = (width_bu, height_bu, 1.0)  # 1 BU tall (= 10 nm) is plenty
    lattice_data.points_u = resolution
    lattice_data.points_v = resolution
    lattice_data.points_w = 2  # 2 layers in Z is enough for membrane bending
    lattice_data.interpolation_type_u = "KEY_BSPLINE"
    lattice_data.interpolation_type_v = "KEY_BSPLINE"
    lattice_data.interpolation_type_w = "KEY_BSPLINE"
    return obj
