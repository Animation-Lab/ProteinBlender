"""Bending controls for DNA/RNA molecules.

Implements a Bezier-curve-based bend modifier with discrete *control nodes*:

  * `dna_add_bend`         – shifts the molecule's pivot to its bottom (so all
    vertices live in +Z object-space), creates a Bezier curve along the
    helix axis, and attaches a Blender Curve modifier on the DNA mesh so
    the helix follows the curve in real time.
  * `dna_edit_bend`        – places N Empty objects evenly along the curve's
    arc length and hooks each one to a Bezier point via a Hook modifier on
    the curve. Selects all of them so the user can grab them with Blender's
    standard transform gizmo (click / shift-click for multi-select).
  * `dna_set_bend_resolution` – changes N (number of control nodes),
    resampling the existing curve shape so the user's bend is preserved.
  * `dna_finish_bend_edit` – deselects nodes and re-activates the parent
    DNA. Empties stay in the scene so the bend persists.
  * `dna_remove_bend`      – removes the modifier, deletes the curve and
    all bend nodes, restores the (vertically) flat helix.
  * `dna_bend_preset`      – overwrites the curve's spline with one of a
    few initial shapes (Straight / Arc / S-curve / Loop). Recreates the
    nodes so they line up with the new spline.

The DNA stores:
  * `pb_bend_curve_name`   – the bend Bezier curve object's name.
  * `pb_bend_node_names`   – JSON list of the control-node Empty names.
"""

import json

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty
from bpy.types import Operator
from mathutils import Vector
from mathutils.geometry import interpolate_bezier


# Custom property keys on the DNA object
BEND_CURVE_PROP = "pb_bend_curve_name"
BEND_NODES_PROP = "pb_bend_node_names"
PIVOT_SHIFTED_PROP = "pb_bend_pivot_shifted"

# Modifier names
_CURVE_MOD = "DNA Bend"
_HOOK_PREFIX = "Hook_BP"

# Default visible bevel on the curve
_CURVE_BEVEL = 0.005

# Empty (control-node) display
_NODE_DISPLAY_TYPE = "SPHERE"
_NODE_DISPLAY_SIZE = 0.04

# Resolution range for the control-node count
RES_MIN = 2
RES_MAX = 12
RES_DEFAULT = 3


# ---------------------------------------------------------------------------
# Mesh pivot helpers
# ---------------------------------------------------------------------------


def _mesh_z_extent(obj):
    mesh = obj.data
    if not mesh or not mesh.vertices:
        return None
    z_vals = [v.co.z for v in mesh.vertices]
    return min(z_vals), max(z_vals)


def shift_origin_to_bottom(obj) -> float:
    """Move mesh data so its lowest atom sits at object-space z = 0.
    Compensates the object's location so visual position is unchanged."""
    extent = _mesh_z_extent(obj)
    if extent is None:
        return 0.0
    z_min, _ = extent
    if abs(z_min) < 1e-6:
        return 0.0

    mesh = obj.data
    for v in mesh.vertices:
        v.co.z -= z_min
    mesh.update()

    world_offset = obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, z_min))
    obj.location = obj.location + world_offset
    obj[PIVOT_SHIFTED_PROP] = True
    return z_min


def restore_origin_to_centre(obj) -> None:
    extent = _mesh_z_extent(obj)
    if extent is None:
        return
    z_min, z_max = extent
    z_mid = 0.5 * (z_min + z_max)
    if abs(z_mid) < 1e-6:
        obj.pop(PIVOT_SHIFTED_PROP, None)
        return

    mesh = obj.data
    for v in mesh.vertices:
        v.co.z -= z_mid
    mesh.update()

    world_offset = obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, z_mid))
    obj.location = obj.location + world_offset
    obj.pop(PIVOT_SHIFTED_PROP, None)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_bend_curve(dna_obj):
    name = dna_obj.get(BEND_CURVE_PROP)
    if not name:
        return None
    return bpy.data.objects.get(name)


def get_bend_nodes(dna_obj):
    """Return list of control-node Empty objects (in order). Filters dangling
    references."""
    raw = dna_obj.get(BEND_NODES_PROP)
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except Exception:
        return []
    return [bpy.data.objects[n] for n in names if n in bpy.data.objects]


