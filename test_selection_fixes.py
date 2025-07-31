"""Test the fixed selection system"""

import bpy
from proteinblender.core.selection_manager import SelectionManager

def print_selection_state():
    """Print current selection state"""
    scene = bpy.context.scene
    
    print("\n=== Current Selection State ===")
    print("Outliner items:")
    for item in scene.outliner_items:
        if item.item_id == "groups_separator":
            print(f"\n--- {item.name} ---")
            continue
            
        selected = "✓" if item.is_selected else "✗"
        indent = "  " * item.indent_level
        
        # Check viewport selection
        viewport_selected = False
        if item.object_name:
            obj = bpy.data.objects.get(item.object_name)
            if obj:
                viewport_selected = obj.select_get()
        
        vp_mark = "[VP]" if viewport_selected else "    "
        
        print(f"{indent}[{selected}] {vp_mark} {item.name} ({item.item_type})")
        
        if item.item_type == 'GROUP':
            # Show if all members are selected
            all_selected = SelectionManager.is_group_fully_selected(scene, item)
            print(f"{indent}      → Members all selected: {all_selected}")
    
    print("\nViewport selected objects:")
    for obj in bpy.context.selected_objects:
        print(f"  - {obj.name}")

def test_group_selection():
    """Test group selection"""
    scene = bpy.context.scene
    
    print("\n=== Testing Group Selection ===")
    
    # Find a group
    group = None
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            group = item
            break
    
    if not group:
        print("No group found to test")
        return
    
    print(f"\nClicking on group '{group.name}'...")
    bpy.ops.proteinblender.outliner_select(item_id=group.item_id)
    
    print_selection_state()
    
    # Click again to toggle
    print(f"\nClicking on group '{group.name}' again to toggle...")
    bpy.ops.proteinblender.outliner_select(item_id=group.item_id)
    
    print_selection_state()

def test_reference_selection():
    """Test selecting reference items in groups"""
    scene = bpy.context.scene
    
    print("\n=== Testing Reference Selection ===")
    
    # Find a reference item
    ref_item = None
    for item in scene.outliner_items:
        if "_ref_" in item.item_id:
            ref_item = item
            break
    
    if not ref_item:
        print("No reference item found to test")
        return
    
    print(f"\nClicking on reference '{ref_item.name}'...")
    bpy.ops.proteinblender.outliner_select(item_id=ref_item.item_id)
    
    print_selection_state()
    
    # Check if original is also selected
    original_id = ref_item.group_memberships
    for item in scene.outliner_items:
        if item.item_id == original_id:
            print(f"\nOriginal item '{item.name}' selected: {item.is_selected}")
            break

def test_chain_selection():
    """Test chain selection"""
    scene = bpy.context.scene
    
    print("\n=== Testing Chain Selection ===")
    
    # Find a chain
    chain = None
    for item in scene.outliner_items:
        if item.item_type == 'CHAIN':
            chain = item
            break
    
    if not chain:
        print("No chain found to test")
        return
    
    print(f"\nClicking on chain '{chain.name}'...")
    bpy.ops.proteinblender.outliner_select(item_id=chain.item_id)
    
    print_selection_state()

# Run all tests
print_selection_state()
test_group_selection()
test_reference_selection() 
test_chain_selection()

print("\n=== Tests Complete ===")