"""Pivot point operators for domain rotation control"""

import bpy
from bpy.types import Operator
from mathutils import Vector
from bpy.app.handlers import persistent

from ..core import domain_space


def _activate_translation_gizmo(context):
    """Activate Move in every live 3D viewport with a valid WINDOW context."""
    screen = context.screen
    window = context.window
    if screen is None:
        return False

    activated = False
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = next((candidate for candidate in area.regions
                       if candidate.type == 'WINDOW'), None)
        if region is None:
            continue
        override = {'area': area, 'region': region}
        if window is not None:
            override['window'] = window
            override['screen'] = screen
        with context.temp_override(**override):
            result = bpy.ops.wm.tool_set_by_id(name="builtin.move")
            activated = activated or result == {'FINISHED'}

        space = area.spaces.active
        space.show_gizmo = True
        space.show_gizmo_tool = True
        space.show_gizmo_object_translate = True
        space.show_gizmo_object_rotate = False
        space.show_gizmo_object_scale = False
        area.tag_redraw()
    return activated


def _apply_origin_to_cursor(obj, world_pos):
    """Move ``obj``'s origin to ``world_pos`` (world space).

    Delegates to ``core.domain_space``, which carries the pivot as a
    geometry-nodes input rather than baking it into mesh vertices. That
    keeps domain meshes shareable, and it means this touches only ``obj``
    by construction: there is no selection to isolate, because nothing
    operator-driven and scene-wide is involved any more.

    (This used to snapshot selection/active/mode/cursor and isolate ``obj``
    purely because ``bpy.ops.object.origin_set`` operates on *every*
    selected object — so the First/Center/Last buttons would otherwise
    also move the parent protein's and sibling domains' origins whenever
    they happened to be selected, which is exactly the state the outliner
    leaves behind after toggling a PROTEIN row.)

    Also stamps ``initial_matrix_local`` so Reset Transform respects the
    new pivot.
    """
    if not domain_space.set_pivot_world(obj, world_pos):
        return False
    bpy.context.view_layer.update()
    obj["initial_matrix_local"] = [list(row) for row in obj.matrix_local]
    return True


def _chain_index_for_item(scene, item):
    """Return the int chain index a CHAIN or DOMAIN outliner row belongs to.

    The protein outliner identifies chains by their numeric index in
    item_ids of the form ``<mol>_chain_<idx>``; DOMAIN rows carry the
    chain LETTER on their object name but their ``parent_id`` points at
    the chain row, so we resolve through the hierarchy rather than
    parsing names. This sidesteps two trap doors: (1) author chain IDs
    are letters that don't map to indices via alphabet math when the
    chain set is gapped (chain T is index 9 in a 10-chain assembly, not
    19), and (2) MN copies the full protein mesh into every domain
    object, so every chain's atoms are present in a domain's mesh and
    must be filtered by index — not by name.
    Returns None if the hierarchy doesn't fit the convention.
    """
    if item.item_type == 'DOMAIN':
        parent_id = item.parent_id or ""
        item = next((it for it in scene.outliner_items
                     if it.item_id == parent_id), None)
        if item is None:
            return None
    if item.item_type != 'CHAIN':
        return None
    item_id = item.item_id or ""
    if "_chain_" in item_id:
        try:
            return int(item_id.rsplit("_chain_", 1)[-1])
        except ValueError:
            return None
    return None


