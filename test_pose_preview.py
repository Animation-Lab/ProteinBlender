"""Test script to debug pose preview display"""

import bpy
import os

def test_pose_preview():
    """Check if pose previews are loaded and available"""
    
    print("\n" + "="*60)
    print("Testing Pose Preview System")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check pose library
    if not hasattr(scene, 'pose_library'):
        print("✗ No pose library found")
        return
    
    print(f"\nFound {len(scene.pose_library)} poses:")
    
    for idx, pose in enumerate(scene.pose_library):
        print(f"\nPose {idx}: '{pose.name}'")
        print(f"  Preview path: {pose.preview_path}")
        
        if pose.preview_path:
            # Check if file exists
            if os.path.exists(pose.preview_path):
                print(f"  ✓ Preview file exists")
                file_size = os.path.getsize(pose.preview_path)
                print(f"    File size: {file_size} bytes")
            else:
                print(f"  ✗ Preview file NOT found at path")
            
            # Check if image is loaded in Blender
            found_image = None
            for img in bpy.data.images:
                if img.filepath == pose.preview_path or img.filepath_raw == pose.preview_path:
                    found_image = img
                    break
            
            if found_image:
                print(f"  ✓ Image loaded in Blender: '{found_image.name}'")
                print(f"    Has data: {found_image.has_data}")
                print(f"    Size: {found_image.size[0]}x{found_image.size[1]}")
                print(f"    Preview exists: {found_image.preview is not None}")
                if found_image.preview:
                    print(f"    Preview icon_id: {found_image.preview.icon_id}")
            else:
                print(f"  ✗ Image NOT loaded in Blender")
                
                # Try to load it manually
                try:
                    print("  Attempting to load image manually...")
                    img = bpy.data.images.load(pose.preview_path)
                    img.name = f"pose_preview_manual_{idx}"
                    img.preview_ensure()
                    print(f"  ✓ Successfully loaded as '{img.name}'")
                    print(f"    Preview icon_id: {img.preview.icon_id}")
                except Exception as e:
                    print(f"  ✗ Failed to load: {e}")
        else:
            print("  No preview path set")
    
    # List all loaded images
    print(f"\n\nAll loaded images ({len(bpy.data.images)}):")
    for img in bpy.data.images:
        print(f"  - {img.name}: {img.filepath}")
    
    print("\n" + "="*60)

# Run the test
if __name__ == "__main__":
    test_pose_preview()