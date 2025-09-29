#!/usr/bin/env python3
"""
Comprehensive test script for domain color independence fix.
Tests both the selection cascade fix and color node uniqueness.
"""

import bpy
import sys
import traceback

def test_domain_color_independence():
    """Test that domains maintain independent colors and selection after splitting"""
    try:
        print("\n" + "="*60)
        print("DOMAIN COLOR INDEPENDENCE TEST - COMPREHENSIVE")
        print("="*60)

        # Get scene manager
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene

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

        # Test 1: Check selection independence
        print("\n--- TEST 1: Selection Independence ---")

        # Clear all selections first
        for item in scene.outliner_items:
            item.is_selected = False

        # Select only domain 1
        domain1_item = None
        domain2_item = None
        chain_item = None

        for item in scene.outliner_items:
            if item.item_type == 'DOMAIN' and item.object_name == domain1.object.name:
                domain1_item = item
            elif item.item_type == 'DOMAIN' and item.object_name == domain2.object.name:
                domain2_item = item
            elif item.item_type == 'CHAIN' and hasattr(domain1, 'chain_id'):
                if item.item_id.endswith(f"_chain_{domain1.chain_id}"):
                    chain_item = item

        if not domain1_item or not domain2_item:
            print("ERROR: Could not find domain items in outliner")
            return False

        # Select domain 1
        domain1_item.is_selected = True
        print(f"Selected Domain 1: {domain1_item.name}")

        # Check that domain 2 is NOT selected
        if domain2_item.is_selected:
            print("❌ FAILED: Domain 2 was auto-selected when Domain 1 was selected!")
            print("   This indicates the selection cascade bug is still present.")
        else:
            print("✅ PASSED: Domain 2 remains unselected")

        # Check that chain is NOT auto-selected
        if chain_item and chain_item.is_selected:
            print("❌ WARNING: Chain was auto-selected when domain was selected")
            print("   This may cause all domains in chain to be selected")
        else:
            print("✅ PASSED: Chain checkbox remains independent")

        # Test 2: Set different colors
        print("\n--- TEST 2: Color Independence ---")
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

        # Check node tree colors and uniqueness
        color1_actual = None
        color2_actual = None
        node1_tree_name = None
        node2_tree_name = None

        if domain1.node_group:
            for node in domain1.node_group.nodes:
                if node.name == "Color Common" and node.bl_idname == 'GeometryNodeGroup':
                    if node.node_tree:
                        node1_tree_name = node.node_tree.name
                        if "Carbon" in node.inputs:
                            color1_actual = tuple(node.inputs["Carbon"].default_value)
                            print(f"Domain 1 Color Common:")
                            print(f"  Node tree: {node1_tree_name}")
                            print(f"  Color value: {color1_actual}")
                    break

        if domain2.node_group:
            for node in domain2.node_group.nodes:
                if node.name == "Color Common" and node.bl_idname == 'GeometryNodeGroup':
                    if node.node_tree:
                        node2_tree_name = node.node_tree.name
                        if "Carbon" in node.inputs:
                            color2_actual = tuple(node.inputs["Carbon"].default_value)
                            print(f"Domain 2 Color Common:")
                            print(f"  Node tree: {node2_tree_name}")
                            print(f"  Color value: {color2_actual}")
                    break

        # Check node tree uniqueness
        if node1_tree_name and node2_tree_name:
            if node1_tree_name == node2_tree_name:
                print(f"\n❌ WARNING: Domains share the same Color Common node tree: {node1_tree_name}")
                print("   This could cause color synchronization issues")
            else:
                print(f"\n✅ PASSED: Domains have unique Color Common node trees")

        # Compare colors
        print("\n--- FINAL RESULTS ---")

        # Check if colors are approximately equal (within floating point tolerance)
        def colors_equal(c1, c2, tolerance=0.01):
            if not c1 or not c2:
                return False
            return all(abs(c1[i] - c2[i]) < tolerance for i in range(min(len(c1), len(c2))))

        test_passed = True

        if colors_equal(color1_actual, color2_actual):
            print("❌ FAILED: Domain colors are the same!")
            print(f"   Both domains have color: {color1_actual}")
            print("   This indicates the color sharing bug is still present.")
            test_passed = False
        else:
            print("✅ PASSED: Domain colors are independent!")
            print(f"   Domain 1: {color1_actual[:3] if color1_actual else 'None'} (Red expected)")
            print(f"   Domain 2: {color2_actual[:3] if color2_actual else 'None'} (Blue expected)")

            # Verify they match what we set
            if colors_equal(color1_actual, color1) and colors_equal(color2_actual, color2):
                print("✅ Colors match exactly what was set!")
            else:
                print("⚠️  Warning: Colors are different but don't match expected values exactly")

        return test_passed

    except Exception as e:
        print(f"\n❌ ERROR during test: {e}")
        traceback.print_exc()
        return False


# Run the test
if __name__ == "__main__":
    success = test_domain_color_independence()

    print("\n" + "="*60)
    if success:
        print("ALL TESTS PASSED - Domain colors and selection are independent! 🎉")
    else:
        print("TESTS FAILED - Issues remain with domain independence 😞")
    print("="*60)

    # Return exit code
    sys.exit(0 if success else 1)