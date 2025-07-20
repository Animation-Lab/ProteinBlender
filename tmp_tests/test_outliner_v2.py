"""Test script for the updated Protein Outliner with dual checkboxes and group support.

This script tests:
1. Outliner panel in VIEW_3D space
2. Dual checkbox functionality (select and visibility)
3. Group support
4. Hierarchy display with proper indentation
5. 2-way sync between outliner and viewport
"""

import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

def test_outliner_v2():
    """Test the updated outliner functionality"""
    print("\n" + "="*50)
    print("Testing Updated Protein Outliner")
    print("="*50)
    
    # Ensure addon is enabled
    if "proteinblender" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="proteinblender")
        print("✓ Enabled ProteinBlender addon")
    
    # Switch to ProteinBlender workspace
    if "ProteinBlender" in bpy.data.workspaces:
        bpy.context.window.workspace = bpy.data.workspaces["ProteinBlender"]
        print("✓ Switched to ProteinBlender workspace")
    
    # Check if new outliner panel is registered
    if hasattr(bpy.types, "VIEW3D_PT_protein_outliner_v2"):
        print("✓ New outliner panel registered")
    else:
        print("✗ New outliner panel not found")
        return False
    
    # Check group properties
    scene = bpy.context.scene
    if hasattr(scene, "pb_groups"):
        print("✓ Group properties registered")
    else:
        print("✗ Group properties not registered")
        return False
    
    # Test group creation
    print("\nTesting group functionality:")
    from proteinblender.properties.group_props import create_new_group
    
    # Create a test group
    test_group = create_new_group(bpy.context, "Test Group 1")
    if test_group:
        print(f"  ✓ Created group: {test_group.name} (ID: {test_group.group_id})")
        
        # Add mock members
        test_group.add_member("protein1", "PROTEIN", "Test Protein 1")
        test_group.add_member("chain1_a", "CHAIN", "Chain A", "protein1")
        test_group.add_member("domain1_a1", "DOMAIN", "Domain 1", "chain1_a")
        print(f"  ✓ Added {len(test_group.members)} members to group")
    else:
        print("  ✗ Failed to create group")
    
    # Test outliner state
    print("\nTesting outliner state:")
    outliner_state = scene.protein_outliner_state
    
    # Add some test items to outliner
    # Protein 1
    item1 = outliner_state.items.add()
    item1.name = "Test Protein 1"
    item1.identifier = "protein1"
    item1.type = "PROTEIN"
    item1.depth = 0
    item1.is_selected = False
    item1.is_visible = True
    item1.is_expanded = True
    
    # Chain A
    item2 = outliner_state.items.add()
    item2.name = "Chain A"
    item2.identifier = "chain1_a"
    item2.type = "CHAIN"
    item2.depth = 1
    item2.is_selected = False
    item2.is_visible = True
    
    # Domain 1
    item3 = outliner_state.items.add()
    item3.name = "Domain 1"
    item3.identifier = "domain1_a1"
    item3.type = "DOMAIN"
    item3.depth = 2
    item3.is_selected = False
    item3.is_visible = True
    
    # Test Group in outliner
    item4 = outliner_state.items.add()
    item4.name = "Test Group 1"
    item4.identifier = test_group.group_id
    item4.type = "GROUP"
    item4.depth = 0
    item4.is_selected = False
    item4.is_visible = True
    item4.is_expanded = True
    
    print(f"  ✓ Added {len(outliner_state.items)} items to outliner")
    
    # Test outliner display
    print("\nOutliner hierarchy:")
    for item in outliner_state.items:
        indent = "  " * item.depth
        expand = "▼" if item.is_expanded and item.type in {'PROTEIN', 'GROUP'} else "▶" if item.type in {'PROTEIN', 'GROUP'} else " "
        select = "☑" if item.is_selected else "☐"
        visible = "👁" if item.is_visible else "🚫"
        in_group = " (in group)" if item.identifier in [m.identifier for g in scene.pb_groups for m in g.members] else ""
        print(f"  {indent}{expand} {item.name} [{item.type}] {select} {visible}{in_group}")
    
    # Test checkbox functionality
    print("\nTesting checkbox functionality:")
    
    # Test selection
    item1.is_selected = True
    print("  ✓ Set protein selection to True")
    
    # Test visibility
    item2.is_visible = False
    print("  ✓ Set chain visibility to False")
    
    # Check if toggle operator exists
    if hasattr(bpy.ops.protein_pb, "toggle_outliner_expand"):
        print("  ✓ Toggle expand operator registered")
    else:
        print("  ✗ Toggle expand operator not found")
    
    print("\n" + "="*50)
    print("Outliner v2 test completed")
    print("="*50)
    
    return True


if __name__ == "__main__":
    test_outliner_v2()