def dna_has_keyframes(dna_obj):
    """True iff the DNA mesh, its bend curve, or any of its bend control nodes
    has at least one transform F-curve key.

    Used by the Builders panel to lock structural changes (add/remove bend,
    change node count) once the strand is animated — those operations rebuild
    the rig from scratch, which orphans the F-curves keyed against the old
    nodes/curve/origin and silently corrupts the animation.
    """
    if dna_obj is None:
        return False
    # Imported here to avoid a circular dependency at module import time
    # (utils.animation can be imported by code that imports bender).
    from ..utils.animation import get_fcurves_from_action

    objs = [dna_obj]
    curve = get_bend_curve(dna_obj)
    if curve is not None:
        objs.append(curve)
    objs.extend(get_bend_nodes(dna_obj))
    for o in objs:
        ad = o.animation_data
        if not ad or not ad.action:
            continue
        for fc in get_fcurves_from_action(ad.action, ad):
            if len(fc.keyframe_points) > 0:
                return True
    return False


def get_dna_for_curve(curve_obj):
    """Reverse lookup: which DNA molecule owns this bend curve?"""
    if curve_obj is None:
        return None
    for o in bpy.data.objects:
        if (o.get("pb_is_nucleic_acid", False)
                and o.get(BEND_CURVE_PROP) == curve_obj.name):
            return o
    return None


def get_dna_for_node(node_obj):
    """Reverse lookup: which DNA molecule owns this bend node?"""
    if node_obj is None:
        return None
    for o in bpy.data.objects:
        if not o.get("pb_is_nucleic_acid", False):
            continue
        raw = o.get(BEND_NODES_PROP)
        if not raw:
            continue
        try:
            names = json.loads(raw)
        except Exception:
            continue
        if node_obj.name in names:
            return o
    return None


def _resolve_dna(obj):
    """Return the DNA molecule for *obj*: either *obj* itself if it's a DNA
    mesh, or the DNA that owns *obj* as a bend node. Returns None otherwise.

    Operators that accept either the DNA mesh or one of its bend control
    nodes as the active object use this to find the underlying molecule.
    """
    if obj is not None and obj.get("pb_is_nucleic_acid", False):
        return obj
    return get_dna_for_node(obj)


# ---------------------------------------------------------------------------
# Curve construction & resampling
# ---------------------------------------------------------------------------


def _set_bezier_points(spline, points, handle_type="ALIGNED"):
    spline.bezier_points.add(len(points) - 1)
    for i, (co, hl, hr) in enumerate(points):
        bp = spline.bezier_points[i]
        bp.co = Vector(co)
        bp.handle_left = Vector(hl)
        bp.handle_right = Vector(hr)
        bp.handle_left_type = handle_type
        bp.handle_right_type = handle_type


def _straight_points(height, n=3):
    pts = []
    handle = height / max(n - 1, 1) * 0.4
    for i in range(n):
        t = i / max(n - 1, 1)
        z = t * height
        pts.append(((0.0, 0.0, z),
                    (0.0, 0.0, z - handle),
                    (0.0, 0.0, z + handle)))
    return pts


def _create_bend_curve(name, dna_obj, height, n_points=RES_DEFAULT):
    curve_data = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = _CURVE_BEVEL
    curve_data.resolution_u = 12

    spline = curve_data.splines.new("BEZIER")
    _set_bezier_points(spline, _straight_points(height, n=n_points))

    curve_obj = bpy.data.objects.new(name, curve_data)
    curve_obj.location = dna_obj.location.copy()
    curve_obj.rotation_mode = dna_obj.rotation_mode
    curve_obj.rotation_euler = dna_obj.rotation_euler.copy()

    # Curve is purely a visual guide: the user shouldn't be able to grab it
    # in the viewport and pull it away from the DNA. Hide it from selection
    # but leave it visible so the bend path stays apparent. It's also
    # excluded from final renders — the panel surfaces this via the
    # "Show Bend Curve" toggle so the user knows they can hide it without
    # affecting the saved image.
    curve_obj.hide_select = True
    curve_obj.hide_render = True

    coll = (dna_obj.users_collection[0]
            if dna_obj.users_collection else bpy.context.collection)
    coll.objects.link(curve_obj)

    # Parent the curve to the DNA so moving the DNA moves the whole rig.
    # Nodes are parented to the curve (set up in _create_bend_nodes), giving
    # the hierarchy: DNA → Curve → Nodes.
    # Flush the depsgraph first — shift_origin_to_bottom may have changed
    # dna_obj.location without matrix_world being recalculated yet.
    bpy.context.view_layer.update()
    curve_obj.parent = dna_obj
    curve_obj.matrix_parent_inverse = dna_obj.matrix_world.inverted()

    return curve_obj


def _add_curve_modifier(dna_obj, curve_obj):
    existing = dna_obj.modifiers.get(_CURVE_MOD)
    if existing is not None:
        dna_obj.modifiers.remove(existing)
    mod = dna_obj.modifiers.new(_CURVE_MOD, "CURVE")
    mod.object = curve_obj
    mod.deform_axis = "POS_Z"
    return mod


