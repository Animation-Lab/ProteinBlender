"""Membrane geometry construction.

Builds:
- The lipid asset mesh (head sphere + two tail cylinders, one per leaflet).
- The Geometry Nodes tree that distributes lipid instances across the
  membrane surface with random Y-rotation, pseudo-random bobbing animation,
  and animatable circular holes.

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
               default=0.6, min_val=0.05, max_val=4.0)
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
    # 1. Density conversion: density input is lipids/nm². Distribute Points
    #    on Faces uses density in 1/BU². NM_PER_BU = 10, so 1 nm² = 0.01 BU²,
    #    meaning 1 lipid/nm² = 100 lipids/BU².
    # ------------------------------------------------------------------
    density_mul = new("ShaderNodeMath", name="Density nm²→BU²")
    density_mul.operation = "MULTIPLY"
    density_mul.inputs[1].default_value = NM_PER_BU * NM_PER_BU  # 100
    density_mul.location = (-2500, 600)
    links.new(get_in("Density (per nm²)"), density_mul.inputs[0])

    # ------------------------------------------------------------------
    # 2. Distribute Points on Faces — produces one point per future lipid.
    #    Used twice: once for upper leaflet, once for lower leaflet, with
    #    different seeds so the two leaflets don't perfectly mirror.
    # ------------------------------------------------------------------
    def make_leaflet(leaflet_index: int, y_pos: float):
        """Build a leaflet sub-graph at vertical layout y position."""
        is_upper = leaflet_index == 0
        seed_off = 0 if is_upper else 9173

        # Distribute points
        dist = new("GeometryNodeDistributePointsOnFaces",
                   name=f"Distribute {('Upper' if is_upper else 'Lower')}")
        dist.distribute_method = "RANDOM"
        dist.location = (-2200, y_pos)
        links.new(get_in("Geometry"), dist.inputs["Mesh"])
        links.new(density_mul.outputs[0], dist.inputs["Density"])

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

        # ---- Compute hole mask -------------------------------------------
        # For each hole slot, compute signed distance to current point in XY
        # plane. If any signed distance < 0, the point is inside that hole.
        # We aggregate using a chain of Boolean ORs.
        hole_mask = None  # will become a Bool socket (True = should delete)
        for h in range(1, MAX_HOLES + 1):
            enabled = get_in(f"Hole {h} Enabled")
            obj_in = get_in(f"Hole {h}")

            oi = new("GeometryNodeObjectInfo", name=f"OI H{h} L{leaflet_index}")
            oi.transform_space = "RELATIVE"
            oi.location = (-1600, y_pos - 600 - h * 200)
            links.new(obj_in, oi.inputs["Object"])

            # Compute XY distance: (point.xy - obj.xy)
            sub_vec = new("ShaderNodeVectorMath", name=f"SubH{h} L{leaflet_index}")
            sub_vec.operation = "SUBTRACT"
            sub_vec.location = (-1400, y_pos - 600 - h * 200)
            links.new(pos.outputs[0], sub_vec.inputs[0])
            links.new(oi.outputs["Location"], sub_vec.inputs[1])

            # Flatten Z: multiply by (1, 1, 0)
            flat_xy = new("ShaderNodeVectorMath", name=f"FlatH{h} L{leaflet_index}")
            flat_xy.operation = "MULTIPLY"
            flat_xy.inputs[1].default_value = (1.0, 1.0, 0.0)
            flat_xy.location = (-1200, y_pos - 600 - h * 200)
            links.new(sub_vec.outputs[0], flat_xy.inputs[0])

            length_node = new("ShaderNodeVectorMath", name=f"LenH{h} L{leaflet_index}")
            length_node.operation = "LENGTH"
            length_node.location = (-1000, y_pos - 600 - h * 200)
            links.new(flat_xy.outputs[0], length_node.inputs[0])

            # Radius = Scale.X (uniform scale) of the empty
            scale_sep = new("ShaderNodeSeparateXYZ", name=f"ScaleH{h} L{leaflet_index}")
            scale_sep.location = (-1000, y_pos - 700 - h * 200)
            links.new(oi.outputs["Scale"], scale_sep.inputs[0])

            inside = new("FunctionNodeCompare", name=f"InsideH{h} L{leaflet_index}")
            inside.data_type = "FLOAT"
            inside.operation = "LESS_THAN"
            inside.location = (-800, y_pos - 600 - h * 200)
            links.new(length_node.outputs["Value"], inside.inputs[0])
            links.new(scale_sep.outputs["X"], inside.inputs[1])

            # Gate by Enabled
            and_node = new("FunctionNodeBooleanMath",
                          name=f"AndH{h} L{leaflet_index}")
            and_node.operation = "AND"
            and_node.location = (-600, y_pos - 600 - h * 200)
            links.new(inside.outputs["Result"], and_node.inputs[0])
            links.new(enabled, and_node.inputs[1])

            if hole_mask is None:
                hole_mask = and_node.outputs[0]
            else:
                or_node = new("FunctionNodeBooleanMath",
                             name=f"OrH{h} L{leaflet_index}")
                or_node.operation = "OR"
                or_node.location = (-400, y_pos - 600 - h * 200)
                links.new(hole_mask, or_node.inputs[0])
                links.new(and_node.outputs[0], or_node.inputs[1])
                hole_mask = or_node.outputs[0]

        # Delete points where hole_mask is True
        delete = new("GeometryNodeDeleteGeometry", name=f"Delete L{leaflet_index}")
        delete.domain = "POINT"
        delete.location = (-200, y_pos)
        links.new(set_pos.outputs["Geometry"], delete.inputs["Geometry"])
        links.new(hole_mask, delete.inputs["Selection"])

        # ---- Apply bob offset along normal -------------------------------
        # phase = random(index) * 2π
        idx = new("GeometryNodeInputIndex", name=f"Idx {leaflet_index}")
        idx.location = (0, y_pos - 350)

        # Random phase 0..2π per point
        rand_phase = new("FunctionNodeRandomValue", name=f"RandPhase {leaflet_index}")
        rand_phase.data_type = "FLOAT"
        rand_phase.location = (200, y_pos - 350)
        rand_phase.inputs[2].default_value = 0.0  # min
        rand_phase.inputs[3].default_value = math.tau  # max
        # seed = id + leaflet_offset
        seed_phase = new("ShaderNodeMath", name=f"SeedPhase {leaflet_index}")
        seed_phase.operation = "ADD"
        seed_phase.inputs[1].default_value = float(7919 + leaflet_index * 13)
        seed_phase.location = (200, y_pos - 500)
        links.new(idx.outputs[0], seed_phase.inputs[0])
        links.new(seed_phase.outputs[0], rand_phase.inputs["Seed"])

        # time = scene seconds * speed
        scene_time = new("GeometryNodeInputSceneTime", name=f"Time {leaflet_index}")
        scene_time.location = (0, y_pos - 600)

        time_x_speed = new("ShaderNodeMath", name=f"TxS {leaflet_index}")
        time_x_speed.operation = "MULTIPLY"
        time_x_speed.location = (200, y_pos - 600)
        links.new(scene_time.outputs["Seconds"], time_x_speed.inputs[0])
        links.new(get_in("Bob Speed"), time_x_speed.inputs[1])

        # angle = time*speed*2π + phase
        time_two_pi = new("ShaderNodeMath", name=f"T2π {leaflet_index}")
        time_two_pi.operation = "MULTIPLY"
        time_two_pi.inputs[1].default_value = math.tau
        time_two_pi.location = (400, y_pos - 600)
        links.new(time_x_speed.outputs[0], time_two_pi.inputs[0])

        angle_add = new("ShaderNodeMath", name=f"Angle {leaflet_index}")
        angle_add.operation = "ADD"
        angle_add.location = (600, y_pos - 500)
        links.new(time_two_pi.outputs[0], angle_add.inputs[0])
        links.new(rand_phase.outputs["Value"], angle_add.inputs[1])

        sine = new("ShaderNodeMath", name=f"Sin {leaflet_index}")
        sine.operation = "SINE"
        sine.location = (800, y_pos - 500)
        links.new(angle_add.outputs[0], sine.inputs[0])

        # amp_bu = bob_amplitude_nm / NM_PER_BU
        amp_bu = new("ShaderNodeMath", name=f"AmpBU {leaflet_index}")
        amp_bu.operation = "MULTIPLY"
        amp_bu.inputs[1].default_value = 1.0 / NM_PER_BU
        amp_bu.location = (200, y_pos - 800)
        links.new(get_in("Bob Amplitude (nm)"), amp_bu.inputs[0])

        # gate by Animate Bob (multiply by 1.0 or 0.0)
        anim_to_float = new("FunctionNodeCompare", name=f"BobGate {leaflet_index}")
        anim_to_float.data_type = "INT"
        anim_to_float.operation = "EQUAL"
        anim_to_float.location = (200, y_pos - 950)
        # We just need to convert bool→float. Use Switch instead.
        bob_switch = new("GeometryNodeSwitch", name=f"BobSwitch {leaflet_index}")
        bob_switch.input_type = "FLOAT"
        bob_switch.location = (400, y_pos - 850)
        bob_switch.inputs["False"].default_value = 0.0
        links.new(get_in("Animate Bob"), bob_switch.inputs[0])  # Switch
        links.new(amp_bu.outputs[0], bob_switch.inputs["True"])

        offset_amount = new("ShaderNodeMath", name=f"OffAmt {leaflet_index}")
        offset_amount.operation = "MULTIPLY"
        offset_amount.location = (1000, y_pos - 600)
        links.new(sine.outputs[0], offset_amount.inputs[0])
        links.new(bob_switch.outputs[0], offset_amount.inputs[1])

        # Bob direction: scale (signed) — upper leaflet bobs up/down with
        # normal; lower leaflet bobs in opposite direction to look natural.
        bob_vec = new("ShaderNodeVectorMath", name=f"BobVec {leaflet_index}")
        bob_vec.operation = "SCALE"
        bob_vec.location = (1200, y_pos - 600)
        links.new(normal.outputs[0], bob_vec.inputs[0])
        links.new(offset_amount.outputs[0], bob_vec.inputs["Scale"])

        # Fold bob_vec into the SetPos 0 Position (so the half-thickness
        # offset survives). Chaining a second Set Position would reset the
        # position to (0,0,0) because Set Position writes its Position input
        # even when unlinked.
        final_pos = new("ShaderNodeVectorMath", name=f"FinalPos {leaflet_index}")
        final_pos.operation = "ADD"
        final_pos.location = (-1300, y_pos)
        links.new(new_pos.outputs[0], final_pos.inputs[0])
        links.new(bob_vec.outputs[0], final_pos.inputs[1])
        links.new(final_pos.outputs[0], set_pos.inputs["Position"])

        # Pass-through: keep the same downstream wiring but skip the
        # redundant second SetPosition. delete.outputs["Geometry"] feeds
        # directly into the next stage.
        bob_set = delete  # alias so subsequent code reads bob_set.outputs["Geometry"]

        # ---- Compute per-instance rotation -------------------------------
        # Step 1: align lipid +Z to normal (upper) or -normal (lower).
        if is_upper:
            align_normal = normal.outputs[0]
        else:
            neg = new("ShaderNodeVectorMath", name=f"NegN {leaflet_index}")
            neg.operation = "MULTIPLY"
            neg.inputs[1].default_value = (-1.0, -1.0, -1.0)
            neg.location = (0, y_pos - 150)
            links.new(normal.outputs[0], neg.inputs[0])
            align_normal = neg.outputs[0]

        align = new("FunctionNodeAlignRotationToVector",
                   name=f"AlignRot {leaflet_index}")
        align.axis = "Z"
        align.pivot_axis = "AUTO"
        align.location = (200, y_pos - 150)
        links.new(align_normal, align.inputs["Vector"])

        # Step 2: random Y-rotation (around lipid's own Z axis, which after
        # alignment points along the surface normal). We use the Rotate
        # Instances node later — easier to incorporate the random Z rotation
        # there. So we just produce the base alignment rotation here.
        base_rot = align.outputs["Rotation"]

        # ---- Instance lipid on points ------------------------------------
        # Scale per-instance.
        scale_to_vec = new("ShaderNodeCombineXYZ", name=f"ScaleVec {leaflet_index}")
        scale_to_vec.location = (1600, y_pos - 200)
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[0])
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[1])
        links.new(get_in("Lipid Scale"), scale_to_vec.inputs[2])

        oi_lipid = new("GeometryNodeObjectInfo", name=f"OI Lipid {leaflet_index}")
        oi_lipid.transform_space = "ORIGINAL"
        oi_lipid.location = (1400, y_pos - 400)
        links.new(get_in("Lipid Asset"), oi_lipid.inputs["Object"])

        iop = new("GeometryNodeInstanceOnPoints", name=f"IoP {leaflet_index}")
        iop.location = (1800, y_pos)
        links.new(bob_set.outputs["Geometry"], iop.inputs["Points"])
        links.new(oi_lipid.outputs["Geometry"], iop.inputs["Instance"])
        links.new(base_rot, iop.inputs["Rotation"])
        links.new(scale_to_vec.outputs[0], iop.inputs["Scale"])

        # ---- Rotate Instances: random Y (around local Z, the lipid's long axis)
        rand_yrot = new("FunctionNodeRandomValue", name=f"RandY {leaflet_index}")
        rand_yrot.data_type = "FLOAT"
        rand_yrot.location = (1600, y_pos - 600)
        rand_yrot.inputs[2].default_value = 0.0
        rand_yrot.inputs[3].default_value = math.tau
        # seed: index + offset
        seed_y = new("ShaderNodeMath", name=f"SeedY {leaflet_index}")
        seed_y.operation = "ADD"
        seed_y.inputs[1].default_value = float(31337 + leaflet_index * 7)
        seed_y.location = (1400, y_pos - 600)
        links.new(idx.outputs[0], seed_y.inputs[0])
        links.new(seed_y.outputs[0], rand_yrot.inputs["Seed"])

        # Gate by Random Rotation bool
        rot_switch = new("GeometryNodeSwitch", name=f"RotSwitch {leaflet_index}")
        rot_switch.input_type = "FLOAT"
        rot_switch.location = (1800, y_pos - 600)
        rot_switch.inputs["False"].default_value = 0.0
        links.new(get_in("Random Rotation"), rot_switch.inputs[0])
        links.new(rand_yrot.outputs["Value"], rot_switch.inputs["True"])

        # Make Euler vector (0, 0, angle) — this is rotation in the
        # INSTANCE's local space (because we set "Local Space" on the
        # Rotate Instances node below).
        rot_vec = new("ShaderNodeCombineXYZ", name=f"RotVec {leaflet_index}")
        rot_vec.location = (2000, y_pos - 600)
        rot_vec.inputs[0].default_value = 0.0
        rot_vec.inputs[1].default_value = 0.0
        links.new(rot_switch.outputs[0], rot_vec.inputs[2])

        rotate_inst = new("GeometryNodeRotateInstances",
                         name=f"RotInst {leaflet_index}")
        rotate_inst.location = (2200, y_pos)
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

    return tree


def get_or_build_membrane_gn_tree() -> bpy.types.GeometryNodeTree:
    """Return the membrane GN tree, building it if missing."""
    tree = bpy.data.node_groups.get(GN_TREE_NAME)
    if tree is None:
        tree = _build_membrane_gn_tree()
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
