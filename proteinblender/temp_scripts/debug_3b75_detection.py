#!/usr/bin/env python3

import sys
sys.path.append(".")

from proteinblender.utils.molecularnodes.entities import load_local
from proteinblender.core.molecule_wrapper import MoleculeWrapper
import biotite.structure as struc

# Load 3B75
print("=== 3B75 Debug ===")
mol = load_local("test_proteins/3b75.pdb")
wrapper = MoleculeWrapper(mol, "test_3b75")

print(f"Chain residue ranges: {wrapper.chain_residue_ranges}")
print(f"Available chains: {wrapper._get_available_chains()}")

# Debug the detection logic
arr = getattr(wrapper, 'working_array', None)
if arr is not None:
    print(f"\nDetection logic debug:")
    
    # Get peptide mask
    peptide_mask = struc.filter_amino_acids(arr)
    int_chain_ids = getattr(arr, 'chain_id_int', None)
    
    if int_chain_ids is not None:
        unique_ints = set(int_chain_ids)
        import numpy as np
        
        non_protein_chains = 0
        
        for int_id in sorted(unique_ints):
            # Atoms in this chain
            mask = (int_chain_ids == int_id)
            total = int(np.count_nonzero(mask))
            # Count peptide atoms
            pep = int(np.count_nonzero(peptide_mask & mask))
            
            # Resolve label for logging
            label = wrapper.idx_to_label_asym_id_map.get(int_id, str(int_id))
            
            print(f"  Chain {label} (int {int_id}) - total atoms: {total}, peptide atoms: {pep}")
            if total > 0 and pep == 0:
                non_protein_chains += 1
                print(f"    ^^ NON-PROTEIN CHAIN DETECTED ^^")
        
        print(f"\nTotal non-protein chains: {non_protein_chains}")
        needs_inclusive = wrapper.needs_inclusive_domains()
        print(f"needs_inclusive_domains() returns: {needs_inclusive}")
    else:
        print("No chain_id_int found")
else:
    print("No working_array found")

# Compare with 1ATN
print("\n=== 1ATN Debug ===")
mol_1atn = load_local("test_proteins/1ATN.pdb")
wrapper_1atn = MoleculeWrapper(mol_1atn, "test_1atn")

print(f"Chain residue ranges: {wrapper_1atn.chain_residue_ranges}")

arr_1atn = getattr(wrapper_1atn, 'working_array', None)
if arr_1atn is not None:
    peptide_mask_1atn = struc.filter_amino_acids(arr_1atn)
    int_chain_ids_1atn = getattr(arr_1atn, 'chain_id_int', None)
    
    if int_chain_ids_1atn is not None:
        unique_ints_1atn = set(int_chain_ids_1atn)
        import numpy as np
        
        non_protein_chains_1atn = 0
        
        for int_id in sorted(unique_ints_1atn):
            mask = (int_chain_ids_1atn == int_id)
            total = int(np.count_nonzero(mask))
            pep = int(np.count_nonzero(peptide_mask_1atn & mask))
            
            label = wrapper_1atn.idx_to_label_asym_id_map.get(int_id, str(int_id))
            
            print(f"  Chain {label} (int {int_id}) - total atoms: {total}, peptide atoms: {pep}")
            if total > 0 and pep == 0:
                non_protein_chains_1atn += 1
                print(f"    ^^ NON-PROTEIN CHAIN DETECTED ^^")
        
        print(f"\nTotal non-protein chains: {non_protein_chains_1atn}")
        needs_inclusive_1atn = wrapper_1atn.needs_inclusive_domains()
        print(f"needs_inclusive_domains() returns: {needs_inclusive_1atn}") 