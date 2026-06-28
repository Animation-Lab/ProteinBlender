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
# Slots reserved for per-protein force fields. Each ProteinBlender molecule
# whose force_field_enabled toggle is on gets one slot on every membrane;
# membranes silently drop overflow if more than this many proteins have the
# toggle on (capacity warning surfaced in the UI).
MAX_PROTEIN_FFS = 8

# Geometry Nodes group / asset names — kept stable so we can find them again
# across rebuilds.
GN_TREE_NAME = "ProteinBlender_Membrane_GN"
HEAD_MATERIAL_NAME = "PB_Membrane_Head"
TAIL_MATERIAL_NAME = "PB_Membrane_Tail"

# Bump whenever _build_membrane_gn_tree's node structure changes. Membranes
# saved with an older tree are detected via this tag and rebuilt on load.
#   v2: six-axis per-lipid mosh-pit motion
#   v3: holes redistribute lipids (radial push) instead of deleting them
#   v4: Poisson-disk lipid distribution + realistic default density
#   v5: holes are spheres — Z offset shrinks/closes the carved hole
#   v6: lipids picked randomly from a 4-variant collection (real PDB
#       conformations) instead of one hand-built mesh
#   v7: render style switchable (stylized/ball-and-stick/surface) — collection
#       is swapped at runtime; rand pick range driven by "Lipid Variant Count"
#   v8: twist channel tamed (smaller amp coefficient + tighter freq/amul
#       range) so even max user settings can't make a lipid spin like a top
#   v9: AlignRotationToVector fed un-perturbed normal — auto-pivot was
#       flipping the quaternion when its input swung with tilt, producing
#       single-frame Z jumps up to ~180°. Tilt now applied as local-space
#       Euler X/Y in the same RotateInstances call as the Z twist.
#   v10: twist channel is continuous rotation (angle = per-lipid signed
#       rate × scene time), not a sine wobble — lipids now slowly spin
#       like tops, each at its own rate and direction.
#   v11: spin rate coefficient doubled (0.5 → 1.0 rad/sec per BobSpeed
#       unit). The quaternion-flip bug had made v9 act faster than its
#       formula said; now that's fixed we can run the real rate hotter.
#   v12: shape-aware hole math — Shape Mode + Sphere Radius (nm) inputs
#       gate per-hole distance/direction between flat-XY and geodesic
#       (tangent-plane on sphere). Same tree handles flat sheet, full
#       sphere, and hemisphere bowl base meshes built outside the tree.
#   v13: protein force-field slots — 8 additional pushers parallel to the
#       hole slots, but radius is supplied as an explicit Float (so the GN
#       can size the push around a protein object whose own scale is 1).
#       Per-protein toggle on the molecule list drives which slots are
#       filled; the math reuses the hole pusher (sphere cross-section in
#       flat mode, geodesic-projected disc in sphere mode).
#   v14: sphere-mode geodesic distance switched from |tangent_away|
#       (= R·sin θ) to R·arccos(p̂·ĥ) (= true arc length). The old
#       formula folded to zero at θ = π, so a pusher near one side of a
#       sphere / hemisphere bowl carved a mirror hole on the opposite
#       side. arccos keeps the distance monotonic out to π.
#   v15: sphere-mode distance switched again — to plain 3D Euclidean
#       |lipid − pusher|. Both the chord-projection and arc-length
#       formulas only used the pusher's *direction* (h_norm), so a
#       protein near the centre of a sphere still carved at the
#       surface point in its direction. Real 3D distance accounts for
#       the pusher's radial position and the carving fades correctly
#       as it moves inward / outward.
#   v16: slot accumulator switched from SUM to strongest-push-wins.
#       Multiple FFs / holes whose influence zones overlap used to
#       have their per-lipid displacements added, so a lipid in the
#       intersection got pushed twice as far as either FF intended —
#       the gap stretched in the direction of the extra pusher.
#       Now each lipid picks just the slot proposing the strongest
#       push, so overlapping pushers behave as the union of their
#       gaps instead of cumulatively over-shooting.
#   v17: reverted v16's strongest-wins back to vector SUM. v16
#       silently dropped contributions from non-dominant pushers,
#       so a lipid inside two FFs only escaped the strongest one
#       and ended up clipping into the other protein. Vector
#       addition is the physically correct combination — both
#       pushes apply and the resultant vector kicks the lipid out
#       of both zones.
#   v18: per-slot push formula switched from area-preserving
#       (sqrt(d² + R²) − d) to clamp-to-boundary (max(0, R − d)).
#       The old formula pushed lipids ~1.4 R *past* the FF
#       boundary even from a single FF, so the user-set Spacing
#       wasn't the actual gap width; under vector-sum with two
#       FFs the gap stretched even further. With the new form,
#       each FF moves an inside-the-zone lipid just to its own
#       boundary, so Spacing literally is the lipid-to-protein
#       gap and multi-FF additions don't compound.
#   v19: multi-pusher combination switched from vector SUM to
#       squared-weight blend. v17/v18's vector sum cancelled to
#       ≈(0,0,0) for lipids in the overlap of two near-equal
#       pushers — per-slot disp vectors are antiparallel and the
#       components along the line joining the two centres cancel,
#       so lipids stuck in the pinch zone got pushed only by the
#       tiny perpendicular residual and stayed inside the union of
#       both protein zones. New combiner per leaflet:
#           weighted_dir = Σ p_i² · dir_i   (vector accumulator)
#           max_pen      = max_i p_i        (scalar accumulator)
#           disp         = normalize(weighted_dir) · max_pen
#       where p_i = per-slot clamp-to-boundary push (the v18
#       scalar) and dir_i = unit outward from pusher centre. The
#       squared weight tilts the resultant direction toward
#       whichever pusher is deeper; max_pen guarantees the lipid
#       moves by the full penetration depth of the deepest zone,
#       so it escapes that zone in one pass (and typically the
#       union, when the lipid is off the line joining centres).
#       Single-pusher case reduces to dir · p — identical to v18.
#       Lipids exactly on the line joining two equal pushers still
#       cancel to zero (degenerate 1D subset; acceptable for now).
#   v20: squared-weight blend unrolled into 3 Jacobi iterations.
#       v19's single-pass push left a visible "snake" of lipids
#       in the overlap region between two close FF proteins: off-
#       midline lipids got pushed perpendicular to the line AB by
#       max_pen, but pen decreases as the lipid moves away from
#       the centres, so a single pass converges to the boundary
#       only in the limit. Three iterations starting from the
#       *displaced* position of the previous iteration move the
#       lipid much closer to the lens edge; in practice this
#       clears the union of the two FF zones.
#           pos₀ = original captured lipid position
#           disp₁ = squared-weight combine of 16 slots at pos₀
#           pos₁ = pos₀ + disp₁
#           disp₂ = squared-weight combine of 16 slots at pos₁
#           pos₂ = pos₁ + disp₂
#           disp₃ = squared-weight combine of 16 slots at pos₂
#           pusher_disp = disp₁ + disp₂ + disp₃
#       Each iteration rebuilds the full pusher subgraph (16
#       slots × ObjectInfo + math + switches) parameterized on
#       a different position socket — tree size roughly triples
#       to ~6k nodes per leaflet. Exact-midline lipids (equal
#       pen, antiparallel dirs) still cancel in every iteration
#       — that's the same 1D degenerate subset as v19.
#   v21: ITERATIONS bumped 3 → 5. v20 with 3 passes left a
#       visible NS strip of lipids in two-FF overlap scenes —
#       the per-iter push magnitude (max_pen) shrinks as the
#       lipid moves perpendicular to the AB line, so 3 passes
#       only reached ~92% of the way to the lens edge. Each
#       extra pass closes the remaining geometric gap; at 5
#       passes lipids reach ~99% of the lens edge for typical
#       D/R ratios. Tree node count scales linearly with the
#       iteration count.
#   v22: ITERATIONS reverted 5 → 3. v21 reliably hangs Build
#       Membrane even on an empty scene with no proteins
#       enabled — the GN evaluator runs the full per-iteration
#       math regardless of whether the per-slot gates are
#       closed, so eval cost scales with tree size not active-
#       slot count. 3 iter is the practical upper bound for
#       this design; the residual NS strip in two-FF overlap
#       is the trade-off. The iterative-squared-weight approach
#       converges asymptotically (push magnitude shrinks as
#       the lipid moves outward) so further iter bumps don't
#       help in proportion to their cost — next step is a
#       different multi-pusher combiner.
#   v23: dynamic slot count. The tree is now sized to the
#       max(holes-per-membrane) + count(FF-enabled proteins)
#       at build time, not the fixed MAX_HOLES + MAX_PROTEIN_FFS.
#       Active counts are stamped on the tree as
#       ``pb_active_holes`` / ``pb_active_ffs``; the get-or-build
#       path rebuilds when scene demand exceeds those tags.
#       Typical first build (0 holes, 0 FFs) skips the pusher
#       graph entirely, dropping eval cost from ~3,600 nodes
#       per lipid to ~500. Operators that grow a slot
#       (Add Hole, force_field_enabled toggle) call into
#       get_or_build_membrane_gn_tree(scene) before pushing the
#       new value, which grows the tree if needed and re-links
#       every membrane modifier to it.
#   v24: ITERATIONS back to 5. Each Jacobi pass already applies the
#       *combined* squared-weight push of every active pusher (per-
#       slot directions are weighted by p_i² and accumulated into a
#       single resultant before the magnitude scales), so "compute
#       combined force then apply" already happens per pass — what
#       limits two-protein overlap quality is convergence, not
#       combination. v22 capped iter at 3 because the 16-slot static
#       tree of v21's 5-iter design hung Build; with v23's dynamic
#       slot count the iter cost only applies when pushers are
#       actually wired, so 5 passes against the typical 1-2 active
#       slots is cheap (10 slot-evals/lipid vs v22's 48). 5 iter
#       takes overlap-zone lipids from ~92% to ~99% of the union-
#       boundary, removing the residual NS strip that called out as
#       "confused" lipids when two proteins are close.
#   v25: analytic SDF + softmax smooth-min. The pushers are
#       already mathematically spheres (one location + one radius
#       per slot), so we can compute each slot's signed distance
#       and outward gradient in 4 nodes — no need to voxelise via
#       Mesh-to-SDF Grid. Per-slot:
#           sdf_i  = length(lipid - pusher) - R_i
#           dir_i  = (lipid - pusher) / length   (radially out)
#           w_i    = enabled_i · exp(−α · sdf_i)
#       Combiner (softmax / log-sum-exp = smooth-min):
#           total      = Σ w_i
#           grad       = Σ w_i · dir_i  / total
#           smin_sdf   = −ln(total) / α
#           push_mag   = max(0, −smin_sdf)
#           disp       = grad · push_mag
#       Properties this gives us:
#       * Single-pass. No Jacobi loop, no convergence asymptote.
#         For a single pusher the formula collapses to exact
#         clamp-to-boundary (lipid moves exactly to the sphere
#         surface in one go).
#       * Native smooth combination. Two overlapping pushers
#         blend into one bulged exit surface via the smin — exactly
#         what the iterative squared-weight scheme was approximating.
#         No degenerate midline cancellation except a measure-zero
#         set, broken in practice by the mosh-pit motion sum.
#       * Per-slot graph drops from ~30 nodes × 5 iter = 150 to
#         ~10 nodes × 1 = 10. Total tree at 2 active FFs goes from
#         920 nodes (v24) to roughly 150 (v25).
#       * α (FF Smoothness) controls how much the combined surface
#         bulges between close pushers. Exposed as a tree input.
#       Shape-aware distance / direction / radius are unchanged
#       per slot (flat XY-only with Z-aware effective R, sphere
#       3D Euclidean with tangent-plane direction) — _build_pusher
#       still does that work; the combiner just consumes its outputs
#       differently.
#   v26: FF Smoothness default lowered 5.0 → 2.0. At α=5 the smin
#       bulge between non-overlapping pusher spheres only extended
#       ~0.28 BU past each individual boundary, so a cluster of
#       proteins whose bounding spheres didn't quite touch still
#       left lipids sitting in the gaps between them — visibly
#       overlapping the proteins in the user's image. At α=2 the
#       bulge extends ~0.69 BU per ln(N) slot, which is enough to
#       merge a typical 4-protein cluster (centres ~1 BU apart,
#       R ~ 0.35 BU) into one combined obstacle. Single-pusher
#       case is unchanged (smin reduces to sdf when N=1). Bump
#       forces a tree rebuild so existing membranes pick up the
#       new default.
#   v27: "Bilayer Thickness (nm)" is now outer-surface-to-outer-surface
#        (visible thickness) rather than instance-origin-to-instance-origin.
#        New "Lipid Outer Extent (nm)" input lets the operator push the
#        per-style mesh extent above the instance origin; the leaflet
#        builder subtracts 2·Extent·LipidScale from Thickness before
#        halving, so the slider value equals what the user measures with
#        a ruler. Default Thickness bumped 3.2 → 5.0 nm (real bilayer).
#   v28: "Lipid Scale" input dropped — lipid size is fixed at 1×. The
#        slider was UI noise: per-style outer-extent constants already
#        calibrate the bilayer to spec; rescaling individual lipids
#        threw that calibration off and was rarely useful. Inset block
#        is now Thickness − 2·Extent (no scale multiply); IoP Scale
#        left at its (1, 1, 1) default; ScaleVec combine nodes removed
#        from both leaflets.
#   v29: SURFACE lipid assets rebaked with VdW-sized metaballs (radii
#        cut ~50%, stiffness 2.0 → 1.0). Surface now reads as fused
#        atom-sized bumps, MN-Surface style, instead of smooth sausages.
#        SURFACE outer extent recalibrated 0.89 → 0.75 nm to keep the
#        Bilayer Thickness slider honest. No tree-structure changes —
#        version bump exists only to force re-push of the new extent
#        value into existing membranes' modifiers.
#   v30: SURFACE radii bumped back up to SAS-style probes (≈ VdW + 1.4 Å,
#        so ~80% of the original v6 values). Stiffness stays at 1.0 from
#        v29. v29's raw-VdW radii made each 50-atom lipid look like a
#        spindly wireframe next to a protein's chunky SAS surface;
#        v30 restores enough volume to read as a packed bilayer while
#        keeping the per-atom bump character. SURFACE outer extent
#        rebumped to track the larger blob (recalibrated by MCP).
#   v31: STYLIZED head sphere halved 0.04 → 0.02 BU. STYLIZED outer
#        extent recalibrated 0.80 → 0.60 nm so the head halving doesn't
#        push the bilayer thinner than the spec. No tree-structure
#        change — version bump exists to force re-push of the new
#        extent into existing membranes' modifiers when they upgrade.
GN_TREE_VERSION = 31


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
                         color_tail: Tuple[float, float, float, float],
                         color_surface: Optional[
                             Tuple[float, float, float, float]] = None) -> None:
    """Re-color the shared lipid materials.

    Head/tail are used by the STYLIZED and BALL_AND_STICK styles. The
    optional surface colour drives the SURFACE style's single material.
    All three live as shared datablocks — re-colouring updates every
    membrane in the scene at once, by design.
    """
    _ensure_material(HEAD_MATERIAL_NAME, color_head, roughness=0.35)
    _ensure_material(TAIL_MATERIAL_NAME, color_tail, roughness=0.55)
    if color_surface is not None:
        lipid_assets.set_surface_color(color_surface)


