#!/usr/bin/env python3
"""
Chain Analysis Test Script for ProteinBlender
This script analyzes the differences between 1ATN and 3B75 PDB files
to understand the chain mapping issue.
"""

import sys
import os
import numpy as np
from pathlib import Path

# Add the proteinblender package to path
current_dir = Path(__file__).parent
proteinblender_path = current_dir / "proteinblender"
sys.path.insert(0, str(proteinblender_path))

try:
    from biotite.structure import AtomArray, AtomArrayStack
    from biotite.structure.io import load_structure
    import biotite.structure as struc
    from biotite.structure.io.pdb import PDBFile
except ImportError:
    print("Biotite not available. Install with: pip install biotite")
    sys.exit(1)

def analyze_pdb_structure(file_path, protein_name):
    """Comprehensive analysis of PDB structure"""
    print(f"\n{'='*60}")
    print(f"ANALYZING {protein_name.upper()} ({file_path})")
    print(f"{'='*60}")
    
    try:
        # Load structure
        arr = load_structure(file_path)
        print(f"Structure type: {type(arr)}")
        
        # Handle AtomArrayStack vs AtomArray
        if isinstance(arr, AtomArrayStack):
            print(f"AtomArrayStack with {len(arr)} models")
            working_array = arr[0]  # Use first model
            print("Using first model for analysis")
        else:
            working_array = arr
            
        print(f"Total atoms: {len(working_array)}")
        print(f"Annotation categories: {working_array.get_annotation_categories()}")
        
        # Analyze chains
        print(f"\n--- CHAIN ANALYSIS ---")
        chain_ids = working_array.chain_id
        unique_chains = np.unique(chain_ids)
        print(f"Chain IDs found: {unique_chains}")
        print(f"Number of chains: {len(unique_chains)}")
        
        # Simulate biotite's np.unique mapping (alphabetical sorting)
        unique_sorted, indices = np.unique(chain_ids, return_inverse=True)
        print(f"Sorted unique chains: {unique_sorted}")
        
        # Create chain_id_int mapping like MoleculeWrapper does
        print(f"\nChain ID to Integer mapping (idx_to_label_asym_id_map):")
        idx_to_label_map = {}
        for i, chain_label in enumerate(unique_sorted):
            idx_to_label_map[i] = str(chain_label)
            print(f"  {i} -> '{chain_label}'")
        
        # Check for chain_mapping_str (author chain IDs)
        auth_chain_map = {}
        if hasattr(working_array, 'chain_mapping_str'):
            mapping_str = working_array.chain_mapping_str()
            print(f"\nAuthor chain mapping string: {mapping_str}")
            if isinstance(mapping_str, dict):
                auth_chain_map = mapping_str
            print(f"Author chain map: {auth_chain_map}")
        else:
            print("\nNo chain_mapping_str available")
            
        # Analyze atom types and hetero atoms
        print(f"\n--- ATOM TYPE ANALYSIS ---")
        hetero_atoms = working_array.hetero if hasattr(working_array, 'hetero') else np.zeros(len(working_array), dtype=bool)
        protein_atoms = ~hetero_atoms
        
        print(f"Protein atoms: {np.sum(protein_atoms)}")
        print(f"Hetero atoms: {np.sum(hetero_atoms)}")
        
        if np.sum(hetero_atoms) > 0:
            hetero_res_names = np.unique(working_array.res_name[hetero_atoms])
            print(f"Hetero residue types: {hetero_res_names}")
            
            # Analyze hetero atoms by chain
            print(f"\nHetero atoms by chain:")
            for chain in unique_chains:
                chain_mask = (chain_ids == chain)
                chain_hetero = hetero_atoms & chain_mask
                if np.sum(chain_hetero) > 0:
                    chain_hetero_res = np.unique(working_array.res_name[chain_hetero])
                    print(f"  Chain '{chain}': {np.sum(chain_hetero)} hetero atoms, residues: {chain_hetero_res}")
        
        # Analyze residue ranges per chain
        print(f"\n--- RESIDUE RANGE ANALYSIS ---")
        if hasattr(working_array, 'res_id'):
            for chain in unique_chains:
                chain_mask = (chain_ids == chain)
                chain_res_ids = working_array.res_id[chain_mask]
                if len(chain_res_ids) > 0:
                    min_res, max_res = np.min(chain_res_ids), np.max(chain_res_ids)
                    unique_res = len(np.unique(chain_res_ids))
                    print(f"  Chain '{chain}': residues {min_res}-{max_res} ({unique_res} unique)")
                    
                    # Check for gaps in residue numbering
                    expected_res_count = max_res - min_res + 1
                    if unique_res != expected_res_count:
                        print(f"    WARNING: Expected {expected_res_count} residues, found {unique_res} (gaps present)")
        
        # Analyze entity information
        print(f"\n--- ENTITY ANALYSIS ---")
        if hasattr(working_array, 'entity_id'):
            entity_ids = working_array.entity_id
            unique_entities = np.unique(entity_ids)
            print(f"Entity IDs: {unique_entities}")
            
            for entity in unique_entities:
                entity_mask = (entity_ids == entity)
                entity_chains = np.unique(chain_ids[entity_mask])
                entity_atoms = np.sum(entity_mask)
                print(f"  Entity {entity}: chains {entity_chains}, {entity_atoms} atoms")
        else:
            print("No entity_id annotation found")
            
        # Check for specific atom names (like alpha carbons)
        print(f"\n--- ATOM NAME ANALYSIS ---")
        if hasattr(working_array, 'atom_name'):
            unique_atom_names = np.unique(working_array.atom_name)
            print(f"Unique atom names: {unique_atom_names[:20]}...")  # Show first 20
            
            # Count alpha carbons
            ca_mask = (working_array.atom_name == 'CA') & protein_atoms
            ca_count = np.sum(ca_mask)
            print(f"Alpha carbons (CA): {ca_count}")
            
            # Alpha carbons per chain
            print("Alpha carbons per chain:")
            for chain in unique_chains:
                chain_ca = np.sum((chain_ids == chain) & ca_mask)
                print(f"  Chain '{chain}': {chain_ca} CA atoms")
        
        return {
            'total_atoms': len(working_array),
            'chains': unique_chains,
            'chain_count': len(unique_chains),
            'idx_to_label_map': idx_to_label_map,
            'auth_chain_map': auth_chain_map,
            'protein_atoms': np.sum(protein_atoms),
            'hetero_atoms': np.sum(hetero_atoms),
            'working_array': working_array
        }
        
    except Exception as e:
        print(f"ERROR analyzing {protein_name}: {e}")
        import traceback
        traceback.print_exc()
        return None

