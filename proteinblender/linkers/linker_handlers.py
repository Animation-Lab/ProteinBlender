"""Handlers for linker distance constraints, undo/redo, and movement tracking.

This module provides:
- Distance constraint enforcement: prevents puppet members from exceeding
  linker max reach via a depsgraph handler
- Undo/redo recovery: revalidates and reconnects linker geometry
- File load recovery: rebuilds linker geometry from stored properties
- Puppet deletion cleanup: removes linkers when their puppet is deleted
"""

import bpy
from bpy.app.handlers import persistent
import logging

from .linker_geometry import (
    update_linker_curve,
    delete_linker_geometry,
    create_linker_curve,
    get_residue_position_from_item,
    get_object_for_item,
    get_backbone_direction,
    _get_numeric_chain_id_from_item,
    BU_PER_RESIDUE,
)

logger = logging.getLogger(__name__)

# Track if handlers are registered
_handlers_registered = False

# Re-entrancy guard for constraint handler
_constraint_active = False


# ---------------------------------------------------------------------------
# Distance constraint handler
# ---------------------------------------------------------------------------

def _get_object_name_for_endpoint(linker, endpoint: str, scene=None) -> str:
    """Get the Blender object name for a linker endpoint."""
    item_id = linker.endpoint_a_item_id if endpoint == 'A' else linker.endpoint_b_item_id
    if scene is None:
        scene = bpy.context.scene
    if not hasattr(scene, 'outliner_items'):
        return ""

    for item in scene.outliner_items:
        if item.item_id == item_id:
            return item.object_name
    return ""


def _world_to_local_direction(obj, world_vector):
    """Convert a world-space direction/offset to an object's local parent space.

    When an object is parented (e.g., to a puppet controller), obj.location
    is in the parent's local space, not world space. We need to transform
    the correction vector accordingly.

    Args:
        obj: The Blender object
        world_vector: Vector in world space

    Returns:
        Vector in the object's parent local space
    """

    if obj.parent:
        # Transform world vector into parent's local space
        parent_inv = obj.parent.matrix_world.inverted()
        # We only want the rotation/scale, not translation
        local_vec = parent_inv.to_3x3() @ world_vector
        return local_vec
    else:
        return world_vector.copy()


@persistent
def linker_constraint_and_update_handler(scene, depsgraph):
    """Enforce distance constraints and update linker curves on movement.

    This handler fires on depsgraph_update_post. It:
    1. Checks which objects were transformed
    2. For each linker, checks if endpoint distance exceeds max reach
    3. If exceeded, snaps the most-recently-moved domain back
    4. Updates linker curve geometry to reflect new positions

    Re-entrancy is guarded: setting obj.location triggers another depsgraph
    update, so the _constraint_active flag prevents infinite recursion.
    """
    global _constraint_active

    if _constraint_active:
        return

    if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
        return

    # Collect which objects had transform updates
    transformed_objects = set()
    for update in depsgraph.updates:
        if update.is_updated_transform and isinstance(update.id, bpy.types.Object):
            transformed_objects.add(update.id.name)

    if not transformed_objects:
        return

    _constraint_active = True
    try:
        for linker in scene.pb2_linkers:
            if not linker.is_valid or not linker.puppet_id:
                continue

            # Check if any endpoint's object was moved
            obj_a_name = _get_object_name_for_endpoint(linker, 'A', scene)
            obj_b_name = _get_object_name_for_endpoint(linker, 'B', scene)

            # Check if the puppet's controller was moved (moves all children)
            controller_moved = False
            if hasattr(scene, 'outliner_items'):
                for item in scene.outliner_items:
                    if (item.item_type == 'PUPPET' and
                            item.item_id == linker.puppet_id and
                            item.controller_object_name in transformed_objects):
                        controller_moved = True
                        break

            moved_a = obj_a_name in transformed_objects
            moved_b = obj_b_name in transformed_objects
            either_moved = moved_a or moved_b or controller_moved

            if not either_moved:
                continue

            # If the controller moved, all children move together so the
            # distance between endpoints within the same puppet doesn't
            # change — just update the curve geometry.
            if controller_moved and not moved_a and not moved_b:
                update_linker_curve(linker)
                continue

            # Get current endpoint positions
            pos_a = get_residue_position_from_item(
                linker.endpoint_a_item_id,
                linker.endpoint_a_chain,
                linker.endpoint_a_residue
            )
            pos_b = get_residue_position_from_item(
                linker.endpoint_b_item_id,
                linker.endpoint_b_chain,
                linker.endpoint_b_residue
            )

            if pos_a is None or pos_b is None:
                continue

            distance = (pos_b - pos_a).length
            max_reach = linker.length_residues * BU_PER_RESIDUE

            # Enforce distance constraint (individual domain moved within puppet)
            corrected = False
            if distance > max_reach:
                overshoot = distance - max_reach
                direction_world = (pos_b - pos_a).normalized()

                if moved_a and not moved_b:
                    obj_a = bpy.data.objects.get(obj_a_name)
                    if obj_a:
                        correction = _world_to_local_direction(
                            obj_a, direction_world * overshoot
                        )
                        obj_a.location += correction
                        corrected = True
                elif moved_b and not moved_a:
                    obj_b = bpy.data.objects.get(obj_b_name)
                    if obj_b:
                        correction = _world_to_local_direction(
                            obj_b, -direction_world * overshoot
                        )
                        obj_b.location += correction
                        corrected = True
                elif moved_a and moved_b:
                    obj_a = bpy.data.objects.get(obj_a_name)
                    obj_b = bpy.data.objects.get(obj_b_name)
                    half_overshoot = overshoot / 2
                    if obj_a:
                        correction = _world_to_local_direction(
                            obj_a, direction_world * half_overshoot
                        )
                        obj_a.location += correction
                    if obj_b:
                        correction = _world_to_local_direction(
                            obj_b, -direction_world * half_overshoot
                        )
                        obj_b.location += correction
                    corrected = True

            # Force matrix_world recalculation after location corrections
            # so update_linker_curve reads the corrected positions.
            # _constraint_active guard prevents re-entrancy.
            if corrected:
                bpy.context.view_layer.update()

            # Update linker curve geometry
            update_linker_curve(linker)

    except Exception as e:
        logger.debug(f"Error in linker constraint handler: {e}")
    finally:
        _constraint_active = False


