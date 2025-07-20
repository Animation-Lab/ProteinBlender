"""Complete UI test to verify all panels work in Properties editor."""

import bpy

def test_complete_ui():
    """Test the complete UI setup with all panels in Properties editor."""
    
    print("=== Complete UI Test ===")
    
    # First, ensure addon is loaded
    addon_name = "proteinblender"
    if addon_name not in bpy.context.preferences.addons:
        print(f"ERROR: {addon_name} addon not loaded!")
        return
    
    print(f"✓ {addon_name} addon is loaded")
    
    # Create workspace
    print("\n1. Creating ProteinBlender workspace...")
    try:
        bpy.ops.pb.create_workspace()
        print("✓ Workspace created/activated")
    except Exception as e:
        print(f"✗ Failed to create workspace: {e}")
        return
    
    # Verify workspace structure
    print("\n2. Verifying workspace structure...")
    workspace = bpy.data.workspaces.get("ProteinBlender")
    if not workspace:
        print("✗ ProteinBlender workspace not found!")
        return
    
    print("✓ ProteinBlender workspace exists")
    
    # Check areas
    for screen in workspace.screens:
        print(f"\nScreen: {screen.name}")
        area_types = {}
        for area in screen.areas:
            area_type = area.type
            if area_type not in area_types:
                area_types[area_type] = 0
            area_types[area_type] += 1
            
            # Check Properties editor configuration
            if area_type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        print(f"  Properties editor context: {space.context}")
        
        print("  Areas:", area_types)
    
    # Test panel visibility
    print("\n3. Testing panel registration...")
    panels_found = []
    panels_missing = []
    
    expected_panels = [
        ('VIEW3D_PT_pb_importer', 'Importer'),
        ('VIEW3D_PT_pb_protein_outliner', 'Protein Outliner'),
        ('VIEW3D_PT_pb_visual_setup', 'Visual Set-up'),
        ('VIEW3D_PT_pb_domain_maker', 'Domain Maker'),
        ('VIEW3D_PT_pb_group_maker', 'Group Maker'),
        ('VIEW3D_PT_pb_protein_pose_library', 'Protein Pose Library'),
        ('VIEW3D_PT_pb_animate_scene', 'Animate Scene'),
    ]
    
    for panel_id, panel_name in expected_panels:
        if hasattr(bpy.types, panel_id):
            panels_found.append(panel_name)
            panel = getattr(bpy.types, panel_id)
            
            # Verify it's configured for Properties
            if hasattr(panel, 'bl_space_type') and panel.bl_space_type == 'PROPERTIES':
                print(f"✓ {panel_name} - configured for Properties editor")
            else:
                print(f"✗ {panel_name} - NOT configured for Properties editor!")
        else:
            panels_missing.append(panel_name)
            print(f"✗ {panel_name} - not registered!")
    
    print(f"\nPanels found: {len(panels_found)}/{len(expected_panels)}")
    if panels_missing:
        print(f"Missing panels: {', '.join(panels_missing)}")
    
    # Test operators
    print("\n4. Testing key operators...")
    operators_to_test = [
        ('pb.create_workspace', 'Create Workspace'),
        ('pb.toggle_outliner_item', 'Toggle Outliner Item'),
        ('pb.sync_outliner_selection', 'Sync Outliner Selection'),
        ('pb.create_edit_group', 'Create/Edit Group'),
        ('pb.split_chain', 'Split Chain'),
        ('pb.create_edit_pose', 'Create/Edit Pose'),
        ('pb.add_keyframe', 'Add Keyframe'),
    ]
    
    for op_id, op_name in operators_to_test:
        if hasattr(bpy.ops.pb, op_id.split('.')[1]):
            print(f"✓ {op_name} operator registered")
        else:
            print(f"✗ {op_name} operator missing!")
    
    print("\n=== Test Complete ===")
    print("\nTo verify the UI:")
    print("1. The ProteinBlender workspace should be active")
    print("2. Look at the Properties editor on the right")
    print("3. Make sure it's showing Scene properties (icon with globe/world)")
    print("4. All 7 panels should be visible there")
    print("\nIf panels are not visible:")
    print("- Check the Properties editor context (should be 'SCENE')")
    print("- Try scrolling in the Properties editor")
    print("- Check for any error messages in the console")

if __name__ == "__main__":
    test_complete_ui()