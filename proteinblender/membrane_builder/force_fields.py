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
from typing import Iterable, List, Optional, Tuple

from .membrane_geometry import MAX_PROTEIN_FFS, NM_PER_BU


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


def compute_force_field_radius_bu(obj: bpy.types.Object,
                                   spacing_nm: float) -> float:
    """Return the force-field radius in Blender Units.

    Half the protein's tallest extent (the bounding-cube radius along its
    longest axis) plus the user's clearance. Uses the atom point cloud
    rather than ``obj.dimensions`` because the MN modifier's output mesh
    massively under-reports the rendered size — see ``_protein_tallest
    _dim_bu`` for the gory details.
    """
    if obj is None:
        return 0.0
    half_extent_bu = _protein_tallest_dim_bu(obj) / 2.0
    spacing_bu = max(0.0, float(spacing_nm)) / NM_PER_BU
    return half_extent_bu + spacing_bu


def _protein_tallest_dim_bu(obj: bpy.types.Object) -> float:
    """Return the protein's longest extent in BU, atom-cloud aware.

    For MN-rendered proteins ``obj.dimensions`` reflects whatever subset
    the MolecularNodes modifier emits, not the real atom cloud — for a
    typical actin import it reads ~20× smaller than the real size. Use
    the raw vertex bbox of ``obj.data`` when available (that's the
    persisted atom point cloud), and only fall back to ``obj.dimensions``
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


def iter_active_force_fields(scene: bpy.types.Scene
                              ) -> Iterable[Tuple[bpy.types.Object, float]]:
    """Yield ``(protein_object, radius_BU)`` for each FF-enabled protein.

    Order matches the scene's molecule_list_items so membrane slots get a
    deterministic assignment across sessions.
    """
    if scene is None or not hasattr(scene, "molecule_list_items"):
        return
    for item in scene.molecule_list_items:
        if not getattr(item, "force_field_enabled", False):
            continue
        obj = _ff_protein_object(item)
        if obj is None:
            continue
        radius_bu = compute_force_field_radius_bu(
            obj, float(getattr(item, "force_field_spacing", 0.0))
        )
        if radius_bu <= 0.0:
            continue
        yield obj, radius_bu


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
                                    scene: Optional[bpy.types.Scene] = None
                                    ) -> None:
    """Write the current scene's active force fields into one membrane.

    Empty slots are cleared (object=None, enabled=False, radius=0) so an
    older membrane built before any proteins had FFs on doesn't carry stale
    assignments.
    """
    if root_obj is None or not root_obj.get("pb_is_membrane", False):
        return
    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return

    if scene is None:
        scene = bpy.context.scene if bpy.context else None
    slots = collect_force_field_slots(scene) if scene is not None else []

    for i in range(1, MAX_PROTEIN_FFS + 1):
        if i <= len(slots):
            obj, radius_bu = slots[i - 1]
            _set_mod_input(mod, f"Protein FF {i}", obj)
            _set_mod_input(mod, f"Protein FF {i} Enabled", True)
            _set_mod_input(mod, f"Protein FF {i} Radius", float(radius_bu))
        else:
            _set_mod_input(mod, f"Protein FF {i}", None)
            _set_mod_input(mod, f"Protein FF {i} Enabled", False)
            _set_mod_input(mod, f"Protein FF {i} Radius", 0.0)

    _refresh_modifier(mod)


def apply_to_all_membranes(scene: Optional[bpy.types.Scene] = None) -> None:
    """Push the current FF list to every membrane in the scene."""
    if scene is None:
        scene = bpy.context.scene if bpy.context else None
    for obj in bpy.data.objects:
        if obj.get("pb_is_membrane", False):
            apply_force_fields_to_membrane(obj, scene)


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
        apply_to_all_membranes()
    except Exception:
        pass
    return None  # one-shot


def _deferred_membrane_refresh():
    """Kick every membrane modifier to re-evaluate against the live
    protein transforms. Runs outside the depsgraph handler so it can
    safely mutate modifier state (which inside the handler is racy).

    Toggling ``show_viewport`` False -> True (with an explicit
    intermediate value, not ``not show_viewport`` twice) is what
    actually dirties the viewport-evaluated mesh. Without that, the
    GN Object Info node keeps returning the protein's stale location.
    """
    try:
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


def _ff_protein_names(scene) -> set:
    """Names of the objects currently driving an enabled force field."""
    out = set()
    if scene is None or not hasattr(scene, "molecule_list_items"):
        return out
    for item in scene.molecule_list_items:
        if getattr(item, "force_field_enabled", False) and item.object_name:
            out.add(item.object_name)
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
        # If any FF-enabled protein transformed this update, schedule a
        # deferred membrane refresh. We defer (rather than dirty inline)
        # because mutating modifier state inside the depsgraph handler
        # is unreliable — the toggles get coalesced and the modifier
        # ends up reading the same stale Object Info value.
        ff_names = _ff_protein_names(scene)
        if not ff_names:
            return
        moved = any(
            isinstance(upd.id, bpy.types.Object)
            and upd.is_updated_transform
            and upd.id.name in ff_names
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
