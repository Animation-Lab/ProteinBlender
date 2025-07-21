"""Script to move Dope Sheet to bottom of screen while preserving its size"""

import bpy

# Instructions:
# 1. Run this script in Blender's Text Editor
# 2. The script will attempt to reorganize your workspace
# 3. If automatic reorganization doesn't work perfectly, you can manually:
#    - Hold mouse over the border between Dope Sheet and 3D View
#    - Right-click and choose "Swap Areas"

def move_dopesheet_to_bottom():
    """Swap Dope Sheet and 3D Viewport positions"""
    
    # Get current screen
    screen = bpy.context.screen
    
    # Find the Dope Sheet and 3D Viewport areas
    dopesheet = None
    viewport = None
    
    for area in screen.areas:
        if area.type == 'DOPESHEET_EDITOR':
            dopesheet = area
        elif area.type == 'VIEW_3D':
            viewport = area
    
    if not dopesheet or not viewport:
        print("Could not find both Dope Sheet and 3D Viewport")
        return False
    
    # Check if dopesheet is above viewport (by comparing y coordinates)
    # In Blender, y coordinates increase from bottom to top
    if dopesheet.y > viewport.y:
        print("Dope Sheet is currently above 3D Viewport")
        
        # Swap the area types
        dopesheet.type = 'VIEW_3D'
        viewport.type = 'DOPESHEET_EDITOR'
        
        print("Successfully swapped Dope Sheet to bottom!")
        return True
    else:
        print("Dope Sheet is already at the bottom")
        return True

# Alternative manual method
def print_manual_instructions():
    print("\n" + "="*50)
    print("MANUAL METHOD:")
    print("="*50)
    print("1. Position your mouse cursor on the border between")
    print("   the Dope Sheet and 3D Viewport")
    print("2. Right-click on the border")
    print("3. Select 'Swap Areas' from the context menu")
    print("4. The areas will swap positions instantly")
    print("="*50 + "\n")

# Run the script
if __name__ == "__main__":
    success = move_dopesheet_to_bottom()
    
    if not success:
        print_manual_instructions()
    
    # Force redraw
    for area in bpy.context.screen.areas:
        area.tag_redraw()