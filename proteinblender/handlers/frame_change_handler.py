"""Frame change handler for updating animated properties"""

import bpy
from bpy.app.handlers import persistent


@persistent
def update_colors_on_frame_change(scene):
    """Update object colors from custom properties when frame changes"""
    # Import here to avoid circular imports
    from ..panels.visual_setup_panel import apply_color_to_object
    
    # Track which objects we've updated to avoid redundant updates
    updated_objects = set()
    
    # Check all objects for color properties
    for obj in bpy.data.objects:
        # Skip if already updated or no color property
        if obj in updated_objects or "pb_color" not in obj:
            continue
            
        # Get the interpolated color value at the current frame
        # Blender automatically interpolates custom properties if they're keyframed
        color = obj["pb_color"]
        
        # Apply the color to the object's visual representation
        if color and len(color) >= 3:
            # Convert to tuple (RGBA)
            if len(color) == 3:
                color = (*color, 1.0)  # Add alpha if not present
            else:
                color = tuple(color[:4])  # Ensure we have exactly 4 components
            
            apply_color_to_object(obj, color)
            updated_objects.add(obj)
            
            # Debug output (can be removed later)
            print(f"Frame {scene.frame_current}: Updated color for {obj.name} to {color}")


def register():
    """Register the frame change handler"""
    # Remove any existing handlers to avoid duplicates
    unregister()
    
    # Add the handler
    bpy.app.handlers.frame_change_post.append(update_colors_on_frame_change)
    print("Registered color update frame change handler")


def unregister():
    """Unregister the frame change handler"""
    # Remove all instances of our handler
    handlers_to_remove = [h for h in bpy.app.handlers.frame_change_post 
                         if h.__name__ == "update_colors_on_frame_change"]
    
    for handler in handlers_to_remove:
        bpy.app.handlers.frame_change_post.remove(handler)
    
    if handlers_to_remove:
        print(f"Unregistered {len(handlers_to_remove)} color update frame change handler(s)")