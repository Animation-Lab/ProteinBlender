#!/usr/bin/env python3
"""
Test script to verify that poses work correctly with undo/redo operations.
This test ensures poses are consistent with the keyframe undo/redo behavior.
"""

import bpy
import sys
import os

# Add the proteinblender module to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(addon_path)

def test_pose_undo_redo():
    """Test that poses are properly preserved during undo/redo operations"""
    print("Testing Pose Undo/Redo Consistency")
    print("=" * 50)
    
    # Clear existing scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    try:
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        print("✓ ProteinBlender modules imported successfully")
        
        # Create test protein and domain objects
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
        protein_obj = bpy.context.active_object
        protein_obj.name = "TestProtein"
        
        # Create a domain object (child of protein)
        bpy.ops.mesh.primitive_sphere_add(location=(2, 0, 0))
        domain_obj = bpy.context.active_object
        domain_obj.name = "TestDomain"
        domain_obj.parent = protein_obj
        
        # Set up molecule and scene
        test_item = scene.molecule_list_items.add()
        test_item.identifier = "test_protein"
        test_item.object_ptr = protein_obj
        scene.selected_molecule_id = "test_protein"
        
        print("✓ Test setup complete")
        
        # Test Step 1: Create first pose with default domain position
        print("\n--- Creating Pose 1 (Default Position) ---")
        bpy.ops.molecule.create_pose(pose_name="Default State")
        
        print(f"After Pose 1 - UI poses: {len(test_item.poses)}")
        if len(test_item.poses) > 0:
            pose1 = test_item.poses[0]
            print(f"  Pose 1: '{pose1.name}' with {len(pose1.domain_transforms)} domain transforms")
        
        # Test Step 2: Move domain and create second pose
        print("\n--- Creating Pose 2 (Moved Position) ---")
        domain_obj.location = (5, 3, 2)
        domain_obj.rotation_euler = (0.5, 0.3, 0.1)
        bpy.ops.molecule.create_pose(pose_name="Moved State")
        
        print(f"After Pose 2 - UI poses: {len(test_item.poses)}")
        if len(test_item.poses) > 1:
            pose2 = test_item.poses[1]
            print(f"  Pose 2: '{pose2.name}' with {len(pose2.domain_transforms)} domain transforms")
        
        # Store the poses data before undo to compare later
        original_poses = []
        for pose in test_item.poses:
            pose_data = {
                'name': pose.name,
                'has_protein_transform': pose.has_protein_transform,
                'domain_count': len(pose.domain_transforms)
            }
            if len(pose.domain_transforms) > 0:
                pose_data['first_domain_location'] = list(pose.domain_transforms[0].location)
                pose_data['first_domain_rotation'] = list(pose.domain_transforms[0].rotation)
            original_poses.append(pose_data)
        
        print("✓ Original poses captured:")
        for i, pose_data in enumerate(original_poses):
            print(f"   {i+1}. {pose_data['name']} ({pose_data['domain_count']} domains)")
            if 'first_domain_location' in pose_data:
                print(f"      Location: {pose_data['first_domain_location']}")
        
        # Test Step 3: UNDO pose 2 creation
        print("\n--- UNDO Pose 2 ---")
        bpy.ops.ed.undo()
        
        print(f"After UNDO - UI poses: {len(test_item.poses)}")
        print("UI poses after UNDO:")
        for i, pose in enumerate(test_item.poses):
            print(f"   {i+1}. {pose.name} ({len(pose.domain_transforms)} domains)")
        
        # Test Step 4: REDO pose 2 creation (THE CRITICAL TEST)
        print("\n--- REDO Pose 2 (Critical Test) ---")
        bpy.ops.ed.redo()
        
        print(f"After REDO - UI poses: {len(test_item.poses)}")
        
        # Verify that all poses are restored correctly
        restored_poses = []
        for pose in test_item.poses:
            pose_data = {
                'name': pose.name,
                'has_protein_transform': pose.has_protein_transform,
                'domain_count': len(pose.domain_transforms)
            }
            if len(pose.domain_transforms) > 0:
                pose_data['first_domain_location'] = list(pose.domain_transforms[0].location)
                pose_data['first_domain_rotation'] = list(pose.domain_transforms[0].rotation)
            restored_poses.append(pose_data)
            print(f"   {len(restored_poses)}. {pose.name} ({len(pose.domain_transforms)} domains)")
            if len(pose.domain_transforms) > 0:
                print(f"      Location: {list(pose.domain_transforms[0].location)}")
        
        # Test Step 5: Compare original vs restored poses
        print("\n--- Verification ---")
        
        success = True
        if len(original_poses) != len(restored_poses):
            print(f"❌ Pose count mismatch: {len(original_poses)} vs {len(restored_poses)}")
            success = False
        else:
            print(f"✓ Pose count matches: {len(restored_poses)}")
            
            for i, (orig, restored) in enumerate(zip(original_poses, restored_poses)):
                matches = True
                for key in ['name', 'has_protein_transform', 'domain_count']:
                    if orig[key] != restored[key]:
                        print(f"❌ Pose {i+1} property '{key}' mismatch: {orig[key]} vs {restored[key]}")
                        matches = False
                        success = False
                
                # Check domain transform data if available
                if 'first_domain_location' in orig and 'first_domain_location' in restored:
                    orig_loc = orig['first_domain_location']
                    restored_loc = restored['first_domain_location']
                    # Check if locations are approximately equal (floating point precision)
                    if not all(abs(a - b) < 0.001 for a, b in zip(orig_loc, restored_loc)):
                        print(f"❌ Pose {i+1} domain location mismatch: {orig_loc} vs {restored_loc}")
                        matches = False
                        success = False
                
                if matches:
                    print(f"✓ Pose {i+1} fully restored: {restored['name']}")
        
        # Test Step 6: Test applying poses after undo/redo
        print("\n--- Testing Pose Application ---")
        if len(test_item.poses) >= 2:
            # Apply first pose
            test_item.active_pose_index = 0
            bpy.ops.molecule.apply_pose()
            first_location = list(domain_obj.location)
            print(f"✓ Applied Pose 1 - Domain location: {first_location}")
            
            # Apply second pose
            test_item.active_pose_index = 1
            bpy.ops.molecule.apply_pose()
            second_location = list(domain_obj.location)
            print(f"✓ Applied Pose 2 - Domain location: {second_location}")
            
            # Verify poses actually change the object position
            if first_location != second_location:
                print("✓ Poses have different domain positions (correct)")
            else:
                print("❌ Poses have same domain positions (incorrect)")
                success = False
        
        print("\n" + "=" * 50)
        if success:
            print("✅ POSE UNDO/REDO FIX VERIFICATION PASSED!")
            print("\nAll poses were properly restored to the UI panel after redo operation.")
            print("Poses are now consistent with keyframe undo/redo behavior.")
        else:
            print("❌ POSE UNDO/REDO FIX VERIFICATION FAILED!")
            print("\nSome poses were not properly restored. Check the output above for details.")
        
        print(f"\nFinal State:")
        print(f"- UI Poses: {len(test_item.poses)}")
        print(f"- Undo/Redo Consistency: {'✓' if success else '❌'}")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pose_undo_redo() 