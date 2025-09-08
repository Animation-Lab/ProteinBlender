"""Pivot point operators for domain rotation control"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty
from mathutils import Vector
from ..utils.scene_manager import ProteinBlenderScene
from bpy.app.handlers import persistent


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
        
        all_first_positions = []
        
        for obj in objects:
            # Check if this is a molecular object with attributes
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                # Fallback to object origin if not a proper molecular object
                all_first_positions.append(obj.location)
                continue
            
            try:
                # Check if alpha carbon attribute exists
                if "is_alpha_carbon" not in obj.data.attributes:
                    # No alpha carbon data, use object origin
                    all_first_positions.append(obj.location)
                    continue
                
                # Get the mesh data with evaluated modifiers
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.data
                
                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)
                
                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)
                
                # Check for residue IDs
                if "res_id" in mesh.attributes:
                    res_id_attr = mesh.attributes["res_id"]
                    res_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                    res_id_attr.data.foreach_get("value", res_ids)
                    
                    # Filter for alpha carbons
                    alpha_positions = positions[is_alpha]
                    alpha_res_ids = res_ids[is_alpha]
                    
                    if len(alpha_positions) > 0:
                        # Find the alpha carbon with the minimum residue ID
                        min_res_idx = np.argmin(alpha_res_ids)
                        first_ca_pos = alpha_positions[min_res_idx]
                        
                        # Convert to world space
                        first_pos = obj.matrix_world @ Vector(first_ca_pos)
                        all_first_positions.append(first_pos)
                    else:
                        all_first_positions.append(obj.location)
                else:
                    # No residue data, just use first alpha carbon by index
                    alpha_positions = positions[is_alpha]
                    if len(alpha_positions) > 0:
                        # Convert to world space
                        first_pos = obj.matrix_world @ Vector(alpha_positions[0])
                        all_first_positions.append(first_pos)
                    else:
                        all_first_positions.append(obj.location)
                    
            except Exception as e:
                # If any error occurs, fallback to object origin
                print(f"Error getting alpha carbon for {obj.name}: {e}")
                all_first_positions.append(obj.location)
        
        if all_first_positions:
            # Return the overall first position (minimum along main axis)
            # This handles multiple domains by finding the true N-terminal
            return min(all_first_positions, key=lambda p: (p.z))  # Proteins often align along Z
        
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
        
        all_last_positions = []
        
        for obj in objects:
            # Check if this is a molecular object with attributes
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                # Fallback to object origin if not a proper molecular object
                all_last_positions.append(obj.location)
                continue
            
            try:
                # Check if alpha carbon attribute exists
                if "is_alpha_carbon" not in obj.data.attributes:
                    # No alpha carbon data, use object origin
                    all_last_positions.append(obj.location)
                    continue
                
                # Get the mesh data with evaluated modifiers
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.data
                
                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)
                
                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)
                
                # Check for residue IDs
                if "res_id" in mesh.attributes:
                    res_id_attr = mesh.attributes["res_id"]
                    res_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                    res_id_attr.data.foreach_get("value", res_ids)
                    
                    # Filter for alpha carbons
                    alpha_positions = positions[is_alpha]
                    alpha_res_ids = res_ids[is_alpha]
                    
                    if len(alpha_positions) > 0:
                        # Find the alpha carbon with the maximum residue ID
                        max_res_idx = np.argmax(alpha_res_ids)
                        last_ca_pos = alpha_positions[max_res_idx]
                        
                        # Convert to world space
                        last_pos = obj.matrix_world @ Vector(last_ca_pos)
                        all_last_positions.append(last_pos)
                    else:
                        all_last_positions.append(obj.location)
                else:
                    # No residue data, just use last alpha carbon by index
                    alpha_positions = positions[is_alpha]
                    if len(alpha_positions) > 0:
                        # Convert to world space
                        last_pos = obj.matrix_world @ Vector(alpha_positions[-1])
                        all_last_positions.append(last_pos)
                    else:
                        all_last_positions.append(obj.location)
                    
            except Exception as e:
                # If any error occurs, fallback to object origin
                print(f"Error getting alpha carbon for {obj.name}: {e}")
                all_last_positions.append(obj.location)
        
        if all_last_positions:
            # Return the overall last position (maximum along main axis)
            # This handles multiple domains by finding the true C-terminal
            return max(all_last_positions, key=lambda p: (p.z))  # Proteins often align along Z
        
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
                
                # Get the mesh data with evaluated modifiers
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(depsgraph)
                mesh = eval_obj.data
                
                # Get alpha carbon mask
                is_alpha_attr = mesh.attributes["is_alpha_carbon"]
                is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
                is_alpha_attr.data.foreach_get("value", is_alpha)
                
                # Get vertex positions
                positions = np.zeros(len(mesh.vertices) * 3)
                mesh.vertices.foreach_get("co", positions)
                positions = positions.reshape(-1, 3)
                
                # Filter for alpha carbons
                alpha_positions = positions[is_alpha]
                
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
    
    # Clean up the empty object
    try:
        bpy.data.objects.remove(pivot_empty, do_unlink=True)
    except:
        pass  # Already removed
    
    # Clean up stored data
    if "custom_pivot_target_items" in scene:
        del scene["custom_pivot_target_items"]
    
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
        for obj in bpy.data.objects:
            if obj.name.startswith("PROTEINBLENDER_PIVOT_GIZMO"):
                bpy.data.objects.remove(obj, do_unlink=True)
        
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
        pivot_empty.location = first_obj.location.copy()
        
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


class PROTEINBLENDER_OT_reset_pivot(Operator):
    """Reset pivot point to original position"""
    bl_idname = "proteinblender.reset_pivot"
    bl_label = "Reset Pivot to Origin"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Clean up any active custom pivot mode
        if scene.get("custom_pivot_active", False):
            pivot_empty = bpy.data.objects.get("PROTEINBLENDER_PIVOT_GIZMO")
            if pivot_empty:
                bpy.data.objects.remove(pivot_empty, do_unlink=True)
            scene["custom_pivot_active"] = False
            if "custom_pivot_target_items" in scene:
                del scene["custom_pivot_target_items"]
        
        # Get selected items
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        if not selected_items:
            self.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        
        success_count = 0
        for item in selected_items:
            if item.item_type == 'DOMAIN' or item.item_type == 'CHAIN':
                obj = bpy.data.objects.get(item.object_name) if item.object_name else None
                if obj:
                    # Check if we have stored original pivot
                    if "original_pivot" in obj:
                        original_pos = Vector(obj["original_pivot"])
                        self.set_object_origin(obj, original_pos)
                        success_count += 1
                    else:
                        # Reset to parent's origin
                        if obj.parent:
                            self.set_object_origin(obj, obj.parent.location)
                            success_count += 1
                        else:
                            # Reset to world origin
                            self.set_object_origin(obj, Vector((0, 0, 0)))
                            success_count += 1
        
        if success_count > 0:
            self.report({'INFO'}, f"Reset pivot for {success_count} item(s)")
        
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
    PROTEINBLENDER_OT_reset_pivot,
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