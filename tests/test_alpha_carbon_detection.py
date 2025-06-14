#!/usr/bin/env python3
"""
Test script to debug alpha carbon detection issues in the protein import process.
"""

import bpy
import sys
import os
import traceback

# Add proteinblender to path
addon_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(addon_path, 'proteinblender'))

try:
    from utils.molecularnodes import load
    from core.molecule_wrapper import MoleculeWrapper
    from data.domain_definition import DomainDefinition
    print("✅ Imports successful")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

def test_alpha_carbon_detection():
    """Test alpha carbon detection"""
    print("Testing alpha carbon detection...")
    
    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Import protein
    mol = load.molecule_rcsb("3b75")
    if not mol:
        print("❌ Failed to import protein")
        return False
    
    print(f"✅ Imported protein: {mol.name}")
    
    # Analyze attributes
    if hasattr(mol.data, 'attributes'):
        attrs = mol.data.attributes
        print(f"📊 Attributes: {list(attrs.keys())}")
        
        # Check alpha carbon attribute
        if 'is_alpha_carbon' in attrs:
            is_alpha_data = attrs['is_alpha_carbon'].data
            alpha_count = sum(1 for item in is_alpha_data if item.value)
            print(f"✅ Alpha carbons found: {alpha_count}")
            return alpha_count > 0
        else:
            print("❌ No is_alpha_carbon attribute found")
            return False
    else:
        print("❌ No attributes found")
        return False

if __name__ == "__main__":
    success = test_alpha_carbon_detection()
    print("✅ Test passed" if success else "❌ Test failed") 