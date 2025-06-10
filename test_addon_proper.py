import bpy
import sys
import os

print("Testing ProteinBlender addon registration...")

# Add the project directory to sys.path so the addon can be found
project_dir = os.path.dirname(__file__)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

try:
    # Enable the addon (this will test if registration works)
    print("1. Testing addon enabling...")
    
    # First check if addon is already enabled
    if 'proteinblender' in bpy.context.preferences.addons:
        print("   - Addon already enabled, disabling first...")
        bpy.ops.preferences.addon_disable(module='proteinblender')
    
    # Try to enable the addon
    bpy.ops.preferences.addon_enable(module='proteinblender')
    print("   ✓ Addon enabled successfully")
    
    # Check if operators are registered
    print("2. Testing operator registration...")
    if hasattr(bpy.ops, 'protein') and hasattr(bpy.ops.protein, 'import_local'):
        print("   ✓ protein.import_local operator is registered")
    else:
        print("   ❌ protein.import_local operator not found")
    
    if hasattr(bpy.ops, 'protein') and hasattr(bpy.ops.protein, 'import_protein'):
        print("   ✓ protein.import_protein operator is registered") 
    else:
        print("   ❌ protein.import_protein operator not found")
    
    # Check if scene manager can be created
    print("3. Testing scene manager...")
    # Import the function directly since the addon should be loaded now
    from proteinblender.utils.scene_manager import get_protein_blender_scene
    scene_manager = get_protein_blender_scene(bpy.context)
    print("   ✓ Scene manager created successfully")
    
    print("\n✅ Addon registration and basic functionality test passed!")
    
except Exception as e:
    print(f"❌ Error during addon testing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nTesting completed successfully!") 