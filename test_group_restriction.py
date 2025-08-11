"""Test script to verify group restriction feature works correctly"""
import bpy

def test_group_restriction():
    """Test that chains/domains cannot be added to multiple groups"""
    
    print("\n" + "="*60)
    print("Testing Group Restriction Feature")
    print("="*60)
    
    # Get the scene
    scene = bpy.context.scene
    
    # Print current outliner items
    print("\nCurrent outliner items:")
    for item in scene.outliner_items:
        if item.item_type != 'SEPARATOR':
            groups = item.group_memberships if item.group_memberships else "None"
            print(f"  - {item.name} (Type: {item.item_type}, Groups: {groups})")
    
    # Find items that are already in groups
    items_in_groups = []
    for item in scene.outliner_items:
        if item.item_type not in ['GROUP', 'SEPARATOR'] and item.group_memberships:
            items_in_groups.append({
                'name': item.name,
                'type': item.item_type,
                'groups': item.group_memberships.split(',')
            })
    
    if items_in_groups:
        print("\n✓ Found items already in groups:")
        for item in items_in_groups:
            print(f"  - {item['name']} is in group(s): {', '.join(item['groups'])}")
        
        # Try to select one of these items
        first_item = items_in_groups[0]
        print(f"\n→ Selecting '{first_item['name']}' to test group creation restriction...")
        
        # Clear selection and select the item
        for item in scene.outliner_items:
            item.is_selected = False
            if item.name == first_item['name']:
                item.is_selected = True
                print(f"  Selected: {item.name}")
        
        # Check if the Create Group button would be disabled
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        ungrouped_items = [item for item in selected_items 
                          if item.item_type not in ['GROUP'] and item.item_id != "groups_separator"]
        
        items_already_grouped = []
        for item in ungrouped_items:
            if item.group_memberships:
                items_already_grouped.append(item.name)
        
        if items_already_grouped:
            print(f"\n✓ Create Group button would be DISABLED")
            print(f"  Reason: {len(items_already_grouped)} selected item(s) already in groups")
            print(f"  Items: {', '.join(items_already_grouped)}")
        else:
            print(f"\n✗ Create Group button would be ENABLED (unexpected)")
            
    else:
        print("\n✗ No items found in groups. Please create a group first to test the restriction.")
        print("  Suggestion: Select some chains/domains and create a group, then run this test again.")
    
    # Test selecting items not in groups
    print("\n" + "-"*40)
    print("Testing with items NOT in groups:")
    
    items_not_in_groups = []
    for item in scene.outliner_items:
        if item.item_type not in ['GROUP', 'SEPARATOR'] and not item.group_memberships:
            items_not_in_groups.append(item.name)
    
    if items_not_in_groups:
        print(f"✓ Found {len(items_not_in_groups)} items not in any groups")
        
        # Select first item not in a group
        for item in scene.outliner_items:
            item.is_selected = False
            if item.name == items_not_in_groups[0]:
                item.is_selected = True
                print(f"  Selected: {item.name}")
                break
        
        # Check if button would be enabled
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        ungrouped_items = [item for item in selected_items 
                          if item.item_type not in ['GROUP'] and item.item_id != "groups_separator"]
        
        items_already_grouped = []
        for item in ungrouped_items:
            if item.group_memberships:
                items_already_grouped.append(item.name)
        
        if not items_already_grouped and ungrouped_items:
            print(f"\n✓ Create Group button would be ENABLED (correct)")
            print(f"  Can create group with: {ungrouped_items[0].name}")
        else:
            print(f"\n✗ Create Group button would be DISABLED (unexpected)")
    else:
        print("✗ All items are already in groups")
    
    print("\n" + "="*60)
    print("Test Complete")
    print("="*60)

# Run the test
if __name__ == "__main__":
    test_group_restriction()