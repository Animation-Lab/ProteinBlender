"""
Debug script to test puppet controller selection sync.
"""

import bpy

print("\n" + "="*60)
print("Debugging Puppet Controller Selection Sync")
print("="*60)

# Check current selection
selected_objects = bpy.context.selected_objects
print(f"\nCurrently selected objects: {len(selected_objects)}")
for obj in selected_objects:
    print(f"  - {obj.name} (type: {obj.type})")

# Find puppets and their controllers
print("\nPuppets and their controllers:")
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'PUPPET' and item.controller_object_name:
        print(f"\nPuppet: {item.name}")
        print(f"  Controller name: {item.controller_object_name}")
        print(f"  Puppet checkbox: {'✓' if item.is_selected else '□'}")

        # Check if controller exists and its selection state
        controller = bpy.data.objects.get(item.controller_object_name)
        if controller:
            print(f"  Controller exists: Yes")
            print(f"  Controller type: {controller.type}")
            print(f"  Controller selected: {'✓' if controller.select_get() else '□'}")

            # Check if controller is in selected_objects
            if controller in selected_objects:
                print(f"  Controller in selected_objects: Yes")
            else:
                print(f"  Controller in selected_objects: No")
        else:
            print(f"  Controller exists: No")

# Manually trigger the sync function
print("\n--- Manually triggering sync ---")
from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
update_outliner_from_blender_selection()

# Check again after sync
print("\nAfter sync:")
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'PUPPET' and item.controller_object_name:
        print(f"\nPuppet: {item.name}")
        print(f"  Puppet checkbox: {'✓' if item.is_selected else '□'}")

        controller = bpy.data.objects.get(item.controller_object_name)
        if controller:
            print(f"  Controller selected: {'✓' if controller.select_get() else '□'}")

# Force UI update
for area in bpy.context.screen.areas:
    if area.type == 'PROPERTIES':
        area.tag_redraw()

print("\nUI refreshed. Check if the checkbox is now updated.")
print("="*60)