"""Pivot point operators for domain rotation control"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
from mathutils import Vector
from ..utils.scene_manager import ProteinBlenderScene
from bpy.app.handlers import persistent


def _apply_origin_to_cursor(obj, world_pos):
    """Move ``obj``'s origin to ``world_pos`` (world space) without
    touching any other object's origin.

    Why: ``bpy.ops.object.origin_set`` operates on every selected
    object, so the "First/Center/Last" pivot buttons used to also move
    the parent protein's (and sibling domains') origins whenever they
    happened to be selected — exactly the case after the user toggles
    a PROTEIN row in the outliner, which selects the protein plus all
    its domains. We snapshot selection/active/mode + cursor, isolate
    just ``obj``, run origin_set, then restore everything. Also stamps
    ``initial_matrix_local`` so Reset Transform respects the new pivot.
    """
    context = bpy.context
    scene = context.scene
    view_layer = context.view_layer

    # Snapshot state we're about to clobber.
    original_mode = context.mode
    original_active = view_layer.objects.active
    original_selected = [o for o in context.selected_objects]
    original_cursor = scene.cursor.location.copy()

    needs_mode_restore = original_mode != 'OBJECT'
    if needs_mode_restore:
        bpy.ops.object.mode_set(mode='OBJECT')

    try:
        # Isolate obj as the sole selected + active target so origin_set
        # only operates on it.
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        view_layer.objects.active = obj

        scene.cursor.location = world_pos
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

        # Refresh the Reset-Transform baseline to the new origin.
        obj["initial_matrix_local"] = [list(row) for row in obj.matrix_local]
    finally:
        # Restore selection set, active, cursor, and mode.
        bpy.ops.object.select_all(action='DESELECT')
        for prev_obj in original_selected:
            try:
                prev_obj.select_set(True)
            except (ReferenceError, RuntimeError):
                # Object may have been deleted mid-operation; skip.
                pass
        if original_active is not None:
            try:
                view_layer.objects.active = original_active
            except (ReferenceError, RuntimeError):
                pass

        scene.cursor.location = original_cursor

        if needs_mode_restore and context.mode != original_mode:
            try:
                bpy.ops.object.mode_set(mode=original_mode)
            except RuntimeError:
                pass


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

    ``targets``: iterable of ``(obj, chain_idx)``. When chain_idx is set
    we restrict to atoms whose ``chain_id`` attribute equals chain_idx —
    essential because MN copies the full protein mesh into every domain
    object, so every chain's atoms live in a domain's mesh. Without
    filtering, an "any alpha carbon" pick would always land on chain 0
    residue 1, which is at mesh-local (0,0,0) → in world space that
    collapses to the domain's current origin and First/Last become
    silent no-ops.

    Skips objects without ``is_alpha_carbon``. If ``res_id`` is missing,
    falls back to a per-position running counter so first/last still
    have a stable ordering.
    """
    import numpy as np

    results = []
    counter = 0
    for obj, chain_idx in targets:
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

            positions = np.zeros(n * 3)
            mesh.vertices.foreach_get("co", positions)
            positions = positions.reshape(-1, 3)
            alpha_positions = positions[mask]
            if len(alpha_positions) == 0:
                continue

            if "res_id" in mesh.attributes:
                res_ids_arr = np.zeros(n, dtype=np.int32)
                mesh.attributes["res_id"].data.foreach_get("value", res_ids_arr)
                alpha_res_ids = res_ids_arr[mask]
                for pos, rid in zip(alpha_positions, alpha_res_ids):
                    results.append((obj.matrix_world @ Vector(pos.tolist()),
                                    int(rid)))
            else:
                for pos in alpha_positions:
                    counter += 1
                    results.append((obj.matrix_world @ Vector(pos.tolist()),
                                    counter))
        except Exception as e:
            print(f"Error collecting alpha carbons for {obj.name}: {e}")

    return results


def _resolve_pivot_targets(scene, selected_items):
    """Map outliner rows to ``[(obj, chain_idx), ...]`` for pivot ops.

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
        targets.append((obj, _chain_index_for_item(scene, item)))
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

        alphas = _collect_chain_filtered_alphas(targets)
        if not alphas:
            self.report({'WARNING'}, "Could not find alpha carbons")
            return {'CANCELLED'}

        # min() returns the first occurrence on ties — matches np.argmin.
        pivot_pos = min(alphas, key=lambda pr: pr[1])[0]

        for obj, _ in targets:
            _apply_origin_to_cursor(obj, pivot_pos)

        self.report({'INFO'},
                    f"Set pivot to first residue for {len(targets)} item(s)")
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

        alphas = _collect_chain_filtered_alphas(targets)
        if not alphas:
            self.report({'WARNING'}, "Could not find alpha carbons")
            return {'CANCELLED'}

        pivot_pos = max(alphas, key=lambda pr: pr[1])[0]

        for obj, _ in targets:
            _apply_origin_to_cursor(obj, pivot_pos)

        self.report({'INFO'},
                    f"Set pivot to last residue for {len(targets)} item(s)")
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

        alphas = _collect_chain_filtered_alphas(targets)
        if alphas:
            # All alpha carbons have the same atomic mass (12.01), so a
            # mass-weighted centroid collapses to a simple mean.
            pivot_pos = sum((pos for pos, _ in alphas), Vector()) / len(alphas)
        else:
            # No alpha carbons in any target — fall back to the combined
            # bounding-box center.
            bbox_pts = []
            for obj, _ in targets:
                bbox_pts.extend(obj.matrix_world @ Vector(c)
                                for c in obj.bound_box)
            if not bbox_pts:
                self.report({'WARNING'}, "Could not calculate center")
                return {'CANCELLED'}
            pivot_pos = sum(bbox_pts, Vector()) / len(bbox_pts)

        for obj, _ in targets:
            _apply_origin_to_cursor(obj, pivot_pos)

        self.report({'INFO'},
                    f"Set pivot to center for {len(targets)} item(s)")
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
    except Exception as e:
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
        pivot_empty.empty_display_type = 'SPHERE'
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
        
        # Force move tool activation
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                # Set the tool directly via the space data
                override = {'area': area, 'region': area.regions[-1]}
                with context.temp_override(**override):
                    bpy.ops.wm.tool_set_by_id(name="builtin.move")
                
                # Ensure gizmo settings are correct
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.show_gizmo = True
                        space.show_gizmo_object_translate = True
                        space.show_gizmo_object_rotate = False
                        space.show_gizmo_object_scale = False
                break
        
        # Activate custom pivot mode. The deselection handler that finalises the
        # placement is registered by addon.register(), not appended here.
        scene["custom_pivot_active"] = True

        self.report({'INFO'}, "Move the orange sphere to position pivot. Click elsewhere to confirm.")
        
        # Force UI redraw
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        
        return {'FINISHED'}


