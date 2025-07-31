"""Debug script to check outliner IDs and group memberships"""

import bpy

scene = bpy.context.scene

print("\n" + "="*60)
print("OUTLINER DEBUG INFO")
print("="*60)

# List all outliner items
print("\nAll outliner items:")
for item in scene.outliner_items:
    print(f"  - {item.name}")
    print(f"    Type: {item.item_type}")
    print(f"    ID: {item.item_id}")
    print(f"    Parent: {item.parent_id}")
    print(f"    Groups: {item.group_memberships}")
    print()

# List all groups and their members
print("\nGroups and their members:")
for item in scene.outliner_items:
    if item.item_type == 'GROUP' and item.item_id != "groups_separator":
        print(f"\nGroup: {item.name} (ID: {item.item_id})")
        print(f"  Members: {item.group_memberships}")
        
        if item.group_memberships:
            member_ids = item.group_memberships.split(',')
            for member_id in member_ids:
                # Find the member
                member_found = False
                for member_item in scene.outliner_items:
                    if member_item.item_id == member_id:
                        print(f"    - {member_item.name} ({member_item.item_type})")
                        member_found = True
                        break
                if not member_found:
                    print(f"    - MISSING: {member_id}")

print("\n" + "="*60)