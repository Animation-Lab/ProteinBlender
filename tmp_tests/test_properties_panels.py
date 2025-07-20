"""Test script to verify all panels are configured for Properties editor."""

import bpy

def test_panel_configuration():
    """Test that all panels are configured correctly for Properties editor."""
    
    print("=== Testing Panel Configuration ===")
    
    # List of all our panels
    panel_classes = [
        'VIEW3D_PT_pb_importer',
        'VIEW3D_PT_pb_protein_outliner',
        'VIEW3D_PT_pb_visual_setup',
        'VIEW3D_PT_pb_domain_maker',
        'VIEW3D_PT_pb_group_maker',
        'VIEW3D_PT_pb_protein_pose_library',
        'VIEW3D_PT_pb_animate_scene',
    ]
    
    # Check each panel
    for panel_name in panel_classes:
        try:
            panel_class = getattr(bpy.types, panel_name)
            
            # Check space type
            if hasattr(panel_class, 'bl_space_type'):
                space_type = panel_class.bl_space_type
                print(f"\n{panel_name}:")
                print(f"  Space Type: {space_type}")
                
                if space_type != 'PROPERTIES':
                    print(f"  WARNING: Panel not configured for Properties editor!")
                
                # Check region type
                if hasattr(panel_class, 'bl_region_type'):
                    print(f"  Region Type: {panel_class.bl_region_type}")
                
                # Check context
                if hasattr(panel_class, 'bl_context'):
                    print(f"  Context: {panel_class.bl_context}")
                
                # Check order
                if hasattr(panel_class, 'bl_order'):
                    print(f"  Order: {panel_class.bl_order}")
            else:
                print(f"\n{panel_name}: Missing bl_space_type!")
                
        except AttributeError:
            print(f"\n{panel_name}: Panel class not found!")
    
    print("\n=== Creating ProteinBlender Workspace ===")
    
    # Create workspace
    bpy.ops.pb.create_workspace()
    
    # Check if workspace was created
    if "ProteinBlender" in bpy.data.workspaces:
        print("✓ Workspace created successfully")
        
        # Check if Properties editor exists
        workspace = bpy.data.workspaces["ProteinBlender"]
        has_properties = False
        
        for screen in workspace.screens:
            for area in screen.areas:
                if area.type == 'PROPERTIES':
                    has_properties = True
                    # Check if it's set to SCENE context
                    for space in area.spaces:
                        if space.type == 'PROPERTIES':
                            print(f"✓ Properties editor found with context: {space.context}")
                            if space.context != 'SCENE':
                                print("  WARNING: Properties context should be 'SCENE'")
                    break
        
        if not has_properties:
            print("✗ No Properties editor found in workspace!")
    else:
        print("✗ Failed to create workspace!")
    
    print("\n=== Panel Visibility Test ===")
    print("Switch to ProteinBlender workspace and check the Properties editor")
    print("All 7 panels should be visible in the Scene properties")

if __name__ == "__main__":
    test_panel_configuration()