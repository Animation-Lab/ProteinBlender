"""
Debug script to diagnose puppet selection sync issues.

Run this script and check the console output to see what's happening.
"""

import bpy

def diagnose_puppet_sync():
    """Diagnose puppet selection sync issues"""
    print("\n" + "="*60)
    print("PUPPET SYNC DIAGNOSTIC")
    print("="*60)
    
    scene = bpy.context.scene
    
    # List all puppets and their controllers
    print("\n1. PUPPET INVENTORY:")
    print("-" * 40)
    puppet_count = 0
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET':
            puppet_count += 1
            controller_exists = False
            controller_obj = None
            if item.controller_object_name:
                controller_obj = bpy.data.objects.get(item.controller_object_name)
                controller_exists = controller_obj is not None
            
            print(f"Puppet: {item.name}")
            print(f"  - Item ID: {item.item_id}")
            print(f"  - Controller name: {item.controller_object_name or 'NOT SET'}")
            print(f"  - Controller exists: {controller_exists}")
            print(f"  - Checkbox selected: {item.is_selected}")
            if controller_obj:
                print(f"  - Controller selected in viewport: {controller_obj.select_get()}")
            print()
    
    if puppet_count == 0:
        print("NO PUPPETS FOUND - Create a puppet first!")
        return
    
    # Test sync from checkbox to Empty
    print("\n2. TEST: Checkbox -> Empty Selection")
    print("-" * 40)
    
    # Find first puppet with controller
    test_puppet = None
    test_empty = None
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            test_empty = bpy.data.objects.get(item.controller_object_name)
            if test_empty:
                test_puppet = item
                break
    
    if not test_puppet:
        print("ERROR: No puppet with valid controller found")
        return
    
    print(f"Testing with: {test_puppet.name}")
    
    # Clear selection
    print("Clearing all selections...")
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    
    # Select puppet checkbox
    print("Setting puppet checkbox to True...")
    test_puppet.is_selected = True
    
    # Call sync function directly
    print("Calling sync_outliner_to_blender_selection...")
    from proteinblender.handlers.selection_sync import sync_outliner_to_blender_selection
    sync_outliner_to_blender_selection(bpy.context, test_puppet.item_id)
    
    # Check result
    print(f"Result: Empty selected = {test_empty.select_get()}")
    if test_empty.select_get():
        print("✓ SUCCESS: Checkbox selection synced to Empty")
    else:
        print("✗ FAIL: Empty not selected despite checkbox")
    
    # Test sync from Empty to checkbox
    print("\n3. TEST: Empty -> Checkbox Selection")
    print("-" * 40)
    
    # Clear selection
    print("Clearing all selections...")
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    
    # Select Empty in viewport
    print(f"Selecting Empty '{test_empty.name}' in viewport...")
    test_empty.select_set(True)
    bpy.context.view_layer.objects.active = test_empty
    
    # Call sync function directly
    print("Calling update_outliner_from_blender_selection...")
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()
    
    # Check result
    print(f"Result: Checkbox selected = {test_puppet.is_selected}")
    if test_puppet.is_selected:
        print("✓ SUCCESS: Empty selection synced to checkbox")
    else:
        print("✗ FAIL: Checkbox not checked despite Empty selection")
    
    # Check timer registration
    print("\n4. TIMER STATUS:")
    print("-" * 40)
    from proteinblender.handlers import selection_sync
    if hasattr(selection_sync, '_timer_handle') and selection_sync._timer_handle:
        print("Timer is registered")
    else:
        print("WARNING: Timer not registered!")
    
    print("\n" + "="*60)
    print("DIAGNOSTIC COMPLETE - Check console for DEBUG output")
    print("="*60)

# Run diagnostic
diagnose_puppet_sync()