def _set_aligned_handles_along_path(spline, factor=0.3):
    """Set each bezier point's left/right handles so they're tangent to the
    smooth path through neighboring control points (Catmull-Rom-style).
    Uses ALIGNED handle types so a hook moving all 3 sub-vertices keeps the
    point's tangent consistent.
    """
    bps = spline.bezier_points
    n = len(bps)
    if n < 2:
        return

    for i in range(n):
        if i == 0:
            tangent = bps[1].co - bps[0].co
            seg_len = tangent.length
        elif i == n - 1:
            tangent = bps[n - 1].co - bps[n - 2].co
            seg_len = tangent.length
        else:
            tangent = bps[i + 1].co - bps[i - 1].co
            seg_len = (
                (bps[i].co - bps[i - 1].co).length
                + (bps[i + 1].co - bps[i].co).length
            ) * 0.5

        if tangent.length < 1e-9:
            tangent = Vector((0.0, 0.0, 1.0))

        offset = tangent.normalized() * (seg_len * factor)
        bps[i].handle_left = bps[i].co - offset
        bps[i].handle_right = bps[i].co + offset
        bps[i].handle_left_type = "ALIGNED"
        bps[i].handle_right_type = "ALIGNED"


def _resample_curve_arc_length(curve_obj, n_points):
    """Resample the first spline to n_points evenly distributed by arc
    length. Tries to preserve the existing shape. Replaces the spline
    in place."""
    n_points = max(RES_MIN, min(RES_MAX, n_points))
    curve_data = curve_obj.data
    if not curve_data.splines:
        return

    old_spline = curve_data.splines[0]
    if old_spline.type != "BEZIER" or len(old_spline.bezier_points) < 2:
        return

    # No-op if the count already matches — preserves the curve exactly.
    if len(old_spline.bezier_points) == n_points:
        return

    SAMPLES_PER_SEG = 32
    polyline = []
    bps = old_spline.bezier_points
    for i in range(len(bps) - 1):
        a = bps[i]
        b = bps[i + 1]
        pts = interpolate_bezier(
            a.co, a.handle_right, b.handle_left, b.co, SAMPLES_PER_SEG,
        )
        if i < len(bps) - 2:
            polyline.extend(pts[:-1])
        else:
            polyline.extend(pts)

    if len(polyline) < 2:
        return

    lens = [0.0]
    for i in range(1, len(polyline)):
        lens.append(lens[-1] + (polyline[i] - polyline[i - 1]).length)
    total = lens[-1]
    if total <= 0:
        return

    # Sample n_points evenly by arc length
    new_positions = []
    for j in range(n_points):
        target = (j / (n_points - 1)) * total
        idx = 0
        while idx < len(lens) - 1 and lens[idx + 1] < target:
            idx += 1
        if idx >= len(lens) - 1:
            new_positions.append(polyline[-1].copy())
        else:
            seg = lens[idx + 1] - lens[idx]
            t = (target - lens[idx]) / seg if seg > 0 else 0.0
            new_positions.append(polyline[idx].lerp(polyline[idx + 1], t))

    # Replace spline with a new one and explicitly set CO + smooth handles.
    # (Just changing handle_type to AUTO/ALIGNED on a freshly-added point
    # leaves the handle COORDINATES at their default (0,0,0) — that makes
    # every handle vector point toward the curve-local origin, sagging the
    # curve and shifting any mesh deformed along it.)
    curve_data.splines.remove(old_spline)
    new_spline = curve_data.splines.new("BEZIER")
    new_spline.bezier_points.add(n_points - 1)
    for i, pos in enumerate(new_positions):
        new_spline.bezier_points[i].co = Vector(pos)

    _set_aligned_handles_along_path(new_spline)

    curve_data.update_tag()


# ---------------------------------------------------------------------------
# Control-node (Empty) management
# ---------------------------------------------------------------------------


def _remove_hook_modifiers(curve_obj):
    if curve_obj is None:
        return
    for mod in list(curve_obj.modifiers):
        if mod.type == "HOOK" and mod.name.startswith(_HOOK_PREFIX):
            curve_obj.modifiers.remove(mod)


def _remove_bend_nodes(dna_obj):
    """Delete all control-node empties referenced by the DNA, plus their
    hook modifiers on the bend curve."""
    nodes = get_bend_nodes(dna_obj)
    for n in nodes:
        try:
            bpy.data.objects.remove(n, do_unlink=True)
        except Exception:
            pass
    curve = get_bend_curve(dna_obj)
    _remove_hook_modifiers(curve)
    dna_obj.pop(BEND_NODES_PROP, None)


