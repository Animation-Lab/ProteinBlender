"""Pivot point operators for domain rotation control"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
from mathutils import Vector
from ..utils.scene_manager import ProteinBlenderScene
from bpy.app.handlers import persistent


def extract_chain_id_from_object_name(obj_name):
    """Extract chain ID from object name.

    Handles multiple naming patterns:
    - "Chain A_0_1_197" -> chain_id = 0
    - "3b75_001_0_1_197_Chain_A" -> chain_id = 0
    - "Domain_A_5_50" -> chain_id = 0 (if A maps to 0)

    Returns:
        int or None: The chain ID if found, None otherwise
    """
    import re

    # Pattern 1: Standard chain/domain pattern with numeric chain ID
    # Matches: "Chain A_0_1_197" or "3b75_001_0_1_197_anything"
    match = re.search(r'_(\d+)_\d+_\d+', obj_name)
    if match:
        return int(match.group(1))

    # Pattern 2: Try to find any numeric ID after underscore
    # This is a more general fallback
    parts = obj_name.split('_')
    for i, part in enumerate(parts):
        if part.isdigit() and i + 2 < len(parts):
            # Check if next two parts are also digits (residue range pattern)
            if parts[i+1].isdigit() and parts[i+2].isdigit():
                return int(part)

    return None


class PROTEINBLENDER_OT_set_pivot_first(Operator):
    """Set pivot point to first residue (N-terminal)"""
    bl_idname = "proteinblender.set_pivot_first"
    bl_label = "Set Pivot to First Residue"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Collect all valid objects
        valid_objects = []
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                if obj:
                    # Store original pivot if not already stored
                    if "original_pivot" not in obj:
                        obj["original_pivot"] = list(obj.location)
                    valid_objects.append(obj)
        
        if not valid_objects:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        
        # Find the first alpha carbon position across ALL selected objects
        first_ca_pos = self.get_first_alpha_carbon_combined(valid_objects)
        
        if first_ca_pos:
            # Set the same pivot position for all selected objects
            for obj in valid_objects:
                self.set_object_origin(obj, first_ca_pos)
            
            self.report({'INFO'}, f"Set pivot to first residue for {len(valid_objects)} item(s)")
        else:
            self.report({'WARNING'}, "Could not find alpha carbons")
        
        return {'FINISHED'}
    
    def get_first_alpha_carbon_combined(self, objects):
        """Find the position of the first alpha carbon across all selected domain objects"""
        if not objects:
            return None
        
        import numpy as np
        
        # Collect ALL alpha carbons from ALL domains
        all_alpha_positions = []
        all_alpha_res_ids = []
        fallback_position = None
        
        for obj in objects:
            # Check if this is a molecular object with attributes
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                # Fallback to object origin if not a proper molecular object
                if fallback_position is None:
                    fallback_position = obj.location
                continue
            
            try:
                # Check if alpha carbon attribute exists
                if "is_alpha_carbon" not in obj.data.attributes:
                    # No alpha carbon data, use object origin as fallback
                    if fallback_position is None:
                        fallback_position = obj.location
                    continue

                # Use the ORIGINAL mesh data (before geometry nodes evaluation)
                # This ensures alpha carbon positions are consistent regardless of style
                mesh = obj.data

                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)

                # Check if we need to filter by chain_id
                # The mesh might contain all chains, so we need to filter to this object's chain
                chain_mask = None
                if "chain_id" in mesh.attributes:
                    # Extract chain ID from object name
                    obj_chain_id = extract_chain_id_from_object_name(obj.name)
                    if obj_chain_id is not None:
                        # Get chain_id attribute
                        chain_id_attr = mesh.attributes["chain_id"]
                        chain_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                        chain_id_attr.data.foreach_get("value", chain_ids)

                        # Create mask for this chain only
                        chain_mask = (chain_ids == obj_chain_id)

                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)

                # Combine alpha carbon mask with chain mask if needed
                if chain_mask is not None:
                    combined_mask = is_alpha & chain_mask
                else:
                    combined_mask = is_alpha

                # Filter for alpha carbons (optionally filtered by chain)
                alpha_positions = positions[combined_mask]

                if len(alpha_positions) > 0:
                    # Check for residue IDs
                    if "res_id" in mesh.attributes:
                        res_id_attr = mesh.attributes["res_id"]
                        res_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                        res_id_attr.data.foreach_get("value", res_ids)
                        # Apply the same mask to residue IDs
                        alpha_res_ids = res_ids[combined_mask]

                        # Convert to world space and add to our collection
                        for ca_pos, res_id in zip(alpha_positions, alpha_res_ids):
                            world_pos = obj.matrix_world @ Vector(ca_pos)
                            all_alpha_positions.append(world_pos)
                            all_alpha_res_ids.append(res_id)
                    else:
                        # No residue data, just add positions
                        for ca_pos in alpha_positions:
                            world_pos = obj.matrix_world @ Vector(ca_pos)
                            all_alpha_positions.append(world_pos)
                            # Use index as pseudo res_id (will still find minimum)
                            all_alpha_res_ids.append(len(all_alpha_positions))
                    
            except Exception as e:
                # If any error occurs, store fallback
                print(f"Error getting alpha carbon for {obj.name}: {e}")
                if fallback_position is None:
                    fallback_position = obj.location
        
        # Now find the global first alpha carbon
        if all_alpha_positions and all_alpha_res_ids:
            # Find the alpha carbon with the minimum residue ID across ALL domains
            min_res_idx = np.argmin(all_alpha_res_ids)
            return all_alpha_positions[min_res_idx]
        elif fallback_position:
            return fallback_position
        
        return None
    
    def set_object_origin(self, obj, new_origin):
        """Set the object's origin to a new position"""
        # Store current state
        current_mode = bpy.context.mode
        original_active = bpy.context.view_layer.objects.active
        original_selection = [o for o in bpy.context.selected_objects]
        
        # Switch to object mode if needed
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Temporarily make this object active without changing selection
        bpy.context.view_layer.objects.active = obj
        
        # Ensure the object is selected for the operation
        was_selected = obj.select_get()
        if not was_selected:
            obj.select_set(True)
        
        # Set 3D cursor to new position
        bpy.context.scene.cursor.location = new_origin
        
        # Set origin to cursor (operates on active object)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
        
        # Restore selection if object wasn't originally selected
        if not was_selected:
            obj.select_set(False)
        
        # Restore original active object
        if original_active:
            bpy.context.view_layer.objects.active = original_active
        
        # Restore original mode
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)


