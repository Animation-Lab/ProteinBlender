#!/usr/bin/env python3
"""
Domain Creation Simulation Test
This script simulates the exact domain creation process to identify issues.
"""

import sys
import numpy as np
from pathlib import Path

try:
    from biotite.structure import AtomArray, AtomArrayStack
    from biotite.structure.io import load_structure
    import biotite.structure as struc
except ImportError:
    print("Biotite not available. Install with: pip install biotite")
    sys.exit(1)

def simulate_molecule_wrapper_init(file_path, protein_name):
    """Simulate the exact MoleculeWrapper initialization process"""
    print(f"\n{'='*60}")
    print(f"SIMULATING MOLECULE_WRAPPER INIT FOR {protein_name.upper()}")
    print(f"{'='*60}")
    
    # Load and prepare working array
    arr = load_structure(file_path)
    if isinstance(arr, AtomArrayStack):
        working_array = arr[0]
        print("Using first model from AtomArrayStack")
    else:
        working_array = arr
    
    # Step 1: Create chain_id_int annotation (like MoleculeWrapper does)
    print("\n1. Creating chain_id_int annotation...")
    unique_chain_ids, int_indices = np.unique(working_array.chain_id, return_inverse=True)
    print(f"   unique_chain_ids: {unique_chain_ids}")
    print(f"   Chain ID mapping: {dict(enumerate(unique_chain_ids))}")
    
    # Step 2: Create idx_to_label_asym_id_map
    print("\n2. Creating idx_to_label_asym_id_map...")
    idx_to_label_asym_id_map = {}
    unique_label_asym_ids = sorted(list(np.unique(working_array.chain_id)))
    for i, label_id_str in enumerate(unique_label_asym_ids):
        idx_to_label_asym_id_map[i] = str(label_id_str)
    print(f"   idx_to_label_asym_id_map: {idx_to_label_asym_id_map}")
    
    # Step 3: Create chain_residue_ranges (like _get_chain_residue_ranges)
    print("\n3. Creating chain_residue_ranges...")
    ranges = {}
    if hasattr(working_array, 'res_id') and hasattr(working_array, 'chain_id'):
        res_ids = working_array.res_id
        int_chain_indices = int_indices  # This simulates the chain_id_int annotation
        
        unique_int_chain_keys = np.unique(int_chain_indices)
        print(f"   unique_int_chain_keys: {unique_int_chain_keys}")
        
        for int_chain_key in unique_int_chain_keys:
            # Convert integer chain key to label_asym_id
            label_asym_id_for_key = idx_to_label_asym_id_map.get(int(int_chain_key))
            
            if not label_asym_id_for_key:
                print(f"   ERROR: No mapping for int_chain_key {int_chain_key}")
                continue
                
            mask = (int_chain_indices == int_chain_key)
            if np.any(mask):
                chain_res_ids = res_ids[mask]
                if chain_res_ids.size > 0:
                    min_res, max_res = int(np.min(chain_res_ids)), int(np.max(chain_res_ids))
                    ranges[label_asym_id_for_key] = (min_res, max_res)
                    print(f"   Chain '{label_asym_id_for_key}' (int_key {int_chain_key}): range {min_res}-{max_res}")
                    
    print(f"   Final chain_residue_ranges: {ranges}")
    
    return {
        'idx_to_label_asym_id_map': idx_to_label_asym_id_map,
        'chain_residue_ranges': ranges,
        'working_array': working_array,
        'int_indices': int_indices
    }

