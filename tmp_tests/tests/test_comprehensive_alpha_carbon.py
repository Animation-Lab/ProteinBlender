#!/usr/bin/env python3
"""
Comprehensive test for alpha carbon detection.
"""

import bpy
import sys
import os

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

def test_comprehensive_alpha_carbon():
    """Test alpha carbon detection comprehensively"""
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
    
    # Test attributes
    if hasattr(mol.data, 'attributes'):
        attrs = mol.data.attributes
        print(f"📊 Attributes: {list(attrs.keys())}")
        
        # Check alpha carbon detection
        if 'is_alpha_carbon' in attrs:
            alpha_data = attrs['is_alpha_carbon'].data
            alpha_count = sum(1 for item in alpha_data if item.value)
            print(f"✅ Alpha carbons found: {alpha_count}")
            
            if alpha_count > 0:
                # Test MoleculeWrapper
                class MockMol:
                    def __init__(self, obj):
                        self.object = obj
                        self.name = obj.name
                
                wrapper = MoleculeWrapper(MockMol(mol), "test")
                
                domain = DomainDefinition(
                    id="test_domain",
                    chain_id="T",
                    start=1,
                    end=251,
                    name="Test Domain",
                    parent_domain_id=None
                )
                
                start_pos = wrapper._find_residue_alpha_carbon_pos(bpy.context, domain, 'START')
                end_pos = wrapper._find_residue_alpha_carbon_pos(bpy.context, domain, 'END')
                
                print(f"START position: {start_pos}")
                print(f"END position: {end_pos}")
                
                return start_pos is not None or end_pos is not None
            
            return alpha_count > 0
        else:
            print("❌ No is_alpha_carbon attribute")
            return False
    else:
        print("❌ No attributes")
        return False

if __name__ == "__main__":
    success = test_comprehensive_alpha_carbon()
    print("✅ Test passed" if success else "❌ Test failed") 