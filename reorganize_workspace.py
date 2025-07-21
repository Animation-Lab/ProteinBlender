"""Script to reorganize Blender workspace layout - moves Dope Sheet to bottom"""

import bpy

def reorganize_workspace():
    """Reorganize the current workspace to move Dope Sheet to bottom"""
    
    # Get the current workspace
    workspace = bpy.context.workspace
    
    # Find the screen associated with this workspace
    screen = workspace.screens[0] if workspace.screens else None
    if not screen:
        print("No screen found in workspace")
        return
    
    # Find areas by type
    dopesheet_area = None
    view3d_area = None
    
    for area in screen.areas:
        if area.type == 'DOPESHEET_EDITOR':
            dopesheet_area = area
        elif area.type == 'VIEW_3D':
            view3d_area = area
    
    if not dopesheet_area:
        print("No Dope Sheet editor found")
        return
        
    if not view3d_area:
        print("No 3D Viewport found")
        return
    
    # Store the current height of the dopesheet
    dopesheet_height = dopesheet_area.height
    
    # We need to split the 3D view area horizontally to create space at the bottom
    # First, we'll join areas if needed to create a clean layout
    
    # Override context for area operations
    override = {'area': view3d_area, 'region': view3d_area.regions[0]}
    
    # Split the 3D view horizontally near the bottom
    # The factor determines where the split occurs (0.8 means 80% for top, 20% for bottom)
    # We'll calculate based on the current dopesheet height
    total_height = view3d_area.height + dopesheet_height
    split_factor = 1.0 - (dopesheet_height / total_height)
    
    with bpy.context.temp_override(**override):
        bpy.ops.screen.area_split(direction='HORIZONTAL', factor=split_factor)
    
    # Find the newly created area (it will be the one with the smallest height)
    new_area = None
    for area in screen.areas:
        if area.type == 'VIEW_3D' and area != view3d_area:
            if new_area is None or area.height < new_area.height:
                new_area = area
    
    if new_area:
        # Change the new area to Dope Sheet
        new_area.type = 'DOPESHEET_EDITOR'
        
        # Now we need to close the original dopesheet area
        # We'll join it with the 3D view
        override_close = {'area': dopesheet_area}
        with bpy.context.temp_override(**override_close):
            # Set cursor position to trigger join
            # This is a bit tricky - we need to position cursor at the edge
            bpy.ops.screen.area_close()
        
        print("Successfully moved Dope Sheet to bottom")
    else:
        print("Failed to create new area")

# Run the reorganization
if __name__ == "__main__":
    reorganize_workspace()