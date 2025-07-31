"""Test script to verify group updates work when splitting/merging domains"""

import bpy

def print_group_info():
    """Print current group membership information"""
    scene = bpy.context.scene
    
    print("\n" + "="*60)
    print("GROUP MEMBERSHIP INFO")
    print("="*60)
    
    # Find all groups
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.item_id != "groups_separator":
            print(f"\nGroup: {item.name} (ID: {item.item_id})")
            print(f"  Members: {item.group_memberships}")
            
            if item.group_memberships:
                member_ids = item.group_memberships.split(',')
                print(f"  Member count: {len(member_ids)}")
                
                # List each member
                for member_id in member_ids:
                    # Find the member item
                    for member_item in scene.outliner_items:
                        if member_item.item_id == member_id:
                            print(f"    - {member_item.name} ({member_item.item_type})")
                            break
                    else:
                        print(f"    - MISSING: {member_id}")
    
    print("\n" + "="*60)

# Run the check
print_group_info()

# Also print any selected chain info
print("\nSelected items:")
for item in bpy.context.scene.outliner_items:
    if item.is_selected:
        print(f"  - {item.name} (Type: {item.item_type}, ID: {item.item_id})")
        if item.group_memberships:
            print(f"    In groups: {item.group_memberships}")