# ===========================================================================
# Lipid asset collection
# ===========================================================================
# The 4 PDB-derived lipid variants live in lipid_assets.py. The GN tree
# reads them via a Collection Info node + Pick Instance, so each lipid in
# the membrane is randomly one of the four real conformations.

from . import lipid_assets


def get_or_build_lipid_collection(
        style: str = lipid_assets.DEFAULT_STYLE) -> bpy.types.Collection:
    """Public accessor for a render-style lipid collection."""
    return lipid_assets.get_or_build_lipid_collection(style)


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


def _build_membrane_gn_tree(num_holes: int = 0,
                             num_ffs: int = 0) -> bpy.types.GeometryNodeTree:
    """Build the membrane Geometry Nodes tree, replacing any existing one.

    ``num_holes`` and ``num_ffs`` determine how many hole / protein-FF pusher
    slots are wired into the tree. The whole pusher subgraph (which evaluates
    on every lipid every frame) is skipped entirely when both counts are 0 —
    typical for a fresh Build with no proteins / holes. Each existing slot
    still costs eval time even when its Enabled bool is False, so sizing the
    tree to the scene's actual demand is the main perf lever.
    """
    num_holes = max(0, min(int(num_holes), MAX_HOLES))
    num_ffs = max(0, min(int(num_ffs), MAX_PROTEIN_FFS))

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

    _new_input(tree, "Lipid Collection", "NodeSocketCollection")
    # How many variants live in the collection. Drives the per-point random
    # Instance Index max: rand(0, count-1). Stylized = 1; ball-and-stick /
    # surface = 4. Pushed by the operator whenever render style changes.
    _new_input(tree, "Lipid Variant Count", "NodeSocketInt",
               default=lipid_assets.NUM_LIPID_VARIANTS, min_val=1, max_val=32)
    _new_input(tree, "Density (per nm²)", "NodeSocketFloat",
               default=1.5, min_val=0.05, max_val=5.0)
    _new_input(tree, "Bilayer Thickness (nm)", "NodeSocketFloat",
               default=5.0, min_val=2.0, max_val=15.0)
    # How far the rendered lipid extends above its instance origin (P side),
    # in nm. The leaflet builder uses (Thickness - 2·Extent) as the effective
    # head-to-head separation so the user's Thickness value matches the
    # visible outer-surface-to-outer-surface thickness of the bilayer.
    # Pushed by the operator on style change. Default tracks SURFACE.
    _new_input(tree, "Lipid Outer Extent (nm)", "NodeSocketFloat",
               default=lipid_assets.outer_extent_for_style(
                   lipid_assets.DEFAULT_STYLE),
               min_val=0.0, max_val=3.0)
    _new_input(tree, "Random Rotation", "NodeSocketBool", default=True)
    _new_input(tree, "Animate Bob", "NodeSocketBool", default=False)
    _new_input(tree, "Bob Amplitude (nm)", "NodeSocketFloat",
               default=0.3, min_val=0.0, max_val=3.0)
    _new_input(tree, "Bob Speed", "NodeSocketFloat",
               default=0.6, min_val=0.05, max_val=5.0)
    _new_input(tree, "Random Seed", "NodeSocketInt", default=0)
    # Shape Mode: 0 = flat sheet, 1 = sphere, 2 = hemisphere bowl. Used
    # to gate hole math (geodesic on sphere vs flat XY on sheet). The
    # base mesh itself is built outside the GN tree; this just tells the
    # tree how to *interpret* point positions for holes.
    _new_input(tree, "Shape Mode", "NodeSocketInt",
               default=0, min_val=0, max_val=2)
    _new_input(tree, "Sphere Radius (nm)", "NodeSocketFloat",
               default=15.0, min_val=1.0, max_val=200.0)
    # SDF combine smoothness (v25). Smaller = more bulge between close
    # pushers (the combined "obstacle" reaches further beyond each
    # individual sphere); larger = closer to hard min (each pusher
    # carves its own gap with little bridging). The smin bulge extent
    # for N equal pushers is ln(N)/α below their individual sdf — so
    # at α=2, four close pushers extend the combined inside region by
    # ~0.69 BU past each individual boundary, which is what's needed
    # to make a cluster act as one obstacle to the membrane.
    # v26: default reduced 5.0 → 2.0 — at 5.0 the bulge between
    # cluster proteins was too narrow and lipids settled in the gaps.
    _new_input(tree, "FF Smoothness", "NodeSocketFloat",
               default=2.0, min_val=0.5, max_val=50.0)

    # Hole controllers — up to ``num_holes`` slots. Each has an "Enabled"
    # bool that gates the slot so unassigned slots don't carve a phantom
    # hole at the origin. v23: count is dynamic; tree grows when a
    # membrane adds a hole past current capacity.
    for i in range(1, num_holes + 1):
        _new_input(tree, f"Hole {i} Enabled", "NodeSocketBool", default=False)
        _new_input(tree, f"Hole {i}", "NodeSocketObject")

    # Protein force-field slots — same pusher math as a hole, but the radius
    # is an explicit Float (BU). The object input is the protein itself
    # (whose own scale stays the user's to control). The owning operator
    # writes these whenever a protein's force_field_enabled / spacing
    # changes, or when a new membrane is built. v23: count is dynamic.
    for i in range(1, num_ffs + 1):
        _new_input(tree, f"Protein FF {i} Enabled", "NodeSocketBool",
                   default=False)
        _new_input(tree, f"Protein FF {i}", "NodeSocketObject")
        _new_input(tree, f"Protein FF {i} Radius", "NodeSocketFloat",
                   default=0.0, min_val=0.0, max_val=50.0)

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
    # 1b. Inset half-thickness — shared by both leaflets.
    #
    # The user's "Bilayer Thickness" is the **outer-surface-to-outer-surface**
    # visible thickness of the rendered bilayer (so the slider matches what
    # they see). The lipid mesh extends some distance above its instance
    # origin (≈0.85 nm for SURFACE, set per style via "Lipid Outer Extent").
    # The effective head-to-head separation we hand to the leaflets is
    # therefore  Thickness − 2 · Extent .  Clamped at zero so a too-thin
    # slider value doesn't invert the leaflets.
    # ------------------------------------------------------------------
    double_extent = new("ShaderNodeMath", name="DoubleExtent")
    double_extent.operation = "MULTIPLY"
    double_extent.inputs[1].default_value = 2.0
    double_extent.location = (-2500, 250)
    links.new(get_in("Lipid Outer Extent (nm)"), double_extent.inputs[0])

    inset_thick_nm = new("ShaderNodeMath", name="InsetThickness")
    inset_thick_nm.operation = "SUBTRACT"
    inset_thick_nm.location = (-2300, 250)
    links.new(get_in("Bilayer Thickness (nm)"), inset_thick_nm.inputs[0])
    links.new(double_extent.outputs[0], inset_thick_nm.inputs[1])

    inset_clamped = new("ShaderNodeMath", name="InsetClamped")
    inset_clamped.operation = "MAXIMUM"
    inset_clamped.inputs[1].default_value = 0.0
    inset_clamped.location = (-2100, 250)
    links.new(inset_thick_nm.outputs[0], inset_clamped.inputs[0])

    # Effective half-thickness in BU — fed into both leaflets' SignedHalf
    # nodes (upper leaves it positive, lower negates it).
    half_thick_shared = new("ShaderNodeMath", name="HalfThick (shared)")
    half_thick_shared.operation = "MULTIPLY"
    half_thick_shared.inputs[1].default_value = 1.0 / (NM_PER_BU * 2.0)
    half_thick_shared.location = (-1900, 250)
    links.new(inset_clamped.outputs[0], half_thick_shared.inputs[0])

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

        # Half thickness (in BU). The shared inset half-thickness sub-graph
        # (see pre-leaflet block) accounts for the rendered lipid mesh
        # extending above its instance origin, so this signed offset places
        # the lipid origin where the visible head sphere meets the user's
        # Bilayer Thickness value, not at the head itself.
        signed_half = new("ShaderNodeMath", name=f"SignedHalf {leaflet_index}")
        signed_half.operation = "MULTIPLY"
        signed_half.inputs[1].default_value = 1.0 if is_upper else -1.0
        signed_half.location = (-1800, y_pos + 100)
        links.new(half_thick_shared.outputs[0], signed_half.inputs[0])

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
        # The hole empty is treated as a real sphere — its Z position matters
        # (see the effective-radius block below): sliding it out of the
        # membrane shrinks and closes the hole.
        #
        # Every hole's displacement is summed. Because Object Info reads the
        # empty live, animating a hole's scale or location makes the lipids
        # flow in real time (grow the hole → lipids stream outward; shrink it
        # → the membrane heals closed).
        HOLE_INFLUENCE = 3.0   # disturbance reaches 3× the pusher radius
        # v25: the Jacobi iteration scheme is replaced by a single
        # softmax-weighted smooth-min pass (see _compute_sdf_displacement
        # below). For sphere pushers the SDF and its gradient are
        # analytic, so a one-shot push lands the lipid on (or arbitrarily
        # close to, depending on the smoothness α) the combined exit
        # surface — no iteration needed, and no asymptotic residual in
        # overlap zones.

        # is_curved = (Shape Mode >= 1) — true for sphere / hemisphere,
        # false for flat sheet. Used to swap the per-hole distance and
        # direction computation between "flat XY distance" and
        # "geodesic-projected tangent-plane distance on a sphere".
        is_curved_node = new("ShaderNodeMath", name=f"IsCurved L{leaflet_index}")
        is_curved_node.operation = "GREATER_THAN"
        is_curved_node.inputs[1].default_value = 0.5
        is_curved_node.location = (-2000, y_pos - 550)
        links.new(get_in("Shape Mode"), is_curved_node.inputs[0])
        is_curved = is_curved_node.outputs[0]

        def _build_pusher(slot_label, enabled_sock, obj_sock,
                          radius_source, hy, pos_socket):
            """Build the per-slot pusher subgraph and return its gated
            displacement vector socket.

            ``radius_source`` is either:
              * a Float socket — used directly as the "raw R" (FFs do this,
                pulling from a per-slot input set by the operator), or
              * a callable ``(oi_node, hy) -> socket`` that builds a sub-
                graph and returns the resulting Float socket (holes do
                this — they derive R from Object Info → Scale.x).

            ``pos_socket`` is the vector socket carrying the current
            lipid position. For v20's Jacobi iteration, each pass passes
            a different position socket so the pusher subgraph is rebuilt
            and re-evaluated against the position the previous iteration
            left the lipid at.
            """
            oi = new("GeometryNodeObjectInfo",
                     name=f"OI {slot_label} L{leaflet_index}")
            oi.transform_space = "RELATIVE"
            oi.location = (-1750, hy)
            links.new(obj_sock, oi.inputs["Object"])

            # sub_vec = point - object.location (3D, used by both paths).
            sub_vec = new("ShaderNodeVectorMath",
                          name=f"Sub{slot_label} L{leaflet_index}")
            sub_vec.operation = "SUBTRACT"
            sub_vec.location = (-1560, hy)
            links.new(pos_socket, sub_vec.inputs[0])
            links.new(oi.outputs["Location"], sub_vec.inputs[1])

            # ============================================================
            # FLAT path: pusher is a vertical column, distance/direction in XY
            # ============================================================
            flat_xy = new("ShaderNodeVectorMath",
                          name=f"Flat{slot_label} L{leaflet_index}")
            flat_xy.operation = "MULTIPLY"
            flat_xy.inputs[1].default_value = (1.0, 1.0, 0.0)
            flat_xy.location = (-1380, hy)
            links.new(sub_vec.outputs[0], flat_xy.inputs[0])

            dist_flat = new("ShaderNodeVectorMath",
                            name=f"LenFlat{slot_label} L{leaflet_index}")
            dist_flat.operation = "LENGTH"
            dist_flat.location = (-1200, hy)
            links.new(flat_xy.outputs[0], dist_flat.inputs[0])

            dir_flat = new("ShaderNodeVectorMath",
                           name=f"DirFlat{slot_label} L{leaflet_index}")
            dir_flat.operation = "NORMALIZE"
            dir_flat.location = (-1200, hy - 130)
            links.new(flat_xy.outputs[0], dir_flat.inputs[0])

            # ============================================================
            # SPHERE path: lipid sits on a sphere centred at the membrane
            # root's origin. The pusher's "surface projection" is the
            # point on the sphere in the direction of pusher_location, at
            # the same radius as the lipid (so a deformed sphere still
            # picks the right rim). The geodesic distance is approximated
            # by the length of the projection of (lipid - h_surf) onto
            # the tangent plane at the lipid — exact for small angles, an
            # under-estimate of true arc length for large ones.
            # ============================================================
            p_len = new("ShaderNodeVectorMath",
                        name=f"PLen{slot_label} L{leaflet_index}")
            p_len.operation = "LENGTH"
            p_len.location = (-1380, hy - 420)
            links.new(pos_socket, p_len.inputs[0])

            p_norm = new("ShaderNodeVectorMath",
                         name=f"PNorm{slot_label} L{leaflet_index}")
            p_norm.operation = "NORMALIZE"
            p_norm.location = (-1380, hy - 560)
            links.new(pos_socket, p_norm.inputs[0])

            h_norm = new("ShaderNodeVectorMath",
                         name=f"HNorm{slot_label} L{leaflet_index}")
            h_norm.operation = "NORMALIZE"
            h_norm.location = (-1380, hy - 700)
            links.new(oi.outputs["Location"], h_norm.inputs[0])

            h_surf = new("ShaderNodeVectorMath",
                         name=f"HSurf{slot_label} L{leaflet_index}")
            h_surf.operation = "SCALE"
            h_surf.location = (-1200, hy - 700)
            links.new(h_norm.outputs[0], h_surf.inputs[0])
            links.new(p_len.outputs["Value"], h_surf.inputs["Scale"])

            sub_sphere = new("ShaderNodeVectorMath",
                             name=f"SubSph{slot_label} L{leaflet_index}")
            sub_sphere.operation = "SUBTRACT"
            sub_sphere.location = (-1020, hy - 700)
            links.new(pos_socket, sub_sphere.inputs[0])
            links.new(h_surf.outputs[0], sub_sphere.inputs[1])

            sub_dot_n = new("ShaderNodeVectorMath",
                            name=f"SubDotN{slot_label} L{leaflet_index}")
            sub_dot_n.operation = "DOT_PRODUCT"
            sub_dot_n.location = (-840, hy - 700)
            links.new(sub_sphere.outputs[0], sub_dot_n.inputs[0])
            links.new(p_norm.outputs[0], sub_dot_n.inputs[1])

            radial_part = new("ShaderNodeVectorMath",
                              name=f"RadPart{slot_label} L{leaflet_index}")
            radial_part.operation = "SCALE"
            radial_part.location = (-660, hy - 700)
            links.new(p_norm.outputs[0], radial_part.inputs[0])
            links.new(sub_dot_n.outputs["Value"], radial_part.inputs["Scale"])

            tangent_away = new("ShaderNodeVectorMath",
                               name=f"TanAway{slot_label} L{leaflet_index}")
            tangent_away.operation = "SUBTRACT"
            tangent_away.location = (-480, hy - 700)
            links.new(sub_sphere.outputs[0], tangent_away.inputs[0])
            links.new(radial_part.outputs[0], tangent_away.inputs[1])

            # Distance is the true 3D Euclidean separation between lipid
            # and the pusher's centre. The earlier arc-length / projected-
            # tangent formulas only considered the *angular* position of
            # the pusher (h_norm) and discarded its radial distance from
            # the membrane's origin — so a protein near the centre of a
            # sphere still carved a hole at the surface point in its
            # direction. Real 3D distance falls off naturally as the
            # protein moves inward (or outward), and the carving
            # disappears once it leaves the FF's influence sphere.
            dist_sphere = new("ShaderNodeVectorMath",
                              name=f"Dist3D{slot_label} L{leaflet_index}")
            dist_sphere.operation = "LENGTH"
            dist_sphere.location = (-300, hy - 540)
            links.new(sub_vec.outputs[0], dist_sphere.inputs[0])

            # Push direction is still the tangent-plane "away from
            # pusher" vector — keeps lipids sliding along the shell
            # rather than off it. Undefined right at the pusher's
            # tangent-projected centre, but the radial component zeros
            # the displacement there anyway, so no visible artefact.
            dir_sphere = new("ShaderNodeVectorMath",
                             name=f"DirSph{slot_label} L{leaflet_index}")
            dir_sphere.operation = "NORMALIZE"
            dir_sphere.location = (-300, hy - 840)
            links.new(tangent_away.outputs[0], dir_sphere.inputs[0])

            # ============================================================
            # Switch between flat and sphere paths
            # ============================================================
            dist_sw = new("GeometryNodeSwitch",
                          name=f"DistSw{slot_label} L{leaflet_index}")
            dist_sw.input_type = "FLOAT"
            dist_sw.location = (-120, hy)
            links.new(is_curved, dist_sw.inputs[0])
            links.new(dist_flat.outputs["Value"], dist_sw.inputs["False"])
            links.new(dist_sphere.outputs["Value"], dist_sw.inputs["True"])

            dir_sw = new("GeometryNodeSwitch",
                         name=f"DirSw{slot_label} L{leaflet_index}")
            dir_sw.input_type = "VECTOR"
            dir_sw.location = (-120, hy - 140)
            links.new(is_curved, dir_sw.inputs[0])
            links.new(dir_flat.outputs[0], dir_sw.inputs["False"])
            links.new(dir_sphere.outputs[0], dir_sw.inputs["True"])

            # ``dist`` is the FLOAT switch; ``direction`` the VECTOR switch.
            dist = dist_sw
            direction = dir_sw

            # Raw radius source: holes pull from Object Info → Scale.X
            # (via the callable form), FFs pass a Float socket directly.
            raw_radius_sock = (radius_source(oi, hy)
                               if callable(radius_source)
                               else radius_source)

            # ---- Z-aware effective radius (FLAT path only) -------------
            # Treat the pusher as a real SPHERE of radius R. The disc it
            # carves in THIS leaflet is the sphere's cross-section at the
            # leaflet's height: effective radius = sqrt(R² - dz²), where
            # dz is the vertical gap between the pusher centre and the
            # leaflet surface. On a curved membrane this trick doesn't
            # apply — surface isn't horizontal — so the sphere path uses
            # the plain radius.
            sub_z = new("ShaderNodeSeparateXYZ",
                        name=f"SubZ{slot_label} L{leaflet_index}")
            sub_z.location = (-1380, hy - 170)
            links.new(sub_vec.outputs[0], sub_z.inputs[0])

            vgap = new("ShaderNodeMath",
                       name=f"VGap{slot_label} L{leaflet_index}")
            vgap.operation = "ADD"
            vgap.location = (-1200, hy - 250)
            links.new(sub_z.outputs["Z"], vgap.inputs[0])
            links.new(signed_half.outputs[0], vgap.inputs[1])

            gap_sq = new("ShaderNodeMath",
                         name=f"GapSq{slot_label} L{leaflet_index}")
            gap_sq.operation = "MULTIPLY"
            gap_sq.location = (-1020, hy - 250)
            links.new(vgap.outputs[0], gap_sq.inputs[0])
            links.new(vgap.outputs[0], gap_sq.inputs[1])

            r_sq = new("ShaderNodeMath",
                       name=f"RSq{slot_label} L{leaflet_index}")
            r_sq.operation = "MULTIPLY"
            r_sq.location = (-1020, hy - 410)
            links.new(raw_radius_sock, r_sq.inputs[0])
            links.new(raw_radius_sock, r_sq.inputs[1])

            eff_sq = new("ShaderNodeMath",
                         name=f"EffSq{slot_label} L{leaflet_index}")
            eff_sq.operation = "SUBTRACT"
            eff_sq.location = (-840, hy - 330)
            links.new(r_sq.outputs[0], eff_sq.inputs[0])
            links.new(gap_sq.outputs[0], eff_sq.inputs[1])

            eff_clamp = new("ShaderNodeMath",
                            name=f"EffClp{slot_label} L{leaflet_index}")
            eff_clamp.operation = "MAXIMUM"
            eff_clamp.inputs[1].default_value = 0.0
            eff_clamp.location = (-660, hy - 330)
            links.new(eff_sq.outputs[0], eff_clamp.inputs[0])

            eff_r_flat = new("ShaderNodeMath",
                             name=f"EffRFlat{slot_label} L{leaflet_index}")
            eff_r_flat.operation = "SQRT"
            eff_r_flat.location = (-480, hy - 330)
            links.new(eff_clamp.outputs[0], eff_r_flat.inputs[0])

            r_sw = new("GeometryNodeSwitch",
                       name=f"REffSw{slot_label} L{leaflet_index}")
            r_sw.input_type = "FLOAT"
            r_sw.location = (-300, hy - 330)
            links.new(is_curved, r_sw.inputs[0])
            links.new(eff_r_flat.outputs[0], r_sw.inputs["False"])
            links.new(raw_radius_sock, r_sw.inputs["True"])

            radius = r_sw.outputs[0]

            dist_out = dist.outputs[0]
            dir_out = direction.outputs[0]

            # v25: return the raw (distance, direction, radius, enabled)
            # quadruple. The SDF combiner downstream forms its own
            # weight = enabled · exp(−α(dist − R)) and combines all slots
            # in a single softmax / log-sum-exp pass, so the per-slot
            # clamp-to-boundary push, smoothstep falloff, and enabled
            # gate that used to live here are no longer needed.
            return dist_out, dir_out, radius, enabled_sock

        def _hole_radius_source(oi_node, hy):
            """Radius source for hole slots: the object's uniform Scale.X."""
            scale_sep = new("ShaderNodeSeparateXYZ",
                            name=f"Scale{oi_node.name} L{leaflet_index}")
            scale_sep.location = (-1560, hy - 170)
            links.new(oi_node.outputs["Scale"], scale_sep.inputs[0])
            return scale_sep.outputs["X"]

        def _compute_sdf_displacement(pos_socket):
            """Build the SDF-based pusher combiner (v25).

            For each active slot, ``_build_pusher`` already emits the
            shape-aware distance, away direction, and effective radius;
            here we form per-slot softmax weights:

                sdf_i = dist_i - radius_i
                w_i   = enabled_i · exp(−α · sdf_i)

            then combine across slots with log-sum-exp / weighted-mean:

                total      = Σ w_i
                grad       = Σ w_i · dir_i / total
                smin_sdf   = −ln(total) / α
                push_mag   = max(0, −smin_sdf)
                disp       = grad · push_mag

            This is a single pass; no Jacobi loop. For 1 active slot it
            collapses to the exact clamp-to-boundary push (w_1 cancels in
            the grad division; smin_sdf = sdf_1). For ≥2 overlapping
            slots it is the polynomial smooth-min, so the combined exit
            surface naturally bulges into a single smooth boundary.
            """
            alpha_sock = get_in("FF Smoothness")
            neg_alpha = new("ShaderNodeMath",
                            name=f"NegAlpha L{leaflet_index}")
            neg_alpha.operation = "MULTIPLY"
            neg_alpha.inputs[1].default_value = -1.0
            neg_alpha.location = (-2400, y_pos + 350)
            links.new(alpha_sock, neg_alpha.inputs[0])

            inv_alpha = new("ShaderNodeMath",
                            name=f"InvAlpha L{leaflet_index}")
            inv_alpha.operation = "DIVIDE"
            inv_alpha.inputs[0].default_value = 1.0
            inv_alpha.location = (-2400, y_pos + 200)
            links.new(alpha_sock, inv_alpha.inputs[1])

            total_w = None
            weighted_dir = None

            def _add_slot(slot_label, enabled_sock, obj_sock,
                          radius_source, hy):
                nonlocal total_w, weighted_dir
                dist_s, dir_s, radius_s, en_s = _build_pusher(
                    slot_label, enabled_sock, obj_sock,
                    radius_source, hy, pos_socket)

                # sdf_i = dist_i - radius_i
                sdf = new("ShaderNodeMath",
                           name=f"Sdf{slot_label} L{leaflet_index}")
                sdf.operation = "SUBTRACT"
                sdf.location = (100, hy)
                links.new(dist_s, sdf.inputs[0])
                links.new(radius_s, sdf.inputs[1])

                # exponent = -α · sdf
                expt = new("ShaderNodeMath",
                            name=f"NegASdf{slot_label} L{leaflet_index}")
                expt.operation = "MULTIPLY"
                expt.location = (280, hy)
                links.new(neg_alpha.outputs[0], expt.inputs[0])
                links.new(sdf.outputs[0], expt.inputs[1])

                # weight_raw = exp(-α · sdf)
                wraw = new("ShaderNodeMath",
                            name=f"Exp{slot_label} L{leaflet_index}")
                wraw.operation = "EXPONENT"
                wraw.location = (460, hy)
                links.new(expt.outputs[0], wraw.inputs[0])

                # w_i = enabled_i · weight_raw (gate)
                w = new("ShaderNodeMath",
                         name=f"W{slot_label} L{leaflet_index}")
                w.operation = "MULTIPLY"
                w.location = (640, hy)
                links.new(en_s, w.inputs[0])
                links.new(wraw.outputs[0], w.inputs[1])

                # contrib = dir_i · w_i (vector, for the weighted_dir sum)
                contrib = new("ShaderNodeVectorMath",
                              name=f"Contrib{slot_label} L{leaflet_index}")
                contrib.operation = "SCALE"
                contrib.location = (820, hy)
                links.new(dir_s, contrib.inputs[0])
                links.new(w.outputs[0], contrib.inputs["Scale"])

                if total_w is None:
                    total_w = w.outputs[0]
                    weighted_dir = contrib.outputs[0]
                    return

                w_acc = new("ShaderNodeMath",
                             name=f"Wacc{slot_label} L{leaflet_index}")
                w_acc.operation = "ADD"
                w_acc.location = (1000, hy)
                links.new(total_w, w_acc.inputs[0])
                links.new(w.outputs[0], w_acc.inputs[1])
                total_w = w_acc.outputs[0]

                d_acc = new("ShaderNodeVectorMath",
                              name=f"Dacc{slot_label} L{leaflet_index}")
                d_acc.operation = "ADD"
                d_acc.location = (1000, hy - 150)
                links.new(weighted_dir, d_acc.inputs[0])
                links.new(contrib.outputs[0], d_acc.inputs[1])
                weighted_dir = d_acc.outputs[0]

            # ---- Hole slots ----------------------------------------------
            for h in range(1, num_holes + 1):
                _add_slot(
                    slot_label=f"H{h}",
                    enabled_sock=get_in(f"Hole {h} Enabled"),
                    obj_sock=get_in(f"Hole {h}"),
                    radius_source=_hole_radius_source,
                    hy=y_pos - 600 - h * 260,
                )

            # ---- Protein force-field slots -------------------------------
            ff_hy_base = y_pos - 600 - (num_holes + 1) * 260
            for f in range(1, num_ffs + 1):
                _add_slot(
                    slot_label=f"FF{f}",
                    enabled_sock=get_in(f"Protein FF {f} Enabled"),
                    obj_sock=get_in(f"Protein FF {f}"),
                    radius_source=get_in(f"Protein FF {f} Radius"),
                    hy=ff_hy_base - f * 260,
                )

            # ---- Combiner: softmax direction + smin penetration --------
            # When the lipid is far outside every pusher, every w_i ≈ 0;
            # total_w is then near-zero but nonzero floats (no NaN from
            # the divide) and ln(total) is very negative, so push_mag
            # clamps to 0 and disp = 0.
            #
            # combined_dir = weighted_dir / total_w
            inv_total = new("ShaderNodeMath",
                            name=f"InvTotal L{leaflet_index}")
            inv_total.operation = "DIVIDE"
            inv_total.inputs[0].default_value = 1.0
            inv_total.location = (1300, y_pos - 300)
            links.new(total_w, inv_total.inputs[1])

            combined_dir = new("ShaderNodeVectorMath",
                                name=f"CombinedDir L{leaflet_index}")
            combined_dir.operation = "SCALE"
            combined_dir.location = (1480, y_pos - 300)
            links.new(weighted_dir, combined_dir.inputs[0])
            links.new(inv_total.outputs[0], combined_dir.inputs["Scale"])

            # smin_sdf = -ln(total_w) / α   (negative inside the combined
            # surface, positive outside, zero on the smooth boundary)
            ln_total = new("ShaderNodeMath",
                            name=f"LnTotal L{leaflet_index}")
            ln_total.operation = "LOGARITHM"
            ln_total.inputs[1].default_value = 2.718281828459045
            ln_total.location = (1300, y_pos - 480)
            links.new(total_w, ln_total.inputs[0])

            neg_ln = new("ShaderNodeMath",
                          name=f"NegLn L{leaflet_index}")
            neg_ln.operation = "MULTIPLY"
            neg_ln.inputs[1].default_value = -1.0
            neg_ln.location = (1480, y_pos - 480)
            links.new(ln_total.outputs[0], neg_ln.inputs[0])

            smin_sdf = new("ShaderNodeMath",
                            name=f"SminSdf L{leaflet_index}")
            smin_sdf.operation = "MULTIPLY"
            smin_sdf.location = (1660, y_pos - 480)
            links.new(neg_ln.outputs[0], smin_sdf.inputs[0])
            links.new(inv_alpha.outputs[0], smin_sdf.inputs[1])

            # push_mag = max(0, -smin_sdf)  (= penetration depth)
            neg_smin = new("ShaderNodeMath",
                            name=f"NegSmin L{leaflet_index}")
            neg_smin.operation = "MULTIPLY"
            neg_smin.inputs[1].default_value = -1.0
            neg_smin.location = (1840, y_pos - 480)
            links.new(smin_sdf.outputs[0], neg_smin.inputs[0])

            push_mag = new("ShaderNodeMath",
                            name=f"PushMag L{leaflet_index}")
            push_mag.operation = "MAXIMUM"
            push_mag.inputs[1].default_value = 0.0
            push_mag.location = (2020, y_pos - 480)
            links.new(neg_smin.outputs[0], push_mag.inputs[0])

            # disp = combined_dir · push_mag
            disp_node = new("ShaderNodeVectorMath",
                             name=f"SdfDisp L{leaflet_index}")
            disp_node.operation = "SCALE"
            disp_node.location = (2200, y_pos - 380)
            links.new(combined_dir.outputs[0], disp_node.inputs[0])
            links.new(push_mag.outputs[0], disp_node.inputs["Scale"])
            return disp_node.outputs[0]

        # ----------------------------------------------------------------
        # SDF pusher (v25): single softmax-weighted smooth-min pass.
        # Skipped entirely when no slots are wired (typical fresh Build).
        # ----------------------------------------------------------------
        if num_holes + num_ffs == 0:
            zero_push = new("FunctionNodeInputVector",
                            name=f"PusherZero {leaflet_index}")
            zero_push.vector = (0.0, 0.0, 0.0)
            zero_push.location = (1300, y_pos - 600)
            pusher_disp = zero_push.outputs[0]
        else:
            pusher_disp = _compute_sdf_displacement(pos.outputs[0])

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

        # Tilt amplitude in radians per nm of master amp. v9: cut from
        # 0.5 → 0.20 — combined with the new "apply tilt as local Euler"
        # path (no more quaternion flips), this keeps the lipid's lean
        # gentle even at max user settings.
        tilt_base = new("ShaderNodeMath", name=f"TiltBase {leaflet_index}")
        tilt_base.operation = "MULTIPLY"
        tilt_base.inputs[1].default_value = 0.20
        tilt_base.location = (200, y_pos - 800)
        links.new(anim_amp.outputs[0], tilt_base.inputs[0])

        # Twist is special — unlike the other channels (translations that
        # naturally read as wiggles), a sine-bounded rotation reads as
        # back-and-forth swinging, not "spinning like a top". v10 makes
        # twist a *continuous* rotation: angle = per-lipid signed rate ×
        # scene time, so each lipid slowly turns in one direction (some
        # CW, some CCW, all at different rates). The rate is wired up
        # below — no twist_base node is needed.

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
        # freqMul / ampMul / phase are all randomised per lipid. Channels
        # can opt into tighter freq/amp ranges (e.g. twist clamps both so
        # rotations stay gentle even at large user-set BobSpeed / Bob Amp).
        def wobble(seed, base_amp_socket, label, lx, ly,
                   fmul_range=(0.55, 1.5), amul_range=(0.4, 1.6)):
            phase = rand_float(seed + 0, 0.0, math.tau, (lx, ly))
            fmul = rand_float(seed + 1, fmul_range[0], fmul_range[1], (lx, ly - 150))
            amul = rand_float(seed + 2, amul_range[0], amul_range[1], (lx, ly - 300))

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
        # Tilt also gets tighter freq/amul ranges than translations — the
        # lipid's lean is more visually disruptive than a sway/bob nudge.
        tiltT_ch = wobble(400, tilt_base.outputs[0], "tiltT", 600, y_pos - 2500,
                          fmul_range=(0.4, 0.9), amul_range=(0.4, 1.0))
        tiltB_ch = wobble(500, tilt_base.outputs[0], "tiltB", 600, y_pos - 3000,
                          fmul_range=(0.4, 0.9), amul_range=(0.4, 1.0))
        # ---- Continuous-rotation twist channel (v10) ---------------------
        # spin_rate = anim_gate × BobSpeed × signed_unit × COEFF
        # angle    = spin_rate × scene_time
        # Result: each lipid steadily turns about its long axis at its own
        # rate (some CW, some CCW) — reads as "lipids spinning like tops"
        # rather than wobbling. Disabling Animate Bob zeroes the rate so
        # every lipid freezes at its static random orientation.
        #
        # The signed unit is built as ±[0.5, 1.0] so no lipid is stuck
        # near-stationary; sign is independent of magnitude, so the spread
        # of rates is half-fast-CW + half-fast-CCW with nothing dead.
        SPIN_RATE_COEFF = 1.0  # rad/sec per unit BobSpeed at full magnitude

        anim_gate = new("GeometryNodeSwitch", name=f"SpinGate {leaflet_index}")
        anim_gate.input_type = "FLOAT"
        anim_gate.location = (600, y_pos - 3500)
        anim_gate.inputs["False"].default_value = 0.0
        anim_gate.inputs["True"].default_value = 1.0
        links.new(get_in("Animate Bob"), anim_gate.inputs[0])

        spin_mag = rand_float(600, 0.5, 1.0, (600, y_pos - 3650))
        spin_sign_src = rand_float(601, -1.0, 1.0, (600, y_pos - 3800))

        spin_sign = new("ShaderNodeMath", name=f"SpinSign {leaflet_index}")
        spin_sign.operation = "SIGN"
        spin_sign.location = (800, y_pos - 3800)
        links.new(spin_sign_src, spin_sign.inputs[0])

        spin_signed = new("ShaderNodeMath", name=f"SpinSigned {leaflet_index}")
        spin_signed.operation = "MULTIPLY"
        spin_signed.location = (1000, y_pos - 3650)
        links.new(spin_mag, spin_signed.inputs[0])
        links.new(spin_sign.outputs[0], spin_signed.inputs[1])

        rate1 = new("ShaderNodeMath", name=f"SpinRate1 {leaflet_index}")
        rate1.operation = "MULTIPLY"
        rate1.location = (800, y_pos - 3500)
        links.new(anim_gate.outputs[0], rate1.inputs[0])
        links.new(get_in("Bob Speed"), rate1.inputs[1])

        rate2 = new("ShaderNodeMath", name=f"SpinRate2 {leaflet_index}")
        rate2.operation = "MULTIPLY"
        rate2.location = (1200, y_pos - 3500)
        links.new(rate1.outputs[0], rate2.inputs[0])
        links.new(spin_signed.outputs[0], rate2.inputs[1])

        rate3 = new("ShaderNodeMath", name=f"SpinRate3 {leaflet_index}")
        rate3.operation = "MULTIPLY"
        rate3.inputs[1].default_value = SPIN_RATE_COEFF
        rate3.location = (1400, y_pos - 3500)
        links.new(rate2.outputs[0], rate3.inputs[0])

        twist_angle = new("ShaderNodeMath", name=f"TwistAngle {leaflet_index}")
        twist_angle.operation = "MULTIPLY"
        twist_angle.location = (1600, y_pos - 3500)
        links.new(rate3.outputs[0], twist_angle.inputs[0])
        links.new(scene_time.outputs["Seconds"], twist_angle.inputs[1])

        twist_ch = twist_angle.outputs[0]

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
        links.new(pusher_disp, motion_sum.inputs[1])

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
        # ORIGINAL APPROACH (v6-v8) — feed a time-varying perturbed normal
        # (normal + tilt vectors) into AlignRotationToVector. That node's
        # AUTO pivot picks the rotation axis based on its input; as the
        # input swings frame-to-frame, the chosen pivot can flip
        # discontinuously, producing single-frame quaternion jumps up to
        # ~180° even when the perturbation itself is bounded. Measured
        # peak step at amp=1.0/speed=1.0 was 177°.
        #
        # NEW APPROACH (v9+) — feed the *un-perturbed* normal (static per
        # surface location) into AlignRotationToVector → a stable rotation
        # whose local frame doesn't change with time. Apply the time-
        # varying tilt as a small Euler rotation around local X / Y in
        # the *same* RotateInstances call that handles the Z twist. Tilt
        # is bounded by the tilt amplitude (no quaternion flips), and the
        # alignment is rebuilt only when the surface deforms.
        if is_upper:
            align_base = normal.outputs[0]
        else:
            neg = new("ShaderNodeVectorMath", name=f"NegN {leaflet_index}")
            neg.operation = "SCALE"
            neg.inputs["Scale"].default_value = -1.0
            neg.location = (2400, y_pos - 250)
            links.new(normal.outputs[0], neg.inputs[0])
            align_base = neg.outputs[0]

        align = new("FunctionNodeAlignRotationToVector",
                   name=f"AlignRot {leaflet_index}")
        align.axis = "Z"
        align.pivot_axis = "AUTO"
        align.location = (3200, y_pos - 150)
        links.new(align_base, align.inputs["Vector"])
        base_rot = align.outputs["Rotation"]

        # ---- Instance lipid on points ------------------------------------
        # ---- Lipid variants: 4 conformations picked randomly per point ---
        # Collection Info with Separate Children outputs each child of the
        # variant collection as its own top-level instance. Instance on
        # Points with Pick Instance + Instance Index then chooses ONE of
        # those variants per lipid point — so the bilayer reads as a real
        # mix of lipid states instead of a repeated cookie-cutter shape.
        ci_lipid = new("GeometryNodeCollectionInfo",
                       name=f"CI Lipid {leaflet_index}")
        ci_lipid.transform_space = "ORIGINAL"
        # Separate Children = each child becomes its own pickable instance.
        # Reset Children = False keeps each variant's own local origin.
        ci_lipid.inputs["Separate Children"].default_value = True
        ci_lipid.inputs["Reset Children"].default_value = False
        ci_lipid.location = (3200, y_pos - 500)
        links.new(get_in("Lipid Collection"), ci_lipid.inputs["Collection"])

        # Per-lipid random integer 0..(VariantCount-1) selecting which
        # variant to use. Seeded by point index so the choice is stable
        # across frames (no flickering) and differs per leaflet (different
        # lipid mosaic on each side).
        rand_pick = new("FunctionNodeRandomValue",
                        name=f"RandPick {leaflet_index}")
        rand_pick.data_type = "INT"
        rand_pick.location = (3200, y_pos - 850)
        # INT Min / Max live at indices 4 / 5 on FunctionNodeRandomValue
        # (the node carries inputs for every data type; only the matching
        # pair is active per data_type).
        rand_pick.inputs[4].default_value = 0
        rand_pick.inputs["Seed"].default_value = 800 + leaflet_index * 10000
        links.new(idx.outputs[0], rand_pick.inputs["ID"])

        # max = VariantCount - 1, driven from the modifier input so the
        # range follows whichever style's collection is plugged in.
        pick_max = new("ShaderNodeMath", name=f"PickMax {leaflet_index}")
        pick_max.operation = "SUBTRACT"
        pick_max.inputs[1].default_value = 1.0
        pick_max.location = (3000, y_pos - 990)
        links.new(get_in("Lipid Variant Count"), pick_max.inputs[0])
        links.new(pick_max.outputs[0], rand_pick.inputs[5])

        iop = new("GeometryNodeInstanceOnPoints", name=f"IoP {leaflet_index}")
        iop.location = (3450, y_pos)
        iop.inputs["Pick Instance"].default_value = True
        links.new(bob_set.outputs["Geometry"], iop.inputs["Points"])
        links.new(ci_lipid.outputs["Instances"], iop.inputs["Instance"])
        # INT output of FunctionNodeRandomValue is at index 2.
        links.new(rand_pick.outputs[2], iop.inputs["Instance Index"])
        links.new(base_rot, iop.inputs["Rotation"])
        # IoP Scale left at its (1, 1, 1) default — lipid size is fixed.

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

        # Euler (tiltT, tiltB, spin) — applied in the INSTANCE's local
        # space (Rotate Instances has Local Space enabled below). Tilt
        # rotates around local X / Y, twist around local Z; for small
        # angles the compose-order doesn't matter, and each channel is
        # bounded by its own sine amplitude — no quaternion flips.
        rot_vec = new("ShaderNodeCombineXYZ", name=f"RotVec {leaflet_index}")
        rot_vec.location = (3850, y_pos - 700)
        links.new(tiltT_ch, rot_vec.inputs[0])
        links.new(tiltB_ch, rot_vec.inputs[1])
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
    tree["pb_active_holes"] = num_holes
    tree["pb_active_ffs"] = num_ffs
    return tree