def _collect_chain_filtered_alphas(targets):
    """Return ``[(world_pos, res_id), ...]`` for every alpha carbon
    across ``targets``, optionally filtered to one chain per target.

    ``targets``: iterable of ``(obj, chain_idx, residue_start, residue_end)``.
    When chain_idx is set
    we restrict to atoms whose ``chain_id`` attribute equals chain_idx —
    essential because every domain object shares the whole molecule's
    mesh, so every chain's atoms live in a domain's mesh. Without
    filtering, an "any alpha carbon" pick would always land on chain 0
    residue 1 and First/Last would pick from the wrong chain.

    Positions come from the *raw* mesh, so they must be mapped with
    ``domain_space.local_to_world`` rather than ``obj.matrix_world @ co``:
    the pivot is applied inside geometry nodes, and raw mesh coordinates
    have not been through it.

    Skips objects without ``is_alpha_carbon``. If ``res_id`` is missing,
    falls back to a per-position running counter so first/last still
    have a stable ordering.
    """
    import numpy as np

    results = []
    counter = 0
    for obj, chain_idx, residue_start, residue_end in targets:
        if obj is None:
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None or not hasattr(mesh, "attributes"):
            continue
        if "is_alpha_carbon" not in mesh.attributes:
            continue
        try:
            n = len(mesh.vertices)
            is_alpha = np.zeros(n, dtype=bool)
            mesh.attributes["is_alpha_carbon"].data.foreach_get("value", is_alpha)

            mask = is_alpha
            if chain_idx is not None and "chain_id" in mesh.attributes:
                chain_ids = np.zeros(n, dtype=np.int32)
                mesh.attributes["chain_id"].data.foreach_get("value", chain_ids)
                mask = is_alpha & (chain_ids == chain_idx)

            # Domain objects share the parent molecule's complete raw mesh;
            # their visible residue range is applied later by geometry nodes.
            # Filtering only by chain therefore makes a 1-50 domain's Last
            # pivot land on the chain terminus. Apply the outliner domain bounds
            # to the raw-mesh alpha carbons before choosing First/Center/Last.
            res_ids_arr = None
            if "res_id" in mesh.attributes:
                res_ids_arr = np.zeros(n, dtype=np.int32)
                mesh.attributes["res_id"].data.foreach_get("value", res_ids_arr)
                if residue_start is not None:
                    mask = mask & (res_ids_arr >= residue_start)
                if residue_end is not None:
                    mask = mask & (res_ids_arr <= residue_end)

            positions = np.zeros(n * 3)
            mesh.vertices.foreach_get("co", positions)
            positions = positions.reshape(-1, 3)
            alpha_positions = positions[mask]
            if len(alpha_positions) == 0:
                continue

            world = domain_space.local_to_world_many(obj, alpha_positions)

            if res_ids_arr is not None:
                alpha_res_ids = res_ids_arr[mask]
                for pos, rid in zip(world, alpha_res_ids):
                    results.append((Vector(pos.tolist()), int(rid)))
            else:
                for pos in world:
                    counter += 1
                    results.append((Vector(pos.tolist()), counter))
        except Exception as e:
            print(f"Error collecting alpha carbons for {obj.name}: {e}")

    return results


def _resolve_pivot_targets(scene, selected_items):
    """Map rows to ``[(obj, chain_idx, range_start, range_end), ...]``.

    Skips rows that aren't CHAIN/DOMAIN, lack an ``object_name``, or
    whose object no longer exists in bpy.data.
    """
    targets = []
    for item in selected_items:
        if item.item_type not in ('DOMAIN', 'CHAIN'):
            continue
        if not item.object_name:
            continue
        obj = bpy.data.objects.get(item.object_name)
        if obj is None:
            continue
        residue_start = residue_end = None
        if item.item_type == 'DOMAIN':
            # These fields are populated directly from Domain.start/end when
            # the outliner hierarchy is built, and copied to puppet references.
            # Zero is the PropertyGroup sentinel for "not a domain range".
            start = int(getattr(item, 'domain_start', 0))
            end = int(getattr(item, 'domain_end', 0))
            if start > 0 and end >= start:
                residue_start, residue_end = start, end
        targets.append((obj, _chain_index_for_item(scene, item),
                        residue_start, residue_end))
    return targets


class PROTEINBLENDER_OT_set_pivot_first(Operator):
    """Set pivot point to first residue (N-terminal)"""
    bl_idname = "proteinblender.set_pivot_first"
    bl_label = "Set Pivot to First Residue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_items = [it for it in scene.outliner_items if it.is_selected]
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}

        targets = _resolve_pivot_targets(scene, selected_items)
        if not targets:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}

        applied = 0
        for target in targets:
            alphas = _collect_chain_filtered_alphas([target])
            if not alphas:
                continue
            # min() returns the first occurrence on ties — matches np.argmin.
            pivot_pos = min(alphas, key=lambda pr: pr[1])[0]
            if _apply_origin_to_cursor(target[0], pivot_pos):
                applied += 1
        if not applied:
            self.report({'WARNING'}, "Could not find alpha carbons")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Set pivot to first residue for {applied} item(s)")
        return {'FINISHED'}

