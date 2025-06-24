#!/usr/bin/env python3
"""
Simple test script to analyze the 1ATN protein structure using basic biotite.
"""

import sys
import os

# Add the project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    # Try to import biotite directly
    import biotite.structure.io.pdb as pdb
    import numpy as np
    
    def analyze_1atn_simple():
        """Simple analysis of 1ATN structure using biotite."""
        
        print("=== Simple 1ATN Structure Analysis ===")
        
        # Load the 1ATN protein using biotite PDB reader
        file_path = os.path.join(project_root, "test_proteins", "1ATN.pdb")
        
        try:
            # Read the PDB file
            pdb_file = pdb.PDBFile.read(file_path)
            array = pdb.get_structure(pdb_file)
            
            print(f"✓ Successfully loaded 1ATN from {file_path}")
            print(f"Total atoms: {len(array)}")
            
            # Analyze chain structure
            unique_chains = np.unique(array.chain_id)
            print(f"Unique chain IDs: {unique_chains}")
            
            # Count atoms per chain and analyze residue types
            print(f"\nAtom counts and residue analysis per chain:")
            for chain in unique_chains:
                chain_mask = array.chain_id == chain
                atom_count = np.sum(chain_mask)
                print(f"\nChain {chain}: {atom_count} atoms")
                
                # Get residue information for this chain
                chain_array = array[chain_mask]
                if hasattr(chain_array, 'res_name'):
                    unique_res = np.unique(chain_array.res_name)
                    print(f"  Residue types: {unique_res}")
                    
                    # Check for standard amino acids vs ligands
                    standard_aa = {'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 
                                  'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 
                                  'THR', 'TRP', 'TYR', 'VAL'}
                    
                    protein_residues = [res for res in unique_res if res in standard_aa]
                    ligand_residues = [res for res in unique_res if res not in standard_aa]
                    
                    protein_atom_count = sum(1 for res in chain_array.res_name if res in standard_aa)
                    
                    print(f"  Protein residues: {protein_residues} ({len(protein_residues)} types)")
                    print(f"  Ligand residues: {ligand_residues} ({len(ligand_residues)} types)")
                    print(f"  Protein atoms: {protein_atom_count}")
                    print(f"  Ligand atoms: {atom_count - protein_atom_count}")
                    
                    # Determine if this chain should be filtered
                    if protein_atom_count == 0 and len(ligand_residues) > 0:
                        print(f"  *** Chain {chain} is LIGAND-ONLY and should be FILTERED ***")
                    elif protein_atom_count > 0:
                        print(f"  *** Chain {chain} contains PROTEIN and should get a DOMAIN ***")
                
                # Get residue range
                if hasattr(chain_array, 'res_id') and len(chain_array.res_id) > 0:
                    min_res = np.min(chain_array.res_id)
                    max_res = np.max(chain_array.res_id)
                    print(f"  Residue range: {min_res}-{max_res}")
            
        except Exception as e:
            print(f"✗ Error loading 1ATN: {e}")
            import traceback
            traceback.print_exc()
    
    def summarize_solution():
        """Summarize the solution for 1ATN."""
        print("\n=== Solution Summary ===")
        print("Based on analysis, 1ATN structure:")
        print("- Chain A: Protein (Actin) -> CREATE DOMAIN")
        print("- Chain B: Ligands only (carbohydrates) -> FILTER OUT completely") 
        print("- Chain D: Protein (DNase I) -> CREATE DOMAIN")
        print("\nCurrent issue: Chain B still renders even though filtered from domains")
        print("Solution needed: Global chain filter in geometry nodes to hide Chain B")
    
    if __name__ == "__main__":
        analyze_1atn_simple()
        summarize_solution()
        
except ImportError as e:
    print(f"Import error: {e}")
    print("This script requires biotite to be available in Blender's Python environment") 