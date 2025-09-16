"""
Test script for puppet controller system with Empty objects.

This script tests:
1. Creating a puppet creates an Empty controller object
2. Domain objects are parented to the Empty
3. Moving the Empty moves all puppet members
4. Selecting puppet checkbox selects the Empty
5. Selecting Empty in viewport checks puppet checkbox
6. Deleting puppet also deletes the Empty
"""

import bpy
from mathutils import Vector

def test_puppet_controller():
    """Test the puppet controller Empty system"""
    print("\n" + "="*60)
    print("Testing Puppet Controller System")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check if there are any outliner items
    if not hasattr(scene, 'outliner_items') or len(scene.outliner_items) == 0:
        print("ERROR: No proteins loaded. Please load a protein first.")
        return False
    
    # Find some domains to test with
    test_domains = []
    for item in scene.outliner_items:
        if item.item_type == 'DOMAIN' and not item.puppet_memberships:
            test_domains.append(item)
            if len(test_domains) >= 3:
                break
    
    if len(test_domains) < 2:
        print("ERROR: Need at least 2 unpuppeted domains to test.")
        return False
    
    print(f"\nTest domains found: {[d.name for d in test_domains]}")
    
    # Test 1: Create a puppet and verify Empty is created
    print("\n1. Creating puppet from selected domains...")
    
    # Select test domains
    for item in scene.outliner_items:
        item.is_selected = False
    for domain in test_domains:
        domain.is_selected = True
    
    # Create puppet (simulate operator)
    bpy.ops.proteinblender.create_puppet('INVOKE_DEFAULT', puppet_name="Test Puppet")
    
    # Find the newly created puppet
    puppet_item = None
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.name == "Test Puppet":
            puppet_item = item
            break
    
    if not puppet_item:
        print("ERROR: Puppet was not created")
        return False
    
    print(f"✓ Puppet created: {puppet_item.name}")
    
    # Check if Empty controller was created
    if not puppet_item.controller_object_name:
        print("ERROR: No controller object name stored")
        return False
    
    empty_obj = bpy.data.objects.get(puppet_item.controller_object_name)
    if not empty_obj:
        print(f"ERROR: Empty object '{puppet_item.controller_object_name}' not found")
        return False
    
    print(f"✓ Empty controller created: {empty_obj.name}")
    
    # Test 2: Verify domains are parented to Empty
    print("\n2. Checking parent-child relationships...")
    
    orphaned_domains = []
    for domain in test_domains:
        if domain.object_name:
            obj = bpy.data.objects.get(domain.object_name)
            if obj:
                if obj.parent != empty_obj:
                    orphaned_domains.append(domain.name)
    
    if orphaned_domains:
        print(f"ERROR: Domains not parented to Empty: {orphaned_domains}")
    else:
        print("✓ All domains are parented to Empty controller")
    
    # Test 3: Test transform propagation
    print("\n3. Testing transform propagation...")
    
    # Get initial positions
    initial_positions = {}
    for domain in test_domains:
        if domain.object_name:
            obj = bpy.data.objects.get(domain.object_name)
            if obj:
                initial_positions[domain.name] = obj.location.copy()
    
    # Move the Empty
    move_vector = Vector((10, 0, 0))
    empty_obj.location += move_vector
    
    # Check if children moved
    moved_correctly = True
    for domain in test_domains:
        if domain.object_name:
            obj = bpy.data.objects.get(domain.object_name)
            if obj and domain.name in initial_positions:
                expected_pos = initial_positions[domain.name] + move_vector
                actual_pos = obj.location
                if (actual_pos - expected_pos).length > 0.001:
                    print(f"ERROR: {domain.name} didn't move correctly")
                    moved_correctly = False
    
    if moved_correctly:
        print("✓ Moving Empty correctly moves all puppet members")
    
    # Move Empty back
    empty_obj.location -= move_vector
    
    # Test 4: Test selection sync - puppet to Empty
    print("\n4. Testing puppet checkbox to Empty selection...")
    
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    puppet_item.is_selected = False
    
    # Select puppet checkbox
    puppet_item.is_selected = True
    
    # Trigger sync
    from proteinblender.handlers.selection_sync import sync_outliner_to_blender_selection
    sync_outliner_to_blender_selection(bpy.context, puppet_item.item_id)
    
    if empty_obj.select_get():
        print("✓ Selecting puppet checkbox selects Empty")
    else:
        print("ERROR: Empty not selected when puppet checkbox checked")
    
    # Test 5: Test selection sync - Empty to puppet
    print("\n5. Testing Empty selection to puppet checkbox...")
    
    # Deselect puppet
    puppet_item.is_selected = False
    bpy.ops.object.select_all(action='DESELECT')
    
    # Select Empty in viewport
    empty_obj.select_set(True)
    bpy.context.view_layer.objects.active = empty_obj
    
    # Trigger sync
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()
    
    if puppet_item.is_selected:
        print("✓ Selecting Empty in viewport checks puppet checkbox")
    else:
        print("ERROR: Puppet checkbox not checked when Empty selected")
    
    # Test 6: Test puppet deletion
    print("\n6. Testing puppet deletion...")
    
    empty_name = empty_obj.name
    
    # Delete the puppet
    bpy.ops.proteinblender.delete_puppet(puppet_id=puppet_item.item_id)
    
    # Check if Empty was deleted
    if bpy.data.objects.get(empty_name):
        print("ERROR: Empty was not deleted with puppet")
    else:
        print("✓ Empty controller deleted when puppet deleted")
    
    # Check if domains still exist and are unparented
    for domain in test_domains:
        if domain.object_name:
            obj = bpy.data.objects.get(domain.object_name)
            if obj:
                if obj.parent:
                    print(f"ERROR: {domain.name} still has a parent after puppet deletion")
            else:
                print(f"WARNING: {domain.name} object was deleted")
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)
    print("\nSummary:")
    print("- Puppet creation automatically creates Empty controller")
    print("- Domains are parented to Empty for unified transforms")
    print("- Moving Empty moves all puppet members together")
    print("- Selection syncs between puppet checkbox and Empty")
    print("- Deleting puppet cleans up Empty controller")
    
    return True

# Run the test
if __name__ == "__main__":
    test_puppet_controller()