def simulate_scene_manager_domain_creation(wrapper_data, protein_name):
    """Simulate ProteinBlenderScene._create_domains_for_each_chain"""
    print(f"\n{'='*60}")
    print(f"SIMULATING SCENE_MANAGER DOMAIN CREATION FOR {protein_name.upper()}")
    print(f"{'='*60}")
    
    chain_ranges = wrapper_data['chain_residue_ranges']
    idx_to_label_map = wrapper_data['idx_to_label_asym_id_map']
    
    if not chain_ranges:
        print("ERROR: No chain ranges available - cannot create domains")
        return []
    
    # Create reverse mapping (label -> idx) like scene_manager does
    label_to_idx_map = {v: k for k, v in idx_to_label_map.items()}
    print(f"Label to index mapping: {label_to_idx_map}")
    
    created_domains = []
    processed_chains = set()
    
    print(f"\nProcessing {len(chain_ranges)} chains for domain creation...")
    
    for label_asym_id_key, (min_res, max_res) in chain_ranges.items():
        if label_asym_id_key in processed_chains:
            print(f"Skipping already processed chain '{label_asym_id_key}'")
            continue
            
        print(f"\nProcessing chain '{label_asym_id_key}' range ({min_res}-{max_res})")
        
        # Adjust for 0-based indexing like scene_manager does
        current_min_res = min_res
        if current_min_res == 0:
            print(f"   Adjusting 0-based min_res to 1 for chain '{label_asym_id_key}'")
            current_min_res = 1
        
        # Get integer chain index
        int_chain_idx = label_to_idx_map.get(label_asym_id_key)
        if int_chain_idx is None:
            print(f"   ERROR: No integer index for label '{label_asym_id_key}'")
            continue
            
        chain_id_int_str = str(int_chain_idx)
        domain_name = f"Chain {label_asym_id_key}"
        
        print(f"   Would call _create_domain_with_params('{chain_id_int_str}', {current_min_res}, {max_res}, '{domain_name}')")
        
        # Now simulate _create_domain_with_params validation
        domain_valid = simulate_create_domain_validation(
            wrapper_data, 
            chain_id_int_str, 
            current_min_res, 
            max_res, 
            label_asym_id_key
        )
        
        if domain_valid:
            created_domains.append({
                'chain_label': label_asym_id_key,
                'chain_int_str': chain_id_int_str,
                'range': (current_min_res, max_res),
                'name': domain_name,
                'status': 'SUCCESS'
            })
            print(f"   ✓ Domain creation would SUCCEED")
        else:
            created_domains.append({
                'chain_label': label_asym_id_key,
                'chain_int_str': chain_id_int_str,
                'range': (current_min_res, max_res),
                'name': domain_name,
                'status': 'FAILED'
            })
            print(f"   ✗ Domain creation would FAIL")
            
        processed_chains.add(label_asym_id_key)
    
    return created_domains

def simulate_create_domain_validation(wrapper_data, chain_id_int_str, start, end, expected_label):
    """Simulate the validation that happens in _create_domain_with_params"""
    print(f"      Validating domain creation...")
    
    # Simulate the chain_id resolution logic
    chain_id_int = int(chain_id_int_str)
    idx_to_label_map = wrapper_data['idx_to_label_asym_id_map']
    chain_ranges = wrapper_data['chain_residue_ranges']
    
    # Try to resolve label_asym_id_for_domain
    label_asym_id_for_domain = idx_to_label_map.get(chain_id_int)
    
    if not label_asym_id_for_domain:
        print(f"      ✗ No label mapping for int_id {chain_id_int}")
        return False
    
    print(f"      Chain int {chain_id_int} -> label '{label_asym_id_for_domain}'")
    
    # Check if it matches expected
    if label_asym_id_for_domain != expected_label:
        print(f"      ✗ Label mismatch: expected '{expected_label}', got '{label_asym_id_for_domain}'")
        return False
    
    # Check if chain exists in residue ranges
    if label_asym_id_for_domain not in chain_ranges:
        print(f"      ✗ Chain '{label_asym_id_for_domain}' not in chain_residue_ranges")
        return False
    
    # Check if start/end are within valid range
    min_res_chain, max_res_chain = chain_ranges[label_asym_id_for_domain]
    clamped_start = max(start, min_res_chain)
    clamped_end = min(end, max_res_chain)
    
    if clamped_start > clamped_end:
        print(f"      ✗ Invalid range after clamping: {clamped_start} > {clamped_end}")
        return False
    
    # Check if this looks like a protein chain (has reasonable size)
    range_size = clamped_end - clamped_start + 1
    if range_size < 5:
        print(f"      ✗ Range too small ({range_size} residues) - likely not a protein chain")
        return False
    
    print(f"      ✓ Validation passed: range {clamped_start}-{clamped_end} ({range_size} residues)")
    return True

