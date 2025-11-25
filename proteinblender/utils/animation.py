"""Animation utilities for ProteinBlender.

This module provides centralized keyframe functions using quaternion rotation
for proper shortest-path interpolation.
"""

import bpy
from mathutils import Vector, Quaternion


def ensure_quaternion_mode(obj):
    """Ensure object uses quaternion rotation mode for proper interpolation.
    
    Quaternions avoid the "long way around" rotation issue that occurs with
    Euler angles when interpolating between keyframes.
    """
    if not obj:
        return
    if obj.rotation_mode != 'QUATERNION':
        # Convert current Euler to Quaternion before switching
        current_euler = obj.rotation_euler.copy()
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = current_euler.to_quaternion()
        
        # Clean up any old Euler keyframes that might interfere
        if obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            euler_fcurves = [fc for fc in action.fcurves if fc.data_path == "rotation_euler"]
            for fc in euler_fcurves:
                action.fcurves.remove(fc)


def _get_previous_quaternion_keyframe(obj, current_frame):
    """Get the quaternion value from the previous keyframe before current_frame."""
    if not obj.animation_data or not obj.animation_data.action:
        return None
    
    action = obj.animation_data.action
    
    # Find the W component fcurve for rotation_quaternion
    w_fcurve = None
    x_fcurve = None
    y_fcurve = None
    z_fcurve = None
    
    for fcurve in action.fcurves:
        if fcurve.data_path == "rotation_quaternion":
            if fcurve.array_index == 0:
                w_fcurve = fcurve
            elif fcurve.array_index == 1:
                x_fcurve = fcurve
            elif fcurve.array_index == 2:
                y_fcurve = fcurve
            elif fcurve.array_index == 3:
                z_fcurve = fcurve
    
    if not all([w_fcurve, x_fcurve, y_fcurve, z_fcurve]):
        return None
    
    # Find the keyframe just before current_frame
    prev_frame = None
    for kp in w_fcurve.keyframe_points:
        if kp.co.x < current_frame:
            if prev_frame is None or kp.co.x > prev_frame:
                prev_frame = kp.co.x
    
    if prev_frame is None:
        return None
    
    # Get quaternion values at that frame
    w = w_fcurve.evaluate(prev_frame)
    x = x_fcurve.evaluate(prev_frame)
    y = y_fcurve.evaluate(prev_frame)
    z = z_fcurve.evaluate(prev_frame)
    
    return Quaternion((w, x, y, z))


def _ensure_shortest_path_quaternion(obj, frame):
    """Ensure the current quaternion takes the shortest path from previous keyframe.
    
    Quaternions q and -q represent the same rotation, but interpolating between
    q1 and q2 vs q1 and -q2 can result in different paths. If dot(q1, q2) < 0,
    we should negate q2 to ensure shortest path interpolation.
    """
    prev_quat = _get_previous_quaternion_keyframe(obj, frame)
    if prev_quat is None:
        # First keyframe - nothing to compare against
        return
    
    current_quat = obj.rotation_quaternion.copy()
    
    # Calculate dot product
    dot = prev_quat.dot(current_quat)
    
    # If dot product is negative, quaternions are on opposite hemispheres
    # Negate the current quaternion to ensure shortest path
    if dot < 0:
        obj.rotation_quaternion = Quaternion((-current_quat.w, -current_quat.x, -current_quat.y, -current_quat.z))


def keyframe_transforms(obj, frame, location=True, rotation=True, scale=True):
    """Insert keyframes for standard transforms using quaternion rotation.
    
    Uses quaternion rotation mode to ensure shortest-path interpolation
    between rotation keyframes.
    """
    if not obj:
        return
    
    # Ensure quaternion mode for proper shortest-path rotation interpolation
    if rotation:
        ensure_quaternion_mode(obj)
        # Ensure shortest path by checking quaternion hemisphere
        _ensure_shortest_path_quaternion(obj, frame)
        
    if location:
        obj.keyframe_insert(data_path="location", frame=frame)
    if rotation:
        obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    if scale:
        obj.keyframe_insert(data_path="scale", frame=frame)

    # Adjust interpolation to BEZIER for smoother animation
    if obj.animation_data and obj.animation_data.action:
        for fcurve in obj.animation_data.action.fcurves:
            for kp in fcurve.keyframe_points:
                if abs(kp.co.x - frame) < 0.001:
                    kp.interpolation = 'BEZIER'


def delete_transform_keyframes(obj, frame, location=True, rotation=True, scale=True):
    """Delete keyframes for standard transforms at a specific frame."""
    if not obj or not obj.animation_data or not obj.animation_data.action:
        return

    data_paths = []
    if location:
        data_paths.append("location")
    if rotation:
        # Handle both rotation types for backwards compatibility
        data_paths.append("rotation_euler")
        data_paths.append("rotation_quaternion")
    if scale:
        data_paths.append("scale")
    
    for path in data_paths:
        try:
            obj.keyframe_delete(data_path=path, frame=frame)
        except:
            pass  # Keyframe might not exist


