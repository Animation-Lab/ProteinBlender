#!/usr/bin/env python3
"""
Simple test script to validate domain creation with undo/redo functionality.
Run this in Blender's text editor to test the improved domain system.
"""

import bpy
from proteinblender.operators.operator_import_protein import PROTEIN_OT_import_protein

def test_domain_creation():
    """Test domain creation with a simple protein"""
    print("=" * 60)
    print("TESTING DOMAIN CREATION WITH UNDO/REDO")
    print("=" * 60)
    
    # Clear the scene first
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    print("\\n1. IMPORTING PROTEIN WITH DOMAIN CREATION...")
    
    # Set up import properties for a simple small protein
    scene = bpy.context.scene
    scene.protein_props.identifier = "1ABC"  # Small protein for testing
    
    # Import the protein
    try:
        import_op = PROTEIN_OT_import_protein()
        result = import_op.execute(bpy.context)
        
        if result == {'FINISHED'}:
            print("✅ Protein import completed")
            
            # Check what objects were created
            print("\\n2. CHECKING CREATED OBJECTS...")
            main_objects = []
            domain_objects = []
            
            for obj in bpy.data.objects:
                if obj.get("is_protein_blender_main"):
                    main_objects.append(obj.name)
                    print(f"   Main protein: {obj.name}")
                elif obj.get("is_protein_blender_domain"):
                    domain_objects.append(obj.name)
                    print(f"   Domain: {obj.name} (parent: {obj.get('parent_molecule')})")
            
            print(f"\\n   Found {len(main_objects)} main proteins and {len(domain_objects)} domains")
            
            if domain_objects:
                print("✅ Domain creation SUCCESS!")
                
                print("\\n3. TESTING UNDO OPERATION...")
                # Test undo
                bpy.ops.ed.undo()
                
                # Check what remains after undo
                remaining_main = []
                remaining_domains = []
                
                for obj in bpy.data.objects:
                    if obj.get("is_protein_blender_main"):
                        remaining_main.append(obj.name)
                    elif obj.get("is_protein_blender_domain"):
                        remaining_domains.append(obj.name)
                
                print(f"   After undo: {len(remaining_main)} main proteins and {len(remaining_domains)} domains")
                
                if len(remaining_main) == 0 and len(remaining_domains) == 0:
                    print("✅ Undo operation SUCCESS!")
                    
                    print("\\n4. TESTING REDO OPERATION...")
                    # Test redo
                    bpy.ops.ed.redo()
                    
                    # Check what's restored after redo
                    restored_main = []
                    restored_domains = []
                    
                    for obj in bpy.data.objects:
                        if obj.get("is_protein_blender_main"):
                            restored_main.append(obj.name)
                        elif obj.get("is_protein_blender_domain"):
                            restored_domains.append(obj.name)
                    
                    print(f"   After redo: {len(restored_main)} main proteins and {len(restored_domains)} domains")
                    
                    if restored_main and restored_domains:
                        print("✅ Redo operation SUCCESS!")
                        print("\\n🎉 ALL TESTS PASSED!")
                    else:
                        print("❌ Redo failed - objects not restored")
                else:
                    print("❌ Undo failed - objects still present")
            else:
                print("❌ Domain creation FAILED - no domains found")
        else:
            print("❌ Protein import FAILED")
            
    except Exception as e:
        print(f"❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_domain_creation() 