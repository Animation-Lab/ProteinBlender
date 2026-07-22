"""Per-object membrane force fields.

Any mesh object (protein, chain, or domain) with ``pb_force_field_enabled``
set on it pushes lipids aside on every membrane in the scene — the membrane
parts around it instead of clipping through. The math reuses the membrane
GN tree's pusher path (see ``membrane_geometry.py``); this module is
responsible for tracking which objects emit a force field, computing each
one's effective radius, and writing the values into the GN modifier's
Protein FF slots.

**Why per-object, not per-protein.** Splitting a protein into chains and
puppeting only some of them is the common case (e.g. an actin monomer
with chain A driven by a separate controller). Storing the FF flag on the
*protein* and using a whole-subtree centroid means the FF anchor only
shifts partway when the puppet moves and the bounding-sphere radius
inflates to span the un-moved chains. Storing the flag on the chain (or
domain) itself, and parenting the anchor to that chain, means the anchor
inherits the chain's world transform for free — moving a puppet member
moves its FF anchor exactly with it.

Sizing:
    R_BU = _local_bbox_extent(obj) / 2  +  spacing_nm / NM_PER_BU

The bbox is read in the *object's own local mesh space* (then scaled by
the world scale). That's the natural frame for a chain / domain, and it
gives the same answer the old whole-subtree pass used to give for the
protein case (since a protein with no children is itself the only mesh).

Anchor lifecycle:
  * Anchor is a hidden Empty named ``{obj.name}.ff_anchor``.
  * ``anchor.parent = obj``, so the anchor's world transform tracks the
    object via the normal parent/child transform stack. No per-frame
    world-location syncing needed — Blender's parenting handles it.
  * ``anchor.location`` is set once (at create time) to the object's
    local-space mesh centroid; subsequent transform changes of the
    object propagate through the parent transform to the anchor's
    world position automatically.
  * On a deletion or FF-flag flip-off, the orphan reaper removes
    the anchor (see ``_remove_orphan_ff_anchors``).

The depsgraph handler still kicks every membrane modifier when an
FF-emitter moves — GN Object-Info dependencies set via Python
assignment aren't always re-evaluated on transform changes alone, so
this is a defensive nudge.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from typing import Iterable, List, Optional, Tuple

from ..utils import gn_compat
from .membrane_geometry import MAX_PROTEIN_FFS, NM_PER_BU


# Anchors are hidden Empties — one per FF-enabled object — *parented* to
# their owning object. Naming: ``{owner.name}.ff_anchor``. The marker prop
# is used by the orphan reaper to find anchors regardless of owner state.
_FF_ANCHOR_SUFFIX = ".ff_anchor"
_FF_ANCHOR_MARKER = "pb_is_ff_anchor"
_FF_ANCHOR_OWNER_PROP = "pb_ff_anchor_owner"


# ---------------------------------------------------------------------------
# RNA props on bpy.types.Object — registered once at addon load.
# ---------------------------------------------------------------------------
#
# We register on the generic Object type (rather than a custom
# PropertyGroup) so the panel can do `layout.prop(obj, "pb_force_field_*")`
# and the update callback fires automatically — same wiring an ID custom
# property would NOT give us. Every Blender object then carries these
# props (default off), which is fine: storage cost is tiny and the
# panel only surfaces them when the selection points at a chain /
# domain / protein mesh.

def _on_ff_changed(context):
    """Fired whenever any object's FF enable / spacing prop is mutated."""
    try:
        scene = context.scene if context else (bpy.context.scene if bpy.context else None)
        apply_to_all_membranes(scene)
    except Exception:
        pass


def _register_object_props() -> None:
    bpy.types.Object.pb_force_field_enabled = bpy.props.BoolProperty(
        name="Membrane Force Field",
        description=(
            "When on, lipid bilayers in the scene part around this object as "
            "it moves — same physics as a membrane hole, sized by the "
            "object's own bounding sphere + the spacing slider. Works on "
            "proteins, chains, and domains: puppeted chains carry the FF "
            "anchor with them via the parent transform."
        ),
        default=False,
        update=lambda self, context: _on_ff_changed(context),
    )
    bpy.types.Object.pb_force_field_spacing = bpy.props.FloatProperty(
        name="Force Field Spacing",
        description=(
            "Extra clearance (in nm) added beyond this object's bounding "
            "sphere. Bigger value → wider gap in the membrane around it"
        ),
        default=1.5,
        min=0.0,
        max=20.0,
        soft_max=5.0,
        update=lambda self, context: _on_ff_changed(context),
    )