def delete_transform_keyframes_in_range(objects, start_frame, end_frame, step=1):
    """Safely delete keyframes in a frame range."""
    if start_frame >= end_frame or step <= 0:
        return
        
    for f in range(start_frame, end_frame, step):
        for obj in objects:
            delete_transform_keyframes(obj, f)


def keyframe_color_properties(obj, frame):
    """Keyframe color properties for MolecularNodes/ProteinBlender domains."""
    mod = None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES':
            mod = modifier
            break

    if not mod or not mod.node_group:
        return False

    node_tree = mod.node_group
    keyframed_rgb = False
    keyframed_alpha = False

    # Look for the Custom Combine Color node
    for node in node_tree.nodes:
        if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
            try:
                node.inputs['Red'].keyframe_insert("default_value", frame=frame)
                node.inputs['Green'].keyframe_insert("default_value", frame=frame)
                node.inputs['Blue'].keyframe_insert("default_value", frame=frame)
                keyframed_rgb = True
            except Exception as e:
                print(f"Error keyframing RGB nodes for {obj.name}: {e}")
            break
    
    # Keyframe alpha in Style node
    style_node = None
    for node in node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
            style_node = node
            break

    if style_node:
        material_input = style_node.inputs.get("Material")
        if material_input and material_input.default_value:
            mat = material_input.default_value
            if mat.use_nodes and mat.node_tree:
                for mat_node in mat.node_tree.nodes:
                    if mat_node.type == 'BSDF_PRINCIPLED':
                        try:
                            mat_node.inputs['Alpha'].keyframe_insert("default_value", frame=frame)
                            keyframed_alpha = True
                        except Exception as e:
                            print(f"Error keyframing alpha for {obj.name}: {e}")
                        break
                        
    return keyframed_rgb or keyframed_alpha


def remove_color_keyframes(obj, frame):
    """Remove color keyframes from MolecularNodes/ProteinBlender domains."""
    mod = None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES':
            mod = modifier
            break

    if not mod or not mod.node_group:
        return False

    node_tree = mod.node_group
    removed = False

    # RGB
    for node in node_tree.nodes:
        if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
            try:
                node.inputs['Red'].keyframe_delete("default_value", frame=frame)
                node.inputs['Green'].keyframe_delete("default_value", frame=frame)
                node.inputs['Blue'].keyframe_delete("default_value", frame=frame)
                removed = True
            except:
                pass
            break

    # Alpha
    style_node = None
    for node in node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
            style_node = node
            break

    if style_node:
        material_input = style_node.inputs.get("Material")
        if material_input and material_input.default_value:
            mat = material_input.default_value
            if mat.use_nodes and mat.node_tree:
                for mat_node in mat.node_tree.nodes:
                    if mat_node.type == 'BSDF_PRINCIPLED':
                        try:
                            mat_node.inputs['Alpha'].keyframe_delete("default_value", frame=frame)
                            removed = True
                        except:
                            pass
                        break
    return removed


def has_color_keyframe(obj, frame):
    """Check if a color keyframe exists at the specified frame."""
    mod = None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES':
            mod = modifier
            break

    if not mod or not mod.node_group:
        return False

    node_tree = mod.node_group

    # Check Custom Combine Color node for RGB keyframes
    for node in node_tree.nodes:
        if node.name == "Custom Combine Color" and node.type == 'COMBINE_COLOR':
            if node_tree.animation_data and node_tree.animation_data.action:
                for fcurve in node_tree.animation_data.action.fcurves:
                    if node.name in fcurve.data_path:
                        for kf in fcurve.keyframe_points:
                            if abs(kf.co.x - frame) < 0.01:
                                return True
            break

    # Also check material alpha keyframes
    style_node = None
    for node in node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
            style_node = node
            break

    if style_node:
        material_input = style_node.inputs.get("Material")
        if material_input and material_input.default_value:
            mat = material_input.default_value
            if mat.use_nodes and mat.node_tree:
                if mat.node_tree.animation_data and mat.node_tree.animation_data.action:
                    for fcurve in mat.node_tree.animation_data.action.fcurves:
                        if 'Alpha' in fcurve.data_path:
                            for kf in fcurve.keyframe_points:
                                if abs(kf.co.x - frame) < 0.01:
                                    return True
    return False


def refresh_timeline():
    """Force refresh of Blender's timeline and UI."""
    bpy.context.view_layer.update()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ['TIMELINE', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'VIEW_3D', 'PROPERTIES']:
                area.tag_redraw()
    
    current_frame = bpy.context.scene.frame_current
    bpy.context.scene.frame_set(current_frame)
