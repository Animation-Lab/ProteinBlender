"""Bending controls for DNA/RNA molecules.

The rig itself - a Bezier curve, control-node Empties, and the hooks tying
them together - lives in :mod:`proteinblender.core.bend_rig`, shared with the
Symmetry panel's helical filament bend. This module is the DNA-specific half:
what the curve is *for*.

The difference is the whole reason they are separate modules. DNA hands its
curve to a Blender **Curve modifier** and deforms the strand, which is right
for a continuous double helix - it genuinely bends. A filament of rigid
protein subunits instead *samples* the curve and re-places each subunit, which
is why ``core/symmetry_bend.py`` exists rather than reusing this.

Operators here:

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
  * `dna_toggle_bend_curve` – shows / hides the guide curve.
  * `dna_remove_bend`      – removes the modifier, deletes the curve and
    all bend nodes, restores the (vertically) flat helix.

Starting shapes (Straight / Arc / S-curve / Coil) are implemented generically
in ``core.bend_rig.apply_preset``; the DNA dialog does not surface them yet.

The DNA stores:
  * `pb_bend_curve_name`   – the bend Bezier curve object's name.
  * `pb_bend_node_names`   – JSON list of the control-node Empty names.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty
from bpy.types import Operator
from mathutils import Vector

from ..core import bend_rig, domain_space


# Custom property keys on the DNA object
BEND_CURVE_PROP = "pb_bend_curve_name"
BEND_NODES_PROP = "pb_bend_node_names"
PIVOT_SHIFTED_PROP = "pb_bend_pivot_shifted"

# Modifier names
_CURVE_MOD = "DNA Bend"
_HOOK_PREFIX = "Hook_BP"

# Resolution range for the control-node count. Re-exported from the shared rig
# so the DNA dialog and the Symmetry panel cannot drift apart on what counts as
# a usable number of handles.
RES_MIN = bend_rig.RES_MIN
RES_MAX = bend_rig.RES_MAX
RES_DEFAULT = bend_rig.RES_DEFAULT

#: How the shared rig identifies DNA's curves and nodes. ``curve_suffix`` and
#: ``node_label`` must stay distinct from the filament rig's, or one feature's
#: orphan sweep would delete the other's objects.
SPEC = bend_rig.BendRigSpec(
    kind="dna",
    curve_prop=BEND_CURVE_PROP,
    nodes_prop=BEND_NODES_PROP,
    curve_suffix="_BendCurve",
    node_label="Bend Node",
    hook_prefix=_HOOK_PREFIX,
    curve_bevel=0.005,
    node_display_size=0.04,
    node_display_type="SPHERE",
    owner_test=lambda obj: bool(obj.get("pb_is_nucleic_acid", False)),
)


# ---------------------------------------------------------------------------
# Origin helpers
# ---------------------------------------------------------------------------
#
# A molecule's origin is not its *mesh* origin. MolecularNodes' modifier
# translates every atom by ``-Pivot``, so the strand the user sees sits at
# ``matrix_world @ (co - pivot)`` (see core/domain_space). The whole bend rig
# lives downstream of that modifier - the Curve modifier deforms the geometry
# the node tree emits - so every coordinate here is in *pivot-applied* object
# space, and the origin is moved by moving the pivot, never the mesh.
#
# Reading raw ``mesh.vertices`` z values as if they were object space is what
# put the control nodes half a helix above the strand.


def _strand_z_extent(obj):
    """Object-space Z extent of the rendered strand (pivot applied)."""
    mesh = obj.data
    if not mesh or not mesh.vertices:
        return None
    pivot_z = domain_space.get_pivot(obj).z
    z_vals = [v.co.z - pivot_z for v in mesh.vertices]
    return min(z_vals), max(z_vals)


def _move_origin_to(obj, z_local) -> bool:
    """Move the origin to object-space height *z_local* along the strand's
    axis. The atoms stay exactly where they are - only the origin (and with
    it the object's location) moves. Returns True if it moved."""
    if abs(z_local) < 1e-6:
        return False
    return domain_space.set_pivot_world(
        obj, obj.matrix_world @ Vector((0.0, 0.0, z_local)))


def shift_origin_to_bottom(obj) -> None:
    """Put the origin on the strand's lowest atom, so the whole strand lives
    in +Z of the origin - the space the bend curve is built in."""
    extent = _strand_z_extent(obj)
    if extent is None:
        return
    if _move_origin_to(obj, extent[0]):
        obj[PIVOT_SHIFTED_PROP] = True


def restore_origin_to_centre(obj) -> None:
    extent = _strand_z_extent(obj)
    if extent is None:
        return
    _move_origin_to(obj, 0.5 * (extent[0] + extent[1]))
    obj.pop(PIVOT_SHIFTED_PROP, None)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_bend_curve(dna_obj):
    return bend_rig.get_curve(SPEC, dna_obj)


def get_bend_nodes(dna_obj):
    """Return list of control-node Empty objects (in order). Filters dangling
    references."""
    return bend_rig.get_nodes(SPEC, dna_obj)


def dna_has_keyframes(dna_obj):
    """True iff the DNA mesh, its bend curve, or any of its bend control nodes
    has at least one transform F-curve key.

    Used by the Builders panel to lock structural changes (add/remove bend,
    change node count) once the strand is animated — those operations rebuild
    the rig from scratch, which orphans the F-curves keyed against the old
    nodes/curve/origin and silently corrupts the animation.
    """
    return bend_rig.has_keyframes(SPEC, dna_obj)


def get_dna_for_curve(curve_obj):
    """Reverse lookup: which DNA molecule owns this bend curve?"""
    return bend_rig.owner_of_curve(SPEC, curve_obj)


def get_dna_for_node(node_obj):
    """Reverse lookup: which DNA molecule owns this bend node?"""
    return bend_rig.owner_of_node(SPEC, node_obj)


def _resolve_dna(obj):
    """Return the DNA molecule for *obj*: either *obj* itself if it's a DNA
    mesh, or the DNA that owns *obj* as a bend node. Returns None otherwise.

    Operators that accept either the DNA mesh or one of its bend control
    nodes as the active object use this to find the underlying molecule.
    """
    return bend_rig.resolve_owner(SPEC, obj)


# ---------------------------------------------------------------------------
# Curve construction & resampling
# ---------------------------------------------------------------------------


def _create_bend_curve(name, dna_obj, height, n_points=RES_DEFAULT):
    """The guide curve, straight up the strand's own +Z."""
    return bend_rig.create_curve(
        SPEC, dna_obj, name,
        bend_rig.straight_points(height, n=n_points, direction=(0.0, 0.0, 1.0)))


def _add_curve_modifier(dna_obj, curve_obj):
    existing = dna_obj.modifiers.get(_CURVE_MOD)
    if existing is not None:
        dna_obj.modifiers.remove(existing)
    mod = dna_obj.modifiers.new(_CURVE_MOD, "CURVE")
    mod.object = curve_obj
    mod.deform_axis = "POS_Z"
    return mod


def _set_aligned_handles_along_path(spline, factor=0.3):
    bend_rig.set_aligned_handles_along_path(spline, factor)


def _resample_curve_arc_length(curve_obj, n_points):
    bend_rig.resample_curve_arc_length(curve_obj, n_points)


# ---------------------------------------------------------------------------
# Control-node (Empty) management
# ---------------------------------------------------------------------------


def _remove_hook_modifiers(curve_obj):
    bend_rig.remove_hook_modifiers(SPEC, curve_obj)


def _remove_bend_nodes(dna_obj):
    """Delete all control-node empties referenced by the DNA, plus their
    hook modifiers on the bend curve."""
    bend_rig.remove_nodes(SPEC, dna_obj)


def _create_bend_nodes(dna_obj, curve_obj, n_points):
    """Create n_points control-node empties along the curve, hook each one
    to the corresponding bezier point. Assumes the curve already has
    n_points bezier points (call _resample_curve_arc_length first)."""
    bend_rig.create_nodes(SPEC, dna_obj, curve_obj, n_points)


def bake_evaluated_curve_shape(curve_obj):
    """Write the user's hook-deformed bend back into the curve's static
    ``bezier_points``. See ``core.bend_rig.bake_evaluated_curve_shape`` for why
    the obvious evaluated-curve read is a silent no-op.

    Bug this exists for (tester report, Janet, Windows): adding a 4th bend node
    after one of the original 3 had been moved made the DNA snap back to
    origin, because the rebuild resampled a curve that still described a
    straight line.
    """
    bend_rig.bake_evaluated_curve_shape(curve_obj)


def _rebuild_bend_nodes(dna_obj, n_points):
    """Tear down & recreate the bend node system at a new resolution while
    preserving the curve's current shape via arc-length resampling."""
    bend_rig.rebuild_nodes(SPEC, dna_obj, n_points)


# ---------------------------------------------------------------------------
# Public API used by other modules (e.g. update_dna)
# ---------------------------------------------------------------------------


def capture_bend_animation(dna_obj):
    """Take custody of the animation on a strand and its bend control nodes,
    so :func:`restore_bend_animation` can put it back after a rebuild.

    ``update_dna`` deletes the molecule object and ``reattach_after_rebuild``
    recreates the control-node Empties from scratch. Both carry the F-curves
    that make a bend *animate*, so without this every keyframe the user set was
    silently discarded the next time they opened the strand's edit dialog and
    pressed OK. The bend CURVE survives the rebuild as the same object, so its
    keys need no handling here - which is exactly why the Animate panel kept
    listing the frames while nothing moved.
    """
    stash = bend_rig.capture_animation(SPEC, dna_obj)
    # Keyed by "dna" historically; kept so a stash captured by an older build
    # still restores.
    return {"dna": stash.get("owner"), "nodes": stash.get("nodes", [])}


def restore_bend_animation(new_dna_obj, stash):
    """Re-bind the actions captured by :func:`capture_bend_animation`."""
    if not stash:
        return
    bend_rig.restore_animation(
        SPEC, new_dna_obj,
        {"owner": stash.get("dna"), "nodes": stash.get("nodes") or []})


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
    extent = _strand_z_extent(new_dna_obj)
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
                and ob.parent == curve_obj
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
    # The Curve modifier is the DNA-specific half of the rig, so it comes off
    # here rather than in the shared teardown. Taking it off first means the
    # strand is never left deforming along a curve that has just been deleted.
    modifier = dna_obj.modifiers.get(_CURVE_MOD)
    if modifier is not None:
        dna_obj.modifiers.remove(modifier)

    bend_rig.remove_rig(SPEC, dna_obj)


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

        extent = _strand_z_extent(dna)
        if extent is None:
            self.report({"ERROR"}, "DNA mesh has no vertices.")
            return {"CANCELLED"}
        z_min, z_max = extent
        height = z_max - z_min
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


class PROTEINBLENDER_OT_dna_toggle_bend_curve(Operator):
    """Show / hide the bend curve guide in the viewport.

    Toggles the curve's *eye* visibility (``hide_set``) — NOT its
    "disable in viewport" flag (``hide_viewport``). The bend curve is the
    target of the DNA's Curve modifier and the anchor for the hook rig;
    ``hide_viewport`` removes it from depsgraph evaluation, which on some
    Blender versions drops the Curve deformation and makes the strand snap
    back to its object-space rest position (tester report, Janet: "the DNA
    jumps down so that end is sitting at the origin"). Eye visibility keeps
    the curve fully evaluated, so hiding the guide never moves the strand.
    The curve is already ``hide_render=True`` / ``hide_select=True``, so this
    is purely a viewport-guide toggle.
    """

    bl_idname = "proteinblender.dna_toggle_bend_curve"
    bl_label = "Toggle Bend Curve"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        if obj.get("pb_is_nucleic_acid", False) and obj.get(BEND_CURVE_PROP):
            return True
        return get_dna_for_node(obj) is not None

    def execute(self, context):
        dna = _resolve_dna(context.active_object)
        if dna is None:
            return {"CANCELLED"}
        curve_obj = get_bend_curve(dna)
        if curve_obj is None:
            self.report({"ERROR"}, "Bend curve not found.")
            return {"CANCELLED"}
        curve_obj.hide_set(not curve_obj.hide_get())
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
    PROTEINBLENDER_OT_dna_toggle_bend_curve,
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
    removed from `bpy.data.objects`. Safe to call from operators.

    ``_BendNode`` is the pre-rename node naming; legacy .blend files still
    contain Empties called that, and they need sweeping up too.
    """
    bend_rig.cleanup_orphans(SPEC, extra_node_patterns=("_BendNode",))


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
