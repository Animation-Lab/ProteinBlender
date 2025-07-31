"""Debug selection issues"""

import bpy

def debug_outliner_items():
    """Print all outliner items and their properties"""
    scene = bpy.context.scene
    
    print("\n=== OUTLINER ITEMS DEBUG ===")
    print("ID | Name | Type | Object Name | Selected | Parent ID | Group Memberships")
    print("-" * 100)
    
    for item in scene.outliner_items:
        print(f"{item.item_id} | {item.name} | {item.item_type} | {item.object_name or 'NONE'} | {item.is_selected} | {item.parent_id or 'NONE'} | {item.group_memberships or 'NONE'}")
    
    print("\n=== BLENDER OBJECTS ===")
    print("Name | Type | Selected")
    print("-" * 50)
    
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            print(f"{obj.name} | {obj.type} | {obj.select_get()}")

def test_direct_selection():
    """Test selecting objects directly"""
    scene = bpy.context.scene
    
    print("\n=== TESTING DIRECT OBJECT SELECTION ===")
    
    # Find an object with a name
    test_item = None
    for item in scene.outliner_items:
        if item.object_name and item.item_type in ['PROTEIN', 'DOMAIN']:
            test_item = item
            break
    
    if test_item:
        print(f"\nTesting with item: {test_item.name} (object: {test_item.object_name})")
        
        # Try to find the object
        obj = bpy.data.objects.get(test_item.object_name)
        if obj:
            print(f"Found object: {obj.name}")
            print(f"Current selection state: {obj.select_get()}")
            
            # Try to select it
            print("Attempting to select...")
            obj.select_set(True)
            print(f"After select_set(True): {obj.select_get()}")
            
            # Force update
            bpy.context.view_layer.update()
            print(f"After view_layer.update(): {obj.select_get()}")
            
            # Try with view layer parameter
            print("Attempting with view_layer parameter...")
            obj.select_set(True, view_layer=bpy.context.view_layer)
            print(f"After select_set with view_layer: {obj.select_get()}")
        else:
            print(f"ERROR: Could not find object named '{test_item.object_name}'")
            print("Available objects:", [obj.name for obj in bpy.data.objects])

def test_selection_operator():
    """Test the selection operator"""
    scene = bpy.context.scene
    
    print("\n=== TESTING SELECTION OPERATOR ===")
    
    # Find a chain
    chain = None
    for item in scene.outliner_items:
        if item.item_type == 'CHAIN':
            chain = item
            break
    
    if chain:
        print(f"\nClicking on chain: {chain.name}")
        print("Before:", [(i.name, i.is_selected, i.object_name) for i in scene.outliner_items if i.parent_id == chain.item_id])
        
        # Call operator
        bpy.ops.proteinblender.outliner_select(item_id=chain.item_id)
        
        print("After:", [(i.name, i.is_selected, i.object_name) for i in scene.outliner_items if i.parent_id == chain.item_id])
        
        # Check viewport
        print("\nViewport selection:")
        for item in scene.outliner_items:
            if item.parent_id == chain.item_id and item.object_name:
                obj = bpy.data.objects.get(item.object_name)
                if obj:
                    print(f"  {item.name}: outliner={item.is_selected}, viewport={obj.select_get()}")

# Run debug
debug_outliner_items()
test_direct_selection()
test_selection_operator()