# ---------------------------------------------------------------------------
# Undo/redo handlers
# ---------------------------------------------------------------------------

def _validate_linker_endpoints(linker) -> bool:
    """Check if both endpoints reference valid objects/residues."""
    pos_a = get_residue_position_from_item(
        linker.endpoint_a_item_id,
        linker.endpoint_a_chain,
        linker.endpoint_a_residue
    )
    pos_b = get_residue_position_from_item(
        linker.endpoint_b_item_id,
        linker.endpoint_b_chain,
        linker.endpoint_b_residue
    )
    return pos_a is not None and pos_b is not None


def _reconnect_linker_geometry(linker) -> bool:
    """Reconnect or recreate linker geometry after undo/redo."""
    if linker.curve_object_name:
        obj = bpy.data.objects.get(linker.curve_object_name)
        if obj:
            return True

    # Geometry missing - try to recreate
    start_pos = get_residue_position_from_item(
        linker.endpoint_a_item_id,
        linker.endpoint_a_chain,
        linker.endpoint_a_residue
    )
    end_pos = get_residue_position_from_item(
        linker.endpoint_b_item_id,
        linker.endpoint_b_chain,
        linker.endpoint_b_residue
    )

    if start_pos and end_pos:
        logger.info(f"Recreating geometry for linker: {linker.name}")

        # Get backbone directions
        obj_a = get_object_for_item(linker.endpoint_a_item_id)
        obj_b = get_object_for_item(linker.endpoint_b_item_id)
        num_chain_a = _get_numeric_chain_id_from_item(linker.endpoint_a_item_id)
        num_chain_b = _get_numeric_chain_id_from_item(linker.endpoint_b_item_id)
        start_dir = get_backbone_direction(
            obj_a, linker.endpoint_a_chain, linker.endpoint_a_residue,
            numeric_chain_id=num_chain_a
        ) if obj_a else None
        end_dir = get_backbone_direction(
            obj_b, linker.endpoint_b_chain, linker.endpoint_b_residue,
            numeric_chain_id=num_chain_b
        ) if obj_b else None

        create_linker_curve(linker, start_pos, end_pos, start_dir, end_dir)
        return True

    return False