def _create_bend_nodes(dna_obj, curve_obj, n_points):
    """Create n_points control-node empties along the curve, hook each one
    to the corresponding bezier point. Assumes the curve already has
    n_points bezier points (call _resample_curve_arc_length first)."""
    import mathutils

    coll = (dna_obj.users_collection[0]
            if dna_obj.users_collection else bpy.context.collection)

    spline = curve_obj.data.splines[0]
    if len(spline.bezier_points) != n_points:
        # Caller didn't resample first
        _resample_curve_arc_length(curve_obj, n_points)
        spline = curve_obj.data.splines[0]

    # Make sure the curve's own matrix_world is current before we read it
    # (it may have been modified by add_bend / shift_origin_to_bottom and
    # not yet picked up by the depsgraph).
    bpy.context.view_layer.update()
    curve_world = curve_obj.matrix_world.copy()

    # First pass: create + link all empties at their target world positions.
    # Each empty is parented to the curve so that when Move Strand
    # translates the curve, the nodes follow automatically. This avoids
    # double-translation issues and keeps hook deformation consistent.
    created = []  # list of (i, empty, bp)
    names = []
    for i in range(n_points):
        bp = spline.bezier_points[i]
        bp_world = curve_world @ bp.co

        # User-facing name: "{dna} Bend Node N" (1-based, spaced).
        # The previous "_BendNode00" scheme made it impossible to tell
        # which node was which in the Keyframe Create dialog and the
        # outliner. Tester report (Janet): "Maybe naming something like
        # 'bend node 1' or something would be helpful."
        empty = bpy.data.objects.new(
            f"{dna_obj.name} Bend Node {i + 1}", None,
        )
        empty.empty_display_type = _NODE_DISPLAY_TYPE
        empty.empty_display_size = _NODE_DISPLAY_SIZE
        empty.location = bp_world
        empty.show_in_front = True
        coll.objects.link(empty)

        # Parent the empty to the curve so it follows the curve when the
        # whole rig is translated (Move Strand selects DNA + curve).
        empty.parent = curve_obj
        empty.matrix_parent_inverse = curve_world.inverted()

        created.append((i, empty, bp))
        names.append(empty.name)

    # Force a view-layer update so each new empty's matrix_world reflects
    # the location we just set. Without this, matrix_world is still the
    # identity from when the data-block was created, so hook_reset below
    # sees stale matrices.
    bpy.context.view_layer.update()

    # Second pass: build the hook modifiers.
    hook_names = []
    for i, empty, bp in created:
        mod = curve_obj.modifiers.new(f"{_HOOK_PREFIX}{i:02d}", "HOOK")
        mod.object = empty
        mod.vertex_indices_set([3 * i + 0, 3 * i + 1, 3 * i + 2])
        mod.center = bp.co.copy()
        # Pin strength + disable falloff so vertex_indices is the only
        # selector (full effect at any distance).
        mod.strength = 1.0
        mod.falloff_radius = 0.0
        mod.falloff_type = "NONE"
        # Pre-set matrix_inverse to a pure translation as a safety net;
        # the canonical hook_reset() below will overwrite it correctly.
        mod.matrix_inverse = mathutils.Matrix.Translation(-empty.location)
        hook_names.append(mod.name)

    # Use Blender's canonical hook_reset operator to recompute
    # matrix_inverse for each hook from the current empty/curve transforms.
    # This is the only fully-reliable way to get zero initial deformation —
    # the operator runs the same C-side code that bpy.ops.object.hook_assign
    # uses, sidestepping any depsgraph-timing issues with reading
    # empty.matrix_world from Python.
    prev_active = bpy.context.view_layer.objects.active
    prev_selected = list(bpy.context.selected_objects)
    prev_mode = bpy.context.mode

    try:
        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        curve_obj.select_set(True)
        bpy.context.view_layer.objects.active = curve_obj
        bpy.ops.object.mode_set(mode="EDIT")
        for hname in hook_names:
            try:
                bpy.ops.object.hook_reset(modifier=hname)
            except Exception:
                pass
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        # Restore the previous selection state.
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for o in prev_selected:
            try:
                if o.name in bpy.data.objects:
                    o.select_set(True)
            except Exception:
                pass
        try:
            if prev_active is not None and prev_active.name in bpy.data.objects:
                bpy.context.view_layer.objects.active = prev_active
        except Exception:
            pass

    bpy.context.view_layer.update()

    dna_obj[BEND_NODES_PROP] = json.dumps(names)


