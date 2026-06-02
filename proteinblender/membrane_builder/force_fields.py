"""Per-protein membrane force fields.

A protein with ``force_field_enabled`` on the MoleculeListItem pushes lipids
aside on every membrane in the scene — the membrane parts around it instead
of clipping through. The math reuses the membrane GN tree's pusher path
(see ``membrane_geometry.py``); this module just figures out which proteins
are active, computes each one's effective radius, and writes the values
into the GN modifier's Protein FF slots.

Sizing:
    R_BU = _protein_tallest_dim_bu(obj) / 2  +  spacing_nm / NM_PER_BU

That is, half the protein's longest atom-cloud extent (NOT ``obj.dimensions``
— the MN modifier's output mesh under-reports the rendered size) plus the
user's clearance.

Two depsgraph-driven sync paths live at the bottom of the module:
  * deletion → re-apply (clear stale slots)
  * movement → membrane refresh (kick the modifier so Object Info re-reads
    the protein's live transform)
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from typing import Iterable, List, Optional, Tuple

from .membrane_geometry import MAX_PROTEIN_FFS, NM_PER_BU


# Anchors are hidden Empties — one per FF-enabled protein — whose
# ``.location`` is set to the centroid of the protein's *rendered*
# descendants (the parent's MN modifier is off once a molecule is split
# into domains, so the parent itself doesn't move when the user grabs a
# chain). The anchor is what gets wired into the GN modifier's FF slot
# so Object Info reads a location that actually follows the rendered
# geometry. Name pattern: ``{protein.name}.ff_anchor``.
_FF_ANCHOR_SUFFIX = ".ff_anchor"
_FF_ANCHOR_MARKER = "pb_is_ff_anchor"
_FF_ANCHOR_OWNER_PROP = "pb_ff_anchor_owner"


def _ff_protein_object(item) -> Optional[bpy.types.Object]:
    """Return the Blender object for a MoleculeListItem, healing if needed."""
    try:
        return item.get_valid_object()
    except Exception:
        # Older items / partial state — fall back to direct lookups.
        if getattr(item, "object_ptr", None):
            return item.object_ptr
        name = getattr(item, "object_name", "") or ""
        return bpy.data.objects.get(name) if name else None


def _render_objects_for(obj: bpy.types.Object) -> List[bpy.types.Object]:
    """Return every mesh object whose vertices represent the molecule's
    rendered atom cloud — the parent if it still has mesh data, plus
    every descendant with a populated mesh.

    When a molecule is split into domains, the parent's MN modifier is
    disabled to avoid double-render and its mesh datablock is typically
    empty; the live atom cloud lives on the domain children. Force-field
    sizing and positioning have to walk the whole subtree to get the real
    rendered footprint.
    """
    if obj is None:
        return []
    out: List[bpy.types.Object] = []
    candidates = [obj] + list(getattr(obj, "children_recursive", []) or [])
    for o in candidates:
        if o is None or o.type != "MESH":
            continue
        # Skip our own bookkeeping objects.
        if o.get(_FF_ANCHOR_MARKER, False):
            continue
        data = getattr(o, "data", None)
        verts = getattr(data, "vertices", None) if data is not None else None
        if verts and len(verts) > 0:
            out.append(o)
    return out


def _world_bbox_extent(objs: List[bpy.types.Object]) -> float:
    """Return the longest world-space bbox axis spanning all ``objs``.

    Computes the union of every object's mesh-vertex AABB transformed
    into world space. Returns 0 if no usable mesh data is found.
    """
    if not objs:
        return 0.0
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            wp = mw @ v.co
            xs.append(wp.x)
            ys.append(wp.y)
            zs.append(wp.z)
    if not xs:
        return 0.0
    return float(max(max(xs) - min(xs),
                      max(ys) - min(ys),
                      max(zs) - min(zs)))


def _world_centroid(objs: List[bpy.types.Object]) -> Optional[Vector]:
    """Return the mean world-space vertex centroid across ``objs``, or
    None if no vertex data is available.

    Vertex-mean (not object-origin mean) so the centroid reflects what's
    actually rendered: each domain object's origin is typically still at
    the molecule's original centre, so an origin-mean would just return
    the parent's location even after the user drags one chain aside.
    """
    if not objs:
        return None
    cx = cy = cz = 0.0
    n = 0
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            wp = mw @ v.co
            cx += wp.x
            cy += wp.y
            cz += wp.z
            n += 1
    if n == 0:
        return None
    return Vector((cx / n, cy / n, cz / n))


def compute_force_field_radius_bu(obj: bpy.types.Object,
                                   spacing_nm: float) -> float:
    """Return the force-field radius in Blender Units.

    Half the protein's tallest extent (the bounding-cube radius along its
    longest axis) plus the user's clearance. Spans every rendered
    descendant: when a molecule is split into domains the parent's mesh
    is empty so reading it alone would yield a zero radius.
    """
    if obj is None:
        return 0.0
    render_objs = _render_objects_for(obj)
    if render_objs:
        half_extent_bu = _world_bbox_extent(render_objs) / 2.0
    else:
        half_extent_bu = _protein_tallest_dim_bu(obj) / 2.0
    spacing_bu = max(0.0, float(spacing_nm)) / NM_PER_BU
    return half_extent_bu + spacing_bu


def _protein_tallest_dim_bu(obj: bpy.types.Object) -> float:
    """Single-object fallback radius source.

    Kept for the rare case where the molecule has no rendered descendants
    (loading mid-init, broken state). For MN-rendered proteins
    ``obj.dimensions`` reflects whatever subset the MolecularNodes
    modifier emits, not the real atom cloud — for a typical actin import
    it reads ~20× smaller than the real size. Use the raw vertex bbox of
    ``obj.data`` when available, and only fall back to ``obj.dimensions``
    for non-mesh objects or empty meshes.
    """
    if obj is None:
        return 0.0
    data = getattr(obj, "data", None)
    verts = getattr(data, "vertices", None) if data is not None else None
    if verts and len(verts) > 0:
        xs = [v.co.x for v in verts]
        ys = [v.co.y for v in verts]
        zs = [v.co.z for v in verts]
        span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        # Object's world scale stretches the rendered protein — fold it in.
        try:
            span *= max(abs(s) for s in obj.scale)
        except Exception:
            pass
        return float(span)
    dim = obj.dimensions
    return float(max(dim.x, dim.y, dim.z))


# ---------------------------------------------------------------------------
# FF anchor lifecycle
# ---------------------------------------------------------------------------

def _ensure_ff_anchor(protein_obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    """Get-or-create the hidden anchor Empty for an FF-enabled protein.

    The anchor's ``.location`` is set to the world-space centroid of the
    protein's rendered descendants; the GN FF slot is wired to the anchor
    (not the protein itself), so a child move flows through anchor →
    Object Info → carved gap. Returns None if the protein has no rendered
    geometry yet.
    """
    if protein_obj is None:
        return None
    name = f"{protein_obj.name}{_FF_ANCHOR_SUFFIX}"
    anchor = bpy.data.objects.get(name)
    if anchor is None:
        anchor = bpy.data.objects.new(name, None)
        anchor.empty_display_type = "PLAIN_AXES"
        anchor.empty_display_size = 0.05
        anchor[_FF_ANCHOR_MARKER] = True
        anchor[_FF_ANCHOR_OWNER_PROP] = protein_obj.name
        try:
            bpy.context.scene.collection.objects.link(anchor)
        except Exception:
            pass
        anchor.hide_set(True)
        anchor.hide_viewport = True
        anchor.hide_render = True
        anchor.hide_select = True
    sync_ff_anchor_location(anchor, protein_obj)
    return anchor


def sync_ff_anchor_location(anchor: bpy.types.Object,
                             protein_obj: bpy.types.Object) -> None:
    """Set ``anchor.location`` to the current centroid of the protein's
    rendered descendants. No-op if no vertex data is available."""
    if anchor is None or protein_obj is None:
        return
    centroid = _world_centroid(_render_objects_for(protein_obj))
    if centroid is None:
        return
    anchor.location = centroid


def sync_all_ff_anchors(scene: Optional[bpy.types.Scene] = None) -> None:
    """Refresh every active FF anchor's location from current scene state.

    Called from the deferred refresh after a move, and before slot writes
    so the modifier reads the up-to-date centroid on the next eval.
    """
    if scene is None:
        scene = bpy.context.scene if bpy.context else None
    if scene is None or not hasattr(scene, "molecule_list_items"):
        return
    for item in scene.molecule_list_items:
        if not getattr(item, "force_field_enabled", False):
            continue
        protein = _ff_protein_object(item)
        if protein is None:
            continue
        name = f"{protein.name}{_FF_ANCHOR_SUFFIX}"
        anchor = bpy.data.objects.get(name)
        if anchor is None:
            anchor = _ensure_ff_anchor(protein)
        else:
            sync_ff_anchor_location(anchor, protein)


def _remove_orphan_ff_anchors(scene: Optional[bpy.types.Scene] = None) -> None:
    """Delete anchor Empties whose owning protein either no longer exists
    or no longer has its force_field_enabled toggle on. Called from the
    same deferred path that re-applies slots."""
    if scene is None:
        scene = bpy.context.scene if bpy.context else None
    active_owners = set()
    if scene is not None and hasattr(scene, "molecule_list_items"):
        for item in scene.molecule_list_items:
            if not getattr(item, "force_field_enabled", False):
                continue
            protein = _ff_protein_object(item)
            if protein is not None:
                active_owners.add(protein.name)
    for obj in list(bpy.data.objects):
        if not obj.get(_FF_ANCHOR_MARKER, False):
            continue
        owner = obj.get(_FF_ANCHOR_OWNER_PROP, "")
        if owner in active_owners and bpy.data.objects.get(owner) is not None:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def iter_active_force_fields(scene: bpy.types.Scene
                              ) -> Iterable[Tuple[bpy.types.Object, float]]:
    """Yield ``(anchor_object, radius_BU)`` for each FF-enabled protein.

    The yielded object is the protein's hidden FF anchor Empty, whose
    location is set to the centroid of the protein's rendered descendants
    (see ``_ensure_ff_anchor``). Wiring the anchor — not the protein
    itself — into the GN modifier's Object Info input is what lets the
    carved gap follow the user grabbing a chain even when the protein
    parent's own ``.location`` stays put.

    Order matches the scene's molecule_list_items so membrane slots get a
    deterministic assignment across sessions.
    """
    if scene is None or not hasattr(scene, "molecule_list_items"):
        return
    for item in scene.molecule_list_items:
        if not getattr(item, "force_field_enabled", False):
            continue
        protein = _ff_protein_object(item)
        if protein is None:
            continue
        radius_bu = compute_force_field_radius_bu(
            protein, float(getattr(item, "force_field_spacing", 0.0))
        )
        if radius_bu <= 0.0:
            continue
        anchor = _ensure_ff_anchor(protein)
        if anchor is None:
            continue
        yield anchor, radius_bu


def collect_force_field_slots(scene: bpy.types.Scene
                               ) -> List[Tuple[bpy.types.Object, float]]:
    """Return up to MAX_PROTEIN_FFS active (object, radius) entries."""
    out: List[Tuple[bpy.types.Object, float]] = []
    for entry in iter_active_force_fields(scene):
        out.append(entry)
        if len(out) >= MAX_PROTEIN_FFS:
            break
    return out


def _set_mod_input(mod: bpy.types.Modifier, socket_name: str, value) -> None:
    """Set a GN modifier input by interface socket name."""
    ng = mod.node_group
    if ng is None:
        return
    for item in ng.interface.items_tree:
        if (hasattr(item, "in_out") and item.in_out == "INPUT"
                and item.name == socket_name):
            try:
                mod[item.identifier] = value
            except Exception:
                pass
            return


def _refresh_modifier(mod: bpy.types.Modifier) -> None:
    """Force a re-eval of the modifier (Object-typed inputs don't dirty it
    on assignment; toggling show_render kicks the depsgraph)."""
    try:
        mod.show_render = not mod.show_render
        mod.show_render = not mod.show_render
        if mod.id_data is not None:
            mod.id_data.update_tag()
    except Exception:
        pass


def _get_gn_modifier(root_obj: bpy.types.Object) -> Optional[bpy.types.Modifier]:
    # Local import — avoids a cycle: membrane_operators imports from us
    # transitively via membrane_props's update callback.
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

    Empty slots (up to the tree's current FF capacity) are cleared so an
    older membrane built before any proteins had FFs on doesn't carry stale
    assignments. The shared tree is grown via
    ``get_or_build_membrane_gn_tree`` first when scene demand exceeds
    capacity, and the modifier is re-pointed at the rebuilt tree if it had
    been dropped during the rebuild.

    ``defer_refresh=True`` skips the trailing modifier refresh — used by
    Build Membrane to batch input writes into a single GN re-eval.
    """
    if root_obj is None or not root_obj.get("pb_is_membrane", False):
        return

    if scene is None:
        scene = bpy.context.scene if bpy.context else None

    # Local import — avoids a cycle with membrane_geometry / operators.
    from .membrane_geometry import get_or_build_membrane_gn_tree
    tree = get_or_build_membrane_gn_tree(scene)

    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return
    if mod.node_group is not tree:
        mod.node_group = tree

    slots = collect_force_field_slots(scene) if scene is not None else []
    tree_ffs = int(tree.get("pb_active_ffs", MAX_PROTEIN_FFS))

    for i in range(1, tree_ffs + 1):
        if i <= len(slots):
            obj, radius_bu = slots[i - 1]
            _set_mod_input(mod, f"Protein FF {i}", obj)
            _set_mod_input(mod, f"Protein FF {i} Enabled", True)
            _set_mod_input(mod, f"Protein FF {i} Radius", float(radius_bu))
        else:
            _set_mod_input(mod, f"Protein FF {i}", None)
            _set_mod_input(mod, f"Protein FF {i} Enabled", False)
            _set_mod_input(mod, f"Protein FF {i} Radius", 0.0)

    if not defer_refresh:
        _refresh_modifier(mod)


