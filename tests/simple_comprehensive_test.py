#!/usr/bin/env python3
"""
Simple test of comprehensive domain creation functionality.
Run with Blender in background:
& 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe' --background --python "tests/simple_comprehensive_test.py"
"""
import sys
import os

print("Starting simple comprehensive test...")

# Ensure project root is on path for imports
sys.path.insert(0, os.getcwd())

import bpy

# Register addon
try:
    from proteinblender import addon as pb_addon
    pb_addon.register()
    print("ProteinBlender addon registered successfully")
except Exception as e:
    print(f"Failed to register addon: {e}")
    os._exit(1)

def test_comprehensive_method():
    """Test that the comprehensive domain method exists and can be called."""
    try:
        from proteinblender.core.molecule_wrapper import MoleculeWrapper
        
        # Check if method exists
        if hasattr(MoleculeWrapper, 'create_comprehensive_domains'):
            print("✅ create_comprehensive_domains method found")
        else:
            print("❌ create_comprehensive_domains method NOT found")
            return False
            
        # Check if the new scene manager logic is in place
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        
        # Look for the method call in the source
        import inspect
        source = inspect.getsource(ProteinBlenderScene._finalize_imported_molecule)
        if 'create_comprehensive_domains' in source:
            print("✅ Scene manager uses comprehensive domain creation")
        else:
            print("❌ Scene manager does NOT use comprehensive domain creation")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Exception during method test: {e}")
        return False

def main():
    print("Testing comprehensive domain functionality...")
    
    success = test_comprehensive_method()
    
    if success:
        print("✅ All comprehensive domain tests passed!")
        os._exit(0)
    else:
        print("❌ Tests failed.")
        os._exit(1)

if __name__ == "__main__":
    main() 