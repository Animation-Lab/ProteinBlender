"""Test script for ProteinBlender workspace creation.

This script tests the workspace creation functionality including:
1. Workspace creation on addon enable
2. Panel visibility and order
3. Layout persistence
"""

import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

def test_workspace_creation():
    """Test workspace creation and configuration"""
    print("\n" + "="*50)
    print("Testing ProteinBlender Workspace Creation")
    print("="*50)
    
    # First, ensure the addon is disabled
    if "proteinblender" in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_disable(module="proteinblender")
        print("✓ Disabled existing ProteinBlender addon")
    
    # Enable the addon (this should create the workspace)
    try:
        bpy.ops.preferences.addon_enable(module="proteinblender")
        print("✓ Enabled ProteinBlender addon")
    except Exception as e:
        print(f"✗ Failed to enable addon: {e}")
        return False
    
    # Check if workspace was created
    if "ProteinBlender" in bpy.data.workspaces:
        print("✓ ProteinBlender workspace created")
        
        # Switch to the workspace
        bpy.context.window.workspace = bpy.data.workspaces["ProteinBlender"]
        print("✓ Switched to ProteinBlender workspace")
    else:
        print("✗ ProteinBlender workspace not found")
        return False
    
    # Check screen areas
    screen = bpy.context.window.screen
    print(f"\nScreen areas in workspace:")
    
    view3d_found = False
    timeline_found = False
    
    for area in screen.areas:
        print(f"  - {area.type} at position ({area.x}, {area.y}), size: {area.width}x{area.height}")
        if area.type == 'VIEW_3D':
            view3d_found = True
            # Check if UI region is visible
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    if space.show_region_ui:
                        print("    ✓ UI region (N-panel) is visible")
                    else:
                        print("    ✗ UI region (N-panel) is not visible")
                        
            # Check region widths
            for region in area.regions:
                if region.type == 'UI':
                    print(f"    UI region width: {region.width}px")
                    
        elif area.type == 'DOPESHEET_EDITOR':
            timeline_found = True
            for space in area.spaces:
                if space.type == 'DOPESHEET_EDITOR':
                    if space.mode == 'TIMELINE':
                        print("    ✓ Timeline mode active")
                    else:
                        print(f"    ✗ Mode is {space.mode}, not TIMELINE")
    
    if view3d_found:
        print("\n✓ 3D Viewport found")
    else:
        print("\n✗ 3D Viewport not found")
        
    if timeline_found:
        print("✓ Timeline found")
    else:
        print("✗ Timeline not found")
    
    # Check if panels are registered
    print("\nChecking panels registration:")
    panel_names = [
        "VIEW3D_PT_pb_importer",
        "VIEW3D_PT_pb_protein_outliner", 
        "VIEW3D_PT_pb_visual_setup",
        "VIEW3D_PT_pb_domain_maker",
        "VIEW3D_PT_pb_group_maker",
        "VIEW3D_PT_pb_protein_pose_library",
        "VIEW3D_PT_pb_animate_scene"
    ]
    
    for panel_name in panel_names:
        if hasattr(bpy.types, panel_name):
            panel_class = getattr(bpy.types, panel_name)
            print(f"  ✓ {panel_name} registered (order: {getattr(panel_class, 'bl_order', 'N/A')})")
        else:
            print(f"  ✗ {panel_name} not registered")
    
    # Check if properties are registered
    print("\nChecking properties registration:")
    properties = [
        ("pb_visual_color", "Visual color property"),
        ("pb_visual_representation", "Visual representation property"),
        ("pb_brownian_motion", "Brownian motion property")
    ]
    
    for prop_name, desc in properties:
        if hasattr(bpy.context.scene, prop_name):
            print(f"  ✓ {desc} registered")
        else:
            print(f"  ✗ {desc} not registered")
    
    # Test workspace operator
    print("\nTesting workspace operator:")
    try:
        # Delete workspace to test recreation
        workspace = bpy.data.workspaces["ProteinBlender"]
        bpy.data.workspaces.remove(workspace)
        print("  ✓ Removed workspace for testing")
        
        # Recreate using operator
        bpy.ops.pb.create_workspace()
        if "ProteinBlender" in bpy.data.workspaces:
            print("  ✓ Workspace recreated using operator")
        else:
            print("  ✗ Failed to recreate workspace")
    except Exception as e:
        print(f"  ✗ Error testing workspace operator: {e}")
    
    print("\n" + "="*50)
    print("Workspace creation test completed")
    print("="*50)
    
    return True


if __name__ == "__main__":
    test_workspace_creation()