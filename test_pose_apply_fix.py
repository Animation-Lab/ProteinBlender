"""Test script to verify pose apply functionality works correctly"""

import bpy
from mathutils import Vector

def test_pose_apply():
    """Test that pose apply correctly restores object positions"""
    
    print("\n" + "="*60)
    print("Testing Pose Apply Fix")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check if we have a pose library
    if not hasattr(scene, 'pose_library'):
        print("✗ No pose library found. Please create a pose first.")
        return False
    
    if len(scene.pose_library) == 0:
        print("✗ No poses in library. Please create a pose first.")
        return False
    
    # Get the first pose
    pose = scene.pose_library[0]
    print(f"\n1. Testing with pose: '{pose.name}'")
    print(f"   - Groups: {pose.group_names}")
    print(f"   - Transforms: {len(pose.transforms)}")
    
    # Store original positions from the pose
    original_positions = {}
    for transform in pose.transforms:
        original_positions[transform.object_name] = Vector(transform.location)
        print(f"   - Object '{transform.object_name}' should be at {list(transform.location)}")
    
    # Move objects away from their saved positions
    print("\n2. Moving objects away from saved positions...")
    moved_objects = []
    for obj_name in original_positions:
        obj = bpy.data.objects.get(obj_name)
        if obj:
            # Move object by 5 units in X
            obj.location.x += 5.0
            moved_objects.append(obj_name)
            print(f"   - Moved '{obj_name}' to {list(obj.location)}")
        else:
            print(f"   - WARNING: Could not find object '{obj_name}'")
    
    if not moved_objects:
        print("✗ No objects could be moved. Check if objects exist.")
        return False
    
    # Apply the pose to restore positions
    print("\n3. Applying pose to restore positions...")
    try:
        bpy.ops.proteinblender.apply_pose(pose_index=0)
    except Exception as e:
        print(f"✗ Failed to apply pose: {e}")
        return False
    
    # Check if positions were restored
    print("\n4. Checking if positions were restored...")
    success_count = 0
    failed_objects = []
    
    for obj_name in moved_objects:
        obj = bpy.data.objects.get(obj_name)
        if obj:
            original_pos = original_positions[obj_name]
            current_pos = obj.location
            diff = (current_pos - original_pos).length
            
            if diff < 0.001:  # Allow tiny floating point differences
                print(f"   ✓ '{obj_name}' restored to {list(current_pos)}")
                success_count += 1
            else:
                print(f"   ✗ '{obj_name}' NOT restored")
                print(f"     Expected: {list(original_pos)}")
                print(f"     Got: {list(current_pos)}")
                print(f"     Difference: {diff:.3f}")
                failed_objects.append(obj_name)
    
    # Summary
    print("\n" + "="*60)
    print("Test Results:")
    print(f"  - Objects tested: {len(moved_objects)}")
    print(f"  - Successfully restored: {success_count}")
    print(f"  - Failed to restore: {len(failed_objects)}")
    
    if failed_objects:
        print(f"  - Failed objects: {failed_objects}")
        print("\nDEBUGGING HELP:")
        print("Check the console output above for debug messages.")
        print("Look for 'Object NOT FOUND' messages in the apply operation.")
    
    success = (success_count == len(moved_objects))
    if success:
        print("\n✓ TEST PASSED: All objects restored correctly!")
    else:
        print("\n✗ TEST FAILED: Some objects were not restored.")
        print("\nPossible issues:")
        print("1. Object names changed between pose creation and apply")
        print("2. Objects were deleted and recreated")
        print("3. Domain IDs don't match between creation and apply")
    
    print("="*60)
    return success

# Run the test
if __name__ == "__main__":
    test_pose_apply()