def bake_evaluated_curve_shape(curve_obj):
    """Write the user's hook-deformed bend back into the curve's static
    ``bezier_points`` so subsequent operations (arc-length resampling,
    rebuild-then-recreate flows) see the deformed shape instead of the
    original straight line.

    **Why not just read ``evaluated_get(deps).data.splines[0].bezier_points``?**
    Hook modifiers on a *curve* deform the final rendered geometry only —
    they never write back to ``bp.co``. The evaluated curve datablock
    exposes the SAME bezier points as the source; the hook delta lives in
    the modifier stack, not in the data. So the obvious "copy eval bp.co
    back to orig bp.co" approach is a silent no-op.

    Instead we read each hook empty's current ``matrix_world.translation``,
    transform into the curve's local space, and snap the corresponding
    bezier point there. Handles are shifted by the same delta so the
    curve's local tangent is preserved (otherwise the handles would point
    at where the point USED to be, kinking the curve).

    Bug fixed (tester report, Janet, Windows): adding a 4th bend node
    after one of the original 3 had been moved made the DNA snap back to
    origin. Root cause: this function silently no-op'd, so the rebuild
    saw a straight curve, resampled it to a straight 4-point curve, and
    the DNA followed the straight curve back to its original axis.
    """
    if curve_obj is None or curve_obj.data is None:
        return
    splines = curve_obj.data.splines
    if not splines:
        return
    spline = splines[0]
    if spline.type != "BEZIER" or not spline.bezier_points:
        return

    # Map hook modifiers → bezier-point index. The hook setup in
    # _create_bend_nodes uses vertex_indices_set([3*i, 3*i+1, 3*i+2]) per
    # bezier point i, so the first index // 3 recovers the point index.
    bp_to_empty = {}
    for m in curve_obj.modifiers:
        if m.type != "HOOK" or m.object is None:
            continue
        vi = list(m.vertex_indices)
        if not vi:
            continue
        bp_index = vi[0] // 3
        if 0 <= bp_index < len(spline.bezier_points):
            bp_to_empty[bp_index] = m.object

    if not bp_to_empty:
        return

    # Make sure each empty's matrix_world is current — the user might
    # have moved a node moments before this call without a viewport tick.
    bpy.context.view_layer.update()

    inv_curve_world = curve_obj.matrix_world.inverted()
    for bp_index, empty in bp_to_empty.items():
        bp = spline.bezier_points[bp_index]
        target_local = inv_curve_world @ empty.matrix_world.translation
        delta = target_local - bp.co
        if delta.length_squared < 1e-12:
            continue
        bp.co = target_local
        # Shift handles by the same delta so local tangents are preserved.
        # (Resetting handles to AUTO is left to the caller — the rebuild
        # path calls _set_aligned_handles_along_path after resampling.)
        bp.handle_left = bp.handle_left + delta
        bp.handle_right = bp.handle_right + delta

    curve_obj.data.update_tag()


def _rebuild_bend_nodes(dna_obj, n_points):
    """Tear down & recreate the bend node system at a new resolution while
    preserving the curve's current shape via arc-length resampling."""
    curve_obj = get_bend_curve(dna_obj)
    if curve_obj is None:
        return

    # Bake the user's hook-deformed shape into the underlying curve so the
    # subsequent resample sees their bend, not the straight starting line.
    bake_evaluated_curve_shape(curve_obj)

    # Remove old nodes & hooks
    _remove_bend_nodes(dna_obj)

    # Resample curve to new N points, then attach new nodes
    _resample_curve_arc_length(curve_obj, n_points)
    _create_bend_nodes(dna_obj, curve_obj, n_points)


# ---------------------------------------------------------------------------
# Public API used by other modules (e.g. update_dna)
# ---------------------------------------------------------------------------


