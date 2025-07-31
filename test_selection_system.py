"""Test script for the new selection system"""

import bpy

def test_selection():
    """Test various selection scenarios"""
    print("\n=== TESTING SELECTION SYSTEM ===\n")
    
    scene = bpy.context.scene
    
    # Print current outliner state
    print("Current outliner items:")
    for item in scene.outliner_items:
        selected = "✓" if item.is_selected else "✗"
        print(f"  [{selected}] {item.name} ({item.item_type}) - ID: {item.item_id}")
        if item.item_type == 'GROUP':
            print(f"      Members: {item.group_memberships}")
    
    print("\n--- Test 1: Select a chain ---")
    # Find a chain to test
    chain_item = None
    for item in scene.outliner_items:
        if item.item_type == 'CHAIN':
            chain_item = item
            break
    
    if chain_item:
        print(f"Clicking on {chain_item.name}")
        bpy.ops.proteinblender.outliner_select(item_id=chain_item.item_id)
        
        # Check state after selection
        print("\nState after selection:")
        for item in scene.outliner_items:
            if item.item_id == chain_item.item_id or item.parent_id == chain_item.item_id:
                selected = "✓" if item.is_selected else "✗"
                print(f"  [{selected}] {item.name}")
    
    print("\n--- Test 2: Check group states ---")
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            from proteinblender.core.selection_manager import SelectionManager
            all_selected = SelectionManager.is_group_fully_selected(scene, item)
            state = "All selected" if all_selected else "Not all selected"
            print(f"  Group '{item.name}': {state}")
            
            # List member states
            member_ids = item.group_memberships.split(',') if item.group_memberships else []
            for member_id in member_ids:
                for member in scene.outliner_items:
                    if member.item_id == member_id:
                        selected = "✓" if member.is_selected else "✗"
                        print(f"    [{selected}] {member.name}")
                        break
    
    print("\n--- Test 3: Toggle a group ---")
    group_item = None
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            group_item = item
            break
    
    if group_item:
        print(f"Clicking on group '{group_item.name}'")
        bpy.ops.proteinblender.outliner_select(item_id=group_item.item_id)
        
        # Check member states after toggle
        print("\nMember states after toggle:")
        member_ids = group_item.group_memberships.split(',') if group_item.group_memberships else []
        for member_id in member_ids:
            for member in scene.outliner_items:
                if member.item_id == member_id:
                    selected = "✓" if member.is_selected else "✗"
                    print(f"  [{selected}] {member.name}")
                    break
    
    print("\n=== TEST COMPLETE ===\n")

# Run the test
test_selection()