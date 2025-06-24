#!/usr/bin/env python3
"""
Test comprehensive domain coverage: ensures create_comprehensive_domains() provides
100% atomic coverage for both 1ATN (mixed chains) and 3B75 (homogeneous protein chains).
Run with Blender in background:
& 'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe' --background --python "tests/comprehensive_test.py"
"""
import sys
import os

print("Starting comprehensive test...")

# Ensure project root is on path for imports
sys.path.insert(0, os.getcwd())
print(f"Working directory: {os.getcwd()}")

try:
    import bpy
    print("Blender Python API imported successfully")
except Exception as e:
    print(f"Failed to import bpy: {e}")
    sys.exit(1)

try:
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    print("ProteinBlenderScene imported successfully")
except Exception as e:
    print(f"Failed to import ProteinBlenderScene: {e}")
    sys.exit(1)

# Optionally register ProteinBlender addon to ensure full environment
try:
    from proteinblender import addon as pb_addon
    pb_addon.register()
    print("ProteinBlender addon registered successfully")
except Exception as e:
    print(f"Failed to register addon: {e}")

try:
    scene_manager = ProteinBlenderScene.get_instance()
    print("Scene manager instance obtained")
except Exception as e:
    print(f"Failed to get scene manager instance: {e}")
    sys.exit(1)

def test_comprehensive_coverage(pdb_file: str, expected_name: str) -> tuple[bool, str]:
    """Test comprehensive domain creation for a PDB file."""
    print(f"\nStarting test for {expected_name}...")
    try:
        # Skip clearing - just test each independently
        print("Starting fresh test...")
        
        # Import the PDB
        pdb_path = os.path.join("test_proteins", pdb_file)
        print(f"Looking for PDB at: {pdb_path}")
        if not os.path.exists(pdb_path):
            return False, f"PDB file not found: {pdb_path}"
            
        print(f"Importing {pdb_file}...")
        # Generate identifier from filename
        identifier = os.path.splitext(pdb_file)[0].lower()
        success = scene_manager.import_molecule_from_file(pdb_path, identifier)
        if not success:
            return False, f"Failed to import {pdb_file}"
            
        print("Getting active molecule...")
        # Get the molecule wrapper
        molecule = scene_manager.get_active_molecule()
        if not molecule:
            return False, f"No active molecule after importing {pdb_file}"
            
        # Get total atom count from the original array
        arr = getattr(molecule, 'working_array', None)
        if arr is None:
            return False, f"No working array for {pdb_file}"
            
        total_atoms = len(arr)
        print(f"\n{expected_name}: Total atoms in molecule: {total_atoms}")
        
        # Test comprehensive domain creation
        print("Creating comprehensive domains...")
        created_domains = molecule.create_comprehensive_domains(clear_existing=True)
        print(f"{expected_name}: Created domains: {created_domains}")
        
        if not created_domains:
            return False, f"No domains created for {pdb_file}"
            
        # Calculate total atoms covered by all domains
        covered_atoms = 0
        
        for domain_id in created_domains:
            domain = molecule.domains.get(domain_id)
            if domain:
                # Get domain's residue range
                start_res = domain.start_residue
                end_res = domain.end_residue
                
                # Count atoms in this range
                domain_mask = (arr.res_id >= start_res) & (arr.res_id <= end_res)
                domain_atom_count = sum(domain_mask)
                covered_atoms += domain_atom_count
                
                print(f"  Domain '{domain_id}': residues {start_res}-{end_res}, {domain_atom_count} atoms")
            else:
                print(f"  Warning: Domain '{domain_id}' not found in wrapper")
        
        print(f"{expected_name}: Total atoms covered by domains: {covered_atoms}")
        coverage_percent = (covered_atoms / total_atoms) * 100 if total_atoms > 0 else 0
        print(f"{expected_name}: Coverage: {coverage_percent:.1f}%")
        
        # Check for 100% coverage
        if covered_atoms == total_atoms:
            return True, f"Perfect coverage: {covered_atoms}/{total_atoms} atoms"
        else:
            return False, f"Incomplete coverage: {covered_atoms}/{total_atoms} atoms ({coverage_percent:.1f}%)"
            
    except Exception as e:
        import traceback
        print(f"Exception during test: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False, f"Exception during test: {e}"

def main():
    """Run comprehensive coverage tests."""
    print("Starting main test function...")
    
    test_cases = [
        ("1ATN.pdb", "1ATN (Mixed Complex)"),
        ("3b75.pdb", "3B75 (Homogeneous Protein)")
    ]
    
    all_pass = True
    
    for pdb_file, expected_name in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing {expected_name}")
        print(f"{'='*60}")
        
        success, message = test_comprehensive_coverage(pdb_file, expected_name)
        
        if success:
            print(f"✅ PASS: {expected_name} - {message}")
        else:
            print(f"❌ FAIL: {expected_name} - {message}")
            all_pass = False
    
    print(f"\n{'='*60}")
    if all_pass:
        print("✅ All comprehensive coverage tests passed!")
        os._exit(0)
    else:
        print("❌ Some tests failed.")
        os._exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"Fatal error in main: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        os._exit(1) 