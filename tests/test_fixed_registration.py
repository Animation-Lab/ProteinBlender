#!/usr/bin/env python3
"""
Test script to validate the fixed registration system.
Run with: blender --background --python tests/test_fixed_registration.py
"""

import sys
import os
import bpy

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_class_validation():
    """Test that all classes in CLASSES tuples are valid Blender classes"""
    print("=" * 60)
    print("Testing class validation...")
    print("=" * 60)
    
    try:
        from proteinblender.addon import _is_blender_class, all_pb_classes
        
        invalid_classes = []
        valid_classes = []
        
        for category_index, class_group in enumerate(all_pb_classes):
            category_names = ["Core", "Handlers", "Operators", "Panels", "Session"]
            category_name = category_names[category_index] if category_index < len(category_names) else f"Category {category_index}"
            
            print(f"\n{category_name} classes:")
            for cls in class_group:
                is_valid = _is_blender_class(cls)
                print(f"  - {cls.__name__}: {'✓ Valid' if is_valid else '✗ Invalid'}")
                
                if is_valid:
                    valid_classes.append((category_name, cls))
                else:
                    invalid_classes.append((category_name, cls))
        
        print(f"\nSummary:")
        print(f"  Valid Blender classes: {len(valid_classes)}")
        print(f"  Invalid classes: {len(invalid_classes)}")
        
        if invalid_classes:
            print("\nInvalid classes found:")
            for category, cls in invalid_classes:
                print(f"  - {category}: {cls.__name__}")
            return False
        else:
            print("✓ All classes are valid Blender classes!")
            return True
            
    except Exception as e:
        print(f"Error during class validation: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_registration_unregistration():
    """Test the registration and unregistration process"""
    print("\n" + "=" * 60)
    print("Testing registration/unregistration...")
    print("=" * 60)
    
    try:
        # Import the addon
        import proteinblender
        
        print("🔧 Starting registration test...")
        
        # Test registration
        proteinblender.register()
        print("✓ Registration completed without errors!")
        
        # Check that things are actually registered
        from proteinblender.addon import _registered_classes, _registered_properties
        print(f"📊 Registered {len(_registered_classes)} classes and {len(_registered_properties)} properties")
        
        # Test unregistration  
        print("\n🔧 Starting unregistration test...")
        proteinblender.unregister()
        print("✓ Unregistration completed without errors!")
        
        # Check that things were properly unregistered
        print(f"📊 After unregistration: {len(_registered_classes)} classes and {len(_registered_properties)} properties remain")
        
        # Test re-registration to make sure we can register again
        print("\n🔧 Testing re-registration...")
        proteinblender.register()
        print("✓ Re-registration completed without errors!")
        
        proteinblender.unregister()
        print("✓ Final unregistration completed without errors!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during registration test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_addon_info():
    """Test addon info and basic structure"""
    print("\n" + "=" * 60)
    print("Testing addon info...")
    print("=" * 60)
    
    try:
        import proteinblender
        
        bl_info = proteinblender.bl_info
        print(f"📦 Addon: {bl_info['name']}")
        print(f"🏷️  Version: {bl_info['version']}")
        print(f"👤 Author: {bl_info['author']}")
        print(f"🎯 Category: {bl_info['category']}")
        print(f"🔢 Blender Version: {bl_info['blender']}")
        
        if bl_info.get('warning'):
            print(f"⚠️  Warning: {bl_info['warning']}")
        else:
            print("✓ No warnings in bl_info")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing addon info: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("🧪 Starting ProteinBlender Registration Tests")
    print("=" * 80)
    
    results = []
    
    # Test 1: Class validation
    results.append(("Class Validation", test_class_validation()))
    
    # Test 2: Addon info
    results.append(("Addon Info", test_addon_info()))
    
    # Test 3: Registration/Unregistration
    results.append(("Registration/Unregistration", test_registration_unregistration()))
    
    # Print results
    print("\n" + "=" * 80)
    print("🏁 TEST RESULTS")
    print("=" * 80)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
        if not passed:
            all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("🎉 ALL TESTS PASSED! The registration system has been fixed.")
    else:
        print("💥 SOME TESTS FAILED! Please check the errors above.")
    
    print("=" * 80)
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 