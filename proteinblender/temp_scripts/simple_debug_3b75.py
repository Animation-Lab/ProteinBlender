#!/usr/bin/env python3

import sys
sys.path.append(".")

# Direct analysis using biotite
import biotite.structure.io.pdb as pdb
import biotite.structure as struc

def analyze_molecule(pdb_path, name):
    print(f"\n=== {name} Analysis ===")
    
    # Load PDB file directly
    pdb_file = pdb.PDBFile.read(pdb_path)
    structure = pdb_file.get_structure()
    
    # Get first model if multiple
    if len(structure.shape) > 1:
        structure = structure[0]
    
    print(f"Total atoms: {len(structure)}")
    
    # Analyze chains
    unique_chains = set(structure.chain_id)
    print(f"Chains found: {sorted(unique_chains)}")
    
    # Get peptide mask
    peptide_mask = struc.filter_amino_acids(structure)
    
    non_protein_chains = 0
    
    for chain_id in sorted(unique_chains):
        # Atoms in this chain
        chain_mask = (structure.chain_id == chain_id)
        total_atoms = int(chain_mask.sum())
        
        # Count peptide atoms in this chain
        peptide_atoms = int((peptide_mask & chain_mask).sum())
        
        print(f"  Chain {chain_id} - total atoms: {total_atoms}, peptide atoms: {peptide_atoms}")
        
        if total_atoms > 0 and peptide_atoms == 0:
            non_protein_chains += 1
            print(f"    ^^ NON-PROTEIN CHAIN DETECTED ^^")
    
    print(f"Total non-protein chains: {non_protein_chains}")
    
    # Simulate needs_inclusive_domains logic
    needs_inclusive = non_protein_chains > 0
    print(f"Would need inclusive domains: {needs_inclusive}")
    
    return needs_inclusive

# Analyze both molecules
result_3b75 = analyze_molecule("test_proteins/3b75.pdb", "3B75")
result_1atn = analyze_molecule("test_proteins/1ATN.pdb", "1ATN")

print(f"\n=== Summary ===")
print(f"3B75 needs inclusive domains: {result_3b75}")
print(f"1ATN needs inclusive domains: {result_1atn}") 