def apply_to_all_membranes(scene: Optional[bpy.types.Scene] = None) -> None:
    """Push the current FF list to every membrane in the scene.

    Also reaps anchor Empties whose protein no longer has FF on — toggling
    the slider off is the natural moment to retire that protein's anchor.
    """
    if scene is None:
        scene = bpy.context.scene if bpy.context else None
    for obj in bpy.data.objects:
        if obj.get("pb_is_membrane", False):
            apply_force_fields_to_membrane(obj, scene)
    _remove_orphan_ff_anchors(scene)


# ---------------------------------------------------------------------------
# Handlers — keep the FF slots and viewport in sync with the live scene
# ---------------------------------------------------------------------------
#
# Two distinct sync paths live here, both driven by ``depsgraph_update_post``:
#
# 1. **Deletion of an FF-enabled protein.** The membrane modifier's slot
#    still holds a stale object pointer + non-zero radius — without a
#    re-apply the GN tree would read Location (0,0,0) and carve a phantom
#    hole at the origin. We detect deletions by watching the total object
#    count drop and schedule a deferred ``apply_to_all_membranes`` (deferred
#    because modifying data inside a depsgraph handler is unsafe).
#
# 2. **Movement of an FF-enabled protein.** GN modifier inputs assigned via
#    ``mod[ident] = obj`` don't always register the depsgraph relation that
#    would re-evaluate the membrane modifier when the source protein moves
#    — so without this handler the carved gap stays at the protein's old
#    position. We tag every membrane object so the next viewport refresh
#    re-evaluates Object Info against the protein's live transform.

