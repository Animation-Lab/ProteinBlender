"""
Test script for complete puppet bidirectional sync.

Tests:
1. Puppet checkbox → Empty controller AND children checkboxes
2. Empty controller → Puppet checkbox AND children checkboxes
"""

import bpy

def test_puppet_complete_sync():
    """Test complete puppet sync with children"""
    print("\n" + "="*60)
    print("TESTING COMPLETE PUPPET SYNC")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Find a puppet with controller and children
    test_puppet = None
    test_empty = None
    puppet_children = []
    
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            empty = bpy.data.objects.get(item.controller_object_name)
            if empty:
                # Find children of this puppet
                children = []
                for child in scene.outliner_items:
                    if child.parent_id == item.item_id and "_ref_" in child.item_id:
                        children.append(child)
                
                if children:  # Only use puppets with children
                    test_puppet = item
                    test_empty = empty
                    puppet_children = children
                    break
    
    if not test_puppet or not test_empty:
        print("ERROR: No puppet with controller and children found.")
        print("Please create a puppet with some domains first.")
        return False
    
    print(f"Testing with:")
    print(f"  Puppet: {test_puppet.name}")
    print(f"  Controller: {test_empty.name}")
    print(f"  Children: {len(puppet_children)} items")
    
    # Test 1: Puppet checkbox → Empty + children
    print("\n1. TEST: Puppet Checkbox → Empty + Children")
    print("-" * 40)
    
    # Clear everything
    print("Clearing all selections...")
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    for child in puppet_children:
        child.is_selected = False
    
    # Simulate clicking puppet checkbox
    print("Clicking puppet checkbox...")
    bpy.ops.proteinblender.outliner_select(item_id=test_puppet.item_id)
    
    # Check results
    results = []
    results.append(f"Puppet checkbox: {test_puppet.is_selected}")
    results.append(f"Empty selected: {test_empty.select_get()}")
    
    children_selected = all(child.is_selected for child in puppet_children)
    results.append(f"All children selected: {children_selected}")
    
    for result in results:
        print(f"  {result}")
    
    if test_puppet.is_selected and test_empty.select_get() and children_selected:
        print("✓ SUCCESS: Puppet checkbox selects Empty and all children!")
    else:
        print("✗ FAIL: Something didn't get selected")
    
    # Test 2: Deselect via checkbox
    print("\n2. TEST: Uncheck Puppet → Deselect Empty + Children")
    print("-" * 40)
    
    # Click checkbox again to deselect
    print("Unchecking puppet checkbox...")
    bpy.ops.proteinblender.outliner_select(item_id=test_puppet.item_id)
    
    # Check results
    results = []
    results.append(f"Puppet checkbox: {test_puppet.is_selected}")
    results.append(f"Empty selected: {test_empty.select_get()}")
    
    children_selected = any(child.is_selected for child in puppet_children)
    results.append(f"Any children selected: {children_selected}")
    
    for result in results:
        print(f"  {result}")
    
    if not test_puppet.is_selected and not test_empty.select_get() and not children_selected:
        print("✓ SUCCESS: Unchecking puppet deselects everything!")
    else:
        print("✗ FAIL: Something is still selected")
    
    # Test 3: Empty → Puppet + children
    print("\n3. TEST: Select Empty → Puppet + Children")
    print("-" * 40)
    
    # Clear everything first
    bpy.ops.object.select_all(action='DESELECT')
    test_puppet.is_selected = False
    for child in puppet_children:
        child.is_selected = False
    
    # Select Empty in viewport
    print(f"Selecting Empty '{test_empty.name}' in viewport...")
    test_empty.select_set(True)
    bpy.context.view_layer.objects.active = test_empty
    
    # Trigger sync
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()
    
    # Check results
    results = []
    results.append(f"Puppet checkbox: {test_puppet.is_selected}")
    results.append(f"Empty selected: {test_empty.select_get()}")
    
    children_selected = all(child.is_selected for child in puppet_children)
    results.append(f"All children selected: {children_selected}")
    
    for result in results:
        print(f"  {result}")
    
    if test_puppet.is_selected and test_empty.select_get() and children_selected:
        print("✓ SUCCESS: Empty selection checks puppet and all children!")
    else:
        print("✗ FAIL: Not everything was selected")
    
    # Test 4: Deselect Empty
    print("\n4. TEST: Deselect Empty → Uncheck Puppet + Children")
    print("-" * 40)
    
    # Deselect Empty
    print("Deselecting Empty in viewport...")
    test_empty.select_set(False)
    bpy.ops.object.select_all(action='DESELECT')
    
    # Trigger sync
    update_outliner_from_blender_selection()
    
    # Check results
    results = []
    results.append(f"Puppet checkbox: {test_puppet.is_selected}")
    results.append(f"Empty selected: {test_empty.select_get()}")
    
    children_selected = any(child.is_selected for child in puppet_children)
    results.append(f"Any children selected: {children_selected}")
    
    for result in results:
        print(f"  {result}")
    
    if not test_puppet.is_selected and not test_empty.select_get() and not children_selected:
        print("✓ SUCCESS: Deselecting Empty unchecks everything!")
    else:
        print("✗ FAIL: Something is still selected")
    
    print("\n" + "="*60)
    print("TEST COMPLETE!")
    print("="*60)
    print("\nSummary of what should work:")
    print("1. Check puppet checkbox → Selects Empty + all children")
    print("2. Uncheck puppet checkbox → Deselects Empty + all children")
    print("3. Select Empty in viewport → Checks puppet + all children")
    print("4. Deselect Empty in viewport → Unchecks puppet + all children")
    
    return True

# Run test
test_puppet_complete_sync()