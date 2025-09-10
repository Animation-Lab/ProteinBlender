"""
Test script for checkbox-only selection in Protein Outliner.

This script verifies that:
1. Row clicking (UIList selection) no longer affects domain selection
2. Only checkbox clicking triggers selection and visual panel sync
3. 2-way sync between viewport and checkbox selection works
"""

import bpy
import time

def test_checkbox_only_selection():
    """Test that only checkbox selection works, not row selection"""
    print("\n" + "="*60)
    print("Testing Checkbox-Only Selection")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check if there are any outliner items
    if not hasattr(scene, 'outliner_items') or len(scene.outliner_items) == 0:
        print("ERROR: No proteins loaded. Please load a protein first.")
        return False
    
    # Find test items
    domain_item = None
    chain_item = None
    for item in scene.outliner_items:
        if item.item_type == 'DOMAIN' and not domain_item:
            domain_item = item
        elif item.item_type == 'CHAIN' and not chain_item:
            chain_item = item
        if domain_item and chain_item:
            break
    
    if not domain_item:
        print("ERROR: No domain items found in outliner.")
        return False
    
    print(f"\nTest items found:")
    print(f"  Domain: {domain_item.name} (ID: {domain_item.item_id})")
    if chain_item:
        print(f"  Chain: {chain_item.name} (ID: {chain_item.item_id})")
    
    # Test 1: Verify row selection doesn't affect checkbox state
    print("\n1. Testing row selection independence:")
    print("   - Row selection (outliner_index) should NOT affect checkbox state")
    
    # Clear all selections
    for item in scene.outliner_items:
        item.is_selected = False
    
    # Find the index of our test domain
    domain_index = -1
    for idx, item in enumerate(scene.outliner_items):
        if item.item_id == domain_item.item_id:
            domain_index = idx
            break
    
    if domain_index >= 0:
        # Set the UIList row selection
        old_index = scene.outliner_index
        scene.outliner_index = domain_index
        print(f"   - Set outliner_index to {domain_index} (domain row)")
        
        # Check if checkbox is still unchecked
        if not domain_item.is_selected:
            print("   ✓ PASS: Checkbox remains unchecked despite row selection")
        else:
            print("   ✗ FAIL: Checkbox was incorrectly checked by row selection")
        
        # Check visual panel
        initial_color = tuple(scene.visual_setup_color)
        print(f"   - Visual panel color: R={initial_color[0]:.2f}, G={initial_color[1]:.2f}, B={initial_color[2]:.2f}")
    
    # Test 2: Verify checkbox selection works and syncs visual panel
    print("\n2. Testing checkbox selection:")
    
    # Select via checkbox
    domain_item.is_selected = True
    print(f"   - Checked checkbox for {domain_item.name}")
    
    # Trigger the sync (simulating operator call)
    from proteinblender.panels.visual_setup_panel import sync_color_to_selection
    sync_color_to_selection(bpy.context)
    
    # Check visual panel updated
    new_color = tuple(scene.visual_setup_color)
    print(f"   - Visual panel color: R={new_color[0]:.2f}, G={new_color[1]:.2f}, B={new_color[2]:.2f}")
    
    if new_color != initial_color:
        print("   ✓ PASS: Visual panel color updated with checkbox selection")
    else:
        print("   ⚠ WARNING: Visual panel color didn't change (might be same color)")
    
    # Test 3: Test viewport selection syncs to checkbox
    print("\n3. Testing viewport-to-checkbox sync:")
    
    # Clear checkbox selection
    domain_item.is_selected = False
    
    # Select object in viewport
    if domain_item.object_name:
        obj = bpy.data.objects.get(domain_item.object_name)
        if obj:
            # Clear all selections first
            bpy.ops.object.select_all(action='DESELECT')
            
            # Select the domain object
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            print(f"   - Selected {obj.name} in viewport")
            
            # Trigger the sync handler manually (normally done by timer)
            from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
            update_outliner_from_blender_selection()
            
            # Check if checkbox is now checked
            if domain_item.is_selected:
                print("   ✓ PASS: Checkbox was checked when object selected in viewport")
            else:
                print("   ✗ FAIL: Checkbox was not checked despite viewport selection")
            
            # Check visual panel updated
            viewport_color = tuple(scene.visual_setup_color)
            print(f"   - Visual panel color: R={viewport_color[0]:.2f}, G={viewport_color[1]:.2f}, B={viewport_color[2]:.2f}")
    
    # Test 4: Verify row index doesn't interfere with operations
    print("\n4. Testing row index doesn't interfere:")
    
    # Set row index to -1 (no selection)
    scene.outliner_index = -1
    print("   - Set outliner_index to -1 (no row selection)")
    
    # Checkbox should still be checked from previous test
    if domain_item.is_selected:
        print("   ✓ PASS: Checkbox state preserved when row index changed")
    else:
        print("   ✗ FAIL: Checkbox state lost when row index changed")
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)
    print("\nSummary:")
    print("- Row clicking should NOT select/deselect domains")
    print("- Only checkbox clicking should trigger selection")
    print("- Visual panel should update when checkbox is clicked")
    print("- Selecting in viewport should check the checkbox")
    print("\nManual verification:")
    print("1. Try clicking on row labels - nothing should happen")
    print("2. Click checkboxes - selection and visual panel should update")
    print("3. Select objects in 3D view - checkboxes should update")
    
    return True

# Run the test
if __name__ == "__main__":
    test_checkbox_only_selection()