_object_count_cache = [-1]


def _deferred_ff_reapply():
    try:
        _remove_orphan_ff_anchors()
        apply_to_all_membranes()
    except Exception:
        pass
    return None  # one-shot


def _deferred_membrane_refresh():
    """Kick every membrane modifier to re-evaluate against the live
    protein transforms. Runs outside the depsgraph handler so it can
    safely mutate modifier state (which inside the handler is racy).

    Order matters: first re-sync every FF anchor to the current centroid
    of its protein's rendered descendants, then dirty the membrane
    modifiers. If the anchor write came after the modifier dirty, the GN
    re-eval could fire before the anchor caught up and would still read
    a stale location.

    Toggling ``show_viewport`` False -> True (with an explicit
    intermediate value, not ``not show_viewport`` twice) is what
    actually dirties the viewport-evaluated mesh. Without that, the
    GN Object Info node keeps returning the anchor's previous location.
    """
    try:
        sync_all_ff_anchors()
        for obj in bpy.data.objects:
            if not obj.get("pb_is_membrane", False):
                continue
            for mod in obj.modifiers:
                if mod.type == "NODES":
                    mod.show_viewport = False
                    mod.show_viewport = True
            obj.update_tag()
        # Force the depsgraph to immediately re-evaluate. Without this,
        # the toggle is queued but not applied before the next viewport
        # redraw, and the gap still looks stale.
        if bpy.context and bpy.context.view_layer:
            bpy.context.view_layer.update()
    except Exception:
        pass
    return None  # one-shot


