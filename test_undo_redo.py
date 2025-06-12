#!/usr/bin/env python3
"""
Test script for ProteinBlender undo/redo functionality.
Run this in Blender's text editor to test the improved undo system.
"""

import bpy
from proteinblender.operators.operator_import_protein import PROTEIN_OT_import_protein
from proteinblender.operators.molecule_operators import MOLECULE_OT_delete

def test_undo_redo_system():
    """Test the improved undo/redo system with protein import and deletion"""
    print("=" * 60)
    print("TESTING PROTEINBLENDER UNDO/REDO SYSTEM")
    print("=" * 60)
    
    # Clear the scene first
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    print("\n1. TESTING PROTEIN IMPORT...")
    
    # Set up import properties
    scene = bpy.context.scene
    scene.protein_props.import_method = 'PDB'
    scene.protein_props.pdb_id = '1ABC'  # Small test protein
    
    # Count objects before import
    objects_before = len(bpy.data.objects)
    print(f"Objects before import: {objects_before}")
    
    # Import protein
    bpy.ops.protein.import_protein()
    
    # Count objects after import
    objects_after = len(bpy.data.objects)
    print(f"Objects after import: {objects_after}")
    
    # Check for main protein object
    main_proteins = []
    domains = []
    for obj in bpy.data.objects:
        if obj.get("is_protein_blender_main"):
            main_proteins.append(obj)
            print(f"  Found main protein: {obj.name} (ID: {obj.get('molecule_identifier')})")
        elif obj.get("is_protein_blender_domain"):
            domains.append(obj)
            domain_id = obj.get("pb_domain_id")
            parent_mol = obj.get("molecule_identifier")
            print(f"  Found domain: {obj.name} (Domain ID: {domain_id}, Parent: {parent_mol})")
    
    print(f"Total main proteins: {len(main_proteins)}")
    print(f"Total domains: {len(domains)}")
    
    if not main_proteins:
        print("ERROR: No main protein found after import!")
        return False
    
    print("\n2. TESTING PROTEIN DELETION...")
    
    # Get the molecule ID for deletion
    molecule_id = main_proteins[0].get("molecule_identifier")
    print(f"Deleting molecule: {molecule_id}")
    
    # Delete the protein
    bpy.ops.molecule.delete(molecule_id=molecule_id)
    
    # Count objects after deletion
    objects_after_delete = len(bpy.data.objects)
    print(f"Objects after deletion: {objects_after_delete}")
    
    # Verify all related objects are gone
    remaining_proteins = []
    remaining_domains = []
    for obj in bpy.data.objects:
        if obj.get("molecule_identifier") == molecule_id:
            if obj.get("is_protein_blender_main"):
                remaining_proteins.append(obj)
            elif obj.get("is_protein_blender_domain"):
                remaining_domains.append(obj)
    
    if remaining_proteins or remaining_domains:
        print(f"ERROR: Found {len(remaining_proteins)} proteins and {len(remaining_domains)} domains still in scene!")
        return False
    
    print("✓ All objects properly deleted")
    
    print("\n3. TESTING UNDO OPERATION...")
    
    # Undo the deletion
    bpy.ops.ed.undo()
    
    # Count objects after undo
    objects_after_undo = len(bpy.data.objects)
    print(f"Objects after undo: {objects_after_undo}")
    
    # Check that objects are restored
    restored_proteins = []
    restored_domains = []
    for obj in bpy.data.objects:
        if obj.get("molecule_identifier") == molecule_id:
            if obj.get("is_protein_blender_main"):
                restored_proteins.append(obj)
                print(f"  Restored main protein: {obj.name}")
            elif obj.get("is_protein_blender_domain"):
                restored_domains.append(obj)
                domain_id = obj.get("pb_domain_id")
                print(f"  Restored domain: {obj.name} (Domain ID: {domain_id})")
    
    print(f"Restored proteins: {len(restored_proteins)}")
    print(f"Restored domains: {len(restored_domains)}")
    
    if not restored_proteins:
        print("ERROR: Main protein not restored after undo!")
        return False
    
    if len(restored_domains) != len(domains):
        print(f"ERROR: Domain count mismatch! Original: {len(domains)}, Restored: {len(restored_domains)}")
        return False
    
    print("✓ All objects properly restored")
    
    print("\n4. TESTING REDO OPERATION...")
    
    # Redo the deletion
    bpy.ops.ed.redo()
    
    # Count objects after redo
    objects_after_redo = len(bpy.data.objects)
    print(f"Objects after redo: {objects_after_redo}")
    
    # Verify objects are deleted again
    final_proteins = []
    final_domains = []
    for obj in bpy.data.objects:
        if obj.get("molecule_identifier") == molecule_id:
            if obj.get("is_protein_blender_main"):
                final_proteins.append(obj)
            elif obj.get("is_protein_blender_domain"):
                final_domains.append(obj)
    
    if final_proteins or final_domains:
        print(f"ERROR: Found {len(final_proteins)} proteins and {len(final_domains)} domains after redo!")
        return False
    
    print("✓ All objects properly deleted again")
    
    print("\n5. TESTING SYNC HANDLER...")
    
    # Trigger the sync handler manually to test it
    from proteinblender.handlers.sync import sync_manager_on_undo_redo
    sync_manager_on_undo_redo(bpy.context.scene)
    
    # Check UI state
    ui_molecules = len(bpy.context.scene.molecule_list_items)
    print(f"UI molecule count: {ui_molecules}")
    
    print("\n" + "=" * 60)
    print("UNDO/REDO TEST COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    return True

def test_ui_consistency():
    """Test that UI stays consistent with undo/redo operations"""
    print("\nTESTING UI CONSISTENCY...")
    
    scene = bpy.context.scene
    
    # Test multiple import/delete/undo cycles
    for i in range(3):
        print(f"\nCycle {i+1}:")
        
        # Import
        scene.protein_props.pdb_id = f"1ABC"  # Use same ID for simplicity
        bpy.ops.protein.import_protein()
        
        ui_count_after_import = len(scene.molecule_list_items)
        print(f"  UI molecules after import: {ui_count_after_import}")
        
        # Delete
        if scene.molecule_list_items:
            mol_id = scene.molecule_list_items[0].identifier
            bpy.ops.molecule.delete(molecule_id=mol_id)
        
        ui_count_after_delete = len(scene.molecule_list_items)
        print(f"  UI molecules after delete: {ui_count_after_delete}")
        
        # Undo
        bpy.ops.ed.undo()
        ui_count_after_undo = len(scene.molecule_list_items)
        print(f"  UI molecules after undo: {ui_count_after_undo}")
    
    print("✓ UI consistency test completed")

if __name__ == "__main__":
    try:
        success = test_undo_redo_system()
        if success:
            test_ui_consistency()
    except Exception as e:
        print(f"ERROR: Test failed with exception: {e}")
        import traceback
        traceback.print_exc() 