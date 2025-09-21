#!/usr/bin/env python
"""
Test script to verify that puppet hierarchy no longer includes protein subsections.
This test checks that when chains are added to puppets, they appear directly
under the puppet without their parent protein as an intermediate level.
"""

import bpy

def check_puppet_hierarchy():
    """Check if puppets have proper hierarchy without protein subsections"""
    scene = bpy.context.scene

    print("\n" + "="*60)
    print("PUPPET HIERARCHY TEST")
    print("="*60)

    puppet_count = 0
    issues_found = []

    for item in scene.outliner_items:
        # Look for puppet items (excluding separator)
        if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
            puppet_count += 1
            print(f"\nPuppet: {item.name} (ID: {item.item_id})")

            # Get puppet members
            member_ids = item.puppet_memberships.split(',') if item.puppet_memberships else []
            print(f"  Members: {member_ids}")

            # Check if any members are proteins
            for member_id in member_ids:
                # Find the member in outliner items
                for check_item in scene.outliner_items:
                    if check_item.item_id == member_id:
                        if check_item.item_type == 'PROTEIN':
                            issues_found.append(f"  ❌ ISSUE: Protein '{check_item.name}' found as puppet member!")
                            print(f"  ❌ ISSUE: Protein '{check_item.name}' (ID: {member_id}) is a puppet member!")
                        else:
                            print(f"  ✓ {check_item.item_type}: {check_item.name}")
                        break

            # Check puppet's reference children in the hierarchy
            print(f"\n  Hierarchy children:")
            for ref_item in scene.outliner_items:
                if ref_item.parent_id == item.item_id and "_ref_" in ref_item.item_id:
                    # Check what type this reference is
                    original_id = ref_item.puppet_memberships  # Original item ID stored here

                    # Find the original item to check its type
                    for orig_item in scene.outliner_items:
                        if orig_item.item_id == original_id:
                            if orig_item.item_type == 'PROTEIN':
                                issues_found.append(f"    ❌ ISSUE: Protein reference '{ref_item.name}' in hierarchy!")
                                print(f"    ❌ Protein reference: {ref_item.name}")
                            else:
                                print(f"    ✓ {orig_item.item_type} reference: {ref_item.name}")
                            break

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    if puppet_count == 0:
        print("No puppets found in the scene.")
    elif issues_found:
        print(f"❌ Found {len(issues_found)} issue(s):")
        for issue in issues_found:
            print(issue)
        print("\nProteins should not appear as puppet members or in puppet hierarchy!")
    else:
        print(f"✅ All {puppet_count} puppet(s) have correct hierarchy!")
        print("No proteins found as puppet members or subsections.")

    return len(issues_found) == 0

if __name__ == "__main__":
    # Run the test
    success = check_puppet_hierarchy()

    if not success:
        print("\n⚠️  To fix existing puppets, try rebuilding the outliner hierarchy:")
        print("   from proteinblender.utils.scene_manager import build_outliner_hierarchy")
        print("   build_outliner_hierarchy()")