def reattach_after_rebuild(new_dna_obj, curve_obj):
    """Re-establish the bend after `update_dna` rebuilds the DNA mesh.

    The curve survives the rebuild because we held a separate reference
    to it before deleting the old molecule. The control-node Empties do
    NOT — they were linked to the old DNA's collection, which was purged
    with the molecule, and their hook modifiers on the curve are now
    pointing at deleted data. We rebuild them from the curve's bezier
    points (the canonical source of the bend shape).
    """
    if curve_obj is None:
        return
    shift_origin_to_bottom(new_dna_obj)
    _add_curve_modifier(new_dna_obj, curve_obj)
    new_dna_obj[BEND_CURVE_PROP] = curve_obj.name

    # Re-parent the curve to the new DNA object AND snap its local transform
    # to identity. This makes the curve sit exactly at the DNA's pivot —
    # which, after shift_origin_to_bottom, is the bottom of the strand.
    # Without this, the curve retains its OLD world position and floats
    # below the new (longer) strand once the bbox-centre correction shifts
    # the new DNA into place.
    import mathutils
    curve_obj.parent = new_dna_obj
    curve_obj.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    curve_obj.location = (0.0, 0.0, 0.0)
    curve_obj.rotation_euler = (0.0, 0.0, 0.0)
    curve_obj.scale = (1.0, 1.0, 1.0)

    splines = curve_obj.data.splines if curve_obj.data else None
    if not splines or len(splines) == 0:
        return
    spline = splines[0]
    n_points = len(spline.bezier_points)
    if n_points < RES_MIN:
        return

    # Resize the curve along Z to span the new DNA's height. The curve's
    # bezier points were sized to the OLD DNA's height; without this
    # rescale, a longer/shorter sequence leaves the curve floating off
    # the strand. X/Y deformation (the user's bend) is preserved.
    #
    # We rescale only the *control point* Z values, then regenerate the
    # bezier handles from scratch via _set_aligned_handles_along_path —
    # blindly rescaling the existing handles can leave them overshooting
    # adjacent control points, which makes the Curve modifier compress or
    # loop the strand even though the control points are correctly placed.
    extent = _mesh_z_extent(new_dna_obj)
    if extent is not None:
        new_height = extent[1] - extent[0]
        old_z_max = max(bp.co.z for bp in spline.bezier_points)
        if old_z_max > 1e-6 and new_height > 1e-6 and abs(new_height - old_z_max) > 1e-4:
            scale_z = new_height / old_z_max
            for bp in spline.bezier_points:
                bp.co.z *= scale_z
            _set_aligned_handles_along_path(spline)
            curve_obj.data.update_tag()

    # Sweep up any stale node Empties still parented to the curve. These
    # may exist as orphans (their old collection was deleted) or have been
    # re-homed to another collection — either way they're broken handles.
    # Match both the old "_BendNode00" naming and the new "Bend Node 1"
    # so legacy .blend files still get cleaned up.
    for ob in list(bpy.data.objects):
        if (ob.type == "EMPTY"
                and ob.parent is curve_obj
                and ("_BendNode" in ob.name or "Bend Node " in ob.name)):
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except Exception:
                pass

    # Drop the curve's now-stale hook modifiers; _create_bend_nodes will
    # rebuild a fresh set keyed to the new Empties.
    _remove_hook_modifiers(curve_obj)

    _create_bend_nodes(new_dna_obj, curve_obj, n_points)


def cleanup_bend_curve(dna_obj):
    """Full teardown: remove modifier, delete nodes, delete curve."""
    _remove_bend_nodes(dna_obj)

    name = dna_obj.get(BEND_CURVE_PROP)
    if name:
        mod = dna_obj.modifiers.get(_CURVE_MOD)
        if mod is not None:
            dna_obj.modifiers.remove(mod)
        curve_obj = bpy.data.objects.get(name)
        if curve_obj is not None:
            curve_data = curve_obj.data
            try:
                bpy.data.objects.remove(curve_obj, do_unlink=True)
            except Exception:
                pass
            if curve_data is not None and curve_data.users == 0:
                try:
                    bpy.data.curves.remove(curve_data)
                except Exception:
                    pass
        dna_obj.pop(BEND_CURVE_PROP, None)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------


class PROTEINBLENDER_OT_dna_add_bend(Operator):
    """Add a Bezier curve bend control to the selected DNA/RNA molecule."""

    bl_idname = "proteinblender.dna_add_bend"
    bl_label = "Add Bend Control"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None
                and obj.get("pb_is_nucleic_acid", False)
                and not obj.get(BEND_CURVE_PROP))

    def execute(self, context):
        dna = context.active_object
        if dna is None or not dna.get("pb_is_nucleic_acid", False):
            self.report({"ERROR"}, "No DNA/RNA molecule selected.")
            return {"CANCELLED"}

        # Sweep up any orphaned bend curves/nodes left behind by previously
        # deleted DNA molecules — safe to do here at well-defined moments
        # (not from a depsgraph handler, which would re-enter and freeze).
        cleanup_orphaned_bend_objects()

        shift_origin_to_bottom(dna)

        extent = _mesh_z_extent(dna)
        if extent is None:
            self.report({"ERROR"}, "DNA mesh has no vertices.")
            return {"CANCELLED"}
        _, z_max = extent
        height = z_max
        if height <= 0:
            self.report({"ERROR"}, "DNA helix has zero height — nothing to bend.")
            return {"CANCELLED"}

        curve_obj = _create_bend_curve(
            f"{dna.name}_BendCurve", dna, height, n_points=RES_DEFAULT,
        )
        _add_curve_modifier(dna, curve_obj)
        dna[BEND_CURVE_PROP] = curve_obj.name

        # Place the control nodes immediately — there's no useful state
        # between "curve added" and "nodes placed", so combining the two
        # makes the workflow one click instead of two.
        _create_bend_nodes(dna, curve_obj, RES_DEFAULT)
        nodes = get_bend_nodes(dna)

        # Select the nodes so the user can start dragging immediately.
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for n in nodes:
            n.select_set(True)
        if nodes:
            context.view_layer.objects.active = nodes[0]

        self.report(
            {"INFO"},
            "Bend rig added — drag the control nodes to bend the strand.",
        )
        return {"FINISHED"}


