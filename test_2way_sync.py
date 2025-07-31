"""Test 2-way selection sync between outliner and viewport"""

import bpy
from proteinblender.core.selection_manager import SelectionManager

def print_sync_status():
    """Print sync status between outliner and viewport"""
    scene = bpy.context.scene
    
    print("\n=== Selection Sync Status ===")
    print("Item                          | Outliner | Viewport | Synced?")
    print("-" * 65)
    
    for item in scene.outliner_items:
        if item.item_id == "groups_separator":
            continue
            
        # Skip reference items for this check
        if "_ref_" in item.item_id:
            continue
            
        outliner_selected = item.is_selected
        viewport_selected = False
        
        if item.object_name:
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                viewport_selected = obj.select_get()
        
        synced = outliner_selected == viewport_selected
        status = "✓" if synced else "✗ MISMATCH"
        
        print(f"{item.name:<30} | {str(outliner_selected):<8} | {str(viewport_selected):<8} | {status}")
    
    print("\nReference items:")
    for item in scene.outliner_items:
        if "_ref_" in item.item_id and item.group_memberships:
            # Find original
            original = None
            for orig in scene.outliner_items:
                if orig.item_id == item.group_memberships:
                    original = orig
                    break
            
            if original:
                ref_selected = item.is_selected
                orig_selected = original.is_selected
                synced = ref_selected == orig_selected
                status = "✓" if synced else "✗ MISMATCH"
                print(f"{item.name:<30} | Ref: {ref_selected} | Orig: {orig_selected} | {status}")

def test_outliner_to_viewport():
    """Test selecting in outliner updates viewport"""
    scene = bpy.context.scene
    
    print("\n=== Test: Outliner → Viewport ===")
    
    # Find a chain to test
    chain = None
    for item in scene.outliner_items:
        if item.item_type == 'CHAIN':
            chain = item
            break
    
    if chain:
        print(f"\n1. Selecting '{chain.name}' in outliner...")
        bpy.ops.proteinblender.outliner_select(item_id=chain.item_id)
        print_sync_status()
        
        print(f"\n2. Deselecting '{chain.name}' in outliner...")
        bpy.ops.proteinblender.outliner_select(item_id=chain.item_id)
        print_sync_status()

def test_group_to_viewport():
    """Test group selection syncs to viewport"""
    scene = bpy.context.scene
    
    print("\n=== Test: Group → Viewport ===")
    
    # Find a group
    group = None
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            group = item
            break
    
    if group:
        print(f"\n1. Clicking group '{group.name}'...")
        bpy.ops.proteinblender.outliner_select(item_id=group.item_id)
        print_sync_status()

def test_viewport_to_outliner():
    """Test selecting in viewport updates outliner"""
    scene = bpy.context.scene
    
    print("\n=== Test: Viewport → Outliner ===")
    
    # Find an object to select
    obj_to_select = None
    for item in scene.outliner_items:
        if item.object_name and item.item_type == 'DOMAIN':
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                obj_to_select = obj
                break
    
    if obj_to_select:
        print(f"\n1. Selecting '{obj_to_select.name}' in viewport...")
        # Deselect all first
        bpy.ops.object.select_all(action='DESELECT')
        # Select the object
        obj_to_select.select_set(True)
        # Give depsgraph time to update
        bpy.context.view_layer.update()
        print_sync_status()

# Run tests
print("Starting 2-way sync tests...")
print_sync_status()
test_outliner_to_viewport()
test_group_to_viewport()
test_viewport_to_outliner()
print("\n=== Tests Complete ===")