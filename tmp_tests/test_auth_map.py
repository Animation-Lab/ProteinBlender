#!/usr/bin/env python3
from biotite.structure.io import load_structure
import sys

def print_auth_map(file_path):
    arr = load_structure(file_path)
    raw_map = arr.chain_mapping_str() if hasattr(arr, 'chain_mapping_str') else {}
    print(f"{file_path} raw_auth_map: {raw_map}")

if __name__ == '__main__':
    for pdb in ["test_proteins/1ATN.pdb", "test_proteins/3b75.pdb"]:
        print_auth_map(pdb) 