def _required_slot_counts(scene: Optional[bpy.types.Scene] = None
                           ) -> Tuple[int, int]:
    """Return ``(num_holes, num_ffs)`` the tree must support to cover every
    membrane + scene FF state.

    Holes: the max ``len(pb_mem_holes)`` across all membrane roots — every
    membrane writes to ``Hole 1 .. Hole N``, so capacity is per-membrane.

    FFs: the count of FF-enabled molecules in the scene (each gets one slot).
    Slots are shared across membranes; one enabled protein → one slot used
    on every membrane.
    """
    if scene is None:
        scene = bpy.context.scene if bpy.context else None

    num_holes = 0
    for obj in bpy.data.objects:
        if obj.get("pb_is_membrane", False):
            raw = obj.get("pb_mem_holes", "")
            count = sum(1 for n in (raw.split("|") if raw else []) if n)
            if count > num_holes:
                num_holes = count

    num_ffs = 0
    if scene is not None and hasattr(scene, "molecule_list_items"):
        for item in scene.molecule_list_items:
            if getattr(item, "force_field_enabled", False):
                num_ffs += 1

    return (min(num_holes, MAX_HOLES), min(num_ffs, MAX_PROTEIN_FFS))


def get_or_build_membrane_gn_tree(
        scene: Optional[bpy.types.Scene] = None
) -> bpy.types.GeometryNodeTree:
    """Return the membrane GN tree, building it if missing, version-stale, or
    too small to fit the scene's required slot counts.

    The tree is shared across all membranes; its hole / FF slot count is
    sized to the scene's max demand (see ``_required_slot_counts``). When
    that demand grows past current capacity — or shrinks well below it —
    the tree is rebuilt, every existing membrane modifier is re-linked to
    the fresh tree, and ``reapply_membrane_settings`` re-pushes the per-
    membrane values that a fresh node_group loses.
    """
    required_holes, required_ffs = _required_slot_counts(scene)

    tree = bpy.data.node_groups.get(GN_TREE_NAME)
    if tree is not None:
        version_ok = tree.get("pb_gn_version", 0) == GN_TREE_VERSION
        cur_holes = int(tree.get("pb_active_holes", -1))
        cur_ffs = int(tree.get("pb_active_ffs", -1))
        # Grow on demand; only shrink when current capacity is meaningfully
        # larger than needed (avoids thrash if the user toggles one FF off
        # and back on repeatedly).
        capacity_ok = (cur_holes >= required_holes
                       and cur_ffs >= required_ffs
                       and (cur_holes - required_holes) <= 4
                       and (cur_ffs - required_ffs) <= 4)
        if version_ok and capacity_ok:
            return tree

    was_stale = tree is not None
    tree = _build_membrane_gn_tree(required_holes, required_ffs)
    # Drop the v5 procedural single-lipid asset if it's still around.
    lipid_assets.cleanup_legacy_lipid_asset()

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
# Base mesh (flat / sphere / hemisphere)
# ===========================================================================

