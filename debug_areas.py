"""Debug script to understand the current area layout"""

import bpy

def debug_areas():
    """Print information about all areas in the current screen"""
    screen = bpy.context.screen
    
    print("\n" + "="*60)
    print("CURRENT SCREEN AREAS:")
    print("="*60)
    
    areas_info = []
    
    for i, area in enumerate(screen.areas):
        info = {
            'index': i,
            'type': area.type,
            'x': area.x,
            'y': area.y,
            'width': area.width,
            'height': area.height,
            'bottom': area.y,
            'top': area.y + area.height
        }
        areas_info.append(info)
        
        print(f"\nArea {i}: {area.type}")
        print(f"  Position: x={area.x}, y={area.y}")
        print(f"  Size: width={area.width}, height={area.height}")
        print(f"  Bottom edge: {area.y}")
        print(f"  Top edge: {area.y + area.height}")
    
    # Find relationships
    print("\n" + "="*60)
    print("AREA RELATIONSHIPS:")
    print("="*60)
    
    for info in areas_info:
        if info['type'] == 'DOPESHEET_EDITOR':
            print(f"\nDOPESHEET is at y={info['y']} (bottom={info['bottom']}, top={info['top']})")
            
            # Check what's below and above
            for other in areas_info:
                if other['type'] != 'DOPESHEET_EDITOR':
                    if abs(other['top'] - info['bottom']) < 5:
                        print(f"  - {other['type']} is BELOW the Dopesheet")
                    elif abs(other['bottom'] - info['top']) < 5:
                        print(f"  - {other['type']} is ABOVE the Dopesheet")
    
    return areas_info

def swap_areas_correctly():
    """Swap the area types between Dopesheet and 3D View"""
    screen = bpy.context.screen
    
    # Get all areas and their info
    areas_info = debug_areas()
    
    # Find dopesheet and 3d view
    dopesheet_area = None
    view3d_area = None
    dopesheet_info = None
    view3d_info = None
    
    for area, info in zip(screen.areas, areas_info):
        if area.type == 'DOPESHEET_EDITOR':
            dopesheet_area = area
            dopesheet_info = info
        elif area.type == 'VIEW_3D':
            view3d_area = area
            view3d_info = info
    
    if dopesheet_area and view3d_area:
        print("\n" + "="*60)
        print("SWAPPING AREAS...")
        print("="*60)
        
        # Simply swap the types
        temp_type = dopesheet_area.type
        dopesheet_area.type = view3d_area.type
        view3d_area.type = temp_type
        
        print("Swapped area types!")
        print(f"Area at y={dopesheet_info['y']} is now: {dopesheet_area.type}")
        print(f"Area at y={view3d_info['y']} is now: {view3d_area.type}")
        
        # Tag for redraw
        for area in screen.areas:
            area.tag_redraw()
        
        return True
    
    return False

# Run the debug and swap
if __name__ == "__main__":
    print("Analyzing current layout...")
    swap_areas_correctly()