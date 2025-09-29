"""
Debug script to test if msgbus subscriptions are working.
Run this in Blender's Text Editor AFTER the addon is loaded.
"""

import bpy

print("\n" + "="*60)
print("Testing msgbus subscription for selection changes")
print("="*60)

# Test if we can manually subscribe to selection changes
test_owner = object()
selection_changed = False

def on_test_selection_changed(*args):
    global selection_changed
    selection_changed = True
    print("✓ Selection change detected via msgbus!")

# Subscribe to selection changes
try:
    # Try subscribing to the generic Object selection property
    key = (bpy.types.Object, "select")
    bpy.msgbus.subscribe_rna(
        key=key,
        owner=test_owner,
        args=(),
        notify=on_test_selection_changed,
    )
    print("✓ Successfully subscribed to Object.select")
except Exception as e:
    print(f"✗ Failed to subscribe to Object.select: {e}")

# Also try subscribing to a specific object if one exists
if len(bpy.data.objects) > 0:
    test_obj = None
    # Find the puppet controller if it exists
    for item in bpy.context.scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            test_obj = bpy.data.objects.get(item.controller_object_name)
            if test_obj:
                print(f"\nFound puppet controller: {test_obj.name}")
                break

    if not test_obj:
        # Just use the first object
        test_obj = bpy.data.objects[0]
        print(f"\nUsing test object: {test_obj.name}")

    try:
        # Try subscribing to this specific object's selection
        key = test_obj.path_resolve("select", False)
        bpy.msgbus.subscribe_rna(
            key=key,
            owner=test_owner,
            args=(),
            notify=on_test_selection_changed,
        )
        print(f"✓ Successfully subscribed to {test_obj.name}.select")
    except Exception as e:
        print(f"✗ Failed to subscribe to specific object: {e}")

print("\n--- Instructions ---")
print("1. Select/deselect any object in the 3D viewport")
print("2. Check if 'Selection change detected' message appears above")
print("3. If it doesn't appear, msgbus is not working properly")

# Check if selection_sync module is loaded
try:
    from proteinblender.handlers import selection_sync
    print(f"\n✓ selection_sync module is loaded")

    # Check if the msgbus owner exists
    if hasattr(selection_sync, '_msgbus_owner') and selection_sync._msgbus_owner:
        print(f"✓ selection_sync has msgbus owner")
    else:
        print(f"✗ selection_sync msgbus owner not found or None")

    # Check subscribed objects
    if hasattr(selection_sync, '_subscribed_objects'):
        count = len(selection_sync._subscribed_objects)
        print(f"✓ selection_sync has {count} subscribed objects")
    else:
        print(f"✗ selection_sync subscribed objects not found")

except ImportError:
    print("\n✗ Could not import selection_sync - addon may not be properly loaded")

print("="*60)