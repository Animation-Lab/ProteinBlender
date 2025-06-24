#!/usr/bin/env python3
"""
Focused test for the specific keyframe undo/redo issue.
This test isolates the exact problem the user is experiencing.
"""

import bpy
import sys
import os

# Add the proteinblender module to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(addon_path)

def debug_keyframe_undo_redo():
    """Debug the specific keyframe undo/redo issue"""
    print("DEBUG: Keyframe Undo/Redo Issue")
    print("=" * 50)
    
    # Clear existing scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    try:
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        # Create test protein
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
        test_obj = bpy.context.active_object
        test_obj.name = "TestProtein"
        
        test_item = scene.molecule_list_items.add()
        test_item.identifier = "test_protein"
        test_item.object_ptr = test_obj
        scene.selected_molecule_id = "test_protein"
        
        print("✓ Test setup complete")
        
        # Step 1: Create keyframe 1
        print("\n--- Creating Keyframe 1 ---")
        scene.frame_set(1)
        bpy.ops.molecule.keyframe_protein(
            keyframe_name="Frame 1",
            frame_number=1,
            use_brownian_motion=True
        )
        
        print(f"After KF1 - UI keyframes: {len(test_item.keyframes)}")
        timeline_kf_count = 0
        if test_obj.animation_data and test_obj.animation_data.action:
            timeline_kf_count = len(test_obj.animation_data.action.fcurves[0].keyframe_points) if test_obj.animation_data.action.fcurves else 0
        print(f"After KF1 - Timeline keyframes: {timeline_kf_count}")
        
        # Step 2: Create keyframe 2  
        print("\n--- Creating Keyframe 2 ---")
        scene.frame_set(50)
        test_obj.location = (5, 0, 0)  # Move the object so we can see the animation
        bpy.ops.molecule.keyframe_protein(
            keyframe_name="Frame 2",
            frame_number=50,
            use_brownian_motion=False
        )
        
        print(f"After KF2 - UI keyframes: {len(test_item.keyframes)}")
        timeline_kf_count = 0
        if test_obj.animation_data and test_obj.animation_data.action:
            timeline_kf_count = len(test_obj.animation_data.action.fcurves[0].keyframe_points) if test_obj.animation_data.action.fcurves else 0
        print(f"After KF2 - Timeline keyframes: {timeline_kf_count}")
        
        # Show current keyframes
        print("Current UI keyframes:")
        for i, kf in enumerate(test_item.keyframes):
            print(f"  {i+1}. {kf.name} (Frame {kf.frame}) - Brownian: {kf.use_brownian_motion}")
        
        # Step 3: UNDO keyframe 2 creation
        print("\n--- UNDO Keyframe 2 ---")
        bpy.ops.ed.undo()
        
        print(f"After UNDO - UI keyframes: {len(test_item.keyframes)}")
        timeline_kf_count = 0
        if test_obj.animation_data and test_obj.animation_data.action:
            timeline_kf_count = len(test_obj.animation_data.action.fcurves[0].keyframe_points) if test_obj.animation_data.action.fcurves else 0
        print(f"After UNDO - Timeline keyframes: {timeline_kf_count}")
        
        print("UI keyframes after UNDO:")
        for i, kf in enumerate(test_item.keyframes):
            print(f"  {i+1}. {kf.name} (Frame {kf.frame}) - Brownian: {kf.use_brownian_motion}")
        
        # Step 4: REDO keyframe 2 creation (THE PROBLEM)
        print("\n--- REDO Keyframe 2 (Critical Test) ---")
        bpy.ops.ed.redo()
        
        print(f"After REDO - UI keyframes: {len(test_item.keyframes)}")
        timeline_kf_count = 0
        if test_obj.animation_data and test_obj.animation_data.action:
            timeline_kf_count = len(test_obj.animation_data.action.fcurves[0].keyframe_points) if test_obj.animation_data.action.fcurves else 0
        print(f"After REDO - Timeline keyframes: {timeline_kf_count}")
        
        print("UI keyframes after REDO:")
        for i, kf in enumerate(test_item.keyframes):
            print(f"  {i+1}. {kf.name} (Frame {kf.frame}) - Brownian: {kf.use_brownian_motion}")
        
        # Check if we have the expected result
        expected_ui_keyframes = 2
        expected_timeline_keyframes = 2  # Should be at least 2 (one at each keyframe)
        
        print("\n--- Results ---")
        ui_success = len(test_item.keyframes) == expected_ui_keyframes
        timeline_success = timeline_kf_count >= expected_timeline_keyframes
        
        print(f"UI Keyframes: {'✓' if ui_success else '❌'} ({len(test_item.keyframes)}/{expected_ui_keyframes})")
        print(f"Timeline Keyframes: {'✓' if timeline_success else '❌'} ({timeline_kf_count}/{expected_timeline_keyframes})")
        
        if ui_success and timeline_success:
            print("✅ UNDO/REDO working correctly!")
        else:
            print("❌ UNDO/REDO still has issues!")
            if not ui_success:
                print("   Problem: UI keyframes not restored properly")
            if not timeline_success:
                print("   Problem: Timeline keyframes not restored properly")
        
        # Debug: Check if undo handler is interfering
        print(f"\nDebug Info:")
        print(f"- Scene manager molecules: {len(scene_manager.molecules)}")
        print(f"- Scene UI items: {len(scene.molecule_list_items)}")
        print(f"- Object animation data: {test_obj.animation_data is not None}")
        if test_obj.animation_data:
            print(f"- Object action: {test_obj.animation_data.action is not None}")
            if test_obj.animation_data.action:
                print(f"- FCurves count: {len(test_obj.animation_data.action.fcurves)}")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_keyframe_undo_redo() 