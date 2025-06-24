#!/usr/bin/env python3
"""
Test script to check addon registration behavior.
Run with: blender --background --python tests/test_registration.py
"""

import sys
import os
import bpy

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_current_registration():
    """Test the current registration process"""
    print("=" * 60)
    print("Testing current registration system...")
    print("=" * 60)
    
    try:
        # Import the addon
        import proteinblender
        
        # Check bl_info
        print(f"Addon name: {proteinblender.bl_info['name']}")
        print(f"Addon version: {proteinblender.bl_info['version']}")
        
        # Try to register
        print("\nAttempting registration...")
        proteinblender.register()
        print("Registration completed successfully!")
        
        # Try to unregister
        print("\nAttempting unregistration...")
        proteinblender.unregister()
        print("Unregistration completed successfully!")
        
    except Exception as e:
        print(f"Error during registration test: {e}")
        import traceback
        traceback.print_exc()

def test_class_inspection():
    """Inspect the classes being registered"""
    print("\n" + "=" * 60)
    print("Inspecting classes...")
    print("=" * 60)
    
    try:
        from proteinblender.core import CLASSES as core_classes
        from proteinblender.operators import CLASSES as operator_classes
        from proteinblender.panels import CLASSES as panel_classes
        from proteinblender.handlers import CLASSES as handler_classes
        from proteinblender.utils.molecularnodes import session
        
        all_classes = [
            ("Core", core_classes),
            ("Operators", operator_classes), 
            ("Panels", panel_classes),
            ("Handlers", handler_classes),
            ("Session", session.CLASSES),
        ]
        
        for category, classes in all_classes:
            print(f"\n{category} classes:")
            for cls in classes:
                print(f"  - {cls.__name__}")
                # Check if it's a Blender class
                is_blender_class = (
                    hasattr(cls, 'bl_idname') or 
                    hasattr(cls, 'bl_label') or
                    issubclass(cls, bpy.types.PropertyGroup) or
                    issubclass(cls, bpy.types.Operator) or
                    issubclass(cls, bpy.types.Panel)
                )
                print(f"    Is Blender class: {is_blender_class}")
                print(f"    Base classes: {[base.__name__ for base in cls.__bases__]}")
                
    except Exception as e:
        print(f"Error during class inspection: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_current_registration()
    test_class_inspection() 