@persistent
def linker_undo_post_handler(scene):
    """Revalidate all linkers and reconnect geometry after undo."""
    if not hasattr(scene, 'pb2_linkers'):
        return

    for linker in scene.pb2_linkers:
        if linker.curve_object_name:
            if linker.curve_object_name not in bpy.data.objects:
                _reconnect_linker_geometry(linker)

        linker.is_valid = _validate_linker_endpoints(linker)
        if linker.is_valid:
            update_linker_curve(linker)


@persistent
def linker_redo_post_handler(scene):
    """Same logic as undo handler."""
    linker_undo_post_handler(scene)


def _deferred_linker_rebuild():
    """Re-validate every linker and re-snap its curve to the current
    endpoint positions. Runs from a 0-second timer scheduled by
    ``linker_load_post_handler`` so the depsgraph has had a chance to
    evaluate world matrices after the file load completed.

    Tester report (Janet, Windows): linker comes back "in a different
    conformation and not attached to proteins after reopening file".
    Root cause: the load_post handler used to run immediately on file
    open, sometimes before the parent puppet's transform was fully
    evaluated — every endpoint lookup multiplies the local atom
    position by ``obj.matrix_world``, and a stale parent matrix puts
    the curve at a stale world position. Deferring by a tick lets
    Blender finish its first depsgraph evaluation before we snap the
    curve.

    Returns None so the timer doesn't reschedule itself."""
    try:
        scene = bpy.context.scene
    except Exception:
        return None
    if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
        return None

    # Force a depsgraph update so any not-yet-evaluated transforms /
    # modifiers are committed before we read world positions. This is
    # belt-and-braces — the timer alone is usually enough — but on
    # complex scenes (puppets parented to controllers, hidden
    # collections being un-hidden on load, etc.) the explicit update
    # eliminates the last race window.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    n_rebuilt = 0
    for linker in scene.pb2_linkers:
        linker.is_valid = _validate_linker_endpoints(linker)
        if not linker.is_valid:
            continue
        if linker.curve_object_name and linker.curve_object_name in bpy.data.objects:
            update_linker_curve(linker)
        else:
            _reconnect_linker_geometry(linker)
        n_rebuilt += 1

    if n_rebuilt:
        logger.info(
            f"Deferred linker rebuild: re-snapped {n_rebuilt} linker(s) "
            f"to evaluated endpoint positions"
        )
    return None


@persistent
def linker_load_post_handler(dummy):
    """Schedule a deferred linker rebuild after file load.

    The immediate load_post moment runs before Blender's first
    depsgraph evaluation in many .blend files — reading endpoint
    world positions then can hand back stale transforms. Schedule
    via a 0-second timer so the rebuild runs after the load has
    fully settled.

    A pass on the *current* state is still kept as a fast-path for
    files where the depsgraph happens to already be ready (typically
    small scenes with no controller parenting). The deferred pass
    overwrites it if positions changed."""
    scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers'):
        return

    logger.info(f"Rebuilding {len(scene.pb2_linkers)} linkers after file load")

    # Best-effort immediate pass (may use stale positions on complex
    # scenes — the deferred pass below cleans up)
    for linker in scene.pb2_linkers:
        linker.is_valid = _validate_linker_endpoints(linker)
        if linker.is_valid:
            if linker.curve_object_name and linker.curve_object_name in bpy.data.objects:
                update_linker_curve(linker)
            else:
                _reconnect_linker_geometry(linker)

    # Deferred pass — runs after the load completes and after the
    # first depsgraph evaluation, so endpoint world positions are
    # current.
    try:
        bpy.app.timers.register(_deferred_linker_rebuild, first_interval=0.0)
    except Exception as e:
        logger.warning(f"Could not schedule deferred linker rebuild: {e}")


# ---------------------------------------------------------------------------
# Frame change handler — ensures linkers update during animation playback
# ---------------------------------------------------------------------------

@persistent
def linker_frame_change_handler(scene):
    """Update all valid linker curves on frame change."""
    if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
        return

    for linker in scene.pb2_linkers:
        if linker.is_valid:
            update_linker_curve(linker)


# ---------------------------------------------------------------------------
# Cascade deletion — remove linkers when the things they reference are deleted
# ---------------------------------------------------------------------------
#
# Linkers are child objects of the puppet/molecule graph: they only make sense
# while both of their endpoints (and the puppet) exist. When a user deletes a
# puppet, protein, chain or domain we must remove any dependent linker so no
# orphaned curve is left hanging in the scene.

