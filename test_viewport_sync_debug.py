"""Debug viewport sync with detailed output"""

import bpy
from proteinblender.core.selection_manager import SelectionManager

# Add temporary debug to sync function
original_sync = SelectionManager._sync_to_viewport

def debug_sync(scene, item_id):
    print(f"\n[SYNC DEBUG] Called _sync_to_viewport for item_id: {item_id}")
    item = SelectionManager._find_item(scene, item_id)
    if item:
        print(f"  Item: {item.name}, object_name: {item.object_name}, is_selected: {item.is_selected}")
        if item.object_name:
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                print(f"  Object found: {obj.name}")
                print(f"  Before sync: select_get() = {obj.select_get()}")
    
    # Call original
    original_sync(scene, item_id)
    
    # Check after
    if item and item.object_name:
        obj = bpy.data.objects.get(item.object_name)
        if obj:
            print(f"  After sync: select_get() = {obj.select_get()}")

# Monkey patch for debugging
SelectionManager._sync_to_viewport = staticmethod(debug_sync)

# Now test
scene = bpy.context.scene

print("=== TESTING CHAIN SELECTION ===")
# Find a chain
for item in scene.outliner_items:
    if item.item_type == 'CHAIN':
        print(f"\nClicking on: {item.name}")
        bpy.ops.proteinblender.outliner_select(item_id=item.item_id)
        break

print("\n=== TESTING GROUP SELECTION ===")
# Find a group
for item in scene.outliner_items:
    if item.item_type == 'GROUP' and item.item_id != "groups_separator":
        print(f"\nClicking on group: {item.name}")
        bpy.ops.proteinblender.outliner_select(item_id=item.item_id)
        break

# Restore original
SelectionManager._sync_to_viewport = original_sync
print("\n[DEBUG COMPLETE]")