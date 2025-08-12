"""Test script for the new group-based pose system"""

import bpy
from mathutils import Vector


def test_pose_system():
    """Test the pose system functionality"""
    
    print("\n" + "="*60)
    print("Testing Pose System")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Import required modules
    try:
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        from proteinblender.utils.pose_manager import PoseManager
        
        scene_manager = ProteinBlenderScene.get_instance()
        print("✓ Imported pose system modules successfully")
    except Exception as e:
        print(f"✗ Failed to import modules: {e}")
        return
    
    # Check for active molecule
    molecule = scene_manager.molecules.get(scene.selected_molecule_id)
    if not molecule:
        print("\n✗ No molecule selected. Please import a protein first.")
        return
    
    print(f"\n✓ Found molecule: {molecule.identifier}")
    
    # Find molecule item
    molecule_item = None
    for item in scene.molecule_list_items:
        if item.identifier == molecule.identifier:
            molecule_item = item
            break
    
    if not molecule_item:
        print("✗ Could not find molecule in UI list")
        return
    
    # Test 1: Check default pose creation
    print("\n--- Test 1: Default Pose ---")
    if len(molecule_item.poses) > 0:
        default_pose = molecule_item.poses[0]
        print(f"✓ Default pose exists: '{default_pose.name}'")
        print(f"  Is default: {default_pose.is_default}")
        print(f"  Created at: {default_pose.created_at[:19] if default_pose.created_at else 'Not set'}")
    else:
        print("✗ No default pose found")
    
    # Test 2: Check groups
    print("\n--- Test 2: Groups ---")
    groups = PoseManager.get_groups_for_molecule(bpy.context, molecule.identifier)
    if groups:
        print(f"✓ Found {len(groups)} groups for molecule:")
        for group_id, members in groups.items():
            # Find group name
            group_name = group_id
            for item in scene.outliner_items:
                if item.item_id == group_id and item.item_type == 'GROUP':
                    group_name = item.name
                    break
            print(f"  - {group_name}: {len(members)} members")
    else:
        print("✗ No groups found. Create groups to test poses.")
        print("  Suggestion: Select chains/domains and use 'Create New Group'")
        return
    
    # Test 3: Alpha carbon center calculation
    print("\n--- Test 3: Alpha Carbon Center ---")
    alpha_center = PoseManager.calculate_alpha_carbon_center(molecule.object)
    print(f"✓ Alpha carbon center: ({alpha_center.x:.2f}, {alpha_center.y:.2f}, {alpha_center.z:.2f})")
    
    # Test 4: Create a test pose
    print("\n--- Test 4: Create Test Pose ---")
    try:
        # Create new pose
        test_pose = molecule_item.poses.add()
        test_pose.name = "Test Pose"
        test_pose.is_default = False
        
        from datetime import datetime
        test_pose.created_at = datetime.now().isoformat()
        test_pose.modified_at = test_pose.created_at
        
        # Set groups
        group_ids = list(groups.keys())
        test_pose.group_ids = ','.join(group_ids)
        
        # Capture transforms
        PoseManager.capture_group_transforms(bpy.context, test_pose, group_ids, alpha_center)
        
        print(f"✓ Created test pose: '{test_pose.name}'")
        print(f"  Groups: {len(group_ids)}")
        print(f"  Transforms captured: {len(test_pose.group_transforms)}")
        
        # Set as active
        molecule_item.active_pose_index = len(molecule_item.poses) - 1
        
    except Exception as e:
        print(f"✗ Failed to create test pose: {e}")
        return
    
    # Test 5: Modify group positions
    print("\n--- Test 5: Modify and Restore Positions ---")
    
    # Get group objects and save original positions
    original_positions = {}
    group_objects = []
    for group_id in group_ids[:1]:  # Test with first group only
        objs = PoseManager.get_group_objects(bpy.context, group_id)
        for obj in objs:
            original_positions[obj.name] = obj.location.copy()
            group_objects.append(obj)
            print(f"  Original position of {obj.name}: {obj.location}")
    
    if group_objects:
        # Move objects
        for obj in group_objects:
            obj.location.x += 5.0
            print(f"  Moved {obj.name} to: {obj.location}")
        
        # Apply the test pose to restore positions
        try:
            PoseManager.apply_group_transforms(bpy.context, test_pose, molecule.object)
            print("✓ Applied pose to restore positions")
            
            # Check if positions were restored
            for obj in group_objects:
                current_pos = obj.location
                original_pos = original_positions[obj.name]
                diff = (current_pos - original_pos).length
                if diff < 0.1:  # Allow small tolerance
                    print(f"  ✓ {obj.name} restored to original position")
                else:
                    print(f"  ✗ {obj.name} not restored (diff: {diff:.3f})")
        except Exception as e:
            print(f"✗ Failed to apply pose: {e}")
    else:
        print("  No group objects found to test")
    
    # Test 6: Screenshot generation
    print("\n--- Test 6: Screenshot Generation ---")
    try:
        screenshot_path = PoseManager.create_pose_screenshot(
            bpy.context, 
            test_pose, 
            group_ids
        )
        test_pose.screenshot_path = screenshot_path
        
        import os
        if os.path.exists(screenshot_path):
            print(f"✓ Screenshot created: {screenshot_path}")
            print(f"  File size: {os.path.getsize(screenshot_path)} bytes")
        else:
            print("✗ Screenshot file not found")
    except Exception as e:
        print(f"✗ Failed to create screenshot: {e}")
    
    # Test 7: Pose operators
    print("\n--- Test 7: Pose Operators ---")
    
    # Test capture operator
    try:
        bpy.ops.molecule.capture_pose(pose_index=molecule_item.active_pose_index)
        print("✓ Capture pose operator works")
    except Exception as e:
        print(f"✗ Capture pose operator failed: {e}")
    
    # Test apply operator
    try:
        bpy.ops.molecule.apply_pose(pose_index=0)  # Apply default pose
        print("✓ Apply pose operator works")
    except Exception as e:
        print(f"✗ Apply pose operator failed: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("Pose System Test Complete")
    print(f"Total poses: {len(molecule_item.poses)}")
    print(f"Active pose: {molecule_item.poses[molecule_item.active_pose_index].name if molecule_item.poses else 'None'}")
    print("="*60)


# Run the test
if __name__ == "__main__":
    test_pose_system()