def _ff_watched_names(scene) -> set:
    """Names whose transform should kick a membrane refresh: the FF-
    enabled protein parent AND every descendant of it.

    Including descendants matters because once a molecule is split into
    domains, the parent's MN modifier is off and the rendered geometry —
    plus the user's grab handle — lives on the children. A move on any
    child needs to refresh the anchor's centroid; only watching the
    parent's name misses every child-only transform update.
    """
    out: set = set()
    if scene is None or not hasattr(scene, "molecule_list_items"):
        return out
    for item in scene.molecule_list_items:
        if not getattr(item, "force_field_enabled", False):
            continue
        protein = _ff_protein_object(item)
        if protein is None:
            name = getattr(item, "object_name", "") or ""
            if name:
                out.add(name)
            continue
        out.add(protein.name)
        for child in getattr(protein, "children_recursive", []) or []:
            if child is not None and not child.get(_FF_ANCHOR_MARKER, False):
                out.add(child.name)
    return out


@persistent
def _on_depsgraph_check(scene, depsgraph):
    try:
        # --- Deletion path ---
        count = len(bpy.data.objects)
        prev = _object_count_cache[0]
        _object_count_cache[0] = count
        if 0 <= prev and count < prev:
            if not bpy.app.timers.is_registered(_deferred_ff_reapply):
                bpy.app.timers.register(_deferred_ff_reapply,
                                        first_interval=0.0)

        # --- Movement path ---
        # If any FF-enabled protein OR any of its rendered descendants
        # transformed this update, schedule a deferred membrane refresh.
        # We defer (rather than dirty inline) because mutating modifier
        # state inside the depsgraph handler is unreliable — the toggles
        # get coalesced and the modifier ends up reading the same stale
        # Object Info value.
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
    # New file → reset the object-count baseline (it's compared against the
    # previous file's count otherwise) and re-apply, so v13 membranes whose
    # FF inputs were saved correctly stay aligned with the actually-present
    # protein list (in case some FF-enabled molecule failed to restore).
    _object_count_cache[0] = -1
    if not bpy.app.timers.is_registered(_deferred_ff_reapply):
        bpy.app.timers.register(_deferred_ff_reapply, first_interval=0.0)


def register() -> None:
    if _on_depsgraph_check not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_check)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    if _on_depsgraph_check in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_check)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