class PROTEINBLENDER_OT_set_pivot_last(Operator):
    """Set pivot point to last residue (C-terminal)"""
    bl_idname = "proteinblender.set_pivot_last"
    bl_label = "Set Pivot to Last Residue"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Collect all valid objects
        valid_objects = []
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                if obj:
                    # Store original pivot if not already stored
                    if "original_pivot" not in obj:
                        obj["original_pivot"] = list(obj.location)
                    valid_objects.append(obj)
        
        if not valid_objects:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        
        # Find the last alpha carbon position across ALL selected objects
        last_ca_pos = self.get_last_alpha_carbon_combined(valid_objects)
        
        if last_ca_pos:
            # Set the same pivot position for all selected objects
            for obj in valid_objects:
                self.set_object_origin(obj, last_ca_pos)
            
            self.report({'INFO'}, f"Set pivot to last residue for {len(valid_objects)} item(s)")
        else:
            self.report({'WARNING'}, "Could not find alpha carbons")
        
        return {'FINISHED'}
    
    def get_last_alpha_carbon_combined(self, objects):
        """Find the position of the last alpha carbon across all selected domain objects"""
        if not objects:
            return None
        
        import numpy as np
        
        # Collect ALL alpha carbons from ALL domains
        all_alpha_positions = []
        all_alpha_res_ids = []
        fallback_position = None
        
        for obj in objects:
            # Check if this is a molecular object with attributes
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                # Fallback to object origin if not a proper molecular object
                if fallback_position is None:
                    fallback_position = obj.location
                continue
            
            try:
                # Check if alpha carbon attribute exists
                if "is_alpha_carbon" not in obj.data.attributes:
                    # No alpha carbon data, use object origin as fallback
                    if fallback_position is None:
                        fallback_position = obj.location
                    continue

                # Use the ORIGINAL mesh data (before geometry nodes evaluation)
                # This ensures alpha carbon positions are consistent regardless of style
                mesh = obj.data

                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)

                # Check if we need to filter by chain_id
                # The mesh might contain all chains, so we need to filter to this object's chain
                chain_mask = None
                if "chain_id" in mesh.attributes:
                    # Extract chain ID from object name
                    obj_chain_id = extract_chain_id_from_object_name(obj.name)
                    if obj_chain_id is not None:
                        # Get chain_id attribute
                        chain_id_attr = mesh.attributes["chain_id"]
                        chain_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                        chain_id_attr.data.foreach_get("value", chain_ids)

                        # Create mask for this chain only
                        chain_mask = (chain_ids == obj_chain_id)

                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)

                # Combine alpha carbon mask with chain mask if needed
                if chain_mask is not None:
                    combined_mask = is_alpha & chain_mask
                else:
                    combined_mask = is_alpha

                # Filter for alpha carbons (optionally filtered by chain)
                alpha_positions = positions[combined_mask]

                if len(alpha_positions) > 0:
                    # Check for residue IDs
                    if "res_id" in mesh.attributes:
                        res_id_attr = mesh.attributes["res_id"]
                        res_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                        res_id_attr.data.foreach_get("value", res_ids)
                        # Apply the same mask to residue IDs
                        alpha_res_ids = res_ids[combined_mask]

                        # Convert to world space and add to our collection
                        for ca_pos, res_id in zip(alpha_positions, alpha_res_ids):
                            world_pos = obj.matrix_world @ Vector(ca_pos)
                            all_alpha_positions.append(world_pos)
                            all_alpha_res_ids.append(res_id)
                    else:
                        # No residue data, just add positions
                        for ca_pos in alpha_positions:
                            world_pos = obj.matrix_world @ Vector(ca_pos)
                            all_alpha_positions.append(world_pos)
                            # Use index as pseudo res_id (will still find maximum)
                            all_alpha_res_ids.append(len(all_alpha_positions))
                    
            except Exception as e:
                # If any error occurs, store fallback
                print(f"Error getting alpha carbon for {obj.name}: {e}")
                if fallback_position is None:
                    fallback_position = obj.location
        
        # Now find the global last alpha carbon
        if all_alpha_positions and all_alpha_res_ids:
            # Find the alpha carbon with the maximum residue ID across ALL domains
            max_res_idx = np.argmax(all_alpha_res_ids)
            return all_alpha_positions[max_res_idx]
        elif fallback_position:
            return fallback_position
        
        return None
    
    def set_object_origin(self, obj, new_origin):
        """Set the object's origin to a new position"""
        # Store current state
        current_mode = bpy.context.mode
        original_active = bpy.context.view_layer.objects.active
        original_selection = [o for o in bpy.context.selected_objects]
        
        # Switch to object mode if needed
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Temporarily make this object active without changing selection
        bpy.context.view_layer.objects.active = obj
        
        # Ensure the object is selected for the operation
        was_selected = obj.select_get()
        if not was_selected:
            obj.select_set(True)
        
        # Set 3D cursor to new position
        bpy.context.scene.cursor.location = new_origin
        
        # Set origin to cursor (operates on active object)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
        
        # Restore selection if object wasn't originally selected
        if not was_selected:
            obj.select_set(False)
        
        # Restore original active object
        if original_active:
            bpy.context.view_layer.objects.active = original_active
        
        # Restore original mode
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)


