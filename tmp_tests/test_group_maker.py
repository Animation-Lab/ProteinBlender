"""Test script for the Group Maker panel functionality.

This script tests:
1. Group Maker panel registration
2. Create/Edit group dialog
3. Group membership management
4. Outliner integration with groups
5. Grayed out behavior for grouped items
"""

import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

def test_group_maker():
    """Test the Group Maker panel functionality"""
    print("\n" + "="*50)
    print("Testing Group Maker Panel")
    print("="*50)
    
    # Ensure addon is enabled
    if "proteinblender" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="proteinblender")
        print("✓ Enabled ProteinBlender addon")
    
    # Switch to ProteinBlender workspace
    if "ProteinBlender" in bpy.data.workspaces:
        bpy.context.window.workspace = bpy.data.workspaces["ProteinBlender"]
        print("✓ Switched to ProteinBlender workspace")
    
    # Check if group maker panel is registered
    if hasattr(bpy.types, "VIEW3D_PT_pb_group_maker"):
        print("✓ Group Maker panel registered")
    else:
        print("✗ Group Maker panel not found")
        return False
    
    # Check operators
    print("\nChecking operators:")
    operators = [
        ("pb.create_edit_group", "Create/Edit group operator"),
        ("pb.toggle_group_member", "Toggle group member operator"),
        ("pb.delete_group", "Delete group operator")
    ]
    
    for op_id, op_name in operators:
        if hasattr(bpy.ops.pb, op_id.split('.')[1]):
            print(f"  ✓ {op_name} registered")
        else:
            print(f"  ✗ {op_name} not found")
    
    # Check group properties
    scene = bpy.context.scene
    if hasattr(scene, "pb_groups"):
        print("✓ Group properties registered")
    else:
        print("✗ Group properties not registered")
        return False
    
    # Test group creation
    print("\nTesting group creation:")
    from proteinblender.properties.group_props import create_new_group
    
    # Clear existing groups
    scene.pb_groups.clear()
    
    # Create test group
    test_group = create_new_group(bpy.context, "Test Group 1")
    if test_group:
        print(f"  ✓ Created group: {test_group.name} (ID: {test_group.group_id})")
    else:
        print("  ✗ Failed to create group")
        return False
    
    # Test member management
    print("\nTesting member management:")
    
    # Add test members
    test_group.add_member("protein1", "PROTEIN", "Test Protein 1")
    test_group.add_member("chain1_a", "CHAIN", "Chain A", "protein1")
    test_group.add_member("domain1_a1", "DOMAIN", "Domain 1", "chain1_a")
    
    print(f"  ✓ Added {len(test_group.members)} members")
    
    # Test member checking
    if test_group.has_member("chain1_a"):
        print("  ✓ has_member() works correctly")
    else:
        print("  ✗ has_member() failed")
    
    # Test member removal
    if test_group.remove_member("domain1_a1"):
        print("  ✓ remove_member() works correctly")
    else:
        print("  ✗ remove_member() failed")
    
    # Test outliner integration
    print("\nTesting outliner integration:")
    from proteinblender.properties.group_props import update_outliner_for_groups
    
    # Update outliner
    update_outliner_for_groups(bpy.context)
    
    # Check if group appears in outliner
    outliner_state = scene.protein_outliner_state
    group_in_outliner = False
    for item in outliner_state.items:
        if item.type == 'GROUP' and item.identifier == test_group.group_id:
            group_in_outliner = True
            print(f"  ✓ Group '{item.name}' appears in outliner")
            break
    
    if not group_in_outliner:
        print("  ✗ Group not found in outliner")
    
    # Test group expansion
    test_group.is_expanded = True
    update_outliner_for_groups(bpy.context)
    
    # Count group children in outliner
    group_children = 0
    found_group = False
    for item in outliner_state.items:
        if found_group and item.depth > 0:
            group_children += 1
        elif item.type == 'GROUP' and item.identifier == test_group.group_id:
            found_group = True
        elif found_group and item.depth == 0:
            break
    
    print(f"  ✓ Group shows {group_children} children when expanded")
    
    # Test create/edit dialog (can't fully test dialog interaction)
    print("\nTesting create/edit dialog operator:")
    try:
        # Test create mode
        result = bpy.ops.pb.create_edit_group(mode='CREATE')
        if result == {'CANCELLED'}:
            print("  ✓ Create dialog can be invoked (cancelled)")
        else:
            print("  ✓ Create dialog executed")
    except Exception as e:
        print(f"  ✗ Create dialog failed: {e}")
    
    # Test grayed out behavior
    print("\nTesting grayed out behavior:")
    from proteinblender.panels.outliner_panel_v2 import is_item_in_group
    
    # Add test item to outliner
    test_item = outliner_state.items.add()
    test_item.name = "Test Item"
    test_item.identifier = "chain1_a"
    test_item.type = "CHAIN"
    
    # Check if item is detected as in group
    if is_item_in_group(test_item, bpy.context):
        print("  ✓ Item correctly detected as in group")
    else:
        print("  ✗ Item not detected as in group")
    
    # Clean up
    outliner_state.items.remove(len(outliner_state.items) - 1)
    
    # Test group deletion
    print("\nTesting group deletion:")
    groups_before = len(scene.pb_groups)
    
    try:
        bpy.ops.pb.delete_group(group_index=0)
        if len(scene.pb_groups) < groups_before:
            print("  ✓ Group deleted successfully")
        else:
            print("  ✗ Group deletion failed")
    except Exception as e:
        print(f"  ✗ Delete group failed: {e}")
    
    print("\n" + "="*50)
    print("Group Maker test completed")
    print("="*50)
    
    return True


if __name__ == "__main__":
    test_group_maker()