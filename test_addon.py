import bpy
import sys
import os

# Add the proteinblender directory to sys.path
addon_path = os.path.join(os.path.dirname(__file__), 'proteinblender')
if addon_path not in sys.path:
    sys.path.insert(0, addon_path)

print("Testing ProteinBlender addon imports...")

try:
    # Test basic imports
    print("1. Testing addon import...")
    import addon
    print("   ✓ addon imported successfully")
    
    print("2. Testing core imports...")
    from core import domain
    print("   ✓ core.domain imported successfully")
    
    print("3. Testing operators imports...")
    from operators import operator_import_local
    print("   ✓ operators.operator_import_local imported successfully")
    
    print("4. Testing panels imports...")
    from panels import molecule_list_panel
    print("   ✓ panels.molecule_list_panel imported successfully")
    
    print("5. Testing scene_manager imports...")
    from utils.scene_manager import get_protein_blender_scene
    print("   ✓ utils.scene_manager.get_protein_blender_scene imported successfully")
    
    print("\n✅ All critical addon components import successfully!")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)

print("\nTesting completed successfully!") 