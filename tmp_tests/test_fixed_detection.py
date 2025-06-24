#!/usr/bin/env python3

import sys
import os
import bpy

# Add current directory to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

def test_molecule_detection(pdb_path, name):
    print(f"\n{'='*50}")
    print(f"Testing {name}")
    print(f"{'='*50}")
    
    try:
        from proteinblender.utils.molecularnodes.entities import load_local
        from proteinblender.core.molecule_wrapper import MoleculeWrapper
        
        # Load molecule
        print(f"Loading {pdb_path}...")
        mol = load_local(pdb_path)
        
        # Create wrapper
        print("Creating wrapper...")
        wrapper = MoleculeWrapper(mol, name)
        
        # Test detection logic
        print("Testing needs_inclusive_domains detection...")
        needs_inclusive = wrapper.needs_inclusive_domains()
        
        print(f"\nRESULT for {name}:")
        print(f"  needs_inclusive_domains: {needs_inclusive}")
        print(f"  Expected for {name}: {name == '1ATN'}")  # 1ATN should need inclusive, 3B75 should not
        
        if name == "3B75" and not needs_inclusive:
            print("  ✅ CORRECT: 3B75 should NOT need inclusive domains")
        elif name == "1ATN" and needs_inclusive:
            print("  ✅ CORRECT: 1ATN should need inclusive domains")
        else:
            print(f"  ❌ INCORRECT: Expected {name == '1ATN'}, got {needs_inclusive}")
        
        return needs_inclusive
        
    except Exception as e:
        print(f"Error testing {name}: {e}")
        import traceback
        traceback.print_exc()
        return None

# Test both molecules
print("Testing fixed detection logic...")
result_3b75 = test_molecule_detection("test_proteins/3b75.pdb", "3B75")
result_1atn = test_molecule_detection("test_proteins/1ATN.pdb", "1ATN")

print(f"\n{'='*50}")
print("SUMMARY")
print(f"{'='*50}")
print(f"3B75 needs_inclusive_domains: {result_3b75} (should be False)")
print(f"1ATN needs_inclusive_domains: {result_1atn} (should be True)")

if result_3b75 is False and result_1atn is True:
    print("✅ ALL TESTS PASSED!")
else:
    print("❌ TESTS FAILED - Detection logic needs further adjustment") 