class PROTEINBLENDER_OT_set_pivot_last(Operator):
    """Set pivot point to last residue (C-terminal)"""
    bl_idname = "proteinblender.set_pivot_last"
    bl_label = "Set Pivot to Last Residue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_items = [it for it in scene.outliner_items if it.is_selected]
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}

        targets = _resolve_pivot_targets(scene, selected_items)
        if not targets:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}

        applied = 0
        for target in targets:
            alphas = _collect_chain_filtered_alphas([target])
            if not alphas:
                continue
            pivot_pos = max(alphas, key=lambda pr: pr[1])[0]
            if _apply_origin_to_cursor(target[0], pivot_pos):
                applied += 1
        if not applied:
            self.report({'WARNING'}, "Could not find alpha carbons")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Set pivot to last residue for {applied} item(s)")
        return {'FINISHED'}

class PROTEINBLENDER_OT_set_pivot_center(Operator):
    """Set pivot point to geometric center"""
    bl_idname = "proteinblender.set_pivot_center"
    bl_label = "Set Pivot to Center"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_items = [it for it in scene.outliner_items if it.is_selected]
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}

        targets = _resolve_pivot_targets(scene, selected_items)
        if not targets:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}

        applied = 0
        for target in targets:
            obj = target[0]
            alphas = _collect_chain_filtered_alphas([target])
            if alphas:
                # All alpha carbons have the same atomic mass (12.01), so a
                # mass-weighted centroid collapses to a simple mean.
                pivot_pos = sum((pos for pos, _ in alphas), Vector()) / len(alphas)
            else:
                bbox_pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
                if not bbox_pts:
                    continue
                pivot_pos = sum(bbox_pts, Vector()) / len(bbox_pts)
            if _apply_origin_to_cursor(obj, pivot_pos):
                applied += 1
        if not applied:
            self.report({'WARNING'}, "Could not calculate center")
            return {'CANCELLED'}

        self.report({'INFO'},
                    f"Set pivot to center for {applied} item(s)")
        return {'FINISHED'}


# Global flag to prevent recursive handler calls
_finalizing_pivot = False

# Deselection handler for custom pivot
@persistent
def custom_pivot_deselection_handler(scene):
    """Monitor for pivot gizmo deselection to finalize pivot placement"""
    global _finalizing_pivot
    
    # Prevent recursive calls
    if _finalizing_pivot:
        return
    
    # Check if we're in custom pivot mode
    if not scene.get("custom_pivot_active", False):
        return
    
    # Check if the pivot gizmo exists
    pivot_empty = bpy.data.objects.get("PROTEINBLENDER_PIVOT_GIZMO")
    if not pivot_empty:
        # Already cleaned up
        return
    
    # Check if pivot is deselected OR if something else is selected
    if not pivot_empty.select_get() or len(bpy.context.selected_objects) > 1:
        # Pivot was deselected or user selected something else - finalize
        _finalizing_pivot = True
        try:
            finalize_custom_pivot()
        finally:
            _finalizing_pivot = False


def finalize_custom_pivot():
    """Finalize the custom pivot placement when gizmo is deselected"""
    scene = bpy.context.scene
    
    # Check if already finalized
    if not scene.get("custom_pivot_active", False):
        return
    
    # Get the pivot empty
    pivot_empty = bpy.data.objects.get("PROTEINBLENDER_PIVOT_GIZMO")
    if not pivot_empty:
        # Already removed
        return
    
    # Store the position before removing
    pivot_pos = pivot_empty.location.copy()
    
    # Clear custom pivot mode FIRST to prevent handler from firing again
    scene["custom_pivot_active"] = False
    
    # Get selected outliner items from stored selection
    if "custom_pivot_target_items" in scene:
        target_items = scene["custom_pivot_target_items"].split(',')
        success_count = 0
        
        for item_id in target_items:
            if item_id:
                # Find the corresponding object
                for item in scene.outliner_items:
                    if item.item_id == item_id and (item.item_type == 'DOMAIN' or item.item_type == 'CHAIN'):
                        obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                        if obj:
                            # Set object origin to pivot position
                            set_object_origin_static(obj, pivot_pos)
                            success_count += 1
                        break
        
        if success_count > 0:
            # Use report instead of print for user feedback
            if hasattr(bpy.context, 'window_manager'):
                bpy.context.window_manager.popup_menu(
                    lambda self, context: self.layout.label(text=f"Set custom pivot for {success_count} item(s)"),
                    title="Pivot Set",
                    icon='INFO'
                )
    
    # Clean up the empty object - ensure it's properly removed from all collections
    try:
        # First unlink from all collections
        for collection in pivot_empty.users_collection:
            collection.objects.unlink(pivot_empty)

        # Then remove the object data
        bpy.data.objects.remove(pivot_empty, do_unlink=True)
    except Exception:
        # Already removed or error
        pass
    
    # Clean up stored data
    if "custom_pivot_target_items" in scene:
        del scene["custom_pivot_target_items"]

    # Deselect all objects to hide the transform gizmo
    bpy.ops.object.select_all(action='DESELECT')

    # Switch back to select tool to hide the move gizmo
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            override = {'area': area, 'region': area.regions[-1]}
            with bpy.context.temp_override(**override):
                bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
            break
    
    # Force UI redraw
    for area in bpy.context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def set_object_origin_static(obj, new_origin):
    """Module-level wrapper retained for external callers; delegates to
    the shared isolation-safe helper."""
    _apply_origin_to_cursor(obj, new_origin)


