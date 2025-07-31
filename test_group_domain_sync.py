"""Test script for verifying group updates when splitting/joining domains"""

import bpy
import sys
import os

# Add the addon directory to the path
addon_dir = os.path.dirname(os.path.abspath(__file__))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

from proteinblender.utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy

def test_group_domain_sync():
    """Test that groups are properly updated when domains are split/joined"""
    
    print("\n" + "="*60)
    print("TESTING GROUP-DOMAIN SYNCHRONIZATION")
    print("="*60)
    
    scene = bpy.context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    
    # Step 1: Check initial state
    print("\n1. Initial State:")
    print(f"   - Number of outliner items: {len(scene.outliner_items)}")
    
    # Find a chain that's not split into domains
    test_chain = None
    test_molecule_id = None
    
    for item in scene.outliner_items:
        if item.item_type == 'CHAIN':
            # Check if this chain has no domain children
            has_domains = False
            for child_item in scene.outliner_items:
                if child_item.item_type == 'DOMAIN' and child_item.parent_id == item.item_id:
                    has_domains = True
                    break
            
            if not has_domains:
                test_chain = item
                test_molecule_id = item.parent_id
                print(f"   - Found unsplit chain: {item.name} (ID: {item.item_id})")
                print(f"   - Chain range: {item.chain_start}-{item.chain_end}")
                break
    
    if not test_chain:
        print("   - No unsplit chains found for testing")
        return
    
    # Step 2: Create a group containing the chain
    print("\n2. Creating test group:")
    
    # Select the chain
    for item in scene.outliner_items:
        item.is_selected = False
    test_chain.is_selected = True
    
    # Create group via operator
    bpy.ops.proteinblender.create_group(group_name="Test Domain Sync Group")
    
    # Find the created group
    test_group = None
    for item in scene.outliner_items:
        if item.item_type == 'GROUP' and item.name == "Test Domain Sync Group":
            test_group = item
            print(f"   - Created group: {item.name} (ID: {item.item_id})")
            print(f"   - Members: {item.group_memberships}")
            break
    
    if not test_group:
        print("   - ERROR: Failed to create test group")
        return
    
    # Step 3: Split the chain into domains
    print("\n3. Splitting chain into domains:")
    
    # Calculate split range (split into 3 parts)
    chain_range = test_chain.chain_end - test_chain.chain_start + 1
    split_size = chain_range // 3
    split_start = test_chain.chain_start + split_size
    split_end = test_chain.chain_start + (2 * split_size)
    
    print(f"   - Splitting at residues {split_start}-{split_end}")
    
    # Execute split
    bpy.ops.proteinblender.split_domain(
        chain_id=test_chain.chain_id,
        molecule_id=test_molecule_id,
        split_start=split_start,
        split_end=split_end
    )
    
    # Rebuild outliner to see changes
    build_outliner_hierarchy(bpy.context)
    
    # Check group membership after split
    print("\n4. Checking group after split:")
    for item in scene.outliner_items:
        if item.item_id == test_group.item_id:
            print(f"   - Group members: {item.group_memberships}")
            member_ids = item.group_memberships.split(',') if item.group_memberships else []
            
            # Count member types
            chain_members = 0
            domain_members = 0
            for member_id in member_ids:
                for member_item in scene.outliner_items:
                    if member_item.item_id == member_id:
                        if member_item.item_type == 'CHAIN':
                            chain_members += 1
                            print(f"     - Chain member: {member_item.name}")
                        elif member_item.item_type == 'DOMAIN':
                            domain_members += 1
                            print(f"     - Domain member: {member_item.name}")
            
            print(f"   - Total: {chain_members} chains, {domain_members} domains")
            
            if chain_members > 0:
                print("   - ERROR: Chain should have been replaced by domains!")
            elif domain_members == 0:
                print("   - ERROR: No domains found in group!")
            else:
                print("   - SUCCESS: Chain was replaced by domains")
            break
    
    # Step 5: Test undo
    print("\n5. Testing undo:")
    bpy.ops.ed.undo()
    
    # Rebuild outliner after undo
    build_outliner_hierarchy(bpy.context)
    
    # Check group membership after undo
    for item in scene.outliner_items:
        if item.item_id == test_group.item_id:
            print(f"   - Group members after undo: {item.group_memberships}")
            member_ids = item.group_memberships.split(',') if item.group_memberships else []
            
            has_chain = test_chain.item_id in member_ids
            if has_chain:
                print("   - SUCCESS: Chain restored in group after undo")
            else:
                print("   - ERROR: Chain not restored in group after undo")
            break
    
    # Step 6: Test redo
    print("\n6. Testing redo:")
    bpy.ops.ed.redo()
    
    # Rebuild outliner after redo
    build_outliner_hierarchy(bpy.context)
    
    # Check group membership after redo
    for item in scene.outliner_items:
        if item.item_id == test_group.item_id:
            print(f"   - Group members after redo: {item.group_memberships}")
            member_ids = item.group_memberships.split(',') if item.group_memberships else []
            
            # Should have domains, not chain
            has_domains = False
            for member_id in member_ids:
                for member_item in scene.outliner_items:
                    if member_item.item_id == member_id and member_item.item_type == 'DOMAIN':
                        has_domains = True
                        break
            
            if has_domains:
                print("   - SUCCESS: Domains restored in group after redo")
            else:
                print("   - ERROR: Domains not restored in group after redo")
            break
    
    # Step 7: Test merging domains back
    print("\n7. Testing domain merge:")
    
    # Select all domains from the split chain
    selected_domains = []
    for item in scene.outliner_items:
        item.is_selected = False
        if item.item_type == 'DOMAIN' and item.parent_id == test_chain.item_id:
            item.is_selected = True
            selected_domains.append(item)
            print(f"   - Selected domain: {item.name}")
    
    if len(selected_domains) >= 2:
        # Merge domains
        bpy.ops.proteinblender.merge_domains()
        
        # Rebuild outliner
        build_outliner_hierarchy(bpy.context)
        
        # Check group membership after merge
        print("\n8. Checking group after merge:")
        for item in scene.outliner_items:
            if item.item_id == test_group.item_id:
                print(f"   - Group members: {item.group_memberships}")
                member_ids = item.group_memberships.split(',') if item.group_memberships else []
                
                # Check what's in the group now
                for member_id in member_ids:
                    for member_item in scene.outliner_items:
                        if member_item.item_id == member_id:
                            print(f"     - Member: {member_item.name} (type: {member_item.item_type})")
                
                # If domains cover entire chain, should have chain in group
                has_chain = test_chain.item_id in member_ids
                if has_chain:
                    print("   - Chain added back to group (domains covered entire chain)")
                break
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    test_group_domain_sync()