#!/usr/bin/env python3
"""
Targeted Investigation of Chain Issue
This script focuses on identifying the specific problem mentioned by the user.
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

def investigate_chain_characteristics(file_path, protein_name):
    """Investigate specific chain characteristics that might cause issues"""
    print(f"\n{'='*50}")
    print(f"INVESTIGATING {protein_name.upper()}")
    print(f"{'='*50}")
    
    arr = load_structure(file_path)
    if isinstance(arr, AtomArrayStack):
        working_array = arr[0]
    else:
        working_array = arr
    
    chain_ids = working_array.chain_id
    unique_chains = np.unique(chain_ids)
    
    print(f"Total chains: {len(unique_chains)}")
    print(f"Chain labels: {unique_chains}")
    
    # Key investigation points based on the codebase analysis
    problems_found = []
    
    # 1. Check for problematic chain characteristics
    print(f"\n--- CHAIN CHARACTERISTICS ---")
    
    for i, chain in enumerate(unique_chains):
        chain_mask = (chain_ids == chain)
        chain_atoms = np.sum(chain_mask)
        
        # Check for very small chains (like ligands or single atoms)
        if chain_atoms < 10:
            problems_found.append(f"Chain '{chain}' has only {chain_atoms} atoms (likely ligand/small molecule)")
            print(f"⚠️  Chain '{chain}': {chain_atoms} atoms (VERY SMALL - likely ligand)")
        else:
            print(f"✓  Chain '{chain}': {chain_atoms} atoms")
            
        # Check alpha carbon content
        if hasattr(working_array, 'atom_name'):
            ca_mask = (working_array.atom_name == 'CA') & chain_mask & (~working_array.hetero)
            ca_count = np.sum(ca_mask)
            
            if ca_count == 0:
                problems_found.append(f"Chain '{chain}' has NO alpha carbons (not a protein chain)")
                print(f"⚠️  Chain '{chain}': NO alpha carbons - not a protein chain")
            elif ca_count < 10:
                problems_found.append(f"Chain '{chain}' has only {ca_count} alpha carbons (very short)")
                print(f"⚠️  Chain '{chain}': {ca_count} alpha carbons (very short)")
            else:
                print(f"✓  Chain '{chain}': {ca_count} alpha carbons")
                
        # Check residue types
        if hasattr(working_array, 'res_name'):
            chain_res_names = working_array.res_name[chain_mask]
            unique_res = np.unique(chain_res_names)
            protein_res = [res for res in unique_res if res in ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLU', 'GLN', 'GLY', 'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL']]
            
            if len(protein_res) == 0:
                problems_found.append(f"Chain '{chain}' contains NO standard amino acids")
                print(f"⚠️  Chain '{chain}': NO standard amino acids - residues: {unique_res[:5]}...")
            else:
                print(f"✓  Chain '{chain}': {len(protein_res)} standard amino acid types")
    
    # 2. Check specific issues that might affect the addon
    print(f"\n--- POTENTIAL ADDON ISSUES ---")
    
    # Check if chain labeling follows expected patterns
    non_standard_chains = [ch for ch in unique_chains if not ch.isalpha() or len(ch) != 1]
    if non_standard_chains:
        problems_found.append(f"Non-standard chain labels found: {non_standard_chains}")
        print(f"⚠️  Non-standard chain labels: {non_standard_chains}")
    
    # Check for very uneven chain sizes that might confuse UI
    chain_sizes = []
    for chain in unique_chains:
        chain_mask = (chain_ids == chain)
        chain_sizes.append(np.sum(chain_mask))
    
    max_size = max(chain_sizes)
    min_size = min(chain_sizes)
    
    if max_size / min_size > 100:  # Very uneven
        problems_found.append(f"Extremely uneven chain sizes: largest={max_size}, smallest={min_size}")
        print(f"⚠️  Very uneven chain sizes: {max_size} vs {min_size}")
    
    # 3. Check residue numbering issues
    print(f"\n--- RESIDUE NUMBERING ISSUES ---")
    
    if hasattr(working_array, 'res_id'):
        for chain in unique_chains:
            chain_mask = (chain_ids == chain)
            chain_res_ids = working_array.res_id[chain_mask]
            
            if len(chain_res_ids) > 0:
                min_res = np.min(chain_res_ids)
                max_res = np.max(chain_res_ids)
                unique_res_count = len(np.unique(chain_res_ids))
                
                # Check for zero-based indexing (problematic for some systems)
                if min_res == 0:
                    problems_found.append(f"Chain '{chain}' uses 0-based residue numbering")
                    print(f"⚠️  Chain '{chain}': starts at residue 0 (0-based indexing)")
                
                # Check for large gaps
                expected_count = max_res - min_res + 1
                if unique_res_count < expected_count * 0.8:  # Missing >20% of residues
                    problems_found.append(f"Chain '{chain}' has large gaps in residue numbering")
                    print(f"⚠️  Chain '{chain}': large gaps in numbering ({unique_res_count}/{expected_count})")
    
    return {
        'protein_name': protein_name,
        'chain_count': len(unique_chains),
        'chains': unique_chains,
        'problems_found': problems_found,
        'working_array': working_array
    }

def compare_and_diagnose(result_1atn, result_3b75):
    """Compare results and diagnose potential issues"""
    print(f"\n{'='*60}")
    print("ISSUE DIAGNOSIS")
    print(f"{'='*60}")
    
    print(f"1ATN problems found: {len(result_1atn['problems_found'])}")
    for problem in result_1atn['problems_found']:
        print(f"  - {problem}")
    
    print(f"\n3B75 problems found: {len(result_3b75['problems_found'])}")
    for problem in result_3b75['problems_found']:
        print(f"  - {problem}")
    
    print(f"\n--- DIAGNOSIS ---")
    
    # Check if the issue pattern matches what the user described
    if len(result_1atn['problems_found']) > len(result_3b75['problems_found']):
        print("✓ 1ATN has more structural issues than 3B75, which matches user's report")
        print("  (User said 3B75 works, 1ATN doesn't)")
    elif len(result_3b75['problems_found']) > len(result_1atn['problems_found']):
        print("? 3B75 has more structural issues than 1ATN")
        print("  This contradicts user's report - need to investigate further")
    
    # Specific issue analysis
    print(f"\n--- KEY DIFFERENCES ---")
    
    # Check for the issues that would most likely affect the addon
    ligand_chains_1atn = [p for p in result_1atn['problems_found'] if 'atoms (likely ligand' in p or 'NO alpha carbons' in p]
    ligand_chains_3b75 = [p for p in result_3b75['problems_found'] if 'atoms (likely ligand' in p or 'NO alpha carbons' in p]
    
    print(f"1ATN non-protein chains: {len(ligand_chains_1atn)}")
    print(f"3B75 non-protein chains: {len(ligand_chains_3b75)}")
    
    zero_indexing_1atn = [p for p in result_1atn['problems_found'] if '0-based indexing' in p]
    zero_indexing_3b75 = [p for p in result_3b75['problems_found'] if '0-based indexing' in p]
    
    if zero_indexing_1atn and not zero_indexing_3b75:
        print("\n🎯 LIKELY ISSUE FOUND:")
        print("   1ATN uses 0-based residue indexing, 3B75 uses 1-based")
        print("   This could cause issues in domain creation logic!")
    
    return {
        'likely_issue': 'zero_indexing' if zero_indexing_1atn and not zero_indexing_3b75 else 'unknown',
        'ligand_chain_difference': len(ligand_chains_1atn) - len(ligand_chains_3b75)
    }

def investigate_molecule_wrapper_impact(result):
    """Investigate how these issues would impact MoleculeWrapper"""
    print(f"\n--- MOLECULE_WRAPPER IMPACT FOR {result['protein_name'].upper()} ---")
    
    working_array = result['working_array']
    
    # Simulate the chain_residue_ranges creation with more detail
    print("Simulating _get_chain_residue_ranges logic...")
    
    chain_ids = working_array.chain_id
    unique_chain_ids, int_indices = np.unique(chain_ids, return_inverse=True)
    
    # Simulate the idx_to_label_asym_id_map
    idx_to_label_map = {}
    for i, label_id_str in enumerate(unique_chain_ids):
        idx_to_label_map[i] = str(label_id_str)
    
    print(f"Chain mapping: {idx_to_label_map}")
    
    ranges = {}
    if hasattr(working_array, 'res_id'):
        res_ids = working_array.res_id
        unique_int_chain_keys = np.unique(int_indices)
        
        for int_chain_key in unique_int_chain_keys:
            label_asym_id = idx_to_label_map.get(int(int_chain_key))
            
            mask = (int_indices == int_chain_key)
            chain_res_ids = res_ids[mask]
            
            if chain_res_ids.size > 0:
                min_res, max_res = int(np.min(chain_res_ids)), int(np.max(chain_res_ids))
                ranges[label_asym_id] = (min_res, max_res)
                
                # Check for issues that would affect domain creation
                if min_res == 0:
                    print(f"⚠️  Chain '{label_asym_id}': range starts at 0 - potential issue with domain bounds!")
                    
                if max_res - min_res > 1000:
                    print(f"⚠️  Chain '{label_asym_id}': very large range ({min_res}-{max_res})")
                
                if max_res - min_res < 5:
                    print(f"⚠️  Chain '{label_asym_id}': very small range ({min_res}-{max_res}) - likely ligand")
    
    print(f"Final ranges: {ranges}")
    return ranges

def main():
    """Main investigation function"""
    test_dir = Path("test_proteins")
    
    pdb_1atn = test_dir / "1ATN.pdb"
    pdb_3b75 = test_dir / "3b75.pdb"
    
    if not pdb_1atn.exists() or not pdb_3b75.exists():
        print("PDB files not found!")
        return
    
    # Investigate both proteins
    result_1atn = investigate_chain_characteristics(pdb_1atn, "1ATN")
    result_3b75 = investigate_chain_characteristics(pdb_3b75, "3B75")
    
    # Compare and diagnose
    diagnosis = compare_and_diagnose(result_1atn, result_3b75)
    
    # Investigate MoleculeWrapper impact
    ranges_1atn = investigate_molecule_wrapper_impact(result_1atn)
    ranges_3b75 = investigate_molecule_wrapper_impact(result_3b75)
    
    print(f"\n{'='*60}")
    print("FINAL RECOMMENDATIONS")
    print(f"{'='*60}")
    
    if diagnosis['likely_issue'] == 'zero_indexing':
        print("🎯 LIKELY ROOT CAUSE: Zero-based vs One-based residue indexing")
        print("\nRECOMMENDED FIXES:")
        print("1. Update _get_chain_residue_ranges to handle 0-based indexing")
        print("2. Adjust domain creation logic to handle residue 0")
        print("3. Add validation in _create_domain_with_params for min_res == 0")
    
    elif diagnosis['ligand_chain_difference'] > 0:
        print("🎯 LIKELY ROOT CAUSE: 1ATN has more non-protein chains")
        print("\nRECOMMENDED FIXES:")
        print("1. Filter out non-protein chains in domain creation")
        print("2. Add validation for minimum chain size")
        print("3. Check for alpha carbon presence before creating domains")
    
    else:
        print("❓ Issue not clearly identified from structure analysis")
        print("Further investigation needed in actual addon behavior")
        
    print(f"\nStructural differences:")
    print(f"- 1ATN: {result_1atn['chain_count']} chains, {len(result_1atn['problems_found'])} issues")
    print(f"- 3B75: {result_3b75['chain_count']} chains, {len(result_3b75['problems_found'])} issues")

if __name__ == "__main__":
    main() 