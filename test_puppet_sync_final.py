"""
Final test for puppet controller 2-way sync after implementing Option 2.
Run this in Blender's Text Editor after reloading the addon.
"""

import bpy

print("\n" + "="*60)
print("Testing Puppet Controller 2-Way Sync - Final")
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
    print(f"Controller object name: {puppet_item.controller_object_name}")
    print(f"Object name property: {puppet_item.object_name}")

    # Verify both properties are set to the same value
    if puppet_item.object_name == puppet_item.controller_object_name:
        print("✓ object_name matches controller_object_name")
    else:
        print("✗ object_name doesn't match controller_object_name")

    # Get the puppet controller Empty object
    empty_obj = bpy.data.objects.get(puppet_item.controller_object_name)
    if not empty_obj:
        print(f"ERROR: Controller object '{puppet_item.controller_object_name}' not found")
    else:
        print(f"\nController object found: {empty_obj.name} (type: {empty_obj.type})")

        # Test 1: Current state
        print("\n--- Test 1: Current Selection State ---")
        print(f"Puppet checkbox: {'✓' if puppet_item.is_selected else '□'}")
        print(f"Controller selected in viewport: {'✓' if empty_obj.select_get() else '□'}")

        # Test 2: Select controller in viewport, check if checkbox updates
        print("\n--- Test 2: Select Controller in Viewport ---")
        bpy.ops.object.select_all(action='DESELECT')
        empty_obj.select_set(True)
        bpy.context.view_layer.objects.active = empty_obj

        # Manually trigger sync to test the logic
        selected_objects = bpy.context.selected_objects
        selected_names = {obj.name for obj in selected_objects}

        print(f"Controller selected: ✓")
        print(f"Controller name '{empty_obj.name}' in selected_names: {empty_obj.name in selected_names}")

        # Check if the sync logic would work
        if puppet_item.object_name and puppet_item.object_name in selected_names:
            print("✓ Sync logic WILL detect this selection (object_name check passes)")
            puppet_item.is_selected = True
        else:
            print("✗ Sync logic WON'T detect this selection")

        print(f"Puppet checkbox after sync: {'✓' if puppet_item.is_selected else '□'}")

        # Test 3: Deselect controller, check sync
        print("\n--- Test 3: Deselect Controller in Viewport ---")
        empty_obj.select_set(False)

        selected_objects = bpy.context.selected_objects
        selected_names = {obj.name for obj in selected_objects}

        print(f"Controller deselected: ✓")

        # The sync logic for puppet needs special handling
        # Check if it would work with the current implementation
        if puppet_item.object_name not in selected_names:
            print("✓ Controller not in selected objects")
            puppet_item.is_selected = False

        print(f"Puppet checkbox after deselect: {'✓' if puppet_item.is_selected else '□'}")

        # Force UI update
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()

        print("\n--- Summary ---")
        if puppet_item.object_name == puppet_item.controller_object_name:
            print("✓ Puppet now uses same selection mechanism as domains")
            print("✓ The 2-way sync should work if msgbus/handlers are properly registered")
            print("\nIf sync still doesn't work automatically:")
            print("1. Disable and re-enable the addon in Preferences")
            print("2. Check if selection_sync handler is registered")
        else:
            print("✗ object_name not properly set - sync won't work")

print("\n" + "="*60)


