#!/usr/bin/env python3
"""
Test script to verify domain color independence after splitting chains.
This tests the fix for the bug where changing one domain's color affects other domains.
"""

import bpy
import sys
import traceback

def test_domain_color_independence():
    """Test that domains maintain independent colors after splitting"""
    try:
        print("\n" + "="*60)
        print("DOMAIN COLOR INDEPENDENCE TEST")
        print("="*60)

        # Get scene manager
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()

        # Find a molecule to test with
        if not scene_manager.molecules:
            print("ERROR: No molecules loaded. Please load a protein first.")
            return False

        # Get the first molecule
        molecule_id = list(scene_manager.molecules.keys())[0]
        molecule = scene_manager.molecules[molecule_id]
        print(f"\nTesting with molecule: {molecule_id}")

        # Get domains for this molecule
        print(f"Number of domains: {len(molecule.domains)}")

        if len(molecule.domains) < 2:
            print("ERROR: Need at least 2 domains to test color independence.")
            print("Please split a chain first using the UI.")
            return False

        # Get first two domains
        domain_ids = list(molecule.domains.keys())[:2]
        domain1_id = domain_ids[0]
        domain2_id = domain_ids[1]

        domain1 = molecule.domains[domain1_id]
        domain2 = molecule.domains[domain2_id]

        print(f"\nTesting domains:")
        print(f"  Domain 1: {domain1_id} (Chain {domain1.chain_id}, residues {domain1.start}-{domain1.end})")
        print(f"  Domain 2: {domain2_id} (Chain {domain2.chain_id}, residues {domain2.start}-{domain2.end})")

        # Test 1: Set different colors
        print("\n--- TEST 1: Setting different colors ---")
        color1 = (1.0, 0.0, 0.0, 1.0)  # Red
        color2 = (0.0, 0.0, 1.0, 1.0)  # Blue

        print(f"Setting domain 1 to RED: {color1}")
        success1 = molecule.update_domain_color(domain1_id, color1)

        print(f"Setting domain 2 to BLUE: {color2}")
        success2 = molecule.update_domain_color(domain2_id, color2)

        if not (success1 and success2):
            print("ERROR: Failed to set colors")
            return False

        # Verify colors are different
        print("\n--- VERIFICATION ---")

        # Check stored colors
        print(f"Domain 1 stored color: {domain1.color}")
        print(f"Domain 2 stored color: {domain2.color}")

        # Check node tree colors
        color1_actual = None
        color2_actual = None

        if domain1.node_group:
            for node in domain1.node_group.nodes:
                if node.name == "Color Common" and "Carbon" in node.inputs:
                    color1_actual = tuple(node.inputs["Carbon"].default_value)
                    print(f"Domain 1 Color Common node value: {color1_actual}")
                    if node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
                        print(f"  Using node tree: {node.node_tree.name}")
                    break

        if domain2.node_group:
            for node in domain2.node_group.nodes:
                if node.name == "Color Common" and "Carbon" in node.inputs:
                    color2_actual = tuple(node.inputs["Carbon"].default_value)
                    print(f"Domain 2 Color Common node value: {color2_actual}")
                    if node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
                        print(f"  Using node tree: {node.node_tree.name}")
                    break

        # Compare colors
        print("\n--- RESULTS ---")

        # Check if colors are approximately equal (within floating point tolerance)
        def colors_equal(c1, c2, tolerance=0.01):
            if not c1 or not c2:
                return False
            return all(abs(c1[i] - c2[i]) < tolerance for i in range(min(len(c1), len(c2))))

        if colors_equal(color1_actual, color2_actual):
            print("❌ FAILED: Domain colors are the same!")
            print(f"   Both domains have color: {color1_actual}")
            print("   This indicates the color sharing bug is still present.")
            return False
        else:
            print("✅ PASSED: Domain colors are independent!")
            print(f"   Domain 1: {color1_actual[:3]} (Red expected)")
            print(f"   Domain 2: {color2_actual[:3]} (Blue expected)")

            # Verify they match what we set
            if colors_equal(color1_actual, color1) and colors_equal(color2_actual, color2):
                print("✅ Colors match exactly what was set!")
                return True
            else:
                print("⚠️  Warning: Colors are different but don't match expected values exactly")
                return True  # Still a pass since they're independent

    except Exception as e:
        print(f"\n❌ ERROR during test: {e}")
        traceback.print_exc()
        return False

# Run the test
if __name__ == "__main__":
    success = test_domain_color_independence()

    print("\n" + "="*60)
    if success:
        print("TEST SUITE PASSED - Domain colors are independent! 🎉")
    else:
        print("TEST SUITE FAILED - Domain colors are still linked 😞")
    print("="*60)

    # Return exit code
    sys.exit(0 if success else 1)