def compare_proteins(result_1atn, result_3b75):
    """Compare analysis results between proteins"""
    print(f"\n{'='*60}")
    print("COMPARISON ANALYSIS")
    print(f"{'='*60}")
    
    if not result_1atn or not result_3b75:
        print("Cannot compare - one or both analyses failed")
        return
    
    print(f"1ATN chains: {result_1atn['chains']} ({result_1atn['chain_count']} total)")
    print(f"3B75 chains: {result_3b75['chains']} ({result_3b75['chain_count']} total)")
    
    print(f"\n1ATN atom distribution:")
    print(f"  Protein: {result_1atn['protein_atoms']}, Hetero: {result_1atn['hetero_atoms']}")
    print(f"3B75 atom distribution:")
    print(f"  Protein: {result_3b75['protein_atoms']}, Hetero: {result_3b75['hetero_atoms']}")
    
    print(f"\n1ATN chain mapping: {result_1atn['idx_to_label_map']}")
    print(f"3B75 chain mapping: {result_3b75['idx_to_label_map']}")
    
    print(f"\n1ATN auth mapping: {result_1atn['auth_chain_map']}")
    print(f"3B75 auth mapping: {result_3b75['auth_chain_map']}")

def simulate_molecule_wrapper_creation(result, protein_name):
    """Simulate the chain mapping logic from MoleculeWrapper"""
    print(f"\n--- SIMULATING MOLECULE_WRAPPER FOR {protein_name.upper()} ---")
    
    if not result:
        return
        
    working_array = result['working_array']
    
    # Simulate chain_id_int annotation creation
    print("1. Creating chain_id_int annotation...")
    unique_chain_ids, int_indices = np.unique(working_array.chain_id, return_inverse=True)
    print(f"   Unique chains from np.unique: {unique_chain_ids}")
    print(f"   Integer indices sample: {int_indices[:10]}...")
    
    # Simulate idx_to_label_asym_id_map creation
    print("2. Creating idx_to_label_asym_id_map...")
    idx_to_label_map = {}
    unique_label_asym_ids = sorted(list(np.unique(working_array.chain_id)))
    for i, label_id_str in enumerate(unique_label_asym_ids):
        idx_to_label_map[i] = str(label_id_str)
    print(f"   idx_to_label_asym_id_map: {idx_to_label_map}")
    
    # Simulate chain_residue_ranges creation
    print("3. Creating chain_residue_ranges...")
    ranges = {}
    if hasattr(working_array, 'res_id'):
        res_ids = working_array.res_id
        int_chain_indices = int_indices  # This would be the chain_id_int annotation
        
        unique_int_chain_keys = np.unique(int_chain_indices)
        print(f"   Unique integer chain keys: {unique_int_chain_keys}")
        
        for int_chain_key in unique_int_chain_keys:
            # Convert integer chain key to label_asym_id
            label_asym_id_for_key = idx_to_label_map.get(int(int_chain_key))
            print(f"   Processing int_chain_key: {int_chain_key} -> label: '{label_asym_id_for_key}'")
            
            mask = (int_chain_indices == int_chain_key)
            if np.any(mask):
                chain_res_ids = res_ids[mask]
                if chain_res_ids.size > 0:
                    ranges[label_asym_id_for_key] = (int(np.min(chain_res_ids)), int(np.max(chain_res_ids)))
                    
        print(f"   Final chain_residue_ranges: {ranges}")
        
    return {
        'idx_to_label_map': idx_to_label_map,
        'chain_residue_ranges': ranges,
        'unique_int_chain_keys': unique_int_chain_keys.tolist()
    }

