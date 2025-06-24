#!/usr/bin/env python3
"""
Test script to verify that the undo/redo fix for keyframes works correctly.
This script specifically tests the issue where keyframes disappeared from the UI panel after redo.
"""

import bpy
import sys
import os

# Add the proteinblender module to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(addon_path)

def test_undo_redo_keyframe_fix():
    """Test that keyframes are properly preserved in UI during undo/redo operations"""
    print("Testing Undo/Redo Keyframe Fix")
    print("=" * 50)
    
    # Clear existing scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    try:
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        print("✓ ProteinBlender modules imported successfully")
        
        # Create a simple test object to simulate a protein
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
        test_obj = bpy.context.active_object
        test_obj.name = "TestProtein"
        
        # Create a mock molecule list item
        test_item = scene.molecule_list_items.add()
        test_item.identifier = "test_protein"
        test_item.object_ptr = test_obj
        scene.selected_molecule_id = "test_protein"
        
        print("✓ Test protein object created")
        
        # Test Step 1: Create first keyframe
        bpy.ops.molecule.keyframe_protein(
            keyframe_name="Start Frame",
            frame_number=1,
            use_brownian_motion=True,
            intensity=0.5,
            frequency=0.4,
            seed=42,
            resolution=2
        )
        
        print(f"✓ After keyframe 1 creation - UI keyframes: {len(test_item.keyframes)}")
        
        # Test Step 2: Create second keyframe with specific settings
        scene.frame_set(50)
        bpy.ops.molecule.keyframe_protein(
            keyframe_name="Second Frame",
            frame_number=50,
            use_brownian_motion=False,  # Different setting to test preservation
            intensity=0.8,
            frequency=0.6,
            seed=123,
            resolution=3
        )
        
        print(f"✓ After keyframe 2 creation - UI keyframes: {len(test_item.keyframes)}")
        
        # Store the keyframes data before undo to compare later
        original_keyframes = []
        for kf in test_item.keyframes:
            original_keyframes.append({
                'name': kf.name,
                'frame': kf.frame,
                'use_brownian_motion': kf.use_brownian_motion,
                'intensity': kf.intensity,
                'frequency': kf.frequency,
                'seed': kf.seed,
                'resolution': kf.resolution
            })
        
        print("✓ Original keyframes captured:")
        for i, kf_data in enumerate(original_keyframes):
            print(f"   {i+1}. {kf_data['name']} (Frame {kf_data['frame']}) - Brownian: {kf_data['use_brownian_motion']}")
        
        # Test Step 3: Undo the second keyframe creation
        print("\n--- Testing UNDO ---")
        bpy.ops.ed.undo()
        
        print(f"✓ After UNDO - UI keyframes: {len(test_item.keyframes)}")
        for i, kf in enumerate(test_item.keyframes):
            print(f"   {i+1}. {kf.name} (Frame {kf.frame}) - Brownian: {kf.use_brownian_motion}")
        
        # Test Step 4: Redo the second keyframe creation (THIS IS THE CRITICAL TEST)
        print("\n--- Testing REDO (Critical Test) ---")
        bpy.ops.ed.redo()
        
        print(f"✓ After REDO - UI keyframes: {len(test_item.keyframes)}")
        
        # Verify that all keyframes are restored correctly
        restored_keyframes = []
        for kf in test_item.keyframes:
            restored_keyframes.append({
                'name': kf.name,
                'frame': kf.frame,
                'use_brownian_motion': kf.use_brownian_motion,
                'intensity': kf.intensity,
                'frequency': kf.frequency,
                'seed': kf.seed,
                'resolution': kf.resolution
            })
            print(f"   {len(restored_keyframes)}. {kf.name} (Frame {kf.frame}) - Brownian: {kf.use_brownian_motion}")
        
        # Test Step 5: Compare original vs restored keyframes
        print("\n--- Verification ---")
        
        success = True
        if len(original_keyframes) != len(restored_keyframes):
            print(f"❌ Keyframe count mismatch: {len(original_keyframes)} vs {len(restored_keyframes)}")
            success = False
        else:
            print(f"✓ Keyframe count matches: {len(restored_keyframes)}")
            
            for i, (orig, restored) in enumerate(zip(original_keyframes, restored_keyframes)):
                matches = True
                for key in orig.keys():
                    if orig[key] != restored[key]:
                        print(f"❌ Keyframe {i+1} property '{key}' mismatch: {orig[key]} vs {restored[key]}")
                        matches = False
                        success = False
                
                if matches:
                    print(f"✓ Keyframe {i+1} fully restored: {restored['name']}")
        
        # Test Step 6: Check timeline synchronization
        timeline_keyframes = 0
        if test_obj.animation_data and test_obj.animation_data.action:
            fcurves = test_obj.animation_data.action.fcurves
            if fcurves and len(fcurves) > 0:
                timeline_keyframes = len(fcurves[0].keyframe_points)
        
        print(f"✓ Timeline keyframes: {timeline_keyframes}")
        
        print("\n" + "=" * 50)
        if success:
            print("✅ UNDO/REDO FIX VERIFICATION PASSED!")
            print("\nAll keyframes were properly restored to the UI panel after redo operation.")
            print("The fix successfully preserves keyframe data during undo/redo operations.")
        else:
            print("❌ UNDO/REDO FIX VERIFICATION FAILED!")
            print("\nSome keyframes were not properly restored. Check the output above for details.")
        
        print(f"\nFinal State:")
        print(f"- UI Keyframes: {len(test_item.keyframes)}")
        print(f"- Timeline Keyframes: {timeline_keyframes}")
        print(f"- UI/Timeline Sync: {'✓' if len(test_item.keyframes) > 0 and timeline_keyframes > 0 else '❌'}")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_undo_redo_keyframe_fix() 