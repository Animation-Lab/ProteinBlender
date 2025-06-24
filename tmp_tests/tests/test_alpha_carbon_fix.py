#!/usr/bin/env python3
"""
Test the alpha carbon detection fix.
This will import a protein and test the improved chain mapping logic.
"""

import bpy
import sys
import os

# Add proteinblender to path
addon_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(addon_path, 'proteinblender'))

def test_alpha_carbon_fix():
    """Test the alpha carbon detection fix"""
    print("🧪 TESTING ALPHA CARBON DETECTION FIX")
    print("=" * 60)
    
    try:
        from utils.molecularnodes import load
        from core.molecule_wrapper import MoleculeWrapper
        from data.domain_definition import DomainDefinition
        
        # Clear scene
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        
        # Import test protein
        print("📥 Importing protein 3b75...")
        mol = load.molecule_rcsb("3b75")
        if not mol:
            print("❌ Failed to import protein")
            return False
        
        print(f"✅ Imported protein: {mol.name}")
        
        # Check basic attributes
        if hasattr(mol.data, 'attributes'):
            attrs = mol.data.attributes
            print(f"📊 Found {len(attrs)} attributes")
            
            # Check for alpha carbon detection
            if 'is_alpha_carbon' in attrs:
                alpha_data = attrs['is_alpha_carbon'].data
                alpha_count = sum(1 for item in alpha_data if item.value)
                print(f"✅ {alpha_count} alpha carbons detected in molecule")
                
                if alpha_count == 0:
                    print("❌ No alpha carbons detected - this indicates an issue with MolecularNodes")
                    return False
            else:
                print("❌ No is_alpha_carbon attribute - this indicates an issue with MolecularNodes")
                return False
            
            # Check chain mapping
            if hasattr(mol, 'keys') and 'chain_ids' in mol.keys():
                chain_mapping = mol['chain_ids']
                print(f"🔗 Chain mapping: {chain_mapping}")
            else:
                print("⚠️  No custom chain mapping found")
            
            # Test with MoleculeWrapper
            print("\n🧪 Testing MoleculeWrapper alpha carbon detection...")
            
            class MockMol:
                def __init__(self, obj):
                    self.object = obj
                    self.name = obj.name
            
            wrapper = MoleculeWrapper(MockMol(mol), "test")
            
            # Test with different chain representations that might be in the data
            test_chains = ["T", "9"]  # Based on the original error
            
            for chain_id in test_chains:
                print(f"\n   Testing chain '{chain_id}':")
                
                domain = DomainDefinition(
                    id=f"test_domain_{chain_id}",
                    chain_id=chain_id,
                    start=1,
                    end=10,  # Test with smaller range first
                    name=f"Test Domain {chain_id}",
                    parent_domain_id=None
                )
                
                # Test START position
                start_pos = wrapper._find_residue_alpha_carbon_pos(bpy.context, domain, 'START')
                if start_pos:
                    print(f"   ✅ Found START alpha carbon for chain '{chain_id}': {start_pos}")
                    return True  # Success if we find any alpha carbon
                else:
                    print(f"   ❌ No START alpha carbon found for chain '{chain_id}'")
            
            print("\n❌ Failed to find alpha carbons with any chain ID")
            return False
            
        else:
            print("❌ No attributes found on imported molecule")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_alpha_carbon_fix()
    if success:
        print("\n🎉 TEST PASSED! Alpha carbon detection is working!")
    else:
        print("\n💥 TEST FAILED! Alpha carbon detection still has issues.")
    
    exit(0 if success else 1) 