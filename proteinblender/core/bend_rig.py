"""A Bezier curve with draggable control nodes - the bend rig, shared.

Two features in ProteinBlender want the same thing: a smooth path the user
shapes by grabbing a handful of spheres in the viewport. The DNA/RNA builder
bends a strand along one; the Symmetry panel bends a helical filament along
one. What they do with the finished curve differs completely - DNA hands it to
a Curve modifier and deforms the mesh, a filament samples it and re-places
rigid subunits - but everything up to that point is the same rig, and it is
the rig that carries the hard-won detail:

* hooks whose ``matrix_inverse`` must come from Blender's own ``hook_reset``,
  not from Python-side matrix arithmetic, or the bend starts non-zero;
* a curve that has to be temporarily un-hidden for ``hook_reset`` to run at
  all, because edit mode refuses hidden objects;
* arc-length resampling that must set handle *coordinates* explicitly, since a
  freshly added Bezier point's handles sit at the local origin and sag the
  curve;
* a "bake the hook deformation back into the control points" step, because
  hooks on a curve deform the evaluated geometry only and never write back to
  ``bp.co`` - so the obvious eval-and-copy is a silent no-op.

Each of those was a real bug. Keeping one implementation is the point of this
module; :class:`BendRigSpec` carries the handful of things that genuinely
differ between the two callers.

Coordinates: control nodes are Empties parented to the curve with the parent
inverse cancelling the curve's matrix, so a node's local ``location`` *is* its
world position. That is what lets an F-curve keyed against a node survive the
rig being rebuilt around it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import bpy
import mathutils
from mathutils import Vector
from mathutils.geometry import interpolate_bezier

logger = logging.getLogger(__name__)

#: Control-node count limits. Two is the fewest that describes a direction;
#: twelve is where dragging individual spheres stops being a usable way to
#: shape a path.
RES_MIN = 2
RES_MAX = 12
RES_DEFAULT = 3

#: Samples per Bezier segment when flattening a spline to measure arc length.
_SAMPLES_PER_SEGMENT = 32


@dataclass(frozen=True)
class BendRigSpec:
    """What distinguishes one caller's bend rig from another's.

    Everything here ends up in a name or a custom property, so the two rigs
    never collide in ``bpy.data`` and neither one's orphan sweep can delete the
    other's objects.
    """

    #: Short identifier, only used in log messages.
    kind: str
    #: Object custom property holding the curve object's name.
    curve_prop: str
    #: Object custom property holding the JSON list of control-node names.
    nodes_prop: str
    #: Suffix given to the curve object, and the pattern the orphan sweep
    #: recognises. Must differ between rigs.
    curve_suffix: str
    #: Human-facing control-node name, as ``"{owner} {node_label} {n}"``.
    node_label: str
    #: Prefix for the hook modifiers on the curve.
    hook_prefix: str
    #: Bevel on the guide curve, so the path is visible without being fat.
    curve_bevel: float = 0.005
    #: Empty display size for a control node.
    node_display_size: float = 0.04
    #: Empty display type for a control node.
    node_display_type: str = "SPHERE"
    #: Optional extra test for "is this object one of mine". Defaults to
    #: "carries my curve property", which is true of every owner by
    #: construction.
    owner_test: Optional[Callable[[bpy.types.Object], bool]] = None

    def owns(self, obj) -> bool:
        if obj is None:
            return False
        if self.owner_test is not None:
            return bool(self.owner_test(obj))
        return bool(obj.get(self.curve_prop))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_curve(spec: BendRigSpec, owner):
    """The bend curve object for *owner*, or None."""
    if owner is None:
        return None
    name = owner.get(spec.curve_prop)
    if not name:
        return None
    return bpy.data.objects.get(name)


def get_nodes(spec: BendRigSpec, owner) -> List[bpy.types.Object]:
    """The control-node Empties in order, dangling references filtered out."""
    if owner is None:
        return []
    raw = owner.get(spec.nodes_prop)
    if not raw:
        return []
    try:
        names = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [bpy.data.objects[n] for n in names if n in bpy.data.objects]


def owner_of_curve(spec: BendRigSpec, curve_obj):
    """Reverse lookup: whose bend curve is this?"""
    if curve_obj is None:
        return None
    for obj in bpy.data.objects:
        if obj.get(spec.curve_prop) == curve_obj.name and spec.owns(obj):
            return obj
    return None


def owner_of_node(spec: BendRigSpec, node_obj):
    """Reverse lookup: whose control node is this?"""
    if node_obj is None:
        return None
    for obj in bpy.data.objects:
        raw = obj.get(spec.nodes_prop)
        if not raw or not spec.owns(obj):
            continue
        try:
            names = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if node_obj.name in names:
            return obj
    return None


def resolve_owner(spec: BendRigSpec, obj):
    """The owner for *obj*: itself if it is one, else whoever owns it as a node.

    Operators that accept either the bent thing or one of its control nodes as
    the active object go through this.
    """
    if spec.owns(obj):
        return obj
    return owner_of_node(spec, obj)


def has_keyframes(spec: BendRigSpec, owner) -> bool:
    """True if the owner, its curve or any control node carries a transform key.

    Callers use this to lock structural changes once a bend is animated: adding
    or removing nodes rebuilds the rig, which orphans F-curves keyed against
    the old nodes and silently corrupts the animation.
    """
    if owner is None:
        return False
    from ..utils.animation import get_fcurves_from_action

    objects = [owner]
    curve = get_curve(spec, owner)
    if curve is not None:
        objects.append(curve)
    objects.extend(get_nodes(spec, owner))

    for obj in objects:
        animation = obj.animation_data
        if not animation or not animation.action:
            continue
        for curve_data in get_fcurves_from_action(animation.action, animation):
            if len(curve_data.keyframe_points) > 0:
                return True
    return False


# ---------------------------------------------------------------------------
# Curve construction and resampling
# ---------------------------------------------------------------------------

def set_bezier_points(spline, points, handle_type="ALIGNED") -> None:
    """Fill a fresh spline from ``(co, handle_left, handle_right)`` triples."""
    spline.bezier_points.add(len(points) - 1)
    for i, (co, handle_left, handle_right) in enumerate(points):
        point = spline.bezier_points[i]
        point.co = Vector(co)
        point.handle_left = Vector(handle_left)
        point.handle_right = Vector(handle_right)
        point.handle_left_type = handle_type
        point.handle_right_type = handle_type


def straight_points(length: float, n: int = RES_DEFAULT,
                    direction=(0.0, 0.0, 1.0)):
    """``n`` evenly spaced points along a straight line of ``length``."""
    axis = Vector(direction)
    if axis.length < 1e-9:
        axis = Vector((0.0, 0.0, 1.0))
    axis = axis.normalized()

    steps = max(n - 1, 1)
    handle = length / steps * 0.4

    points = []
    for i in range(n):
        along = (i / steps) * length
        centre = axis * along
        points.append((centre, centre - axis * handle, centre + axis * handle))
    return points


def set_aligned_handles_along_path(spline, factor: float = 0.3) -> None:
    """Point every handle along the smooth path through its neighbours.

    Catmull-Rom style. ALIGNED handles matter here: a hook moves all three of a
    Bezier point's sub-vertices together, and only ALIGNED keeps the point's
    tangent consistent when it does.
    """
    points = spline.bezier_points
    count = len(points)
    if count < 2:
        return

    for i in range(count):
        if i == 0:
            tangent = points[1].co - points[0].co
            segment = tangent.length
        elif i == count - 1:
            tangent = points[count - 1].co - points[count - 2].co
            segment = tangent.length
        else:
            tangent = points[i + 1].co - points[i - 1].co
            segment = ((points[i].co - points[i - 1].co).length
                       + (points[i + 1].co - points[i].co).length) * 0.5

        if tangent.length < 1e-9:
            tangent = Vector((0.0, 0.0, 1.0))

        offset = tangent.normalized() * (segment * factor)
        points[i].handle_left = points[i].co - offset
        points[i].handle_right = points[i].co + offset
        points[i].handle_left_type = "ALIGNED"
        points[i].handle_right_type = "ALIGNED"


def create_curve(spec: BendRigSpec, owner, name: str, points,
                 parent_to_owner: bool = True):
    """Build the guide curve and park it on the owner.

    The curve is a guide, not a thing to grab: hidden from selection so it
    cannot be dragged away from what it is bending, and hidden from renders so
    it never appears in a saved image. It stays *visible* though, because the
    path is the whole point.
    """
    curve_data = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = spec.curve_bevel
    curve_data.resolution_u = 12

    spline = curve_data.splines.new("BEZIER")
    set_bezier_points(spline, points)

    curve_obj = bpy.data.objects.new(name, curve_data)
    curve_obj.location = owner.location.copy()
    curve_obj.rotation_mode = owner.rotation_mode
    curve_obj.rotation_euler = owner.rotation_euler.copy()
    curve_obj.hide_select = True
    curve_obj.hide_render = True

    collection = (owner.users_collection[0]
                  if owner.users_collection else bpy.context.collection)
    collection.objects.link(curve_obj)

    if parent_to_owner:
        # owner -> curve -> nodes, so moving the owner moves the whole rig.
        # Flush the depsgraph first: the caller may have changed the owner's
        # location without matrix_world having been recalculated yet.
        bpy.context.view_layer.update()
        curve_obj.parent = owner
        curve_obj.matrix_parent_inverse = owner.matrix_world.inverted()

    owner[spec.curve_prop] = curve_obj.name
    return curve_obj


def resample_curve_arc_length(curve_obj, n_points: int) -> None:
    """Redistribute the first spline over ``n_points`` even by arc length.

    Preserves the shape the user made. A no-op when the count already matches,
    which keeps the curve exactly rather than round-tripping it.
    """
    n_points = max(RES_MIN, min(RES_MAX, int(n_points)))
    curve_data = curve_obj.data
    if not curve_data.splines:
        return

    old_spline = curve_data.splines[0]
    if old_spline.type != "BEZIER" or len(old_spline.bezier_points) < 2:
        return
    if len(old_spline.bezier_points) == n_points:
        return

    polyline = _flatten(old_spline)
    if len(polyline) < 2:
        return

    lengths = [0.0]
    for i in range(1, len(polyline)):
        lengths.append(lengths[-1] + (polyline[i] - polyline[i - 1]).length)
    total = lengths[-1]
    if total <= 0:
        return

    positions = [_at_arc_length(polyline, lengths,
                                (j / (n_points - 1)) * total)
                 for j in range(n_points)]

    # Replace the spline outright and set the coordinates explicitly. Adding a
    # Bezier point and only setting its handle *type* leaves the handle
    # coordinates at (0, 0, 0), so every handle points at the curve-local
    # origin - which sags the curve and drags whatever follows it out of place.
    curve_data.splines.remove(old_spline)
    new_spline = curve_data.splines.new("BEZIER")
    new_spline.bezier_points.add(n_points - 1)
    for i, position in enumerate(positions):
        new_spline.bezier_points[i].co = Vector(position)

    set_aligned_handles_along_path(new_spline)
    curve_data.update_tag()


def _flatten(spline) -> List[Vector]:
    """A Bezier spline as a dense polyline, for measuring along."""
    points = spline.bezier_points
    polyline: List[Vector] = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        segment = interpolate_bezier(
            a.co, a.handle_right, b.handle_left, b.co, _SAMPLES_PER_SEGMENT)
        polyline.extend(segment[:-1] if i < len(points) - 2 else segment)
    return polyline


def _at_arc_length(polyline, lengths, target: float) -> Vector:
    index = 0
    while index < len(lengths) - 1 and lengths[index + 1] < target:
        index += 1
    if index >= len(lengths) - 1:
        return polyline[-1].copy()
    span = lengths[index + 1] - lengths[index]
    t = (target - lengths[index]) / span if span > 0 else 0.0
    return polyline[index].lerp(polyline[index + 1], t)


def bake_evaluated_curve_shape(curve_obj) -> None:
    """Write the hook deformation back into the curve's own control points.

    Hooks on a *curve* deform the evaluated geometry only - they never write
    back to ``bp.co``, and the evaluated datablock exposes the same Bezier
    points as the source. So reading ``evaluated_get(...).data.splines`` and
    copying it back is a silent no-op, and anything that resamples afterwards
    sees the original straight line instead of the user's bend.

    Reading each hook's Empty and snapping the point there is what actually
    works. Handles move by the same delta, or they would point at where the
    point used to be and kink the curve.
    """
    if curve_obj is None or curve_obj.data is None:
        return
    splines = curve_obj.data.splines
    if not splines:
        return
    spline = splines[0]
    if spline.type != "BEZIER" or not spline.bezier_points:
        return

    # vertex_indices_set([3i, 3i+1, 3i+2]) per Bezier point, so the first
    # index recovers which point a hook drives.
    by_point = {}
    for modifier in curve_obj.modifiers:
        if modifier.type != "HOOK" or modifier.object is None:
            continue
        indices = list(modifier.vertex_indices)
        if not indices:
            continue
        point_index = indices[0] // 3
        if 0 <= point_index < len(spline.bezier_points):
            by_point[point_index] = modifier.object

    if not by_point:
        return

    # The user may have moved a node moments ago without a viewport tick.
    bpy.context.view_layer.update()

    to_local = curve_obj.matrix_world.inverted()
    for point_index, empty in by_point.items():
        point = spline.bezier_points[point_index]
        target = to_local @ empty.matrix_world.translation
        delta = target - point.co
        if delta.length_squared < 1e-12:
            continue
        point.co = target
        point.handle_left = point.handle_left + delta
        point.handle_right = point.handle_right + delta

    curve_obj.data.update_tag()


# ---------------------------------------------------------------------------
# Control nodes
# ---------------------------------------------------------------------------

def remove_hook_modifiers(spec: BendRigSpec, curve_obj) -> None:
    if curve_obj is None:
        return
    for modifier in list(curve_obj.modifiers):
        if modifier.type == "HOOK" and modifier.name.startswith(spec.hook_prefix):
            curve_obj.modifiers.remove(modifier)


def remove_nodes(spec: BendRigSpec, owner) -> None:
    """Delete the control-node Empties and the hooks that referenced them."""
    for node in get_nodes(spec, owner):
        try:
            bpy.data.objects.remove(node, do_unlink=True)
        except Exception:
            pass
    remove_hook_modifiers(spec, get_curve(spec, owner))
    owner.pop(spec.nodes_prop, None)


def create_nodes(spec: BendRigSpec, owner, curve_obj, n_points: int) -> None:
    """Place ``n_points`` control nodes and hook each to its Bezier point."""
    collection = (owner.users_collection[0]
                  if owner.users_collection else bpy.context.collection)

    spline = curve_obj.data.splines[0]
    if len(spline.bezier_points) != n_points:
        resample_curve_arc_length(curve_obj, n_points)
        spline = curve_obj.data.splines[0]

    # The curve's matrix_world may have been changed without the depsgraph
    # having picked it up.
    bpy.context.view_layer.update()
    curve_world = curve_obj.matrix_world.copy()

    created, names = [], []
    for i in range(n_points):
        point = spline.bezier_points[i]

        # Named for a human, because these show up in the outliner and in the
        # keyframe dialog: "<owner> Bend Node 1", one-based.
        empty = bpy.data.objects.new(
            f"{owner.name} {spec.node_label} {i + 1}", None)
        empty.empty_display_type = spec.node_display_type
        empty.empty_display_size = spec.node_display_size
        empty.location = curve_world @ point.co
        empty.show_in_front = True
        collection.objects.link(empty)

        # Parented to the curve with the parent inverse cancelling it, so the
        # node follows when the rig is moved as a whole and its local location
        # still reads as a world position.
        empty.parent = curve_obj
        empty.matrix_parent_inverse = curve_world.inverted()

        created.append((i, empty, point))
        names.append(empty.name)

    # Force the new Empties' matrix_world to reflect the location just set -
    # without this they are still identity from creation, and hook_reset below
    # would read stale matrices.
    bpy.context.view_layer.update()

    hook_names = []
    for i, empty, point in created:
        modifier = curve_obj.modifiers.new(f"{spec.hook_prefix}{i:02d}", "HOOK")
        modifier.object = empty
        modifier.vertex_indices_set([3 * i + 0, 3 * i + 1, 3 * i + 2])
        modifier.center = point.co.copy()
        # Pin the strength and kill the falloff so vertex_indices is the only
        # thing selecting what this hook moves.
        modifier.strength = 1.0
        modifier.falloff_radius = 0.0
        modifier.falloff_type = "NONE"
        # A pure translation as a safety net; hook_reset overwrites it with the
        # correct value below.
        modifier.matrix_inverse = mathutils.Matrix.Translation(-empty.location)
        hook_names.append(modifier.name)

    _reset_hooks(curve_obj, hook_names)
    bpy.context.view_layer.update()

    owner[spec.nodes_prop] = json.dumps(names)


def _reset_hooks(curve_obj, hook_names) -> None:
    """Recompute every hook's ``matrix_inverse`` through Blender's own operator.

    ``hook_reset`` runs the same C-side code as ``hook_assign``, which is the
    only fully reliable way to get zero initial deformation - Python-side
    matrix arithmetic against ``empty.matrix_world`` is at the mercy of
    depsgraph timing.

    It needs edit mode, and edit mode refuses a hidden object. The guide curve
    may well be hidden (the user hid it, or a legacy file saved it with the old
    viewport toggle), so it is revealed for the duration and put back
    afterwards. Without that, changing the node count on a hidden curve errored
    and left the rig half-rebuilt.
    """
    previous_active = bpy.context.view_layer.objects.active
    previously_selected = list(bpy.context.selected_objects)
    previous_mode = bpy.context.mode

    was_hidden_viewport = curve_obj.hide_viewport
    was_hidden_eye = curve_obj.hide_get()
    curve_obj.hide_viewport = False
    curve_obj.hide_set(False)

    try:
        if previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        curve_obj.select_set(True)
        bpy.context.view_layer.objects.active = curve_obj
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            for name in hook_names:
                try:
                    bpy.ops.object.hook_reset(modifier=name)
                except Exception:
                    pass
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            # No edit mode available - fall back to the translation-only
            # matrix_inverse set above, which still starts near zero.
            if bpy.context.mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
    finally:
        curve_obj.hide_viewport = was_hidden_viewport
        try:
            curve_obj.hide_set(was_hidden_eye)
        except Exception:
            pass
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for obj in previously_selected:
            try:
                if obj.name in bpy.data.objects:
                    obj.select_set(True)
            except Exception:
                pass
        try:
            if previous_active is not None and previous_active.name in bpy.data.objects:
                bpy.context.view_layer.objects.active = previous_active
        except Exception:
            pass


def rebuild_nodes(spec: BendRigSpec, owner, n_points: int) -> None:
    """Change the node count, keeping the shape the user made."""
    curve_obj = get_curve(spec, owner)
    if curve_obj is None:
        return

    # Bake first, or the resample below sees the straight starting line rather
    # than the user's bend and throws their work away.
    bake_evaluated_curve_shape(curve_obj)
    remove_nodes(spec, owner)
    resample_curve_arc_length(curve_obj, n_points)
    create_nodes(spec, owner, curve_obj, n_points)


# ---------------------------------------------------------------------------
# Starting shapes
# ---------------------------------------------------------------------------
#
# Offered as a starting point rather than a constraint: every preset is just a
# set of control-point positions the user goes on to drag.

#: (id, label, description) for the shapes :func:`preset_points` can make.
PRESETS = (
    ("STRAIGHT", "Straight", "No bend - the path the rig started from"),
    ("ARC", "Arc", "A single smooth bow to one side"),
    ("S", "S-curve", "Bowed one way then the other"),
    ("COIL", "Coil", "A wide loop, curling back on itself"),
)


def preset_points(preset: str, length: float, n_points: int,
                  direction=(0.0, 0.0, 1.0), amplitude: Optional[float] = None):
    """Control points for one of :data:`PRESETS`, in curve-local space.

    ``amplitude`` is how far the path departs from straight; it defaults to a
    quarter of the length, which reads as a clear bend at any scale.
    """
    import math

    axis = Vector(direction)
    if axis.length < 1e-9:
        axis = Vector((0.0, 0.0, 1.0))
    axis = axis.normalized()
    side = _perpendicular(axis)

    n_points = max(RES_MIN, min(RES_MAX, int(n_points)))
    if amplitude is None:
        amplitude = length * 0.25

    steps = max(n_points - 1, 1)
    preset = (preset or "STRAIGHT").upper()

    positions = []
    for i in range(n_points):
        t = i / steps
        along = t * length
        if preset == "ARC":
            offset = amplitude * math.sin(math.pi * t)
        elif preset == "S":
            offset = amplitude * math.sin(2.0 * math.pi * t)
        elif preset == "COIL":
            # A planar loop: the path curls a full turn, so "along" stops being
            # monotonic. Arc length still increases, which is all the samplers
            # downstream require.
            angle = 2.0 * math.pi * t
            radius = length / (2.0 * math.pi)
            positions.append(axis * (radius * math.sin(angle))
                             + side * (radius * (1.0 - math.cos(angle))))
            continue
        else:
            offset = 0.0
        positions.append(axis * along + side * offset)

    # Handles are regenerated from the positions rather than guessed at, for
    # the same reason resampling does it: default handles sit at the origin.
    return [(p, p, p) for p in positions]


def apply_preset(spec: BendRigSpec, owner, preset: str, length: float,
                 n_points: Optional[int] = None,
                 direction=(0.0, 0.0, 1.0)) -> bool:
    """Overwrite the curve with a starting shape and rebuild the nodes on it."""
    curve_obj = get_curve(spec, owner)
    if curve_obj is None or not curve_obj.data.splines:
        return False

    if n_points is None:
        n_points = len(curve_obj.data.splines[0].bezier_points)
    n_points = max(RES_MIN, min(RES_MAX, int(n_points)))

    remove_nodes(spec, owner)

    curve_data = curve_obj.data
    for spline in list(curve_data.splines):
        curve_data.splines.remove(spline)
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(n_points - 1)
    for i, (co, _l, _r) in enumerate(
            preset_points(preset, length, n_points, direction)):
        spline.bezier_points[i].co = Vector(co)
    set_aligned_handles_along_path(spline)
    curve_data.update_tag()

    create_nodes(spec, owner, curve_obj, n_points)
    return True


def _perpendicular(axis: Vector) -> Vector:
    """Any unit vector at right angles to *axis*, chosen so it never degenerates."""
    cardinal = [Vector((1.0, 0.0, 0.0)),
                Vector((0.0, 1.0, 0.0)),
                Vector((0.0, 0.0, 1.0))]
    least = min(cardinal, key=lambda v: abs(axis.dot(v)))
    return axis.cross(least).normalized()


# ---------------------------------------------------------------------------
# Animation custody across a rebuild
# ---------------------------------------------------------------------------

def _bind_action(id_data, action) -> None:
    """Assign *action*, binding a slot where the file uses slotted actions.

    Blender 4.4+ auto-binds the slot whose name matches the ID's, which is why
    a rebuild keeps the old names - but fall back to the action's first slot if
    that lookup came up empty, or the channels sit in the action driving
    nothing.
    """
    if id_data is None or action is None:
        return
    if id_data.animation_data is None:
        id_data.animation_data_create()
    id_data.animation_data.action = action
    animation = id_data.animation_data
    if hasattr(animation, "action_slot") and animation.action_slot is None:
        slots = getattr(action, "slots", None)
        if slots:
            try:
                animation.action_slot = slots[0]
            except Exception:
                pass


def capture_animation(spec: BendRigSpec, owner) -> dict:
    """Take custody of the animation on an owner and its control nodes.

    A rebuild recreates the Empties from scratch, and they carry the F-curves
    that make a bend *animate*. Without this every keyframe is silently
    discarded the next time the rig is rebuilt. Each captured action gets a
    fake user so deleting its owner does not free it while it is held.
    """
    stash = {"owner": None, "nodes": []}
    if owner is None:
        return stash

    def take(obj):
        animation = getattr(obj, "animation_data", None)
        action = animation.action if animation else None
        if action is not None:
            action.use_fake_user = True
        return action

    stash["owner"] = take(owner)
    stash["nodes"] = [take(node) for node in get_nodes(spec, owner)]
    return stash


def restore_animation(spec: BendRigSpec, owner, stash) -> None:
    """Re-bind what :func:`capture_animation` took.

    Nodes are matched by position: they are rebuilt in Bezier-point order, so
    node *i* afterwards is the handle the user keyed as node *i* before. A
    node's local ``location`` is its world position, so the old F-curve values
    still mean the same place.
    """
    if not stash or owner is None:
        return
    _bind_action(owner, stash.get("owner"))
    for node, action in zip(get_nodes(spec, owner), stash.get("nodes") or []):
        _bind_action(node, action)

    # Drop the fake users again - these actions have real owners now. Anything
    # that could not be re-bound (the node count changed) keeps its fake user
    # so the user can still recover it from the Dope Sheet.
    for action in [stash.get("owner")] + list(stash.get("nodes") or []):
        if action is not None and action.users > 1:
            action.use_fake_user = False


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def remove_rig(spec: BendRigSpec, owner) -> None:
    """Delete the control nodes, the curve, and the properties naming them."""
    remove_nodes(spec, owner)

    name = owner.get(spec.curve_prop)
    if not name:
        return

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
    owner.pop(spec.curve_prop, None)


def cleanup_orphans(spec: BendRigSpec, extra_node_patterns: Sequence[str] = ()) -> None:
    """Delete curves and nodes whose owner has gone.

    Deliberately not driven from a depsgraph handler: removing objects inside
    ``depsgraph_update_post`` mutates the depsgraph and re-enters. Callers run
    this at deterministic moments instead - file load, and just before building
    a new rig.
    """
    live_curves, live_nodes = set(), set()
    for obj in bpy.data.objects:
        if not spec.owns(obj):
            continue
        curve_name = obj.get(spec.curve_prop)
        if curve_name:
            live_curves.add(curve_name)
        raw = obj.get(spec.nodes_prop)
        if raw:
            try:
                live_nodes.update(json.loads(raw))
            except (ValueError, TypeError):
                pass

    node_patterns = [f" {spec.node_label} "] + list(extra_node_patterns)

    doomed = []
    for obj in bpy.data.objects:
        if obj.type == "CURVE" and obj.name.endswith(spec.curve_suffix):
            if obj.name not in live_curves:
                doomed.append(obj)
        elif obj.type == "EMPTY" and any(p in obj.name for p in node_patterns):
            if obj.name not in live_nodes:
                doomed.append(obj)

    for obj in doomed:
        data = obj.data
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            continue
        if data is not None and getattr(data, "users", 1) == 0:
            try:
                if isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Reading the finished path
# ---------------------------------------------------------------------------

def sample_along(curve_obj, arc_lengths: Sequence[float],
                 samples_per_segment: int = _SAMPLES_PER_SEGMENT
                 ) -> List[Tuple[Vector, Vector, Vector]]:
    """``(position, tangent, normal)`` in world space at each arc length.

    Reads the *evaluated* curve, so the hook deformation the user dragged into
    place is included - the source ``bezier_points`` would describe the path
    before their edits, which is the same trap
    :func:`bake_evaluated_curve_shape` exists for.

    The normal is carried forward from one sample to the next (a rotation-
    minimising frame) rather than recomputed from the curvature. A Frenet
    normal flips sign wherever the path has an inflection, which would snap
    every subunit past that point a half-turn around the filament.

    Arc lengths past the end of the path continue straight on along the final
    tangent, so asking for more subunits than the curve is long extends the
    filament rather than piling them all on the last point.
    """
    polyline, lengths = _world_polyline(curve_obj, samples_per_segment)
    if len(polyline) < 2:
        return []

    frames = _rotation_minimising_frames(polyline)
    total = lengths[-1]

    out = []
    for target in arc_lengths:
        target = float(target)
        if target <= total:
            position = _at_arc_length(polyline, lengths, target)
            tangent, normal = _frame_at(frames, lengths, target)
        else:
            # Off the end: carry on in a straight line from the last point.
            tangent, normal = frames[-1]
            position = polyline[-1] + tangent * (target - total)
        out.append((position, tangent, normal))
    return out


def curve_length(curve_obj, samples_per_segment: int = _SAMPLES_PER_SEGMENT) -> float:
    """Total arc length of the evaluated curve, in Blender units."""
    _polyline, lengths = _world_polyline(curve_obj, samples_per_segment)
    return lengths[-1] if lengths else 0.0


def _world_polyline(curve_obj, samples_per_segment):
    """The evaluated curve as world-space points, with cumulative lengths."""
    if curve_obj is None:
        return [], []

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = curve_obj.evaluated_get(depsgraph)
    data = evaluated.data
    if data is None or not getattr(data, "splines", None):
        return [], []

    spline = data.splines[0]
    to_world = evaluated.matrix_world

    if spline.type == "BEZIER" and len(spline.bezier_points) >= 2:
        local = _flatten_dense(spline, samples_per_segment)
    else:
        local = [p.co.to_3d() for p in getattr(spline, "points", [])]

    polyline = [to_world @ p for p in local]
    if len(polyline) < 2:
        return polyline, [0.0] * len(polyline)

    lengths = [0.0]
    for i in range(1, len(polyline)):
        lengths.append(lengths[-1] + (polyline[i] - polyline[i - 1]).length)
    return polyline, lengths


def _flatten_dense(spline, samples_per_segment):
    points = spline.bezier_points
    out = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        segment = interpolate_bezier(
            a.co, a.handle_right, b.handle_left, b.co, samples_per_segment)
        out.extend(segment[:-1] if i < len(points) - 2 else segment)
    return out


def _rotation_minimising_frames(polyline):
    """A tangent and a normal at every polyline vertex, carried forward.

    The double-reflection method: each frame is the previous one transported
    onto the next tangent, which keeps the normal from spinning about the path
    and never flips it at an inflection.
    """
    count = len(polyline)
    tangents = []
    for i in range(count):
        if i == 0:
            direction = polyline[1] - polyline[0]
        elif i == count - 1:
            direction = polyline[-1] - polyline[-2]
        else:
            direction = polyline[i + 1] - polyline[i - 1]
        if direction.length < 1e-12:
            direction = Vector((0.0, 0.0, 1.0))
        tangents.append(direction.normalized())

    normal = _perpendicular(tangents[0])
    frames = [(tangents[0], normal)]
    for i in range(1, count):
        previous_tangent, previous_normal = frames[-1]
        transported = _transport(previous_normal, previous_tangent, tangents[i])
        frames.append((tangents[i], transported))
    return frames


def _transport(normal: Vector, from_tangent: Vector, to_tangent: Vector) -> Vector:
    """Rotate *normal* by the shortest rotation taking one tangent to the other."""
    axis = from_tangent.cross(to_tangent)
    if axis.length < 1e-9:
        # Parallel (or antiparallel) tangents: nothing to transport around.
        return normal.copy()
    angle = from_tangent.angle(to_tangent)
    rotation = mathutils.Matrix.Rotation(angle, 3, axis.normalized())
    moved = rotation @ normal
    # Re-orthogonalise against drift accumulated over many steps.
    moved -= to_tangent * moved.dot(to_tangent)
    if moved.length < 1e-9:
        return _perpendicular(to_tangent)
    return moved.normalized()


def _frame_at(frames, lengths, target: float):
    index = 0
    while index < len(lengths) - 1 and lengths[index + 1] < target:
        index += 1
    if index >= len(frames) - 1:
        return frames[-1]

    span = lengths[index + 1] - lengths[index]
    t = (target - lengths[index]) / span if span > 0 else 0.0

    tangent_a, normal_a = frames[index]
    tangent_b, normal_b = frames[index + 1]
    tangent = tangent_a.lerp(tangent_b, t)
    if tangent.length < 1e-9:
        tangent = tangent_a.copy()
    tangent = tangent.normalized()

    normal = normal_a.lerp(normal_b, t)
    normal -= tangent * normal.dot(tangent)
    if normal.length < 1e-9:
        normal = _perpendicular(tangent)
    return tangent, normal.normalized()
