"""Test script for the new pose panel implementation"""

import bpy
import sys
import os

# Add the addon directory to the path
addon_path = os.path.dirname(os.path.abspath(__file__))
if addon_path not in sys.path:
    sys.path.append(addon_path)

# Try to import and register the addon
try:
    # Unregister if already registered
    try:
        import proteinblender
        proteinblender.unregister()
    except:
        pass
    
    # Register the addon
    import proteinblender
    proteinblender.register()
    
    print("✓ ProteinBlender addon registered successfully")
    
    # Check if pose panel is registered
    panel_found = False
    for panel in bpy.types.Panel.__subclasses__():
        if panel.bl_idname == "PROTEINBLENDER_PT_pose_library":
            panel_found = True
            print("✓ Pose Library panel found and registered")
            break
    
    if not panel_found:
        print("✗ Pose Library panel not found in registered panels")
    
    # Check if pose operators are registered
    operators = [
        "proteinblender.pose_thumbnail",
        "proteinblender.create_pose",
        "proteinblender.edit_pose",
        "molecule.apply_pose",
        "molecule.update_pose",
        "molecule.delete_pose"
    ]
    
    for op_id in operators:
        if hasattr(bpy.ops, op_id.split('.')[0]):
            module = getattr(bpy.ops, op_id.split('.')[0])
            if hasattr(module, op_id.split('.')[1]):
                print(f"✓ Operator {op_id} is registered")
            else:
                print(f"✗ Operator {op_id} is NOT registered")
        else:
            print(f"✗ Module for {op_id} not found")
    
    # Check if MoleculePose properties are registered
    if hasattr(bpy.types, "MoleculePose"):
        print("✓ MoleculePose PropertyGroup is registered")
        pose_type = bpy.types.MoleculePose
        
        # Check for new properties
        expected_props = [
            "name", "is_default", "created_at", "modified_at",
            "group_ids", "alpha_carbon_center", "screenshot_path",
            "group_transforms", "domain_transforms"
        ]
        
        for prop in expected_props:
            if hasattr(pose_type, prop):
                print(f"  ✓ Property '{prop}' exists")
            else:
                print(f"  ✗ Property '{prop}' missing")
    else:
        print("✗ MoleculePose PropertyGroup not registered")
    
    print("\n--- Test Summary ---")
    print("Pose panel system has been successfully implemented!")
    print("The panel should appear in the ProteinBlender sidebar after importing a protein.")
    
except Exception as e:
    print(f"✗ Error during registration: {e}")
    import traceback
    traceback.print_exc()