class PROTEINBLENDER_OT_set_pivot_center(Operator):
    """Set pivot point to geometric center"""
    bl_idname = "proteinblender.set_pivot_center"
    bl_label = "Set Pivot to Center"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        # Collect all valid objects
        valid_objects = []
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                if obj:
                    # Store original pivot if not already stored
                    if "original_pivot" not in obj:
                        obj["original_pivot"] = list(obj.location)
                    valid_objects.append(obj)
        
        if not valid_objects:
            self.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        
        # Calculate geometric center across ALL selected objects
        center = self.get_geometric_center_combined(valid_objects)
        
        if center:
            # Set the same pivot position for all selected objects
            for obj in valid_objects:
                self.set_object_origin(obj, center)
            
            self.report({'INFO'}, f"Set pivot to center for {len(valid_objects)} item(s)")
        else:
            self.report({'WARNING'}, "Could not calculate center")
        
        return {'FINISHED'}
    
    def get_geometric_center_combined(self, objects):
        """Calculate the center of mass of alpha carbons across all selected domain objects"""
        if not objects:
            return None

        import numpy as np

        all_alpha_positions = []
        all_masses = []

        for obj in objects:
            # Check if this is a molecular object with attributes
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                # Fallback to bounding box center if not a proper molecular object
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                if bbox:
                    center = sum(bbox, Vector()) / len(bbox)
                    all_alpha_positions.append(center)
                    all_masses.append(1.0)  # Default mass
                continue
            
            try:
                # Check if alpha carbon attribute exists
                if "is_alpha_carbon" not in obj.data.attributes:
                    # No alpha carbon data, use bounding box center
                    bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                    if bbox:
                        center = sum(bbox, Vector()) / len(bbox)
                        all_alpha_positions.append(center)
                        all_masses.append(1.0)
                    continue

                # Use the ORIGINAL mesh data (before geometry nodes evaluation)
                # This ensures alpha carbon positions are consistent regardless of style
                mesh = obj.data

                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)

                # Check if we need to filter by chain_id
                # The mesh might contain all chains, so we need to filter to this object's chain
                chain_mask = None
                if "chain_id" in mesh.attributes:
                    # Extract chain ID from object name
                    obj_chain_id = extract_chain_id_from_object_name(obj.name)
                    if obj_chain_id is not None:
                        # Get chain_id attribute
                        chain_id_attr = mesh.attributes["chain_id"]
                        chain_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                        chain_id_attr.data.foreach_get("value", chain_ids)

                        # Create mask for this chain only
                        chain_mask = (chain_ids == obj_chain_id)

                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)

                # Combine alpha carbon mask with chain mask if needed
                if chain_mask is not None:
                    combined_mask = is_alpha & chain_mask
                else:
                    combined_mask = is_alpha

                # Filter for alpha carbons (optionally filtered by chain)
                alpha_positions = positions[combined_mask]

                if len(alpha_positions) > 0:
                    # Convert to world space and add to list
                    for ca_pos in alpha_positions:
                        world_pos = obj.matrix_world @ Vector(ca_pos)
                        all_alpha_positions.append(world_pos)
                        all_masses.append(12.01)  # Carbon mass
                else:
                    # No alpha carbons, use bounding box center
                    bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                    if bbox:
                        center = sum(bbox, Vector()) / len(bbox)
                        all_alpha_positions.append(center)
                        all_masses.append(1.0)

            except Exception as e:
                # If any error occurs, fallback to bounding box
                print(f"Error getting alpha carbons for {obj.name}: {e}")
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                if bbox:
                    center = sum(bbox, Vector()) / len(bbox)
                    all_alpha_positions.append(center)
                    all_masses.append(1.0)

        if all_alpha_positions:
            # Calculate center of mass
            total_mass = sum(all_masses)
            if total_mass > 0:
                weighted_sum = Vector((0, 0, 0))
                for pos, mass in zip(all_alpha_positions, all_masses):
                    weighted_sum += pos * mass
                return weighted_sum / total_mass
            else:
                # Simple average if mass calculation fails
                return sum(all_alpha_positions, Vector()) / len(all_alpha_positions)

        return None
    
    def set_object_origin(self, obj, new_origin):
        """Set the object's origin to a new position"""
        # Store current state
        current_mode = bpy.context.mode
        original_active = bpy.context.view_layer.objects.active
        original_selection = [o for o in bpy.context.selected_objects]
        
        # Switch to object mode if needed
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Temporarily make this object active without changing selection
        bpy.context.view_layer.objects.active = obj
        
        # Ensure the object is selected for the operation
        was_selected = obj.select_get()
        if not was_selected:
            obj.select_set(True)
        
        # Set 3D cursor to new position
        bpy.context.scene.cursor.location = new_origin
        
        # Set origin to cursor (operates on active object)
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
        
        # Restore selection if object wasn't originally selected
        if not was_selected:
            obj.select_set(False)
        
        # Restore original active object
        if original_active:
            bpy.context.view_layer.objects.active = original_active
        
        # Restore original mode
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)


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
    """Static version of set_object_origin for use in handlers"""
    # Store current state
    current_mode = bpy.context.mode
    original_active = bpy.context.view_layer.objects.active
    original_selection = [o for o in bpy.context.selected_objects]
    
    # Switch to object mode if needed
    if current_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # Temporarily make this object active without changing selection
    bpy.context.view_layer.objects.active = obj
    
    # Ensure the object is selected for the operation
    was_selected = obj.select_get()
    if not was_selected:
        obj.select_set(True)
    
    # Set 3D cursor to new position
    bpy.context.scene.cursor.location = new_origin
    
    # Set origin to cursor (operates on active object)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
    
    # Restore selection if object wasn't originally selected
    if not was_selected:
        obj.select_set(False)
    
    # Restore original active object
    if original_active:
        bpy.context.view_layer.objects.active = original_active
    
    # Restore original mode
    if current_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=current_mode)


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
        
        # Activate custom pivot mode
        scene["custom_pivot_active"] = True
        
        # Register the deselection handler if not already registered
        if custom_pivot_deselection_handler not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(custom_pivot_deselection_handler)
        
        self.report({'INFO'}, "Move the orange sphere to position pivot. Click elsewhere to confirm.")
        
        # Force UI redraw
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        
        return {'FINISHED'}
    
    def set_object_origin(self, obj, new_origin):
        """Set the object's origin to a new position"""
        set_object_origin_static(obj, new_origin)


# Classes to register
CLASSES = [
    PROTEINBLENDER_OT_set_pivot_first,
    PROTEINBLENDER_OT_set_pivot_last,
    PROTEINBLENDER_OT_set_pivot_center,
    PROTEINBLENDER_OT_set_pivot_custom,
]


def register():
    """Register pivot operators"""
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    
    # Register the deselection handler
    if custom_pivot_deselection_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(custom_pivot_deselection_handler)


def unregister():
    """Unregister pivot operators"""
    # Remove the deselection handler
    if custom_pivot_deselection_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(custom_pivot_deselection_handler)
    
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)