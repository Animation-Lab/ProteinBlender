#!/usr/bin/env python3
"""
Diagnostic test to examine chain mapping issues in alpha carbon detection.
This test will help us understand the exact chain ID mapping problem.
"""

import sys
import os

# Add proteinblender to path
addon_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(addon_path, 'proteinblender'))

def examine_chain_mapping_issue():
    """Examine the chain mapping issue causing alpha carbon detection to fail"""
    
    print("🔍 EXAMINING CHAIN MAPPING ISSUE")
    print("=" * 60)
    
    # Let's examine the error from the log:
    # The system is trying to resolve chain '9' to label 'T'
    # But then searching for residues in that chain fails
    
    # First, let's create a simple test that doesn't require PDB download
    # Instead, let's examine the chain mapping logic directly
    
    # Test the get_possible_chain_ids helper function logic
    def test_get_possible_chain_ids():
        """Test the chain ID resolution logic"""
        print("\n🧪 Testing get_possible_chain_ids logic...")
        
        def get_possible_chain_ids(chain_id):
            """Replicated logic from molecule_wrapper.py"""
            search_ids = [chain_id]
            if isinstance(chain_id, str) and chain_id.isalpha():
                try:
                    numeric_chain = ord(chain_id.upper()) - ord('A')
                    search_ids.append(numeric_chain)
                except Exception: pass
            elif isinstance(chain_id, (str, int)) and str(chain_id).isdigit():
                try:
                    int_chain_id = int(chain_id)
                    alpha_chain = chr(int_chain_id + ord('A'))
                    search_ids.append(alpha_chain)
                    search_ids.append(int_chain_id)
                    search_ids.append(str(int_chain_id))
                except Exception: pass
            return list(set(filter(None.__ne__, search_ids)))
        
        # Test cases based on the error log
        test_cases = [
            ("T", "Testing chain T (from error log)"),
            ("9", "Testing chain 9 (from error log)"), 
            (9, "Testing numeric chain 9"),
            ("A", "Testing chain A"),
            ("0", "Testing chain 0"),
            (0, "Testing numeric chain 0")
        ]
        
        for chain_id, description in test_cases:
            result = get_possible_chain_ids(chain_id)
            print(f"   {description}: {chain_id} -> {result}")
        
        # The issue might be here - let's see what '9' resolves to
        chain_9_result = get_possible_chain_ids("9")
        print(f"\n   🚨 Key finding: Chain '9' resolves to: {chain_9_result}")
        
        # And what 'T' resolves to
        chain_T_result = get_possible_chain_ids("T")
        print(f"   🚨 Key finding: Chain 'T' resolves to: {chain_T_result}")
        
        # Check if they have any overlap
        overlap = set(chain_9_result) & set(chain_T_result)
        print(f"   🔍 Overlap between '9' and 'T' chains: {overlap}")
        
        return chain_9_result, chain_T_result
    
    def analyze_chain_id_conversion():
        """Analyze the chain ID conversion that might be causing issues"""
        print("\n🧪 Analyzing chain ID conversions...")
        
        # From the error: "DEBUG: Resolved '9' as numeric_idx -> label 'T'."
        # This suggests: numeric index 9 corresponds to label 'T'
        
        # Let's check what ord('T') - ord('A') gives us
        T_numeric = ord('T') - ord('A')
        print(f"   ord('T') - ord('A') = {T_numeric}")
        
        # So 'T' is the 19th letter (index 19)
        # But the error shows '9' -> 'T', which suggests a different mapping system
        
        # Let's check if there's an off-by-one error or different indexing
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        print(f"   Letter at index 9: {alphabet[9]} (0-based indexing)")
        print(f"   Letter at index 19: {alphabet[19]} (0-based indexing)")
        print(f"   Position of 'T' in alphabet: {alphabet.index('T')} (0-based)")
        
        # The issue might be that the system is using a different mapping
        # Let's simulate what the actual protein data might look like
        
        return T_numeric
    
    def simulate_attribute_matching():
        """Simulate how the attribute matching might be failing"""
        print("\n🧪 Simulating attribute matching logic...")
        
        # From the error log, the search is looking for:
        # - Chain ID that matches some conversion of '9' or 'T' 
        # - Residues 1-251
        # - Alpha carbon atoms
        
        # The problem might be that:
        # 1. Data has chain IDs as numbers (0, 1, 2, etc.)
        # 2. Domain is defined with chain_id="T" 
        # 3. Conversion logic tries to map "T" to a number
        # 4. But the mapping is wrong or the data doesn't match
        
        print("   🔍 Potential issue scenarios:")
        print("   1. Data uses chain_id=9, domain uses chain_id='T', mapping fails")
        print("   2. Data uses chain_id='T', domain uses chain_id=9, mapping fails") 
        print("   3. Custom chain mapping is incorrect or missing")
        print("   4. Search logic doesn't account for all possible representations")
        
        # Let's check what the search_chain_ids_str would look like
        def simulate_search_logic(domain_chain_id):
            """Simulate the search logic from the actual code"""
            
            # Replicate get_possible_chain_ids
            def get_possible_chain_ids(chain_id):
                search_ids = [chain_id]
                if isinstance(chain_id, str) and chain_id.isalpha():
                    try:
                        numeric_chain = ord(chain_id.upper()) - ord('A')
                        search_ids.append(numeric_chain)
                    except Exception: pass
                elif isinstance(chain_id, (str, int)) and str(chain_id).isdigit():
                    try:
                        int_chain_id = int(chain_id)
                        alpha_chain = chr(int_chain_id + ord('A'))
                        search_ids.append(alpha_chain)
                        search_ids.append(int_chain_id)
                        search_ids.append(str(int_chain_id))
                    except Exception: pass
                return list(set(filter(None.__ne__, search_ids)))
            
            search_chain_ids = get_possible_chain_ids(domain_chain_id)
            search_chain_ids_str = [str(s) for s in search_chain_ids]
            
            print(f"      Domain chain_id '{domain_chain_id}' -> search IDs: {search_chain_ids}")
            print(f"      String versions for matching: {search_chain_ids_str}")
            
            return search_chain_ids_str
        
        # Test with the failing case
        print("   Testing with domain_chain_id='T':")
        t_search = simulate_search_logic("T")
        
        print("   Testing with domain_chain_id='9':")
        nine_search = simulate_search_logic("9")
        
        print("   Testing with domain_chain_id=9:")
        numeric_nine_search = simulate_search_logic(9)
        
        return t_search, nine_search, numeric_nine_search
    
    # Run all tests
    chain_results = test_get_possible_chain_ids()
    numeric_result = analyze_chain_id_conversion()
    search_results = simulate_attribute_matching()
    
    print("\n" + "=" * 60)
    print("📊 DIAGNOSTIC SUMMARY")
    print("=" * 60)
    
    print("\n🔍 Key Findings:")
    print("1. Chain ID mapping logic seems correct in isolation")
    print("2. The issue is likely in the data vs. domain definition mismatch")
    print("3. Need to examine actual protein data to see what chain IDs it contains")
    
    print("\n💡 Recommended Next Steps:")
    print("1. Add debug logging to show what chain IDs exist in the imported protein")
    print("2. Add debug logging to show what chain ID the domain is actually searching for")
    print("3. Add debug logging to show the custom chain mapping (if any)")
    print("4. Ensure the search logic handles all possible chain ID representations")
    
    return True

if __name__ == "__main__":
    try:
        success = examine_chain_mapping_issue()
        print(f"\n{'✅ SUCCESS' if success else '❌ FAILURE'}: Chain mapping analysis completed")
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc() 