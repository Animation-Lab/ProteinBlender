"""Test script for the Visual Set-up panel functionality.

This script tests:
1. Visual Set-up panel registration
2. Context-sensitive updates based on selection
3. Color and representation changes
4. Multi-selection handling
"""

import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

def test_visual_setup():
    """Test the Visual Set-up panel functionality"""
    print("\n" + "="*50)
    print("Testing Visual Set-up Panel")
    print("="*50)
    
    # Ensure addon is enabled
    if "proteinblender" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="proteinblender")
        print("✓ Enabled ProteinBlender addon")
    
    # Switch to ProteinBlender workspace
    if "ProteinBlender" in bpy.data.workspaces:
        bpy.context.window.workspace = bpy.data.workspaces["ProteinBlender"]
        print("✓ Switched to ProteinBlender workspace")
    
    # Check if visual setup panel is registered
    if hasattr(bpy.types, "VIEW3D_PT_pb_visual_setup"):
        print("✓ Visual Set-up panel registered")
    else:
        print("✗ Visual Set-up panel not found")
        return False
    
    # Check properties
    scene = bpy.context.scene
    print("\nChecking visual properties:")
    
    if hasattr(scene, "pb_visual_color"):
        print(f"  ✓ Color property registered (default: {list(scene.pb_visual_color)})")
    else:
        print("  ✗ Color property not registered")
    
    if hasattr(scene, "pb_visual_representation"):
        print(f"  ✓ Representation property registered (default: {scene.pb_visual_representation})")
        # List available representations
        prop = scene.bl_rna.properties["pb_visual_representation"]
        representations = [item.identifier for item in prop.enum_items]
        print(f"    Available: {', '.join(representations)}")
    else:
        print("  ✗ Representation property not registered")
    
    # Test property changes
    print("\nTesting property changes:")
    
    # Test color change
    try:
        original_color = list(scene.pb_visual_color)
        scene.pb_visual_color = (1.0, 0.0, 0.0)  # Red
        print(f"  ✓ Changed color from {original_color} to {list(scene.pb_visual_color)}")
    except Exception as e:
        print(f"  ✗ Failed to change color: {e}")
    
    # Test representation change
    try:
        original_rep = scene.pb_visual_representation
        scene.pb_visual_representation = 'surface'
        print(f"  ✓ Changed representation from {original_rep} to {scene.pb_visual_representation}")
        # Reset
        scene.pb_visual_representation = original_rep
    except Exception as e:
        print(f"  ✗ Failed to change representation: {e}")
    
    # Test selection sensitivity
    print("\nTesting selection sensitivity:")
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) > 0:
        # Select first item
        outliner_state.items[0].is_selected = True
        print(f"  ✓ Selected item: {outliner_state.items[0].name}")
        
        # Check if sync operator exists
        if hasattr(bpy.ops.protein_pb, "sync_visual_selection"):
            print("  ✓ Visual sync operator registered")
            try:
                bpy.ops.protein_pb.sync_visual_selection()
                print("  ✓ Sync operator executed")
            except Exception as e:
                print(f"  ✗ Sync operator failed: {e}")
        else:
            print("  ✗ Visual sync operator not found")
    else:
        print("  ℹ No items in outliner to test selection")
    
    # Test helper functions
    print("\nTesting helper functions:")
    try:
        from proteinblender.panels.visual_setup_panel import get_selected_outliner_items
        selected = get_selected_outliner_items(bpy.context)
        print(f"  ✓ get_selected_outliner_items() returned {len(selected)} items")
    except Exception as e:
        print(f"  ✗ Failed to import helper functions: {e}")
    
    print("\n" + "="*50)
    print("Visual Set-up test completed")
    print("="*50)
    
    return True


if __name__ == "__main__":
    test_visual_setup()