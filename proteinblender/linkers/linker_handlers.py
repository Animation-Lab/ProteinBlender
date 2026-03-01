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
    from mathutils import Vector

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
            if not linker.is_valid or (not linker.puppet_id_a and not linker.puppet_id_b):
                continue

            # Check if any endpoint's object was moved
            obj_a_name = _get_object_name_for_endpoint(linker, 'A', scene)
            obj_b_name = _get_object_name_for_endpoint(linker, 'B', scene)

            # Check if either puppet's controller was moved (moves all children)
            controller_moved = False
            if hasattr(scene, 'outliner_items'):
                puppet_ids = {linker.puppet_id_a, linker.puppet_id_b} - {''}
                for item in scene.outliner_items:
                    if (item.item_id in puppet_ids and
                        item.item_type == 'PUPPET' and
                        item.controller_object_name in transformed_objects):
                        controller_moved = True
                        break

            moved_a = obj_a_name in transformed_objects
            moved_b = obj_b_name in transformed_objects
            either_moved = moved_a or moved_b or controller_moved

            if not either_moved:
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

            # Enforce distance constraint
            if distance > max_reach and not controller_moved:
                overshoot = distance - max_reach
                direction_world = (pos_b - pos_a).normalized()

                # Determine which object to snap back
                if moved_a and not moved_b:
                    obj_a = bpy.data.objects.get(obj_a_name)
                    if obj_a:
                        correction = _world_to_local_direction(
                            obj_a, direction_world * overshoot
                        )
                        obj_a.location += correction
                elif moved_b and not moved_a:
                    obj_b = bpy.data.objects.get(obj_b_name)
                    if obj_b:
                        correction = _world_to_local_direction(
                            obj_b, -direction_world * overshoot
                        )
                        obj_b.location += correction
                elif moved_a and moved_b:
                    # Both moved: split the correction equally
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
        start_dir = get_backbone_direction(
            obj_a, linker.endpoint_a_chain, linker.endpoint_a_residue
        ) if obj_a else None
        end_dir = get_backbone_direction(
            obj_b, linker.endpoint_b_chain, linker.endpoint_b_residue
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


@persistent
def linker_load_post_handler(dummy):
    """Rebuild linker geometry from stored properties after file load."""
    scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers'):
        return

    logger.info(f"Rebuilding {len(scene.pb2_linkers)} linkers after file load")

    for linker in scene.pb2_linkers:
        linker.is_valid = _validate_linker_endpoints(linker)

        if linker.is_valid:
            if linker.curve_object_name and linker.curve_object_name in bpy.data.objects:
                update_linker_curve(linker)
            else:
                _reconnect_linker_geometry(linker)


# ---------------------------------------------------------------------------
# Puppet deletion cleanup
# ---------------------------------------------------------------------------

def on_puppet_deleted(puppet_id: str):
    """Remove all linkers that involve a deleted puppet.

    Called from group_maker_panel.py when a puppet is deleted.
    For cross-puppet linkers, the linker is removed if either
    endpoint's puppet is the deleted one.

    Args:
        puppet_id: ID of the deleted puppet
    """
    scene = bpy.context.scene
    if not hasattr(scene, 'pb2_linkers'):
        return

    linkers_to_remove = []
    for i, linker in enumerate(scene.pb2_linkers):
        if linker.puppet_id_a == puppet_id or linker.puppet_id_b == puppet_id:
            linkers_to_remove.append(i)

    for i in reversed(linkers_to_remove):
        linker = scene.pb2_linkers[i]
        logger.info(f"Removing linker '{linker.name}' (puppet deleted)")
        delete_linker_geometry(linker)
        scene.pb2_linkers.remove(i)

    if scene.pb2_linkers_index >= len(scene.pb2_linkers):
        scene.pb2_linkers_index = max(0, len(scene.pb2_linkers) - 1)


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

    _handlers_registered = False
    logger.info("Linker handlers unregistered")