# Shape identifiers (kept stable — also used as enum identifiers in the
# props module and as the int values pushed to the GN tree's Shape Mode
# input via SHAPE_MODE_INT).
SHAPE_FLAT = "FLAT"
SHAPE_SPHERE = "SPHERE"
SHAPE_HEMISPHERE = "HEMISPHERE"

SHAPE_MODE_INT = {
    SHAPE_FLAT: 0,
    SHAPE_SPHERE: 1,
    SHAPE_HEMISPHERE: 2,
}


def _build_flat_mesh(width_nm: float, height_nm: float,
                     subdivisions_per_nm: float = 0.5) -> bpy.types.Mesh:
    """Subdivided plane sized in nm. Subdivisions give lattice + distribute
    enough resolution to look smooth when deformed."""
    import bmesh

    width_bu = width_nm / NM_PER_BU
    height_bu = height_nm / NM_PER_BU
    x_subs = max(8, int(width_nm * subdivisions_per_nm))
    y_subs = max(8, int(height_nm * subdivisions_per_nm))

    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=x_subs, y_segments=y_subs, size=1.0)
    sx = width_bu / 2.0
    sy = height_bu / 2.0
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy

    mesh = bpy.data.meshes.new("PB_Membrane_Grid")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _uv_sphere_segments(radius_nm: float) -> tuple:
    """Pick (u_segments, v_segments) for a UV-sphere big enough that
    Poisson-disk distribution gets uniform-ish coverage. Scales with
    radius so larger spheres aren't undersampled. Capped to keep build
    + per-frame GN eval snappy."""
    # ~12 segs per nm of circumference along u; v gets half that (poles).
    circumf_nm = 2 * 3.141592 * radius_nm
    u = max(24, min(128, int(circumf_nm * 1.5)))
    v = max(12, min(64, u // 2))
    # Force even v so the equator is a clean ring (matters for hemisphere cut).
    if v % 2:
        v += 1
    return u, v


def _build_sphere_mesh(radius_nm: float) -> bpy.types.Mesh:
    """Closed UV-sphere centred at origin, radius in nm. Vertex normals
    point outward; Distribute Points on Faces reads those, so 'upper
    leaflet' = outer surface and 'lower leaflet' = inner surface."""
    import bmesh

    radius_bu = radius_nm / NM_PER_BU
    u_segs, v_segs = _uv_sphere_segments(radius_nm)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(
        bm, u_segments=u_segs, v_segments=v_segs, radius=radius_bu,
    )
    mesh = bpy.data.meshes.new("PB_Membrane_Sphere")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _build_hemisphere_mesh(radius_nm: float) -> bpy.types.Mesh:
    """Open-top bowl: lower half of a UV-sphere (z ≤ 0), with the cut
    edge at z = 0 left open (no flat cap) so the user can see inside
    the cell when looking down. Vertex normals on the curved shell
    still point outward, so 'upper leaflet' = outer side of the bowl."""
    import bmesh

    radius_bu = radius_nm / NM_PER_BU
    u_segs, v_segs = _uv_sphere_segments(radius_nm)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(
        bm, u_segments=u_segs, v_segments=v_segs, radius=radius_bu,
    )
    # Drop everything above the equator. v_segs even → the equator is a
    # clean ring at z = 0, so deleting verts with z > tiny_epsilon leaves
    # the bowl with an open ring at z = 0.
    upper = [v for v in bm.verts if v.co.z > 1e-4]
    if upper:
        bmesh.ops.delete(bm, geom=upper, context="VERTS")

    mesh = bpy.data.meshes.new("PB_Membrane_Hemisphere")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_membrane_base_mesh(shape: str, width_nm: float, height_nm: float,
                              radius_nm: float) -> bpy.types.Mesh:
    """Dispatch: build the right base mesh for ``shape``."""
    if shape == SHAPE_SPHERE:
        return _build_sphere_mesh(radius_nm)
    if shape == SHAPE_HEMISPHERE:
        return _build_hemisphere_mesh(radius_nm)
    return _build_flat_mesh(width_nm, height_nm)


def update_base_mesh(mesh: bpy.types.Mesh, shape: str, width_nm: float,
                     height_nm: float, radius_nm: float) -> None:
    """Rebuild the given mesh in place to match ``shape`` + dimensions.

    Used by the resize and shape-change operators so the existing mesh
    datablock stays put (modifier references stay valid).
    """
    new_mesh = build_membrane_base_mesh(shape, width_nm, height_nm, radius_nm)
    bpy_verts = [v.co.copy() for v in new_mesh.vertices]
    bpy_edges = [tuple(e.vertices) for e in new_mesh.edges]
    bpy_faces = [tuple(p.vertices) for p in new_mesh.polygons]
    mesh.clear_geometry()
    mesh.from_pydata(bpy_verts, bpy_edges, bpy_faces)
    mesh.update()
    bpy.data.meshes.remove(new_mesh)


# Backwards-compat shims for callers that still import the old names.
_build_grid_mesh = _build_flat_mesh

def update_grid_mesh(mesh, width_nm, height_nm):
    update_base_mesh(mesh, SHAPE_FLAT, width_nm, height_nm, 0.0)


# ===========================================================================
# Lattice (deformation)
# ===========================================================================

def _lattice_dims_for_shape(shape: str, width_nm: float, height_nm: float,
                             radius_nm: float) -> tuple:
    """Return (scale_xyz_BU, location_xyz_BU) for a lattice that encloses
    the shape exactly. Lattice center is at the geometric center of the
    enclosing box; for hemisphere bowl the box is offset down so it
    bounds z ∈ [-R, 0]."""
    if shape == SHAPE_SPHERE:
        r = radius_nm / NM_PER_BU
        return (2 * r, 2 * r, 2 * r), (0.0, 0.0, 0.0)
    if shape == SHAPE_HEMISPHERE:
        r = radius_nm / NM_PER_BU
        # Bowl occupies z ∈ [-r, 0]; lattice cube centered at z = -r/2.
        return (2 * r, 2 * r, r), (0.0, 0.0, -r / 2.0)
    # Flat: width × height × 1 BU (= 10 nm, plenty of vertical headroom).
    return (width_nm / NM_PER_BU, height_nm / NM_PER_BU, 1.0), (0.0, 0.0, 0.0)


def build_membrane_lattice(shape: str, width_nm: float, height_nm: float,
                            radius_nm: float, resolution: int = 5
                            ) -> bpy.types.Object:
    """Create a Lattice object sized to enclose the membrane base mesh.

    Returns the object (not linked to any collection; caller links it).
    For sphere/hemisphere shapes the lattice is a 3-D box around the
    curved mesh, so the user can deform the sphere into ellipsoids or
    dent the bowl in place.
    """
    lattice_data = bpy.data.lattices.new("PB_Membrane_Lattice")
    obj = bpy.data.objects.new("PB_Membrane_Lattice", lattice_data)

    scale, loc = _lattice_dims_for_shape(shape, width_nm, height_nm, radius_nm)
    obj.scale = scale
    obj.location = loc
    lattice_data.points_u = resolution
    lattice_data.points_v = resolution
    # For shapes with real Z extent (sphere/hemisphere) give a bit more
    # vertical resolution so deformation has somewhere to bend.
    lattice_data.points_w = (resolution if shape != SHAPE_FLAT else 2)
    lattice_data.interpolation_type_u = "KEY_BSPLINE"
    lattice_data.interpolation_type_v = "KEY_BSPLINE"
    lattice_data.interpolation_type_w = "KEY_BSPLINE"
    return obj


def update_lattice_for_shape(lattice_obj: bpy.types.Object, shape: str,
                              width_nm: float, height_nm: float,
                              radius_nm: float) -> None:
    """Resize / reposition an existing lattice in place to fit ``shape``.

    Lattice points get reset to their rest pose (any prior deformation is
    discarded — destructive shape switching by design).
    """
    scale, loc = _lattice_dims_for_shape(shape, width_nm, height_nm, radius_nm)
    lattice_obj.scale = scale
    lattice_obj.location = loc
    for p in lattice_obj.data.points:
        p.co_deform = tuple(p.co)