class PROTEINBLENDER_OT_set_pivot_custom(Operator):
    """Set custom pivot point using Blender's move gizmo"""
    bl_idname = "proteinblender.set_pivot_custom"
    bl_label = "Set Custom Pivot"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Check if we're already in custom pivot mode
        if scene.get("custom_pivot_active", False):
            # Cancel current custom pivot mode
            pivot_empty = bpy.data.objects.get("PROTEINBLENDER_PIVOT_GIZMO")
            if pivot_empty:
                bpy.data.objects.remove(pivot_empty, do_unlink=True)
            
            scene["custom_pivot_active"] = False
            if "custom_pivot_target_items" in scene:
                del scene["custom_pivot_target_items"]
            
            self.report({'INFO'}, "Cancelled custom pivot placement")
            
            # Force UI redraw
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
            
            return {'FINISHED'}
        
        # Clean up any existing pivot gizmos first
        for obj in list(bpy.data.objects):  # Use list() to avoid iteration issues
            if obj.name.startswith("PROTEINBLENDER_PIVOT_GIZMO"):
                try:
                    # Unlink from all collections first
                    for collection in obj.users_collection:
                        collection.objects.unlink(obj)
                    # Then remove
                    bpy.data.objects.remove(obj, do_unlink=True)
                except:
                    pass
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Get the first selected object to position the gizmo
        first_obj = None
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                if obj:
                    first_obj = obj
                    # Store original pivot if not already stored
                    if "original_pivot" not in obj:
                        obj["original_pivot"] = list(obj.location)
                    break
        
        if not first_obj:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        
        # Store target items for later
        target_item_ids = []
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                target_item_ids.append(item.item_id)
        scene["custom_pivot_target_items"] = ','.join(target_item_ids)
        
        # Create an empty object as the pivot gizmo
        pivot_empty = bpy.data.objects.new("PROTEINBLENDER_PIVOT_GIZMO", None)
        # A SPHERE Empty draws three orange wire circles around the helper.
        # Although those are not rotation handles, they look exactly like a
        # rotation gizmo beside the Move arrows. Plain axes keep the helper
        # selectable and visible without any surrounding circles.
        pivot_empty.empty_display_type = 'PLAIN_AXES'
        pivot_empty.empty_display_size = 0.5

        # Get the actual current origin (pivot point) of the object in world space
        # The origin is at the object's world matrix location
        pivot_empty.location = first_obj.matrix_world.translation.copy()

        # Make the sphere a bright color so it's visible
        pivot_empty.color = (1.0, 0.5, 0.0, 1.0)  # Orange color
        pivot_empty.show_in_front = True  # Always show on top
        
        # Add to scene
        context.collection.objects.link(pivot_empty)
        
        # Select ONLY the pivot sphere
        bpy.ops.object.select_all(action='DESELECT')
        pivot_empty.select_set(True)
        context.view_layer.objects.active = pivot_empty
        
        # Force the move tool
        # Ensure we're in object mode
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        if not _activate_translation_gizmo(context):
            self.report({'WARNING'}, "Could not activate the Move tool")
        
        # Activate custom pivot mode. The deselection handler that finalises the
        # placement is registered by addon.register(), not appended here.
        scene["custom_pivot_active"] = True

        self.report({'INFO'}, "Move the pivot helper to position the pivot. Click elsewhere to confirm.")
        
        # Force UI redraw
        for area in context.screen.areas:
            if area.type in {'PROPERTIES', 'VIEW_3D'}:
                area.tag_redraw()
        
        return {'FINISHED'}
