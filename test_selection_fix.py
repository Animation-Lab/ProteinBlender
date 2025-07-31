"""Test script to verify selection system fixes"""

import bpy
import time

def print_selection_info():
    """Print current selection state"""
    scene = bpy.context.scene
    
    print("\n" + "="*60)
    print("SELECTION STATE")
    print("="*60)
    
    selected_items = []
    for item in scene.outliner_items:
        if item.is_selected:
            selected_items.append(f"{item.name} ({item.item_type}, ID: {item.item_id})")
    
    print(f"\nSelected items ({len(selected_items)}):")
    for item in selected_items:
        print(f"  - {item}")
    
    # Check for group memberships
    print("\nGroup memberships:")
    for item in scene.outliner_items:
        if item.group_memberships:
            print(f"  - {item.name}: {item.group_memberships}")
    
    print("\n" + "="*60)

def test_group_creation():
    """Test that group creation doesn't cause unexpected selections"""
    print("\n\nTEST 1: Group Creation")
    print("-" * 60)
    
    # Get some chains to group
    chains_to_group = []
    for item in bpy.context.scene.outliner_items:
        if item.item_type == 'CHAIN' and len(chains_to_group) < 2:
            chains_to_group.append(item)
            item.is_selected = True
        else:
            item.is_selected = False
    
    if len(chains_to_group) >= 2:
        print(f"Selected chains: {[c.name for c in chains_to_group]}")
        print_selection_info()
        
        # Create a group
        print("\nCreating group...")
        bpy.ops.proteinblender.create_group('INVOKE_DEFAULT', group_name="Test Group 1")
        
        # Wait a bit for any async operations
        time.sleep(0.5)
        
        print("\nAfter group creation:")
        print_selection_info()
        
        # Check if any unexpected items got selected
        unexpected_selections = []
        for item in bpy.context.scene.outliner_items:
            if item.is_selected and item not in chains_to_group:
                if item.item_type != 'GROUP' or item.name != "Test Group 1":
                    unexpected_selections.append(item.name)
        
        if unexpected_selections:
            print(f"\nWARNING: Unexpected selections found: {unexpected_selections}")
        else:
            print("\nSUCCESS: No unexpected selections after group creation")
    else:
        print("Not enough chains found for test")

def test_group_selection():
    """Test that selecting a group doesn't force member selection"""
    print("\n\nTEST 2: Group Selection")
    print("-" * 60)
    
    # Find a group
    test_group = None
    for item in bpy.context.scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            test_group = item
            break
    
    if test_group:
        # Deselect everything first
        for item in bpy.context.scene.outliner_items:
            item.is_selected = False
        
        print(f"Found group: {test_group.name}")
        print("All items deselected")
        
        # Select the group
        print(f"\nSelecting group '{test_group.name}'...")
        bpy.ops.proteinblender.outliner_select(item_id=test_group.item_id)
        
        # Wait a bit
        time.sleep(0.5)
        
        print("\nAfter selecting group:")
        print_selection_info()
        
        # Check if members got auto-selected
        member_ids = test_group.group_memberships.split(',') if test_group.group_memberships else []
        auto_selected_members = []
        
        for member_id in member_ids:
            for item in bpy.context.scene.outliner_items:
                if item.item_id == member_id and item.is_selected:
                    auto_selected_members.append(item.name)
        
        if auto_selected_members:
            print(f"\nWARNING: Group members were auto-selected: {auto_selected_members}")
            print("This should not happen with the new selection logic")
        else:
            print("\nSUCCESS: Group selection did not cascade to members")
    else:
        print("No groups found for test")

def test_hierarchy_rebuild():
    """Test that selection states are preserved during hierarchy rebuild"""
    print("\n\nTEST 3: Hierarchy Rebuild")
    print("-" * 60)
    
    # Select some specific items
    selected_ids = []
    for i, item in enumerate(bpy.context.scene.outliner_items):
        if i % 3 == 0 and item.item_type in ['CHAIN', 'DOMAIN']:
            item.is_selected = True
            selected_ids.append(item.item_id)
        else:
            item.is_selected = False
    
    print(f"Selected {len(selected_ids)} items before rebuild")
    
    # Force a hierarchy rebuild
    from proteinblender.utils.scene_manager import build_outliner_hierarchy
    build_outliner_hierarchy(bpy.context)
    
    # Check if selections were preserved
    preserved = 0
    lost = 0
    
    for item_id in selected_ids:
        found = False
        for item in bpy.context.scene.outliner_items:
            if item.item_id == item_id:
                if item.is_selected:
                    preserved += 1
                else:
                    lost += 1
                found = True
                break
        if not found:
            lost += 1
    
    print(f"\nAfter rebuild:")
    print(f"  - Preserved selections: {preserved}")
    print(f"  - Lost selections: {lost}")
    
    if lost == 0:
        print("\nSUCCESS: All selections preserved during rebuild")
    else:
        print(f"\nWARNING: {lost} selections were lost during rebuild")

# Run tests
if __name__ == "__main__":
    print("\n" + "="*60)
    print("TESTING SELECTION SYSTEM FIXES")
    print("="*60)
    
    test_group_creation()
    test_group_selection()
    test_hierarchy_rebuild()
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60)