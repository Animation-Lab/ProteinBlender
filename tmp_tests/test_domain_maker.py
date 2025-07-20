"""Test script for the Domain Maker panel functionality.

This script tests:
1. Domain Maker panel registration
2. Chain detection and selection
3. Button enable/disable states
4. Split chain operator
5. Auto-split on import functionality
"""

import bpy
import sys
import os

# Add the addon directory to sys.path
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

def test_domain_maker():
    """Test the Domain Maker panel functionality"""
    print("\n" + "="*50)
    print("Testing Domain Maker Panel")
    print("="*50)
    
    # Ensure addon is enabled
    if "proteinblender" not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module="proteinblender")
        print("✓ Enabled ProteinBlender addon")
    
    # Switch to ProteinBlender workspace
    if "ProteinBlender" in bpy.data.workspaces:
        bpy.context.window.workspace = bpy.data.workspaces["ProteinBlender"]
        print("✓ Switched to ProteinBlender workspace")
    
    # Check if domain maker panel is registered
    if hasattr(bpy.types, "VIEW3D_PT_pb_domain_maker"):
        print("✓ Domain Maker panel registered")
    else:
        print("✗ Domain Maker panel not found")
        return False
    
    # Check operators
    print("\nChecking operators:")
    if hasattr(bpy.ops.pb, "split_chain"):
        print("  ✓ Split chain operator registered")
    else:
        print("  ✗ Split chain operator not found")
    
    if hasattr(bpy.ops.pb, "auto_split_chains"):
        print("  ✓ Auto split chains operator registered")
    else:
        print("  ✗ Auto split chains operator not found")
    
    # Test with outliner state
    scene = bpy.context.scene
    outliner_state = scene.protein_outliner_state
    
    print("\nSetting up test data:")
    # Clear existing items
    outliner_state.items.clear()
    
    # Add test protein
    protein = outliner_state.items.add()
    protein.name = "Test Protein"
    protein.identifier = "test_protein_1"
    protein.type = "PROTEIN"
    protein.depth = 0
    protein.is_selected = False
    protein.is_visible = True
    protein.is_expanded = True
    
    # Add test chains
    chain_a = outliner_state.items.add()
    chain_a.name = "Chain A"
    chain_a.identifier = "test_protein_1_chain_A"
    chain_a.type = "CHAIN"
    chain_a.depth = 1
    chain_a.is_selected = False
    chain_a.is_visible = True
    
    chain_b = outliner_state.items.add()
    chain_b.name = "Chain B"
    chain_b.identifier = "test_protein_1_chain_B"
    chain_b.type = "CHAIN"
    chain_b.depth = 1
    chain_b.is_selected = False
    chain_b.is_visible = True
    
    print(f"  ✓ Added test protein with 2 chains")
    
    # Test selection scenarios
    print("\nTesting selection scenarios:")
    
    # Test 1: No selection
    print("  Test 1: No chain selected")
    from proteinblender.panels.domain_maker_panel import get_selected_outliner_items
    selected = get_selected_outliner_items(bpy.context)
    if len(selected) == 0:
        print("    ✓ No items selected (correct)")
    
    # Test 2: Single chain selection
    print("  Test 2: Single chain selected")
    chain_a.is_selected = True
    selected = get_selected_outliner_items(bpy.context)
    selected_chains = [item for item in selected if item.type == 'CHAIN']
    if len(selected_chains) == 1:
        print(f"    ✓ Single chain selected: {selected_chains[0].name}")
        
        # Test chain info extraction
        from proteinblender.panels.domain_maker_panel import get_chain_info
        chain_info = get_chain_info(selected_chains[0])
        if chain_info:
            print(f"    ✓ Chain info extracted: ID={chain_info['chain_id']}, Protein={chain_info['protein_id']}")
        else:
            print("    ✗ Failed to extract chain info")
    
    # Test 3: Multiple chain selection
    print("  Test 3: Multiple chains selected")
    chain_b.is_selected = True
    selected = get_selected_outliner_items(bpy.context)
    selected_chains = [item for item in selected if item.type == 'CHAIN']
    if len(selected_chains) == 2:
        print(f"    ✓ Multiple chains selected: {len(selected_chains)} chains")
    
    # Reset selection
    chain_a.is_selected = False
    chain_b.is_selected = False
    
    # Test auto-split functionality
    print("\nTesting auto-split functionality:")
    try:
        # Run auto-split operator
        bpy.ops.pb.auto_split_chains()
        
        # Check if domains were created
        domains = [item for item in outliner_state.items if item.type == 'DOMAIN']
        if len(domains) > 0:
            print(f"  ✓ Auto-split created {len(domains)} domains")
            for domain in domains:
                print(f"    - {domain.name} ({domain.identifier})")
        else:
            print("  ℹ No domains created (may already exist)")
    except Exception as e:
        print(f"  ✗ Auto-split failed: {e}")
    
    # Test split chain operator
    print("\nTesting split chain operator:")
    chain_a.is_selected = True
    try:
        bpy.ops.pb.split_chain(
            chain_id="A",
            protein_id="test_protein_1",
            chain_name="Chain A"
        )
        print("  ✓ Split chain operator executed (placeholder)")
    except Exception as e:
        print(f"  ✗ Split chain operator failed: {e}")
    
    print("\n" + "="*50)
    print("Domain Maker test completed")
    print("="*50)
    
    return True


if __name__ == "__main__":
    test_domain_maker()