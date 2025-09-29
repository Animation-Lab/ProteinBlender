"""
Test script to verify that alpha changes on domains are now independent.
This tests the fix for the material sharing issue.
"""

import bpy
from mathutils import Vector

print("\n" + "="*80)
print("ALPHA INDEPENDENCE TEST - Verifying Fix")
print("="*80 + "\n")

def test_independent_alpha():
    """Test that changing alpha on one domain doesn't affect others"""

    # Find all domain objects with geometry nodes
    domain_objects = []
    for obj in bpy.data.objects:
        if 'domain' in obj.name.lower() or 'chain' in obj.name.lower():
            # Check if it has a geometry nodes modifier
            for modifier in obj.modifiers:
                if modifier.type == 'NODES':
                    domain_objects.append(obj)
                    break

    if len(domain_objects) < 2:
        print("⚠️  Need at least 2 domain objects to test independence")
        print("   Please load a protein with multiple domains first")
        return False

    print(f"Found {len(domain_objects)} domain objects to test\n")

    # Select first two domains for testing
    domain1 = domain_objects[0]
    domain2 = domain_objects[1]

    print(f"Test domains:")
    print(f"  1. {domain1.name}")
    print(f"  2. {domain2.name}")
    print()

    # Function to get alpha value from a domain
    def get_alpha_value(obj):
        """Get the current alpha value from a domain's material"""
        for modifier in obj.modifiers:
            if modifier.type == 'NODES' and modifier.node_group:
                for node in modifier.node_group.nodes:
                    if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                        material_input = node.inputs.get("Material")
                        if material_input and material_input.default_value:
                            mat = material_input.default_value
                            if mat.use_nodes and mat.node_tree:
                                for mat_node in mat.node_tree.nodes:
                                    if mat_node.type == 'BSDF_PRINCIPLED':
                                        return mat_node.inputs['Alpha'].default_value
        return None

    # Function to get material name
    def get_material_name(obj):
        """Get the material name from a domain"""
        for modifier in obj.modifiers:
            if modifier.type == 'NODES' and modifier.node_group:
                for node in modifier.node_group.nodes:
                    if node.type == 'GROUP' and node.node_tree and 'Style' in node.node_tree.name:
                        material_input = node.inputs.get("Material")
                        if material_input and material_input.default_value:
                            return material_input.default_value.name
        return None

    print("INITIAL STATE:")
    print(f"  {domain1.name}:")
    print(f"    Material: {get_material_name(domain1) or 'None'}")
    print(f"    Alpha: {get_alpha_value(domain1) or 'N/A'}")
    print(f"  {domain2.name}:")
    print(f"    Material: {get_material_name(domain2) or 'None'}")
    print(f"    Alpha: {get_alpha_value(domain2) or 'N/A'}")
    print()

    # Test: Change alpha on domain1 using the visual setup panel logic
    print("TEST 1: Setting domain1 alpha to 0.3")

    # Import the function from visual_setup_panel
    from proteinblender.panels.visual_setup_panel import apply_material_transparency_to_style_node

    # Apply alpha change to domain1
    apply_material_transparency_to_style_node(domain1, 0.3)

    # Check both domains
    alpha1_after = get_alpha_value(domain1)
    alpha2_after = get_alpha_value(domain2)
    mat1_after = get_material_name(domain1)
    mat2_after = get_material_name(domain2)

    print(f"\nAFTER CHANGING DOMAIN1 TO 0.3:")
    print(f"  {domain1.name}:")
    print(f"    Material: {mat1_after or 'None'}")
    print(f"    Alpha: {alpha1_after:.3f if alpha1_after else 'N/A'}")
    print(f"  {domain2.name}:")
    print(f"    Material: {mat2_after or 'None'}")
    print(f"    Alpha: {alpha2_after:.3f if alpha2_after else 'N/A'}")
    print()

    # Check if materials are different
    if mat1_after == mat2_after:
        print("❌ FAILED: Both domains are using the SAME material!")
        print(f"   Material name: {mat1_after}")
        return False

    # Check independence
    if abs(alpha1_after - 0.3) < 0.01:
        print("✓ Domain1 alpha correctly set to 0.3")
    else:
        print(f"❌ Domain1 alpha is {alpha1_after:.3f}, expected 0.3")

    if abs(alpha2_after - 1.0) < 0.01 or alpha2_after != alpha1_after:
        print("✓ Domain2 alpha remains independent")
    else:
        print(f"❌ Domain2 alpha changed to {alpha2_after:.3f} (should be independent)")

    # Test 2: Change alpha on domain2
    print("\nTEST 2: Setting domain2 alpha to 0.7")
    apply_material_transparency_to_style_node(domain2, 0.7)

    alpha1_final = get_alpha_value(domain1)
    alpha2_final = get_alpha_value(domain2)

    print(f"\nFINAL STATE:")
    print(f"  {domain1.name}: Alpha = {alpha1_final:.3f if alpha1_final else 'N/A'}")
    print(f"  {domain2.name}: Alpha = {alpha2_final:.3f if alpha2_final else 'N/A'}")
    print()

    # Final verification
    success = True
    if abs(alpha1_final - 0.3) < 0.01:
        print("✓ Domain1 maintains its alpha value (0.3)")
    else:
        print(f"❌ Domain1 alpha changed to {alpha1_final:.3f}")
        success = False

    if abs(alpha2_final - 0.7) < 0.01:
        print("✓ Domain2 has independent alpha value (0.7)")
    else:
        print(f"❌ Domain2 alpha is {alpha2_final:.3f}, expected 0.7")
        success = False

    return success

# Run the test
print("Running alpha independence test...\n")
if test_independent_alpha():
    print("\n" + "="*80)
    print("✅ SUCCESS: Alpha changes are now INDEPENDENT for each domain!")
    print("="*80)
    print("\nThe fix is working correctly. Each domain can now have")
    print("its own alpha value for independent animation.")
else:
    print("\n" + "="*80)
    print("⚠️  ISSUE DETECTED")
    print("="*80)
    print("\nThe domains may still be sharing materials.")
    print("Check the console output above for details.")