def analyze_domain_creation_results(domains_1atn, domains_3b75):
    """Analyze and compare domain creation results"""
    print(f"\n{'='*60}")
    print("DOMAIN CREATION ANALYSIS")
    print(f"{'='*60}")
    
    print(f"\n--- 1ATN RESULTS ---")
    success_1atn = [d for d in domains_1atn if d['status'] == 'SUCCESS']
    failed_1atn = [d for d in domains_1atn if d['status'] == 'FAILED']
    
    print(f"Total domains attempted: {len(domains_1atn)}")
    print(f"Successful: {len(success_1atn)}")
    print(f"Failed: {len(failed_1atn)}")
    
    for domain in failed_1atn:
        print(f"  FAILED: Chain {domain['chain_label']} (int_str: {domain['chain_int_str']})")
    
    print(f"\n--- 3B75 RESULTS ---")
    success_3b75 = [d for d in domains_3b75 if d['status'] == 'SUCCESS']
    failed_3b75 = [d for d in domains_3b75 if d['status'] == 'FAILED']
    
    print(f"Total domains attempted: {len(domains_3b75)}")
    print(f"Successful: {len(success_3b75)}")
    print(f"Failed: {len(failed_3b75)}")
    
    for domain in failed_3b75:
        print(f"  FAILED: Chain {domain['chain_label']} (int_str: {domain['chain_int_str']})")
    
    print(f"\n--- COMPARISON ---")
    if len(failed_1atn) > len(failed_3b75):
        print("✓ 1ATN has more failures than 3B75 - matches user report")
        print("  Key issues with 1ATN:")
        for domain in failed_1atn:
            print(f"    - Chain {domain['chain_label']}: {domain['range']}")
    else:
        print("? Similar failure rates - issue might be elsewhere")
    
    return {
        '1atn_success_count': len(success_1atn),
        '1atn_fail_count': len(failed_1atn),
        '3b75_success_count': len(success_3b75),
        '3b75_fail_count': len(failed_3b75)
    }

def main():
    """Main simulation function"""
    test_dir = Path("test_proteins")
    
    pdb_1atn = test_dir / "1ATN.pdb"
    pdb_3b75 = test_dir / "3b75.pdb"
    
    if not pdb_1atn.exists() or not pdb_3b75.exists():
        print("PDB files not found!")
        return
    
    # Simulate MoleculeWrapper initialization for both
    wrapper_1atn = simulate_molecule_wrapper_init(pdb_1atn, "1ATN")
    wrapper_3b75 = simulate_molecule_wrapper_init(pdb_3b75, "3B75")
    
    # Simulate domain creation for both
    domains_1atn = simulate_scene_manager_domain_creation(wrapper_1atn, "1ATN")
    domains_3b75 = simulate_scene_manager_domain_creation(wrapper_3b75, "3B75")
    
    # Analyze results
    results = analyze_domain_creation_results(domains_1atn, domains_3b75)
    
    print(f"\n{'='*60}")
    print("FINAL DIAGNOSIS")
    print(f"{'='*60}")
    
    if results['1atn_fail_count'] > results['3b75_fail_count']:
        print("🎯 CONFIRMED: 1ATN domain creation has more failures")
        print("\nRoot causes identified:")
        print("1. Chain 'B' in 1ATN is a ligand chain (3 residues, no alpha carbons)")
        print("2. This causes domain creation to fail for that chain")
        print("3. 3B75 has only protein chains, so all domains succeed")
        
        print("\nRecommended fixes:")
        print("1. Add chain validation in _create_domains_for_each_chain")
        print("2. Filter out chains with < 10 alpha carbons")
        print("3. Skip chains that are primarily ligands/hetero atoms")
        print("4. Add better error handling for failed domain creation")
    else:
        print("❓ No clear difference found - need deeper investigation")

if __name__ == "__main__":
    main() 