class PROTEINBLENDER_OT_dna_edit_bend(Operator):
    """Place / select control nodes along the bend curve so you can drag
    them with the standard transform gizmo. Click to select, Shift-click
    to multi-select."""

    bl_idname = "proteinblender.dna_edit_bend"
    bl_label = "Edit Bend"
    bl_options = {"REGISTER", "UNDO"}

    n_points: IntProperty(
        name="Nodes",
        description="Number of control nodes (only used when first creating them)",
        default=RES_DEFAULT, min=RES_MIN, max=RES_MAX,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False) and obj.get(BEND_CURVE_PROP):
            return True
        # Allow when a control node is active (re-select after just placing).
        if get_dna_for_node(obj) is not None:
            return True
        return False

    def execute(self, context):
        dna = _resolve_dna(context.active_object)
        if dna is None:
            self.report({"ERROR"}, "Could not resolve DNA molecule.")
            return {"CANCELLED"}
        curve_obj = get_bend_curve(dna)
        if curve_obj is None:
            self.report({"ERROR"}, "Bend curve not found.")
            return {"CANCELLED"}

        # Ensure Object Mode (subsequent ops need it)
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        # Create nodes if they don't exist yet
        existing_nodes = get_bend_nodes(dna)
        if not existing_nodes:
            _resample_curve_arc_length(curve_obj, self.n_points)
            _create_bend_nodes(dna, curve_obj, self.n_points)
            existing_nodes = get_bend_nodes(dna)

        # Select all nodes (active = first one, so the gizmo anchors there).
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for n in existing_nodes:
            n.select_set(True)
        if existing_nodes:
            context.view_layer.objects.active = existing_nodes[0]

        return {"FINISHED"}


class PROTEINBLENDER_OT_dna_set_bend_resolution(Operator):
    """Change the number of control nodes along the bend curve. Resamples
    the curve so the user's bend is preserved as faithfully as possible."""

    bl_idname = "proteinblender.dna_set_bend_resolution"
    bl_label = "Set Bend Resolution"
    bl_options = {"REGISTER", "UNDO"}

    n_points: IntProperty(
        name="Nodes",
        description="Number of control nodes",
        default=RES_DEFAULT, min=RES_MIN, max=RES_MAX,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False) and obj.get(BEND_CURVE_PROP):
            return True
        # Allow when a control node is active
        if get_dna_for_node(obj) is not None:
            return True
        return False

    def execute(self, context):
        dna = _resolve_dna(context.active_object)
        if dna is None:
            return {"CANCELLED"}

        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        _rebuild_bend_nodes(dna, self.n_points)

        # Re-select the new nodes so the user can keep editing.
        nodes = get_bend_nodes(dna)
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for n in nodes:
            n.select_set(True)
        if nodes:
            context.view_layer.objects.active = nodes[0]
        return {"FINISHED"}


class PROTEINBLENDER_OT_dna_finish_bend_edit(Operator):
    """Deselect bend nodes and re-activate the parent DNA molecule."""

    bl_idname = "proteinblender.dna_finish_bend_edit"
    bl_label = "Done Editing Bend"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        # Active obj is a bend node, OR any selected obj is a bend node.
        if get_dna_for_node(obj) is not None:
            return True
        for o in context.selected_objects:
            if get_dna_for_node(o) is not None:
                return True
        return False

    def execute(self, context):
        dna = get_dna_for_node(context.active_object)
        if dna is None:
            for o in context.selected_objects:
                dna = get_dna_for_node(o)
                if dna is not None:
                    break
        if dna is None:
            return {"CANCELLED"}

        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass


        dna.select_set(True)
        context.view_layer.objects.active = dna
        return {"FINISHED"}


