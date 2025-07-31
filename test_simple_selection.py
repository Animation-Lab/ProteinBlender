"""Simple test to verify viewport selection works"""

import bpy

print("\n=== SIMPLE SELECTION TEST ===")

# Get all mesh objects
meshes = [obj for obj in bpy.data.objects if obj.type == 'MESH']
print(f"Found {len(meshes)} mesh objects")

if meshes:
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    print("Deselected all objects")
    
    # Try to select first mesh
    test_obj = meshes[0]
    print(f"\nTrying to select: {test_obj.name}")
    print(f"Before: {test_obj.select_get()}")
    
    # Method 1: Direct
    test_obj.select_set(True)
    print(f"After select_set(True): {test_obj.select_get()}")
    
    # Method 2: With view layer
    view_layer = bpy.context.view_layer
    test_obj.select_set(True, view_layer=view_layer)
    print(f"After select_set with view_layer: {test_obj.select_get()}")
    
    # Method 3: Set as active
    view_layer.objects.active = test_obj
    print(f"After setting as active: {test_obj.select_get()}")
    
    # Check if it's in the view layer
    print(f"\nIs in view layer: {test_obj.name in view_layer.objects}")
    
    # Try through view layer objects
    if test_obj.name in view_layer.objects:
        vl_obj = view_layer.objects[test_obj.name]
        print(f"View layer object found: {vl_obj}")
        vl_obj.select_set(True)
        print(f"After view layer select: {test_obj.select_get()}")

print("\n=== Testing with outliner ===")
scene = bpy.context.scene

# Find a domain with an object
for item in scene.outliner_items:
    if item.item_type == 'DOMAIN' and item.object_name:
        print(f"\nTesting with domain: {item.name} (object: {item.object_name})")
        
        obj = bpy.data.objects.get(item.object_name)
        if obj:
            # Deselect first
            obj.select_set(False)
            print(f"Deselected: {obj.select_get()}")
            
            # Now select through our method
            from proteinblender.core.selection_manager import SelectionManager
            SelectionManager._sync_to_viewport(scene, item.item_id)
            print(f"After _sync_to_viewport: {obj.select_get()}")
            
            # Also check item selection state
            print(f"Item is_selected: {item.is_selected}")
        break