def simulate_domain_creation(wrapper_sim, protein_name):
    """Simulate the domain creation process from ProteinBlenderScene"""
    print(f"\n--- SIMULATING DOMAIN CREATION FOR {protein_name.upper()} ---")
    
    if not wrapper_sim or not wrapper_sim['chain_residue_ranges']:
        print("Cannot simulate - no chain ranges available")
        return
        
    chain_ranges = wrapper_sim['chain_residue_ranges']
    idx_to_label_map = wrapper_sim['idx_to_label_map']
    
    # Create reverse mapping (label -> idx)
    label_to_idx_map = {v: k for k, v in idx_to_label_map.items()}
    print(f"Label to index mapping: {label_to_idx_map}")
    
    print("Simulating _create_domains_for_each_chain...")
    created_domains = []
    
    for label_asym_id_key, (min_res, max_res) in chain_ranges.items():
        print(f"\nProcessing chain '{label_asym_id_key}' range ({min_res}-{max_res})")
        
        # Get corresponding integer chain index
        int_chain_idx = label_to_idx_map.get(label_asym_id_key)
        if int_chain_idx is None:
            print(f"   ERROR: No integer index found for label '{label_asym_id_key}'")
            continue
            
        chain_id_int_str = str(int_chain_idx)
        domain_name = f"Chain {label_asym_id_key}"
        
        print(f"   Would call _create_domain_with_params('{chain_id_int_str}', {min_res}, {max_res}, '{domain_name}')")
        
        # Simulate the domain creation logic
        domain_id = f"protein_{label_asym_id_key}_{min_res}_{max_res}_domain"
        created_domains.append({
            'domain_id': domain_id,
            'chain_label': label_asym_id_key,
            'chain_int_str': chain_id_int_str,
            'range': (min_res, max_res),
            'name': domain_name
        })
        
    print(f"\nTotal domains that would be created: {len(created_domains)}")
    for domain in created_domains:
        print(f"   {domain}")
        
    return created_domains

def main():
    """Main analysis function"""
    test_dir = Path("test_proteins")
    if not test_dir.exists():
        print(f"Test directory {test_dir} not found!")
        return
        
    pdb_1atn = test_dir / "1ATN.pdb"
    pdb_3b75 = test_dir / "3b75.pdb"
    
    if not pdb_1atn.exists():
        print(f"1ATN.pdb not found in {test_dir}")
        return
    if not pdb_3b75.exists():
        print(f"3b75.pdb not found in {test_dir}")
        return
    
    # Analyze both proteins
    result_1atn = analyze_pdb_structure(pdb_1atn, "1ATN")
    result_3b75 = analyze_pdb_structure(pdb_3b75, "3B75")
    
    # Compare results
    compare_proteins(result_1atn, result_3b75)
    
    # Simulate MoleculeWrapper creation for both
    wrapper_1atn = simulate_molecule_wrapper_creation(result_1atn, "1ATN")
    wrapper_3b75 = simulate_molecule_wrapper_creation(result_3b75, "3B75")
    
    # Simulate domain creation for both
    domains_1atn = simulate_domain_creation(wrapper_1atn, "1ATN")
    domains_3b75 = simulate_domain_creation(wrapper_3b75, "3B75")
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    if domains_1atn and domains_3b75:
        print(f"1ATN would create {len(domains_1atn)} domains")
        print(f"3B75 would create {len(domains_3b75)} domains")
        
        print("\nKey differences that might cause issues:")
        print("1. Hetero atom distribution")
        print("2. Chain labeling patterns")
        print("3. Residue numbering schemes")
        print("4. Entity organization")

if __name__ == "__main__":
    main() 