class PROTEINBLENDER_OT_dna_remove_bend(Operator):
    """Remove the bend modifier and delete the bend curve and all nodes."""

    bl_idname = "proteinblender.dna_remove_bend"
    bl_label = "Remove Bend"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False) and obj.get(BEND_CURVE_PROP):
            return True
        if get_dna_for_node(obj) is not None:
            return True
        return False

    def execute(self, context):
        dna = _resolve_dna(context.active_object)
        if dna is None:
            return {"CANCELLED"}

        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        cleanup_bend_curve(dna)
        restore_origin_to_centre(dna)

        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        dna.select_set(True)
        context.view_layer.objects.active = dna

        self.report({"INFO"}, "Bend removed.")
        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_dna_add_bend,
    PROTEINBLENDER_OT_dna_edit_bend,
    PROTEINBLENDER_OT_dna_set_bend_resolution,
    PROTEINBLENDER_OT_dna_finish_bend_edit,
    PROTEINBLENDER_OT_dna_remove_bend,
)


# ---------------------------------------------------------------------------
# Orphan cleanup
# ---------------------------------------------------------------------------
#
# When the user deletes a DNA molecule the bend curve and bend-node empties
# can survive as orphans. We don't use a depsgraph handler for cleanup
# (that triggers a re-entrancy loop because removing objects from inside a
# depsgraph_update_post callback mutates the depsgraph). Instead, cleanup
# runs at deterministic moments:
#   * file load (load_post)
#   * just before creating a new bend
#   * the user's manual "Add Bend Control" / "Place Control Nodes" actions
# ---------------------------------------------------------------------------


def cleanup_orphaned_bend_objects():
    """Delete bend curves and bend nodes whose owning DNA molecule has been
    removed from `bpy.data.objects`. Safe to call from operators."""
    live_curves = set()
    live_nodes = set()
    for obj in bpy.data.objects:
        if not obj.get("pb_is_nucleic_acid", False):
            continue
        cn = obj.get(BEND_CURVE_PROP)
        if cn:
            live_curves.add(cn)
        raw = obj.get(BEND_NODES_PROP)
        if raw:
            try:
                for n in json.loads(raw):
                    live_nodes.add(n)
            except Exception:
                pass

    to_remove = []
    for o in bpy.data.objects:
        if o.type == "CURVE" and o.name.endswith("_BendCurve"):
            if o.name not in live_curves:
                to_remove.append(o)
        elif o.type == "EMPTY" and ("_BendNode" in o.name or "Bend Node " in o.name):
            if o.name not in live_nodes:
                to_remove.append(o)

    for o in to_remove:
        data = o.data
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            continue
        if data is not None and getattr(data, "users", 1) == 0:
            try:
                if isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
            except Exception:
                pass


# Tracks the set of DNA-molecule names seen on the previous depsgraph
# update tick. When a name disappears (i.e., the DNA was deleted), we
# schedule a deferred cleanup via a timer to avoid mutating the depsgraph
# from inside its own update callback (which would re-enter and freeze).
_last_dna_names = None
_cleanup_pending = False


def _deferred_cleanup():
    global _cleanup_pending
    _cleanup_pending = False
    try:
        cleanup_orphaned_bend_objects()
    except Exception:
        pass
    return None  # don't re-fire


@persistent
def _on_depsgraph_update(_scene, _depsgraph):
    global _last_dna_names, _cleanup_pending
    try:
        current = {
            o.name for o in bpy.data.objects
            if o.get("pb_is_nucleic_acid", False)
        }
    except Exception:
        return

    if _last_dna_names is not None:
        deleted = _last_dna_names - current
        if deleted and not _cleanup_pending:
            _cleanup_pending = True
            try:
                # Run cleanup on a timer so we're outside the depsgraph
                # update cycle when objects get removed.
                bpy.app.timers.register(_deferred_cleanup, first_interval=0.05)
            except Exception:
                _cleanup_pending = False
    _last_dna_names = current


@persistent
def _load_post_cleanup(_dummy):
    global _last_dna_names
    _last_dna_names = None  # reset on file load
    try:
        cleanup_orphaned_bend_objects()
    except Exception:
        pass
    # Migration: older bend curves were created without hide_render=True,
    # so they would render as a thin tube in saved images. Force the flag
    # here once per file load. New curves get hide_render=True at creation
    # in _create_bend_curve, so this only matters for legacy files.
    try:
        for o in bpy.data.objects:
            if o.type == "CURVE" and o.name.endswith("_BendCurve"):
                if not o.hide_render:
                    o.hide_render = True
    except Exception:
        pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if _load_post_cleanup not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_cleanup)
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _load_post_cleanup in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_cleanup)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
