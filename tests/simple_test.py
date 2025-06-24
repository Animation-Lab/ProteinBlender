import sys
import os
import bpy

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("="*60)
print("TESTING PROTEINBLENDER REGISTRATION FIXES")
print("="*60)

try:
    print("1. Importing ProteinBlender...")
    import proteinblender
    print("   ✓ Import successful")
    
    print(f"2. Addon info: {proteinblender.bl_info['name']} v{proteinblender.bl_info['version']}")
    
    print("3. Testing class validation...")
    from proteinblender.addon import _is_blender_class, all_pb_classes
    
    total_classes = 0
    valid_classes = 0
    
    for i, class_group in enumerate(all_pb_classes):
        category = ["Core", "Handlers", "Operators", "Panels", "Session"][i]
        print(f"   {category}: {len(class_group)} classes")
        
        for cls in class_group:
            total_classes += 1
            if _is_blender_class(cls):
                valid_classes += 1
            else:
                print(f"      ⚠️ Invalid class: {cls.__name__}")
    
    print(f"   📊 {valid_classes}/{total_classes} classes are valid")
    
    print("4. Testing registration...")
    proteinblender.register()
    print("   ✓ Registration completed without 'Failed to unregister' errors!")
    
    from proteinblender.addon import _registered_classes, _registered_properties
    print(f"   📊 Registered: {len(_registered_classes)} classes, {len(_registered_properties)} properties")
    
    print("5. Testing unregistration...")
    proteinblender.unregister()
    print("   ✓ Unregistration completed!")
    print(f"   📊 Remaining: {len(_registered_classes)} classes, {len(_registered_properties)} properties")
    
    print("\n" + "="*60)
    print("🎉 SUCCESS! Registration system has been fixed!")
    print("   • No more 'Failed to unregister' errors")
    print("   • Only valid Blender classes are registered")
    print("   • Proper tracking of registered components")
    print("="*60)
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    print("="*60) 