def _unregister_object_props() -> None:
    for attr in ("pb_force_field_enabled", "pb_force_field_spacing"):
        try:
            delattr(bpy.types.Object, attr)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FF emitter inventory
# ---------------------------------------------------------------------------

def iter_ff_emitter_objects() -> Iterable[bpy.types.Object]:
    """Yield every Blender object whose ``pb_force_field_enabled`` is on
    and is itself not an FF anchor. Order matches ``bpy.data.objects``
    iteration so slot assignment is deterministic across sessions."""
    for obj in bpy.data.objects:
        if obj.get(_FF_ANCHOR_MARKER, False):
            continue
        if getattr(obj, "pb_force_field_enabled", False):
            yield obj


def _evaluated_coords_local(obj: bpy.types.Object):
    """Return an Nx3 numpy array of the evaluated mesh's vertex coordinates
    in obj's local space, or None if no usable vertices.

    Reading the *evaluated* mesh is critical: a per-chain object inherits
    the parent protein's full 5k-vert atom cloud as its raw mesh data,
    and a ``DomainNodes`` Geometry-Nodes modifier filters it down to
    only that chain's atoms at evaluation time. Reading
    ``obj.data.vertices`` would give us the whole protein's centroid /
    bbox, not the chain's. The same logic applies to domain children.

    Coords are returned in obj's local space (no matrix_world applied)
    because anchor.location is interpreted in obj's local frame.
    """
    import numpy as np
    if obj is None or obj.type != "MESH":
        return None
    deps = bpy.context.evaluated_depsgraph_get() if bpy.context else None
    if deps is None:
        return None
    eo = obj.evaluated_get(deps)
    mesh = getattr(eo, "data", None)
    if mesh is None:
        return None
    n = len(mesh.vertices)
    if n == 0:
        return None
    coords = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    return coords.reshape(n, 3)


def _local_centroid(obj: bpy.types.Object) -> Optional[Vector]:
    """Mean vertex position in obj's local space, from the *evaluated* mesh.

    Parented to obj, anchor.location is interpreted in obj's local frame,
    so storing the local centroid there means anchor.matrix_world ends
    up at obj.matrix_world @ centroid_local — exactly the chain's visual
    centre, tracked live through any puppet transform.
    """
    coords = _evaluated_coords_local(obj)
    if coords is None:
        return None
    mean = coords.mean(axis=0)
    return Vector((float(mean[0]), float(mean[1]), float(mean[2])))


def _world_centroid(obj: bpy.types.Object) -> Optional[Vector]:
    """Owner's evaluated mesh centroid in WORLD space.

    ``_local_centroid`` gives the centroid in the owner's local frame; mapping
    it through ``matrix_world`` gives the point in world space, including the
    owner's height above or below the membrane. That Z is exactly what the FF
    needs and what parenting failed to deliver.
    """
    local = _local_centroid(obj)
    if local is not None:
        return obj.matrix_world @ local
    # A molecule renders as a geometry-nodes point cloud, so its evaluated
    # *mesh* has zero vertices and _local_centroid measures nothing - which is
    # why the anchor was never positioned and stayed at the world origin
    # regardless of where the protein was. The object's origin is a good
    # stand-in: import centres the atoms on it. What matters most here is that
    # it carries the object's world Z, so the anchor finally tracks height.
    return obj.matrix_world.translation.copy()


def _local_bbox_extent(obj: bpy.types.Object) -> float:
    """Longest axis of the object's local-space *evaluated* mesh AABB,
    scaled by the world-scale magnitude.

    Falls back to ``obj.dimensions`` only if no evaluated geometry is
    available (e.g. a split-protein parent whose own MN modifier emits
    nothing — the chain children would be the things to FF in that case
    anyway, so this fallback is for safety, not the common path).
    """
    coords = _evaluated_coords_local(obj)
    if coords is None:
        dim = obj.dimensions
        return float(max(dim.x, dim.y, dim.z))
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    span = float((maxs - mins).max())
    try:
        span *= max(abs(s) for s in obj.matrix_world.to_scale())
    except Exception:
        pass
    return span


