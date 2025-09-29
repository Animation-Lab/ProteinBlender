"""
Test if domain selection sync is actually working automatically.
This will help us understand what's different between domains and puppets.
"""

import bpy

print("\n" + "="*60)
print("Testing Domain Selection Sync Mechanism")
print("="*60)

# Find a domain in the outliner
domain_item = None
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'DOMAIN' and item.object_name:
        domain_item = item
        break

if not domain_item:
    print("No domain found. Looking for a chain instead...")
    for item in bpy.context.scene.outliner_items:
        if item.item_type == 'CHAIN' and item.object_name:
            domain_item = item
            break

if not domain_item:
    print("ERROR: No domain or chain with object found.")
else:
    print(f"\nFound item: {domain_item.name} (type: {domain_item.item_type})")
    print(f"Object name: {domain_item.object_name}")

    # Get the actual object
    obj = bpy.data.objects.get(domain_item.object_name)
    if obj:
        print(f"Object found: {obj.name} (type: {obj.type})")

        # Test current state
        print(f"\nCurrent state:")
        print(f"  Item checkbox: {'✓' if domain_item.is_selected else '□'}")
        print(f"  Object selected: {'✓' if obj.select_get() else '□'}")

        # Select the object
        print(f"\n--- Selecting {obj.name} in viewport ---")
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)

        print(f"Object now selected: {'✓' if obj.select_get() else '□'}")
        print(f"Item checkbox (before manual sync): {'✓' if domain_item.is_selected else '□'}")

        # Wait a moment and check again
        print("\nWaiting for automatic sync...")
        import time
        # Can't actually sleep in Blender, but we can check the state

        print(f"Item checkbox (current): {'✓' if domain_item.is_selected else '□'}")

        if not domain_item.is_selected:
            print("\n✗ Domain checkbox did NOT update automatically either!")
            print("This means the selection sync handler isn't working for ANY items.")

            # Try manually triggering the sync
            print("\n--- Manually triggering sync ---")
            try:
                from proteinblender.handlers import selection_sync
                selection_sync.update_outliner_from_blender_selection()
                print("✓ Manual sync triggered successfully")
                print(f"Item checkbox after manual sync: {'✓' if domain_item.is_selected else '□'}")
            except:
                print("✗ Could not import selection_sync")
        else:
            print("\n✓ Domain checkbox updated automatically!")
            print("This means domains have a working trigger that puppets don't.")

# Check handler registration
print("\n" + "="*60)
print("Checking Handler Registration")
print("="*60)

# Check if depsgraph handler is registered
if hasattr(bpy.app.handlers, 'depsgraph_update_post'):
    print(f"Depsgraph handlers registered: {len(bpy.app.handlers.depsgraph_update_post)}")
    for handler in bpy.app.handlers.depsgraph_update_post:
        print(f"  - {handler.__name__ if hasattr(handler, '__name__') else handler}")

# Check if the selection_sync module is loaded
try:
    import sys
    if 'proteinblender.handlers.selection_sync' in sys.modules:
        print("\n✓ selection_sync module is loaded in sys.modules")

        from proteinblender.handlers import selection_sync

        # Check if msgbus owner exists
        if hasattr(selection_sync, '_msgbus_owner'):
            print(f"✓ _msgbus_owner exists: {selection_sync._msgbus_owner is not None}")

        # Check subscribed objects
        if hasattr(selection_sync, '_subscribed_objects'):
            print(f"✓ _subscribed_objects: {len(selection_sync._subscribed_objects)} objects")
    else:
        print("\n✗ selection_sync module NOT in sys.modules")
except Exception as e:
    print(f"\n✗ Error checking selection_sync: {e}")

print("\n" + "="*60)