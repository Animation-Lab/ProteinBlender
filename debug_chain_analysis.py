#!/usr/bin/env python3

import bpy
import sys
import os

# Add the proteinblender directory to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from proteinblender.utils.molecularnodes.entities import load_local
from proteinblender.core.molecule_wrapper import MoleculeWrapper
import biotite.structure as struc

def analyze_molecule_chains(pdb_path, name):
    print(f"\n{'='*50}")
    print(f"ANALYZING {name}")
    print(f"{'='*50}")
    
    # Load molecule
    mol = load_local(pdb_path)
    wrapper = MoleculeWrapper(mol, name)
    
    # Get biotite array
    arr = getattr(wrapper, 'working_array', None)
    if arr is None:
        print("No working array found")
        return
    
    # Get unique chains
    chain_ids = getattr(arr, 'chain_id_int', None)
    if chain_ids is None:
        print("No chain_id_int found")
        return
        
    unique_chains = set(chain_ids)
    
    # Peptide mask
    peptide_mask = struc.filter_amino_acids(arr)
    
    # Analyze each chain
    for chain_id in sorted(unique_chains):
        chain_mask = (chain_ids == chain_id)
        total_atoms = int(chain_mask.sum())
        peptide_atoms = int((peptide_mask & chain_mask).sum())
        non_peptide_atoms = total_atoms - peptide_atoms
        
        # Get label for this chain
        label = wrapper.idx_to_label_asym_id_map.get(chain_id, f"chain_{chain_id}")
        
        print(f"\nChain {label} (id={chain_id}):")
        print(f"  Total atoms: {total_atoms}")
        print(f"  Peptide atoms: {peptide_atoms}")
        print(f"  Non-peptide atoms: {non_peptide_atoms}")
        print(f"  Percentage protein: {(peptide_atoms/total_atoms*100):.1f}%" if total_atoms > 0 else "  Percentage protein: 0%")
        
        # Classify chain type
        if total_atoms == 0:
            chain_type = "Empty"
        elif peptide_atoms == 0:
            chain_type = "Pure non-protein"
        elif non_peptide_atoms == 0:
            chain_type = "Pure protein"
        else:
            chain_type = "Mixed protein + non-protein"
        
        print(f"  Type: {chain_type}")
        
        # Get residue types in this chain
        if total_atoms > 0:
            chain_res_names = arr.res_name[chain_mask]
            unique_res_names = set(chain_res_names)
            print(f"  Residue types: {sorted(unique_res_names)}")
    
    # Test current detection logic
    needs_inclusive = wrapper.needs_inclusive_domains()
    print(f"\nCurrent detection says needs_inclusive_domains: {needs_inclusive}")
    
    # Print chain residue ranges
    print(f"\nChain residue ranges: {wrapper.chain_residue_ranges}")

# Test both molecules
try:
    analyze_molecule_chains("test_proteins/3b75.pdb", "3B75")
    analyze_molecule_chains("test_proteins/1ATN.pdb", "1ATN") 
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc() 