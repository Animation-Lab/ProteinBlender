"""
Debug script to test puppet controller selection sync.
Run this directly in Blender's Text Editor.
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

# Build set of selected names for quick lookup
selected_names = {obj.name for obj in selected_objects}
print(f"\nSelected object names: {selected_names}")

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

            # Check if controller name is in selected_names
            if item.controller_object_name in selected_names:
                print(f"  Controller name in selected_names: Yes")
            else:
                print(f"  Controller name in selected_names: No")
        else:
            print(f"  Controller exists: No")

print("\n--- Testing sync logic ---")
# Replicate the sync logic inline
scene = bpy.context.scene

# First check if any puppet Empty controllers are selected
for item in scene.outliner_items:
    if item.item_type == 'PUPPET':
        if item.controller_object_name:
            print(f"\nChecking puppet: {item.name}")
            print(f"  Looking for controller: {item.controller_object_name}")

            # Check if the Empty controller is selected
            if item.controller_object_name in selected_names:
                print(f"  ✓ Controller name found in selected_names")
                print(f"  Setting puppet checkbox to SELECTED")
                item.is_selected = True
            else:
                # Check if the Empty object actually exists
                empty_obj = bpy.data.objects.get(item.controller_object_name)
                if empty_obj:
                    is_selected = empty_obj.select_get()
                    print(f"  Controller object found, select_get() = {is_selected}")
                    if not is_selected:
                        print(f"  Setting puppet checkbox to DESELECTED")
                        item.is_selected = False
                    else:
                        print(f"  Controller IS selected, setting puppet checkbox to SELECTED")
                        item.is_selected = True
                else:
                    print(f"  Controller object not found")
                    print(f"  Setting puppet checkbox to DESELECTED")
                    item.is_selected = False

# Check final state
print("\n--- Final State ---")
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