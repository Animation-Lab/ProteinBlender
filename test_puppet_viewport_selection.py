"""
Test script to verify puppet Empty selection syncs with Protein Outliner checkbox.

This script tests that selecting the puppet's Empty controller in the 3D viewport
properly checks the puppet checkbox in the Protein Outliner.
"""

import bpy
import time

def test_puppet_viewport_selection():
    """Test that selecting puppet Empty in viewport checks the outliner checkbox"""
    print("\n" + "="*60)
    print("Testing Puppet Viewport Selection Sync")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Find a puppet with a controller
    puppet_item = None
    empty_obj = None
    
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            puppet_item = item
            empty_obj = bpy.data.objects.get(item.controller_object_name)
            if empty_obj:
                break
    
    if not puppet_item or not empty_obj:
        print("ERROR: No puppet with Empty controller found.")
        print("Please create a puppet first using the Puppet Maker panel.")
        return False
    
    print(f"\nFound puppet: {puppet_item.name}")
    print(f"Controller Empty: {empty_obj.name}")
    
    # Test 1: Deselect everything first
    print("\n1. Clearing all selections...")
    bpy.ops.object.select_all(action='DESELECT')
    puppet_item.is_selected = False
    
    # Force update
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()
    
    if puppet_item.is_selected:
        print("ERROR: Puppet checkbox should be unchecked")
    else:
        print("✓ Puppet checkbox is unchecked")
    
    # Test 2: Select Empty in viewport
    print("\n2. Selecting Empty controller in viewport...")
    empty_obj.select_set(True)
    bpy.context.view_layer.objects.active = empty_obj
    
    # Trigger sync
    update_outliner_from_blender_selection()
    
    # Check if puppet checkbox is now checked
    if puppet_item.is_selected:
        print("✓ SUCCESS: Puppet checkbox is checked when Empty selected!")
    else:
        print("✗ FAIL: Puppet checkbox not checked despite Empty selection")
    
    # Test 3: Deselect Empty in viewport
    print("\n3. Deselecting Empty in viewport...")
    empty_obj.select_set(False)
    bpy.ops.object.select_all(action='DESELECT')
    
    # Trigger sync
    update_outliner_from_blender_selection()
    
    # Check if puppet checkbox is now unchecked
    if not puppet_item.is_selected:
        print("✓ SUCCESS: Puppet checkbox unchecked when Empty deselected!")
    else:
        print("✗ FAIL: Puppet checkbox still checked after Empty deselection")
    
    # Test 4: Test with multiple puppets (if available)
    print("\n4. Testing multiple puppets...")
    puppet_count = 0
    test_puppets = []
    
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            obj = bpy.data.objects.get(item.controller_object_name)
            if obj:
                test_puppets.append((item, obj))
                puppet_count += 1
    
    if puppet_count > 1:
        print(f"Found {puppet_count} puppets to test")
        
        # Select all puppet Empties
        for puppet, empty in test_puppets:
            empty.select_set(True)
        
        # Trigger sync
        update_outliner_from_blender_selection()
        
        # Check all are selected
        all_selected = all(puppet.is_selected for puppet, _ in test_puppets)
        if all_selected:
            print("✓ All puppet checkboxes checked when Empties selected")
        else:
            print("✗ Some puppet checkboxes not checked")
        
        # Deselect all
        bpy.ops.object.select_all(action='DESELECT')
        update_outliner_from_blender_selection()
        
        all_deselected = all(not puppet.is_selected for puppet, _ in test_puppets)
        if all_deselected:
            print("✓ All puppet checkboxes unchecked when Empties deselected")
        else:
            print("✗ Some puppet checkboxes still checked")
    else:
        print("Only one puppet found, skipping multi-puppet test")
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)
    print("\nSummary:")
    print("- Selecting puppet Empty in viewport should check puppet checkbox")
    print("- Deselecting Empty should uncheck puppet checkbox")
    print("- Multiple puppet selection should work independently")
    print("\nManual verification:")
    print("1. Click on puppet Empty in 3D viewport")
    print("2. Check that puppet checkbox in Protein Outliner is checked")
    print("3. The Visual Set-up panel should also update")
    
    return True

# Run the test
if __name__ == "__main__":
    test_puppet_viewport_selection()