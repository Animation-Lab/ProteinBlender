import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.abspath(__file__))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

# Import and register the addon
try:
    # First unregister if already registered
    from proteinblender import addon
    try:
        addon.unregister()
    except:
        pass
    
    # Now register
    addon.register()
    print("ProteinBlender addon registered successfully!")
    
    # Check if panels are registered
    print("\nRegistered panels:")
    for cls in bpy.types.__dir__():
        if cls.startswith("PROTEIN") and "_PT_" in cls:
            print(f"  - {cls}")
    
    # Check sidebar visibility
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    print(f"\nSidebar visible: {space.show_region_ui}")
                    
    print("\nPanels should now be visible in the 3D View sidebar under the 'ProteinBlender' tab.")
    print("Press 'N' in the 3D viewport to toggle the sidebar if it's not visible.")
    
except Exception as e:
    print(f"Error registering addon: {e}")
    import traceback
    traceback.print_exc()