#!/usr/bin/env python3
import sys
import numpy as np
from biotite.structure import AtomArray, AtomArrayStack
from biotite.structure.io import load_structure

def analyze_pdb(file_path):
    print(f"\nAnalyzing {file_path}")
    arr = load_structure(file_path)
    if isinstance(arr, AtomArrayStack):
        arr0 = arr[0]
        print("Detected AtomArrayStack, using first model for analysis")
    else:
        arr0 = arr
    chain_ids = arr0.chain_id

    # Compute sorted unique chain IDs via numpy.unique
    unique_sorted, idx_sorted = np.unique(chain_ids, return_inverse=True)
    unique_sorted = unique_sorted.tolist()
    print("Sorted unique chain IDs:", unique_sorted)

    # Mapping from integer to chain ID
    idx_to_label_map = {i: unique_sorted[i] for i in range(len(unique_sorted))}
    print("idx_to_label_asym_id_map:", idx_to_label_map)

    # Encounter order unique chain IDs
    unique_encounter = []
    for cid in chain_ids:
        if cid not in unique_encounter:
            unique_encounter.append(cid)
    print("Encounter order chain IDs:", unique_encounter)

    # Compute unique_pairs as in MoleculeWrapper logic
    seen = set()
    unique_pairs = []
    for chain_int, chain_label in zip(idx_sorted, chain_ids):
        if chain_int not in seen:
            unique_pairs.append((int(chain_int), chain_label))
            seen.add(chain_int)
    unique_pairs_sorted = sorted(unique_pairs, key=lambda x: x[0])
    print("Unique pairs first occurrences (chain_int, chain_label):", unique_pairs)
    print("Unique pairs sorted by chain_int:", unique_pairs_sorted)

    # Residue ID ranges per chain
    res_ids = arr0.res_id
    for cid in unique_sorted:
        mask = chain_ids == cid
        res = res_ids[mask]
        if res.size > 0:
            print(f"Chain '{cid}' residue range: {int(res.min())} to {int(res.max())}")
        else:
            print(f"Chain '{cid}' has no residues in model.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_chain_mappings.py <pdb_file1> [<pdb_file2> ...]")
        sys.exit(1)
    for pdb_file in sys.argv[1:]:
        analyze_pdb(pdb_file)

if __name__ == "__main__":
    main() 