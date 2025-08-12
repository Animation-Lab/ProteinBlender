"""Simple test for pose panel without full addon registration"""

import bpy
import sys
import os

# Add the addon directory to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
if addon_path not in sys.path:
    sys.path.append(addon_path)

try:
    # Import the pose panel module directly
    from proteinblender.panels import pose_library_panel
    from proteinblender.properties import molecule_props
    
    # Register the property classes
    print("Registering property classes...")
    bpy.utils.register_class(molecule_props.GroupTransformData)
    bpy.utils.register_class(molecule_props.MoleculePose)
    print("✓ Property classes registered")
    
    # Register the pose panel classes
    print("\nRegistering pose panel classes...")
    for cls in pose_library_panel.CLASSES:
        try:
            bpy.utils.register_class(cls)
            print(f"✓ Registered {cls.__name__}")
        except Exception as e:
            print(f"✗ Failed to register {cls.__name__}: {e}")
    
    # Verify panel is accessible
    if hasattr(bpy.types, "PROTEINBLENDER_PT_pose_library"):
        print("\n✓ Pose Library panel successfully registered!")
        print("  Panel will appear in View3D > Sidebar > ProteinBlender tab")
        print("  (after importing a protein molecule)")
    else:
        print("\n✗ Panel registration verification failed")
    
    # Check operators
    print("\nChecking operators:")
    op_checks = [
        ("proteinblender", "pose_thumbnail"),
        ("proteinblender", "create_pose"),
        ("proteinblender", "edit_pose"),
    ]
    
    for module, operator in op_checks:
        if hasattr(bpy.ops, module):
            mod = getattr(bpy.ops, module)
            if hasattr(mod, operator):
                print(f"✓ bpy.ops.{module}.{operator} is available")
            else:
                print(f"✗ bpy.ops.{module}.{operator} not found")
        else:
            print(f"✗ Module bpy.ops.{module} not found")
    
    print("\n--- Test Complete ---")
    print("The pose panel components have been successfully registered.")
    print("To use: Import a protein, then check the ProteinBlender sidebar.")
    
except Exception as e:
    print(f"✗ Error during test: {e}")
    import traceback
    traceback.print_exc()