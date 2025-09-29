"""
Test script for puppet checkbox and controller 2-way sync.

This test verifies that:
1. Puppet checkbox only controls the puppet controller (Empty object)
2. Selecting/deselecting puppet members doesn't affect the puppet checkbox
3. Selecting the puppet controller in 3D view checks the puppet checkbox
4. Deselecting the puppet controller unchecks the puppet checkbox
"""

import bpy

print("\n" + "="*60)
print("Testing Puppet Checkbox and Controller 2-Way Sync")
print("="*60)

# Find a puppet in the outliner
puppet_item = None
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'PUPPET' and item.controller_object_name:
        puppet_item = item
        break

if not puppet_item:
    print("ERROR: No puppet found. Please create a puppet first.")
else:
    print(f"\nFound puppet: {puppet_item.name}")
    print(f"Controller: {puppet_item.controller_object_name}")

    # Get the puppet controller Empty object
    empty_obj = bpy.data.objects.get(puppet_item.controller_object_name)
    if not empty_obj:
        print(f"ERROR: Controller object '{puppet_item.controller_object_name}' not found")
    else:
        print("\n--- Initial State ---")
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")

        # Test 1: Deselect puppet checkbox, verify controller deselects
        print("\n--- Test 1: Deselect puppet checkbox ---")
        puppet_item.is_selected = False
        # Trigger sync
        from proteinblender.handlers.selection_sync import sync_outliner_to_blender_selection
        sync_outliner_to_blender_selection(bpy.context, puppet_item.item_id)
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")
        assert not empty_obj.select_get(), "Controller should be deselected"
        print("✓ PASS: Controller deselected when checkbox unchecked")

        # Test 2: Select puppet checkbox, verify controller selects
        print("\n--- Test 2: Select puppet checkbox ---")
        puppet_item.is_selected = True
        sync_outliner_to_blender_selection(bpy.context, puppet_item.item_id)
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")
        assert empty_obj.select_get(), "Controller should be selected"
        print("✓ PASS: Controller selected when checkbox checked")

        # Test 3: Select controller in 3D view, verify checkbox
        print("\n--- Test 3: Select controller in 3D view ---")
        # First deselect everything
        bpy.ops.object.select_all(action='DESELECT')
        puppet_item.is_selected = False
        print("Deselected all objects")

        # Select the controller
        empty_obj.select_set(True)
        # Trigger sync from Blender to outliner
        from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
        update_outliner_from_blender_selection()
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")
        assert puppet_item.is_selected, "Puppet checkbox should be checked"
        print("✓ PASS: Checkbox checked when controller selected in viewport")

        # Test 4: Deselect controller in 3D view, verify checkbox
        print("\n--- Test 4: Deselect controller in 3D view ---")
        empty_obj.select_set(False)
        update_outliner_from_blender_selection()
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")
        assert not puppet_item.is_selected, "Puppet checkbox should be unchecked"
        print("✓ PASS: Checkbox unchecked when controller deselected in viewport")

        # Test 5: Select puppet members, verify checkbox not affected
        print("\n--- Test 5: Select puppet members without affecting checkbox ---")
        # Get puppet members
        member_ids = puppet_item.puppet_memberships.split(',') if puppet_item.puppet_memberships else []
        if member_ids:
            # Start with puppet deselected
            puppet_item.is_selected = False
            empty_obj.select_set(False)

            # Select a member
            for item in bpy.context.scene.outliner_items:
                if item.item_id in member_ids and item.item_type != 'PUPPET':
                    print(f"Selecting member: {item.name}")
                    item.is_selected = True
                    sync_outliner_to_blender_selection(bpy.context, item.item_id)
                    break

            # Check puppet state
            print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
            print(f"Controller selected: {'✓' if empty_obj.select_get() else '□'}")
            assert not puppet_item.is_selected, "Puppet checkbox should remain unchecked"
            assert not empty_obj.select_get(), "Controller should remain deselected"
            print("✓ PASS: Puppet checkbox not affected by member selection")
        else:
            print("No members to test")

        print("\n" + "="*60)
        print("All tests passed! ✓")
        print("Puppet checkbox now only controls the puppet controller.")
        print("="*60)