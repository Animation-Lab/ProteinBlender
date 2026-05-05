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
    # but leave it visible so the bend path stays apparent.
    curve_obj.hide_select = True

    coll = (dna_obj.users_collection[0]
            if dna_obj.users_collection else bpy.context.collection)
    coll.objects.link(curve_obj)
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

        empty = bpy.data.objects.new(
            f"{dna_obj.name}_BendNode{i:02d}", None,
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


def _rebuild_bend_nodes(dna_obj, n_points):
    """Tear down & recreate the bend node system at a new resolution while
    preserving the curve's current shape via arc-length resampling."""
    curve_obj = get_bend_curve(dna_obj)
    if curve_obj is None:
        return

    # Save the empties' positions first via the *evaluated* curve (positions
    # already include any hook deformation the user has applied).
    deps = bpy.context.evaluated_depsgraph_get()
    eval_curve = curve_obj.evaluated_get(deps)
    eval_data = eval_curve.data
    # Bake the deformed positions into the original curve so resampling
    # accounts for the user's bend.
    eval_spline = eval_data.splines[0] if eval_data.splines else None
    if eval_spline is not None:
        orig_spline = curve_obj.data.splines[0]
        # Number of bezier points may match the original (hooks don't
        # change topology) so we copy point-by-point.
        if len(eval_spline.bezier_points) == len(orig_spline.bezier_points):
            for ebp, obp in zip(eval_spline.bezier_points,
                                orig_spline.bezier_points):
                obp.co = ebp.co.copy()
                obp.handle_left = ebp.handle_left.copy()
                obp.handle_right = ebp.handle_right.copy()

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

    The curve and any bend nodes are separate scene objects that survive
    the rebuild; we just shift the new mesh's pivot back to its bottom and
    re-add the Curve modifier. The control nodes & hooks on the curve
    don't need to be touched.
    """
    if curve_obj is None:
        return
    shift_origin_to_bottom(new_dna_obj)
    _add_curve_modifier(new_dna_obj, curve_obj)
    new_dna_obj[BEND_CURVE_PROP] = curve_obj.name


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
        return (obj is not None
                and obj.get("pb_is_nucleic_acid", False)
                and obj.get(BEND_CURVE_PROP))

    def execute(self, context):
        dna = context.active_object
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
        dna = context.active_object
        if not (dna is not None and dna.get("pb_is_nucleic_acid", False)):
            dna = get_dna_for_node(context.active_object)
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

        # Re-hide the curve from selection (Move Strand may have enabled it).
        curve = get_bend_curve(dna)
        if curve is not None:
            curve.hide_select = True

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
        dna = context.active_object
        if not (dna is not None and dna.get("pb_is_nucleic_acid", False)):
            dna = get_dna_for_node(context.active_object)
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


class PROTEINBLENDER_OT_dna_select_rig(Operator):
    """Select DNA + bend curve and immediately start a translate drag, so the
    user can move the whole strand in a single click + drag.

    Bend nodes are parented to the curve, so they follow the curve
    automatically. Moving DNA + curve together preserves their relative
    offset, keeping the Curve modifier deformation unchanged. The hooks
    also see no change because the nodes' positions relative to the curve
    (their parent) stay constant."""

    bl_idname = "proteinblender.dna_select_rig"
    bl_label = "Move Strand"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False):
            return True
        return get_dna_for_curve(obj) is not None or get_dna_for_node(obj) is not None

    def _select(self, context):
        """Set up the rig selection (DNA + curve). Returns the DNA or None.

        Bend nodes are parented to the curve, so they follow automatically
        when the curve is translated — no need to select them explicitly.
        Selecting DNA + curve preserves the relative offset between them,
        which keeps the Curve modifier deformation unchanged. The hooks
        also see no change because the nodes' positions relative to the
        curve stay constant.
        """
        dna = context.active_object
        if dna is not None and not dna.get("pb_is_nucleic_acid", False):
            dna = get_dna_for_curve(dna) or get_dna_for_node(dna)
        if dna is None:
            return None

        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass

        curve = get_bend_curve(dna)

        # Select the curve (temporarily allow selection — it's normally
        # hidden from selection to prevent accidental solo-grabs).
        if curve is not None:
            curve.hide_select = False
            curve.select_set(True)

        dna.select_set(True)
        context.view_layer.objects.active = dna
        return dna

    def execute(self, context):
        dna = self._select(context)
        if dna is None:
            return {"CANCELLED"}
        return {"FINISHED"}

    def invoke(self, context, event):
        dna = self._select(context)
        if dna is None:
            return {"CANCELLED"}

        # After selection is set, immediately invoke the standard translate
        # operator so the user is dragging the whole rig from a single
        # button click. translate() needs a 3D viewport context, so we find
        # one and override before invoking.
        for area in context.window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    try:
                        with context.temp_override(area=area, region=region):
                            bpy.ops.transform.translate("INVOKE_DEFAULT")
                        return {"FINISHED"}
                    except Exception:
                        pass
        # No 3D viewport found (or override failed). Fall back to just leaving
        # the user with the rig selected — they can press G manually.
        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_dna_add_bend,
    PROTEINBLENDER_OT_dna_edit_bend,
    PROTEINBLENDER_OT_dna_set_bend_resolution,
    PROTEINBLENDER_OT_dna_finish_bend_edit,
    PROTEINBLENDER_OT_dna_remove_bend,
    PROTEINBLENDER_OT_dna_select_rig,
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
        elif o.type == "EMPTY" and "_BendNode" in o.name:
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
