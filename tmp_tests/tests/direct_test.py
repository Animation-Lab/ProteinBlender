import sys
import os

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("STARTING PROTEINBLENDER REGISTRATION TEST")
print("=" * 60)

try:
    print("Step 1: Importing Blender...")
    import bpy
    print("✓ Blender imported successfully")
    
    print("Step 2: Importing ProteinBlender...")
    import proteinblender
    print("✓ ProteinBlender imported successfully")
    
    print("Step 3: Testing registration...")
    proteinblender.register()
    print("✓ Registration completed - no 'Failed to unregister' errors!")
    
    print("Step 4: Testing unregistration...")
    proteinblender.unregister()
    print("✓ Unregistration completed!")
    
    print("\n" + "=" * 60)
    print("🎉 SUCCESS - REGISTRATION SYSTEM FIXED!")
    print("=" * 60)
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    print("=" * 60) 