def _remove_linker_indices(scene, indices, reason=""):
    """Delete geometry for the given linker indices and drop them from the list.

    Indices are removed in descending order so earlier indices stay valid.
    Returns the number removed.
    """
    removed = 0
    for i in sorted(set(indices), reverse=True):
        linker = scene.pb2_linkers[i]
        logger.info(
            "Cascade-removing linker '%s'%s",
            linker.name, f" ({reason})" if reason else "",
        )
        delete_linker_geometry(linker)
        scene.pb2_linkers.remove(i)
        removed += 1

    if scene.pb2_linkers_index >= len(scene.pb2_linkers):
        scene.pb2_linkers_index = max(0, len(scene.pb2_linkers) - 1)
    return removed


def _endpoint_root_molecule(scene, item_id: str):
    """Return the molecule id an endpoint belongs to by walking parent_id.

    Chain/domain outliner items chain up to their PROTEIN item, whose item_id
    is the molecule identifier. Returns None if the item can't be resolved.
    """
    items = {it.item_id: it for it in scene.outliner_items}
    cur = items.get(item_id)
    seen = set()
    while cur is not None and cur.parent_id and cur.item_id not in seen:
        seen.add(cur.item_id)
        cur = items.get(cur.parent_id)
    return cur.item_id if cur is not None else None


def on_puppet_deleted(puppet_id: str):
    """Remove all linkers belonging to a deleted puppet.

    Called from group_maker_panel.py when a puppet is deleted.
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers'):
        return
    indices = [i for i, linker in enumerate(scene.pb2_linkers)
               if linker.puppet_id == puppet_id]
    _remove_linker_indices(scene, indices, "puppet deleted")


def on_molecule_deleted(molecule_id: str):
    """Remove linkers with an endpoint belonging to a deleted molecule.

    Called from the molecule delete flow *before* the molecule's objects and
    outliner rows are removed, so endpoint ancestry can still be resolved. A
    linker is removed if either endpoint traces back to ``molecule_id`` (a
    puppet can hold chains from several proteins, so a linker may straddle two).
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
        return
    indices = []
    for i, linker in enumerate(scene.pb2_linkers):
        root_a = _endpoint_root_molecule(scene, linker.endpoint_a_item_id)
        root_b = _endpoint_root_molecule(scene, linker.endpoint_b_item_id)
        if root_a == molecule_id or root_b == molecule_id:
            indices.append(i)
    _remove_linker_indices(scene, indices, f"molecule '{molecule_id}' deleted")


def prune_dangling_linkers(scene=None, reason="dangling"):
    """Remove any linker whose endpoint no longer resolves to an outliner item.

    Call this after an outliner rebuild that dropped rows (chain/domain
    deletion). Because a valid linker's endpoints are always present outliner
    items, anything that can't be resolved is genuinely orphaned. Intended for
    synchronous use inside delete operators only — the undo/load handlers
    instead *recreate* transiently-missing geometry, so this must not run there.
    """
    if scene is None:
        scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers') or len(scene.pb2_linkers) == 0:
        return 0
    valid_ids = {it.item_id for it in scene.outliner_items}
    indices = [i for i, linker in enumerate(scene.pb2_linkers)
               if linker.endpoint_a_item_id not in valid_ids
               or linker.endpoint_b_item_id not in valid_ids]
    return _remove_linker_indices(scene, indices, reason)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register():
    """Register linker handlers."""
    global _handlers_registered

    if _handlers_registered:
        return

    if linker_undo_post_handler not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(linker_undo_post_handler)

    if linker_redo_post_handler not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(linker_redo_post_handler)

    if linker_load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(linker_load_post_handler)

    if linker_constraint_and_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(linker_constraint_and_update_handler)

    if linker_frame_change_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(linker_frame_change_handler)

    _handlers_registered = True
    logger.info("Linker handlers registered")


def unregister():
    """Unregister linker handlers."""
    global _handlers_registered

    if linker_undo_post_handler in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(linker_undo_post_handler)

    if linker_redo_post_handler in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(linker_redo_post_handler)

    if linker_load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(linker_load_post_handler)

    if linker_constraint_and_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(linker_constraint_and_update_handler)

    if linker_frame_change_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(linker_frame_change_handler)

    _handlers_registered = False
    logger.info("Linker handlers unregistered")
