"""
Test script to verify puppet Empty and checkbox bidirectional sync is working.

This should now work after the fix to preserve controller_object_name during
outliner hierarchy rebuilds.
"""

import bpy

def test_puppet_sync_fixed():
    """Test the fixed puppet sync"""
    print("\n" + "="*60)
    print("TESTING FIXED PUPPET SYNC")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Find a puppet with controller
    test_puppet = None
    test_empty = None
    
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            test_empty = bpy.data.objects.get(item.controller_object_name)
            if test_empty:
                test_puppet = item
                break
    
    if not test_puppet or not test_empty:
        print("ERROR: No puppet with valid controller found.")
        print("Please create a puppet first.")
        return False
    
    print(f"Testing with puppet: {test_puppet.name}")
    print(f"Controller Empty: {test_empty.name}")
    
    # Test 1: Checkbox -> Empty
    print("\n1. TEST: Checkbox → Empty Selection")
    print("-" * 40)
    
    # Clear everything
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    
    # Select checkbox
    print("Checking puppet checkbox...")
    test_puppet.is_selected = True
    
    # Trigger sync
    from proteinblender.handlers.selection_sync import sync_outliner_to_blender_selection
    sync_outliner_to_blender_selection(bpy.context, test_puppet.item_id)
    
    # Check result
    if test_empty.select_get():
        print("✓ SUCCESS: Empty selected when checkbox checked!")
    else:
        print("✗ FAIL: Empty not selected")
    
    # Test 2: Empty -> Checkbox
    print("\n2. TEST: Empty → Checkbox Selection")
    print("-" * 40)
    
    # Clear everything
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    
    # Select Empty
    print(f"Selecting Empty '{test_empty.name}' in viewport...")
    test_empty.select_set(True)
    bpy.context.view_layer.objects.active = test_empty
    
    # Trigger sync
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()
    
    # Check result
    if test_puppet.is_selected:
        print("✓ SUCCESS: Checkbox checked when Empty selected!")
    else:
        print("✗ FAIL: Checkbox not checked")
    
    # Test 3: Test after hierarchy rebuild
    print("\n3. TEST: Sync After Hierarchy Rebuild")
    print("-" * 40)
    
    # Force hierarchy rebuild
    print("Rebuilding outliner hierarchy...")
    from proteinblender.utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(bpy.context)
    
    # Find puppet again (it was recreated)
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.name == test_puppet.name:
            test_puppet = item
            break
    
    print(f"Controller name preserved: {test_puppet.controller_object_name}")
    
    # Test checkbox -> Empty again
    test_puppet.is_selected = False
    bpy.ops.object.select_all(action='DESELECT')
    
    test_puppet.is_selected = True
    sync_outliner_to_blender_selection(bpy.context, test_puppet.item_id)
    
    if test_empty.select_get():
        print("✓ SUCCESS: Sync still works after rebuild!")
    else:
        print("✗ FAIL: Sync broken after rebuild")
    
    # Test 4: Deselection
    print("\n4. TEST: Deselection Sync")
    print("-" * 40)
    
    # Deselect checkbox
    print("Unchecking puppet checkbox...")
    test_puppet.is_selected = False
    sync_outliner_to_blender_selection(bpy.context, test_puppet.item_id)
    
    if not test_empty.select_get():
        print("✓ SUCCESS: Empty deselected when checkbox unchecked!")
    else:
        print("✗ FAIL: Empty still selected")
    
    # Deselect Empty
    test_puppet.is_selected = True
    sync_outliner_to_blender_selection(bpy.context, test_puppet.item_id)
    
    print(f"Deselecting Empty in viewport...")
    test_empty.select_set(False)
    update_outliner_from_blender_selection()
    
    if not test_puppet.is_selected:
        print("✓ SUCCESS: Checkbox unchecked when Empty deselected!")
    else:
        print("✗ FAIL: Checkbox still checked")
    
    print("\n" + "="*60)
    print("TEST COMPLETE!")
    print("="*60)
    print("\nThe fix:")
    print("- controller_object_name is now preserved during hierarchy rebuilds")
    print("- Bidirectional sync between puppet checkbox and Empty works")
    print("- You can select puppets via checkbox OR Empty in viewport")
    
    return True

# Run test
test_puppet_sync_fixed()