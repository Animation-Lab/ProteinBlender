"""
Test script for verifying puppet expansion fix in protein outliner
Run this in Blender with ProteinBlender addon enabled
"""

import bpy

def test_puppet_expansion():
    """Test that puppet domain expansion states persist correctly"""

    scene = bpy.context.scene

    print("\n=== Testing Puppet Expansion Fix ===")
    print(f"Total outliner items: {len(scene.outliner_items)}")

    # Find all puppet items
    puppets = []
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
            puppets.append(item)
            print(f"\nPuppet found: {item.name}")
            print(f"  ID: {item.item_id}")
            print(f"  Expanded: {item.is_expanded}")
            print(f"  Members: {item.puppet_memberships}")

    if not puppets:
        print("\nNo puppets found. Please create a puppet first.")
        return False

    # Check puppet children
    for puppet in puppets:
        print(f"\n--- Checking children of puppet: {puppet.name} ---")
        children = []
        for item in scene.outliner_items:
            if item.parent_id == puppet.item_id:
                children.append(item)
                print(f"  Child: {item.name}")
                print(f"    Type: {item.item_type}")
                print(f"    ID: {item.item_id}")
                print(f"    Expanded: {item.is_expanded}")

                # Check for domain children if this is a chain
                if item.item_type == 'CHAIN':
                    domain_children = []
                    for domain_item in scene.outliner_items:
                        if domain_item.parent_id == item.item_id:
                            domain_children.append(domain_item)
                            print(f"      Domain: {domain_item.name}")

                    if not domain_children and item.has_domains:
                        print(f"      WARNING: Chain marked as having domains but none found!")

        if not children:
            print(f"  WARNING: Puppet has no visible children!")

    # Test toggling puppet expansion
    print("\n=== Testing Expansion Toggle ===")
    if puppets:
        puppet = puppets[0]
        original_state = puppet.is_expanded

        # Count children before toggle
        children_before = sum(1 for item in scene.outliner_items if item.parent_id == puppet.item_id)

        print(f"Puppet '{puppet.name}' before toggle:")
        print(f"  Expanded: {original_state}")
        print(f"  Visible children: {children_before}")

        # Toggle expansion
        bpy.ops.proteinblender.toggle_expand(item_id=puppet.item_id)

        # Count children after toggle
        children_after = sum(1 for item in scene.outliner_items if item.parent_id == puppet.item_id)

        print(f"\nPuppet '{puppet.name}' after toggle:")
        print(f"  Expanded: {puppet.is_expanded}")
        print(f"  Visible children: {children_after}")

        # Toggle back
        bpy.ops.proteinblender.toggle_expand(item_id=puppet.item_id)

        # Count children after second toggle
        children_final = sum(1 for item in scene.outliner_items if item.parent_id == puppet.item_id)

        print(f"\nPuppet '{puppet.name}' after second toggle:")
        print(f"  Expanded: {puppet.is_expanded}")
        print(f"  Visible children: {children_final}")

        # Check for chain domain persistence
        print("\n=== Checking Chain Domain Persistence ===")
        for item in scene.outliner_items:
            if item.parent_id == puppet.item_id and item.item_type == 'CHAIN':
                print(f"\nChain: {item.name}")
                print(f"  Expanded: {item.is_expanded}")
                domain_count = sum(1 for d in scene.outliner_items if d.parent_id == item.item_id)
                print(f"  Domain children count: {domain_count}")

                if item.has_domains and domain_count == 0:
                    print(f"  ERROR: Chain has domains but none are visible!")
                    return False

        return True

    return False

# Run the test
if __name__ == "__main__":
    success = test_puppet_expansion()
    if success:
        print("\n✓ Test completed successfully!")
    else:
        print("\n✗ Test revealed issues")