def compute_force_field_radius_bu(obj: bpy.types.Object,
                                   spacing_nm: float) -> float:
    """Return the force-field radius in Blender Units for one FF emitter."""
    if obj is None:
        return 0.0
    half_extent_bu = _local_bbox_extent(obj) / 2.0
    spacing_bu = max(0.0, float(spacing_nm)) / NM_PER_BU
    return half_extent_bu + spacing_bu


# ---------------------------------------------------------------------------
# FF anchor lifecycle
# ---------------------------------------------------------------------------

def _ensure_ff_anchor(owner_obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    """Get-or-create the hidden anchor Empty for an FF-emitting object.

    Anchor is parented to ``owner_obj`` so its world transform follows
    automatically as the owner is moved / puppeteered. Local position
    is the owner's mesh centroid (in owner-local space).
    """
    if owner_obj is None:
        return None
    name = f"{owner_obj.name}{_FF_ANCHOR_SUFFIX}"
    anchor = bpy.data.objects.get(name)
    if anchor is None:
        anchor = bpy.data.objects.new(name, None)
        anchor.empty_display_type = "PLAIN_AXES"
        anchor.empty_display_size = 0.05
        anchor[_FF_ANCHOR_MARKER] = True
        try:
            bpy.context.scene.collection.objects.link(anchor)
        except Exception:
            pass
        anchor.hide_set(True)
        anchor.hide_viewport = True
        anchor.hide_render = True
        anchor.hide_select = True

    # Drive the anchor's WORLD position directly to the owner's mesh centroid,
    # unparented.
    #
    # This used to parent the anchor to the owner and store the local centroid,
    # trusting Blender to propagate the owner's transform to the child. That
    # silently failed for Z: a molecule object at z = 20 left its parented
    # anchor evaluated at z = 0 (identity parent-inverse, zero local offset, yet
    # the child's matrix_world.z stayed 0), so a protein lifted far off the
    # membrane still carved a hole - the force field behaved as an infinite
    # vertical column instead of a 3D body. Writing the world position directly
    # makes the anchor's Z track the protein. apply_to_all_membranes (FF
    # toggles) and _deferred_membrane_refresh (emitter moves) both re-sync it,
    # so it follows the owner through ordinary moves and puppet transforms.
    anchor[_FF_ANCHOR_OWNER_PROP] = owner_obj.name
    if anchor.parent is not None:
        anchor.parent = None
        anchor.matrix_parent_inverse.identity()
    world_centre = _world_centroid(owner_obj)
    if world_centre is not None:
        anchor.location = world_centre
    return anchor


def _remove_orphan_ff_anchors(scene: Optional[bpy.types.Scene] = None) -> None:
    """Delete anchor Empties whose owner is gone or has FF turned off."""
    active_owner_names = {obj.name for obj in iter_ff_emitter_objects()}
    for obj in list(bpy.data.objects):
        if not obj.get(_FF_ANCHOR_MARKER, False):
            continue
        owner = obj.get(_FF_ANCHOR_OWNER_PROP, "")
        if owner in active_owner_names and bpy.data.objects.get(owner) is not None:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Slot collection
# ---------------------------------------------------------------------------

def iter_active_force_fields(scene: Optional[bpy.types.Scene]
                              ) -> Iterable[Tuple[bpy.types.Object, float]]:
    """Yield ``(owner_object, radius_BU)`` for each FF-enabled object.

    The *owner* itself is handed to the geometry-nodes tree, whose Object Info
    node reads its live evaluated position - so the field tracks the protein as
    it moves, with no anchor Empty and no Python-side transform read. The anchor
    is still created (it is the visible marker and what the orphan reaper
    tracks) but the tree no longer reads it.
    """
    for owner in iter_ff_emitter_objects():
        spacing_nm = float(getattr(owner, "pb_force_field_spacing", 1.5))
        radius_bu = compute_force_field_radius_bu(owner, spacing_nm)
        if radius_bu <= 0.0:
            continue
        _ensure_ff_anchor(owner)  # marker + orphan-reaper bookkeeping only
        yield owner, radius_bu


def collect_force_field_slots(scene: Optional[bpy.types.Scene]
                               ) -> List[Tuple[bpy.types.Object, float]]:
    """Return up to MAX_PROTEIN_FFS active (owner, radius) entries."""
    out: List[Tuple[bpy.types.Object, float]] = []
    for entry in iter_active_force_fields(scene):
        out.append(entry)
        if len(out) >= MAX_PROTEIN_FFS:
            break
    return out


# ---------------------------------------------------------------------------
# Membrane wiring
# ---------------------------------------------------------------------------

def _set_mod_input(mod: bpy.types.Modifier, socket_name: str, value) -> None:
    """Set a GN modifier input. See ``gn_compat`` for the 4.2/5.1 vs 5.2 split."""
    gn_compat.set_modifier_input(mod, socket_name, value)


def _refresh_modifier(mod: bpy.types.Modifier) -> None:
    try:
        mod.show_render = not mod.show_render
        mod.show_render = not mod.show_render
        if mod.id_data is not None:
            mod.id_data.update_tag()
    except Exception:
        pass


def _get_gn_modifier(root_obj: bpy.types.Object) -> Optional[bpy.types.Modifier]:
    from .membrane_operators import GN_MOD_NAME
    for mod in root_obj.modifiers:
        if mod.type == "NODES" and mod.name == GN_MOD_NAME:
            return mod
    return None


def apply_force_fields_to_membrane(root_obj: bpy.types.Object,
                                    scene: Optional[bpy.types.Scene] = None,
                                    defer_refresh: bool = False,
                                    ) -> None:
    """Write the current scene's active force fields into one membrane.

    Empty slots (up to the tree's current FF capacity) are cleared so a
    membrane built before any objects had FFs on doesn't carry stale
    assignments. The shared tree is grown via
    ``get_or_build_membrane_gn_tree`` first when scene demand exceeds
    capacity, and the modifier is re-pointed at the rebuilt tree if it
    had been dropped during the rebuild.

    ``defer_refresh=True`` skips the trailing modifier refresh — used
    by Build Membrane to batch input writes into a single GN re-eval.
    """
    if root_obj is None or not root_obj.get("pb_is_membrane", False):
        return

    if scene is None:
        scene = bpy.context.scene if bpy.context else None

    from .membrane_geometry import get_or_build_membrane_gn_tree
    tree = get_or_build_membrane_gn_tree(scene)

    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return
    # != , not `is not` - see the note in membrane_operators. A fresh
    # wrapper per access makes `is not` always True, and reassigning
    # node_group wipes the modifier's inputs.
    if mod.node_group != tree:
        mod.node_group = tree

    slots = collect_force_field_slots(scene) if scene is not None else []
    tree_ffs = int(tree.get("pb_active_ffs", MAX_PROTEIN_FFS))

    for i in range(1, tree_ffs + 1):
        if i <= len(slots):
            owner, radius_bu = slots[i - 1]
            _set_mod_input(mod, f"Protein FF {i}", owner)
            _set_mod_input(mod, f"Protein FF {i} Enabled", True)
            _set_mod_input(mod, f"Protein FF {i} Radius", float(radius_bu))
        else:
            _set_mod_input(mod, f"Protein FF {i}", None)
            _set_mod_input(mod, f"Protein FF {i} Enabled", False)
            _set_mod_input(mod, f"Protein FF {i} Radius", 0.0)

    if not defer_refresh:
        _refresh_modifier(mod)


def apply_to_all_membranes(scene: Optional[bpy.types.Scene] = None) -> None:
    """Push the current FF list to every membrane in the scene, then sweep
    up anchors whose owner is gone or no longer has FF on."""
    if scene is None:
        scene = bpy.context.scene if bpy.context else None

    # Reposition every anchor to its owner's world centre, then flush the
    # depsgraph BEFORE any membrane reads them. The membrane's Geometry-Nodes
    # tree reads each anchor through an Object Info node, which sees the
    # anchor's *evaluated* transform. If the anchor is moved and the membrane
    # re-evaluated in the same pass without a flush in between, Object Info
    # reads the anchor's previous position - so a protein that just moved off
    # the membrane still carved a hole at its old spot for one refresh. Moving
    # the anchors first and updating the view layer makes the evaluated
    # transforms current before the membranes consume them.
    for owner in iter_ff_emitter_objects():
        _ensure_ff_anchor(owner)
    try:
        view_layer = bpy.context.view_layer if bpy.context else None
        if view_layer is not None:
            view_layer.update()
    except Exception:
        pass

    for obj in bpy.data.objects:
        if obj.get("pb_is_membrane", False):
            apply_force_fields_to_membrane(obj, scene)
    _remove_orphan_ff_anchors(scene)


# ---------------------------------------------------------------------------
# Depsgraph sync — keep membranes responsive to FF emitter movement
# ---------------------------------------------------------------------------
#
# Anchor *location* is handled by Blender's parent-transform chain — no
# manual sync needed. What we still need is a defensive modifier kick:
# Object-typed GN inputs assigned via Python don't reliably register a
# depsgraph relation that would re-evaluate the membrane modifier when
# the source object moves. Without this handler the carved gap can stay
# at the FF emitter's old position until something else dirties the
# membrane.

_object_count_cache = [-1]


def _deferred_ff_reapply():
    try:
        _remove_orphan_ff_anchors()
        apply_to_all_membranes()
    except Exception:
        pass
    return None  # one-shot


def _deferred_membrane_refresh():
    """Kick every membrane modifier so its Object Info nodes re-read the live
    positions of the force-field proteins after one moved. Runs outside the
    depsgraph handler so it can safely mutate modifier state.

    The field's centre comes from an Object Info node reading the protein
    (v34), so its position tracks automatically when the geometry-nodes tree
    re-evaluates. An Object socket assigned from Python does not always register
    the dependency that would trigger that re-evaluation on its own, so this
    forces it - the same defensive kick a hole controller relies on."""
    try:
        for obj in bpy.data.objects:
            if not obj.get("pb_is_membrane", False):
                continue
            for mod in obj.modifiers:
                if mod.type == "NODES":
                    mod.show_viewport = False
                    mod.show_viewport = True
            obj.update_tag()
        if bpy.context and bpy.context.view_layer:
            bpy.context.view_layer.update()
    except Exception:
        pass
    return None  # one-shot


def _ff_watched_names(scene) -> set:
    """Names whose transform should kick a membrane refresh: every
    FF-enabled object (one per emitter, parented anchor follows for free)."""
    return {obj.name for obj in iter_ff_emitter_objects()}


@persistent
def _on_depsgraph_check(scene, depsgraph):
    try:
        # Deletion path: an FF-emitter or anchor going away leaves stale
        # references in the membrane modifier; schedule a re-apply.
        count = len(bpy.data.objects)
        prev = _object_count_cache[0]
        _object_count_cache[0] = count
        if 0 <= prev and count < prev:
            if not bpy.app.timers.is_registered(_deferred_ff_reapply):
                bpy.app.timers.register(_deferred_ff_reapply,
                                        first_interval=0.0)

        # Movement path: any watched emitter (or its parent up the
        # transform stack) moving means matrix_world changed on the
        # emitter too, which Blender's depsgraph reports as
        # is_updated_transform on the emitter object itself.
        watched = _ff_watched_names(scene)
        if not watched:
            return
        moved = any(
            isinstance(upd.id, bpy.types.Object)
            and upd.is_updated_transform
            and upd.id.name in watched
            for upd in depsgraph.updates
        )
        if moved and not bpy.app.timers.is_registered(_deferred_membrane_refresh):
            bpy.app.timers.register(_deferred_membrane_refresh,
                                    first_interval=0.0)
    except Exception:
        pass


@persistent
def _on_load_post(_dummy):
    # New file → reset the object-count baseline and re-apply, so the
    # membrane modifiers' FF inputs come up aligned with the actual
    # post-load set of FF-emitting objects.
    _object_count_cache[0] = -1
    if not bpy.app.timers.is_registered(_deferred_ff_reapply):
        bpy.app.timers.register(_deferred_ff_reapply, first_interval=0.0)


def register() -> None:
    _register_object_props()
    if _on_depsgraph_check not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_check)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    if _on_depsgraph_check in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_check)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _unregister_object_props()
