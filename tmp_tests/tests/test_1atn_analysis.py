#!/usr/bin/env python3
"""
Test script to analyze the 1ATN protein structure and understand chain organization.
This will help us understand why 1ATN causes issues with domain creation.
"""

import sys
sys.path.append("../")

import bpy
import numpy as np
from proteinblender.utils.molecularnodes.entities.molecule.molecule import Molecule

def analyze_1atn_structure():
    """Analyze the 1ATN protein structure to understand chain organization."""
    
    print("=== 1ATN Structure Analysis ===")
    
    # Load the 1ATN protein
    file_path = "../test_proteins/1ATN.pdb"
    
    try:
        # Create molecule using MolecularNodes
        mol = Molecule.from_pdb(file_path)
        print(f"✓ Successfully loaded 1ATN from {file_path}")
        
        # Analyze chain structure
        print(f"\nChain Analysis:")
        unique_chains = np.unique(mol.array.chain_id)
        print(f"Unique chain IDs: {unique_chains}")
        
        # Get chain mapping information
        if hasattr(mol.array, 'chain_mapping_str'):
            chain_mapping = mol.array.chain_mapping_str()
            print(f"Chain mapping: {chain_mapping}")
        
        # Count atoms per chain
        print(f"\nAtom counts per chain:")
        for chain in unique_chains:
            chain_mask = mol.array.chain_id == chain
            atom_count = np.sum(chain_mask)
            print(f"Chain {chain}: {atom_count} atoms")
            
            # Check if chain has protein atoms
            if hasattr(mol.array, 'element_symbol'):
                elements = mol.array.element_symbol[chain_mask]
                unique_elements = np.unique(elements)
                print(f"  Elements: {unique_elements}")
            
            # Check residue types
            if hasattr(mol.array, 'res_name'):
                res_names = mol.array.res_name[chain_mask]
                unique_res = np.unique(res_names)
                print(f"  Residue types: {unique_res}")
                
                # Check for standard amino acids
                standard_aa = {'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 
                              'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 
                              'THR', 'TRP', 'TYR', 'VAL'}
                protein_residues = [res for res in unique_res if res in standard_aa]
                non_protein_residues = [res for res in unique_res if res not in standard_aa]
                
                print(f"  Protein residues: {protein_residues}")
                print(f"  Non-protein residues: {non_protein_residues}")
                
                protein_atom_count = sum(1 for res in res_names if res in standard_aa)
                print(f"  Protein atoms: {protein_atom_count}")
                print(f"  Non-protein atoms: {atom_count - protein_atom_count}")
        
        # Analyze residue ranges per chain
        print(f"\nResidue ranges per chain:")
        if hasattr(mol.array, 'res_id'):
            for chain in unique_chains:
                chain_mask = mol.array.chain_id == chain
                if np.any(chain_mask):
                    chain_res_ids = mol.array.res_id[chain_mask]
                    if len(chain_res_ids) > 0:
                        min_res = np.min(chain_res_ids)
                        max_res = np.max(chain_res_ids)
                        print(f"Chain {chain}: residues {min_res}-{max_res}")
    
    except Exception as e:
        print(f"✗ Error loading 1ATN: {e}")
        import traceback
        traceback.print_exc()

def test_domain_creation_strategy():
    """Test different strategies for creating domains from 1ATN."""
    
    print("\n=== Domain Creation Strategy Analysis ===")
    
    # Based on RCSB info and our analysis, 1ATN should have:
    # Chain A: Actin (protein) 
    # Chain B: Carbohydrate ligands only (NAG, BMA)
    # Chain D: DNase I (protein)
    
    print("Expected 1ATN structure:")
    print("- Chain A: Actin (protein) -> should get 1 domain")
    print("- Chain B: Ligands only (carbohydrates) -> should be filtered out")  
    print("- Chain D: DNase I (protein) -> should get 1 domain")
    print("\nExpected result: 2 domains total (Chain A, Chain D)")
    print("Problem: Chain B ligands still render as 'orphaned' protein")

def propose_solution():
    """Propose the solution for handling 1ATN properly."""
    
    print("\n=== Proposed Solution ===")
    print("Implement Global Chain Filter as described in CHAIN_FILTERING_SOLUTION.md:")
    print("1. Filter ligand-only chains at domain level (already working)")
    print("2. Add geometry node filtering to hide filtered chains from rendering")
    print("3. Chain B should be completely invisible")
    print("4. Only Chains A and D should be visible and controllable via domains")

if __name__ == "__main__":
    analyze_1atn_structure()
    test_domain_creation_strategy()
    propose_solution() 