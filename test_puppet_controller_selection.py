"""
Test if we can actually select the puppet controller and if it stays selected.
"""

import bpy

print("\n" + "="*60)
print("Testing Puppet Controller Selection")
print("="*60)

# Find the puppet and its controller
puppet_item = None
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'PUPPET' and item.object_name:
        puppet_item = item
        break

if not puppet_item:
    print("ERROR: No puppet found")
else:
    print(f"Puppet: {puppet_item.name}")
    print(f"Controller name: {puppet_item.controller_object_name}")

    # Get the controller object
    controller = bpy.data.objects.get(puppet_item.controller_object_name)

    if not controller:
        print(f"ERROR: Controller object '{puppet_item.controller_object_name}' not found in scene")
    else:
        print(f"\nController object found: {controller.name}")
        print(f"  Type: {controller.type}")
        print(f"  Hide select: {controller.hide_select}")
        print(f"  Visible: {controller.visible_get()}")

        # Try to select it
        print(f"\n--- Attempting to select controller ---")
        print(f"Before: Controller selected = {controller.select_get()}")
        print(f"Before: Puppet checkbox = {puppet_item.is_selected}")

        # Clear selection and select only the controller
        bpy.ops.object.select_all(action='DESELECT')
        controller.select_set(True)
        bpy.context.view_layer.objects.active = controller

        print(f"After select_set(True): Controller selected = {controller.select_get()}")

        # Check what's actually selected
        selected_objects = list(bpy.context.selected_objects)
        print(f"\nSelected objects count: {len(selected_objects)}")
        for obj in selected_objects:
            print(f"  - {obj.name} (type: {obj.type})")

        # Now manually call the sync
        print(f"\n--- Manually triggering sync ---")
        try:
            from bl_ext.vscode_development.proteinblender.handlers import selection_sync
            selection_sync.update_outliner_from_blender_selection()
            print("✓ Sync called successfully")
        except Exception as e:
            print(f"✗ Could not call sync: {e}")

        print(f"\nAfter sync: Puppet checkbox = {puppet_item.is_selected}")

        # Check if something is interfering with selection
        print(f"\n--- Checking for interference ---")

        # Check if the controller has constraints or drivers
        if hasattr(controller, 'constraints'):
            print(f"Constraints: {len(controller.constraints)}")

        # Check parent-child relationships
        if controller.parent:
            print(f"Controller has parent: {controller.parent.name}")

        children = list(controller.children)
        if children:
            print(f"Controller has {len(children)} children")
            for child in children[:3]:  # Show first 3
                print(f"  - {child.name}")

print("\n" + "="*60)