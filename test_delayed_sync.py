"""
Test if the sync happens with a delay (on next depsgraph update or UI redraw).
"""

import bpy

print("\n" + "="*60)
print("Testing Delayed Sync Mechanism")
print("="*60)

# Find test items
chain_item = None
puppet_item = None

for item in bpy.context.scene.outliner_items:
    if not chain_item and item.item_type == 'CHAIN' and item.object_name:
        chain_item = item
    if not puppet_item and item.item_type == 'PUPPET' and item.object_name:
        puppet_item = item
    if chain_item and puppet_item:
        break

print("Test items:")
if chain_item:
    print(f"  Chain: {chain_item.name} -> {chain_item.object_name}")
if puppet_item:
    print(f"  Puppet: {puppet_item.name} -> {puppet_item.object_name}")

# Test chain
if chain_item:
    chain_obj = bpy.data.objects.get(chain_item.object_name)
    if chain_obj:
        print(f"\n--- Testing Chain ---")
        # Deselect
        bpy.ops.object.select_all(action='DESELECT')
        chain_item.is_selected = False

        print(f"Initial: object={chain_obj.select_get()}, checkbox={chain_item.is_selected}")

        # Select
        chain_obj.select_set(True)
        print(f"After select: object={chain_obj.select_get()}, checkbox={chain_item.is_selected}")

        # Force a depsgraph update
        bpy.context.view_layer.update()
        print(f"After depsgraph update: object={chain_obj.select_get()}, checkbox={chain_item.is_selected}")

        # Force UI redraw
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        print(f"After UI redraw: object={chain_obj.select_get()}, checkbox={chain_item.is_selected}")

# Test puppet
if puppet_item:
    puppet_obj = bpy.data.objects.get(puppet_item.object_name)
    if puppet_obj:
        print(f"\n--- Testing Puppet ---")
        # Deselect
        bpy.ops.object.select_all(action='DESELECT')
        puppet_item.is_selected = False

        print(f"Initial: object={puppet_obj.select_get()}, checkbox={puppet_item.is_selected}")

        # Select
        puppet_obj.select_set(True)
        print(f"After select: object={puppet_obj.select_get()}, checkbox={puppet_item.is_selected}")

        # Force a depsgraph update
        bpy.context.view_layer.update()
        print(f"After depsgraph update: object={puppet_obj.select_get()}, checkbox={puppet_item.is_selected}")

        # Force UI redraw
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        print(f"After UI redraw: object={puppet_obj.select_get()}, checkbox={puppet_item.is_selected}")

# Check if the on_depsgraph_update_post handler is actually being called
print("\n--- Checking if handler is called ---")

# Try to access the handler directly
try:
    from bl_ext.vscode_development.proteinblender.handlers import selection_sync

    # Check the internal state
    if hasattr(selection_sync, '_selection_update_depth'):
        print(f"_selection_update_depth: {selection_sync._selection_update_depth}")

    if hasattr(selection_sync, '_msgbus_owner'):
        print(f"_msgbus_owner exists: {selection_sync._msgbus_owner is not None}")

    if hasattr(selection_sync, '_subscribed_objects'):
        print(f"_subscribed_objects count: {len(selection_sync._subscribed_objects)}")

        # Check if our objects are subscribed
        if chain_obj and chain_obj.name in selection_sync._subscribed_objects:
            print(f"  ✓ Chain object IS subscribed")
        else:
            print(f"  ✗ Chain object NOT subscribed")

        if puppet_obj and puppet_obj.name in selection_sync._subscribed_objects:
            print(f"  ✓ Puppet object IS subscribed")
        else:
            print(f"  ✗ Puppet object NOT subscribed")

except Exception as e:
    print(f"Error checking handler: {e}")

print("\n" + "="*60)