import bpy
import random
from mathutils import Vector, Quaternion
import json

def keyframe_transforms(obj, frame, location=True, rotation=True, scale=True):
    """Insert keyframes for standard transforms."""
    if not obj:
        return
        
    if location:
        obj.keyframe_insert(data_path="location", frame=frame)
    if rotation:
        obj.keyframe_insert(data_path="rotation_euler", frame=frame)
    if scale:
        obj.keyframe_insert(data_path="scale", frame=frame)

    # Adjust interpolation to BEZIER for smoother animation by default
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
    if location: data_paths.append("location")
    if rotation: 
        data_paths.append("rotation_euler")
        data_paths.append("rotation_quaternion")
    if scale: data_paths.append("scale")
    
    for path in data_paths:
        try:
            obj.keyframe_delete(data_path=path, frame=frame)
        except:
            pass # Keyframe might not exist

def delete_transform_keyframes_in_range(objects, start_frame, end_frame, step=1):
    """Safely delete keyframes in a frame range."""
    if start_frame >= end_frame or step <= 0:
        return
        
    for f in range(start_frame, end_frame, step):
        if f >= end_frame:
            break
        for obj in objects:
            delete_transform_keyframes(obj, f)

def keyframe_color_properties(obj, frame):
    """Keyframe color properties for MolecularNodes/ProteinBlender domains."""
    # Find the MolecularNodes modifier
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
            # Check if RGB inputs have animation data
            # Note: We need to check the node group's animation data
            if node_tree.animation_data and node_tree.animation_data.action:
                for fcurve in node_tree.animation_data.action.fcurves:
                    # Check if this fcurve targets this node's input
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

def bake_brownian(op, context, molecule, start_frame, end_frame, intensity, frequency, seed, resolution):
    """Bake Brownian motion keyframes between two frames using linear interpolation + jitter."""
    random.seed(seed)
    scene = context.scene
    
    # Collect all objects to animate: protein + all domain objects
    objects_to_animate = []
    if molecule.object:
        objects_to_animate.append(molecule.object)
    
    # Add all domain objects
    for domain_id, domain in molecule.domains.items():
        if domain.object:
            objects_to_animate.append(domain.object)
    
    # For each object, store starting and ending transforms
    object_transforms = {}
    
    # Helper to capture transform
    def capture_transform(obj):
        return {
            'loc': obj.location.copy(),
            'rot': obj.rotation_euler.copy(),
            'scale': obj.scale.copy()
        }

    # Sample starting transforms
    scene.frame_set(start_frame)
    for obj in objects_to_animate:
        object_transforms[obj.name] = {'start': capture_transform(obj)}
    
    # Sample ending transforms
    scene.frame_set(end_frame)
    for obj in objects_to_animate:
        object_transforms[obj.name]['end'] = capture_transform(obj)
    
    duration = end_frame - start_frame
    
    # Iterate and apply brownian motion
    for f in range(start_frame + resolution, end_frame, resolution):
        t = (f - start_frame) / duration
        scene.frame_set(f)
        
        for obj in objects_to_animate:
            transforms = object_transforms[obj.name]
            start = transforms['start']
            end = transforms['end']
            
            # Linear interpolation
            loc = start['loc'].lerp(end['loc'], t)
            
            # Use Slerp (Spherical Linear Interpolation) for rotation
            # This avoids the "long way around" issue by taking the shortest path on the sphere
            q_start = start['rot'].to_quaternion()
            q_end = end['rot'].to_quaternion()
            q_interp = q_start.slerp(q_end, t)
            
            # Convert back to Euler, preserving original rotation order
            rot = q_interp.to_euler(start['rot'].order)
            
            scale = start['scale'].lerp(end['scale'], t)
            
            # Jitter (use different random values for each object)
            # Use a deterministic seed based on object name and frame to avoid jitter jumping if re-run
            obj_seed = seed + hash(obj.name) + f 
            random.seed(obj_seed)
            
            loc += Vector((random.uniform(-intensity, intensity),
                           random.uniform(-intensity, intensity),
                           random.uniform(-intensity, intensity)))
            
            rot.x += random.uniform(-intensity, intensity)
            rot.y += random.uniform(-intensity, intensity)
            rot.z += random.uniform(-intensity, intensity)
            
            # Apply and keyframe
            obj.location = loc
            obj.rotation_euler = rot
            obj.scale = scale
            
            keyframe_transforms(obj, f)
    
    # Restore end frame
    scene.frame_set(end_frame)

def refresh_timeline():
    """Force refresh of Blender's timeline and UI."""
    bpy.context.view_layer.update()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ['TIMELINE', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'VIEW_3D', 'PROPERTIES']:
                area.tag_redraw()
    
    # Also update the scene frame to trigger refresh
    current_frame = bpy.context.scene.frame_current
    bpy.context.scene.frame_set(current_frame)
