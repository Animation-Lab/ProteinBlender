"""
Simple test for undo/redo functionality in ProteinBlender
"""
import bpy
from proteinblender.utils.scene_manager import ProteinBlenderScene
from proteinblender.core.molecule_state import _is_object_valid


def test_simple_undo_redo():
    """Test basic protein delete/undo cycle"""
    print("=== Starting Simple Undo/Redo Test ===")
    
    # 1. Import a protein
    scene_manager = ProteinBlenderScene.get_instance()
    print("Importing protein 1CRN...")
    success = scene_manager.create_molecule_from_id("1CRN", "PDB", "pdb")
    assert success, "Failed to import protein 1CRN"
    
    # Get the molecule that was imported
    molecule_id = list(scene_manager.molecules.keys())[0]
    molecule = scene_manager.molecules[molecule_id]
    print(f"Imported molecule ID: {molecule_id}")
    
    # 2. Verify domains exist
    print(f"Number of domains: {len(molecule.domains)}")
    assert len(molecule.domains) > 0, "No domains were created"
    
    # Store initial state for comparison
    initial_domain_count = len(molecule.domains)
    initial_domain_ids = set(molecule.domains.keys())
    print(f"Initial domain IDs: {initial_domain_ids}")
    
    # 3. Delete the molecule
    print(f"Deleting molecule: {molecule_id}")
    success = scene_manager.delete_molecule(molecule_id)
    assert success, "Failed to delete molecule"
    assert molecule_id not in scene_manager.molecules, "Molecule still exists after deletion"
    print("Molecule successfully deleted")
    
    # 4. Undo deletion
    print("Performing undo...")
    bpy.ops.ed.undo()
    
    # 5. Verify everything is restored
    print("Verifying restoration...")
    assert molecule_id in scene_manager.molecules, "Molecule not restored after undo"
    
    restored_molecule = scene_manager.molecules[molecule_id]
    assert _is_object_valid(restored_molecule.object), "Restored molecule object is invalid"
    assert len(restored_molecule.domains) == initial_domain_count, f"Domain count mismatch: expected {initial_domain_count}, got {len(restored_molecule.domains)}"
    
    restored_domain_ids = set(restored_molecule.domains.keys())
    assert restored_domain_ids == initial_domain_ids, f"Domain IDs mismatch: expected {initial_domain_ids}, got {restored_domain_ids}"
    
    # 6. Verify domains are restored
    for domain_id, domain in restored_molecule.domains.items():
        assert _is_object_valid(domain.object), f"Domain {domain_id} object is invalid"
        print(f"Domain {domain_id}: OK")
    
    print("=== Undo/Redo Test PASSED ===")
    return True


def test_multiple_undo_redo_cycles():
    """Test multiple undo/redo cycles"""
    print("=== Starting Multiple Undo/Redo Cycles Test ===")
    
    scene_manager = ProteinBlenderScene.get_instance()
    
    # Get existing molecule or import one
    if not scene_manager.molecules:
        success = scene_manager.create_molecule_from_id("1UBQ", "PDB", "pdb")
        assert success, "Failed to import protein 1UBQ"
    
    molecule_id = list(scene_manager.molecules.keys())[0]
    print(f"Testing with molecule: {molecule_id}")
    
    # Perform multiple delete/undo cycles
    for cycle in range(3):
        print(f"\n--- Cycle {cycle + 1} ---")
        
        # Verify molecule exists
        assert molecule_id in scene_manager.molecules, f"Molecule missing at start of cycle {cycle + 1}"
        molecule = scene_manager.molecules[molecule_id]
        domain_count = len(molecule.domains)
        print(f"Domain count: {domain_count}")
        
        # Delete
        success = scene_manager.delete_molecule(molecule_id)
        assert success, f"Failed to delete molecule in cycle {cycle + 1}"
        
        # Undo
        bpy.ops.ed.undo()
        
        # Verify restoration
        assert molecule_id in scene_manager.molecules, f"Molecule not restored in cycle {cycle + 1}"
        restored_molecule = scene_manager.molecules[molecule_id]
        assert len(restored_molecule.domains) == domain_count, f"Domain count mismatch in cycle {cycle + 1}"
        
        print(f"Cycle {cycle + 1}: OK")
    
    print("=== Multiple Cycles Test PASSED ===")
    return True


def run_all_tests():
    """Run all undo/redo tests"""
    try:
        # Clean up any existing molecules first
        scene_manager = ProteinBlenderScene.get_instance()
        for mol_id in list(scene_manager.molecules.keys()):
            scene_manager.delete_molecule(mol_id)
        
        # Run tests
        test_simple_undo_redo()
        test_multiple_undo_redo_cycles()
        
        print("\n🎉 ALL TESTS PASSED! 🎉")
        print("Undo/Redo functionality is working correctly.")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    # Run this in Blender's Python console:
    # exec(open("test_simple_undo_redo.py").read())
    run_all_tests() 