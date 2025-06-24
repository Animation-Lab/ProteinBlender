#!/usr/bin/env python3
"""
Test inclusive domain detection: ensures needs_inclusive_domains() returns True for 1ATN (mixed chains)
and False for 3B75 (homogeneous protein chains).
Run with Blender in background:
& 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe' --background --python "tests/inclusive_test.py"
"""
import sys
import os  # For os._exit to ensure proper Blender exit codes

# Ensure project root is on path for imports
sys.path.insert(0, os.getcwd())

import bpy
from proteinblender.utils.scene_manager import ProteinBlenderScene

# Optionally register ProteinBlender addon to ensure full environment
try:
    from proteinblender import addon as pb_addon
    pb_addon.register()
except Exception:
    pass

scene_manager = ProteinBlenderScene.get_instance()

# Utility to import and test a PDB file

def import_and_test(filename, expected):
    identifier = os.path.splitext(filename)[0].lower()
    pdb_dir = os.path.join(os.getcwd(), 'test_proteins')
    filepath = os.path.join(pdb_dir, filename)
    print(f"\n--- Testing {filename} ---")
    # Import molecule from local PDB
    success = scene_manager.import_molecule_from_file(filepath, identifier)
    if not success:
        print(f"❌ Failed to import {filename}")
        return False
    # Fetch wrapper
    mol = scene_manager.molecules.get(identifier)
    if mol is None:
        print(f"❌ Molecule '{identifier}' not found after import")
        return False
    # Test needs_inclusive_domains
    result = mol.needs_inclusive_domains()
    print(f"{filename}: needs_inclusive_domains() -> {result} (expected {expected})")
    # Clean up
    scene_manager.delete_molecule(identifier)
    return result == expected

if __name__ == '__main__':
    targets = [
        ('1ATN.pdb', True),
        ('3B75.pdb', False),
    ]
    all_pass = True
    for fname, exp in targets:
        ok = import_and_test(fname, exp)
        if ok:
            print(f"✓ {fname} detected correctly.")
        else:
            print(f"✗ {fname} detection failed.")
            all_pass = False
    if all_pass:
        print("\nAll inclusive domain detection tests passed.")
        os._exit(0)
    else:
        print("\nSome tests failed.")
        os._exit(1) 