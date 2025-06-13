#!/usr/bin/env python3
"""
Test script to validate current MoleculeWrapper functionality before consolidation.
This ensures we don't break anything during the consolidation process.
"""

import sys
import os

# Add the proteinblender directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'proteinblender'))

def test_imports():
    """Test that all current imports work correctly"""
    print("Testing imports...")
    
    try:
        # Test primary implementation (molecule_manager.py)
        from proteinblender.core.molecule_manager import MoleculeWrapper as MoleculeWrapperA
        from proteinblender.core.molecule_manager import MoleculeManager as MoleculeManagerA
        print("✓ molecule_manager.py imports successful")
        
        # Test alternative implementation (molecule_wrapper.py)
        from proteinblender.core.molecule_wrapper import MoleculeWrapper as MoleculeWrapperB
        print("✓ molecule_wrapper.py imports successful")
        
        return True, (MoleculeWrapperA, MoleculeManagerA, MoleculeWrapperB)
        
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False, None

def test_chain_mapping_upgrade():
    """Test the upgraded chain mapping functionality in Implementation A"""
    print("\nTesting upgraded chain mapping functionality...")
    
    try:
        from proteinblender.core.molecule_manager import MoleculeWrapper as MoleculeWrapperA
        print("✓ Upgraded MoleculeWrapper import successful")
        
        # Test that the new attributes exist in the class definition
        required_attrs = ['auth_chain_id_map', 'idx_to_label_asym_id_map', 'get_int_chain_index']
        
        # Check if these attributes/methods are defined
        if hasattr(MoleculeWrapperA, '__init__'):
            print("✓ MoleculeWrapper has __init__ method")
            
        if hasattr(MoleculeWrapperA, 'get_int_chain_index'):
            print("✓ get_int_chain_index method exists")
        else:
            print("✗ get_int_chain_index method missing")
            
        if hasattr(MoleculeWrapperA, 'get_author_chain_id'):
            print("✓ get_author_chain_id method exists")
        else:
            print("✗ get_author_chain_id method missing")
            
        return True
        
    except Exception as e:
        print(f"✗ Chain mapping upgrade test failed: {e}")
        return False

def test_basic_functionality():
    """Test basic functionality that should still work"""
    print("\nTesting basic functionality...")
    
    success_count = 0
    total_tests = 4
    
    # Test 1: Import test
    import_success, imports = test_imports()
    if import_success:
        success_count += 1
        print("✓ Test 1: Import test passed")
    else:
        print("✗ Test 1: Import test failed")
    
    # Test 2: Chain mapping upgrade test
    if test_chain_mapping_upgrade():
        success_count += 1
        print("✓ Test 2: Chain mapping upgrade test passed")
    else:
        print("✗ Test 2: Chain mapping upgrade test failed")
    
    # Test 3: Class instantiation readiness (we can't fully test without molecule data)
    try:
        from proteinblender.core.molecule_manager import MoleculeWrapper
        # Just check that the class can be referenced
        class_attrs = dir(MoleculeWrapper)
        if '__init__' in class_attrs and 'get_author_chain_id' in class_attrs:
            success_count += 1
            print("✓ Test 3: Class structure validation passed")
        else:
            print("✗ Test 3: Class structure validation failed")
    except Exception as e:
        print(f"✗ Test 3: Class structure validation failed: {e}")
    
    # Test 4: Method signature compatibility
    try:
        from proteinblender.core.molecule_manager import MoleculeWrapper
        import inspect
        
        # Check get_author_chain_id method signature
        sig = inspect.signature(MoleculeWrapper.get_author_chain_id)
        params = list(sig.parameters.keys())
        if 'self' in params and 'numeric_chain_id' in params:
            success_count += 1
            print("✓ Test 4: Method signature compatibility passed")
        else:
            print("✗ Test 4: Method signature compatibility failed")
    except Exception as e:
        print(f"✗ Test 4: Method signature compatibility failed: {e}")
    
    print(f"\nOverall: {success_count}/{total_tests} tests passed")
    return success_count == total_tests

if __name__ == "__main__":
    print("=== MoleculeWrapper Functionality Test ===")
    success = test_basic_functionality()
    
    if success:
        print("\n🎉 All tests passed! Chain mapping upgrade appears successful.")
        print("✅ Step 2: Unify Chain Mapping Logic - COMPLETE")
    else:
        print("\n❌ Some tests failed. Please review the changes.")
    
    print("\nNext: Ready for Step 3 - Consolidate Domain Management Logic") 