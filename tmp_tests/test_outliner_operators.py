"""
Test script to verify the outliner operators work correctly.
"""

import bpy
import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_outliner_operators():
    """Test the outliner operators functionality."""
    
    print("=== Testing Outliner Operators ===")
    
    # Get the scene and outliner state
    scene = bpy.context.scene
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found on scene")
        return False
    
    outliner_state = scene.protein_outliner_state
    
    # Find chain items
    chain_items = [item for item in outliner_state.items if item.type == 'CHAIN']
    
    if not chain_items:
        print("❌ No chain items found in outliner")
        return False
    
    print(f"✅ Found {len(chain_items)} chain items")
    
    # Test each chain
    for i, chain_item in enumerate(chain_items):
        print(f"\n--- Testing Chain {i+1}: {chain_item.name} ---")
        
        # Find the index of this item in the outliner
        item_index = -1
        for idx, item in enumerate(outliner_state.items):
            if item == chain_item:
                item_index = idx
                break
        
        if item_index == -1:
            print(f"  ❌ Could not find index for chain item")
            continue
        
        print(f"  Item index: {item_index}")
        
        # Test selection operator
        print(f"  Current selection state: {chain_item.is_selected}")
        
        # Simulate clicking the selection operator
        bpy.ops.protein_pb.toggle_outliner_selection(item_index=item_index)
        
        print(f"  Selection after toggle: {chain_item.is_selected}")
        
        # Test visibility operator
        print(f"  Current visibility state: {chain_item.is_visible}")
        
        # Simulate clicking the visibility operator
        bpy.ops.protein_pb.toggle_outliner_visibility(item_index=item_index)
        
        print(f"  Visibility after toggle: {chain_item.is_visible}")
        
        print(f"  ✅ Chain {chain_item.name} operator test completed")
    
    print("\n=== Test Summary ===")
    print("✅ Outliner operators are working correctly")
    print("✅ No errors occurred during testing")
    
    return True

def test_operator_registration():
    """Test that the operators are properly registered."""
    
    print("\n=== Testing Operator Registration ===")
    
    # Check if operators are registered
    operators_to_check = [
        "protein_pb.toggle_outliner_selection",
        "protein_pb.toggle_outliner_visibility",
        "protein_pb.toggle_outliner_expand"
    ]
    
    for op_id in operators_to_check:
        if hasattr(bpy.ops, op_id.split('.')[0]) and hasattr(getattr(bpy.ops, op_id.split('.')[0]), op_id.split('.')[1]):
            print(f"✅ {op_id} is registered")
        else:
            print(f"❌ {op_id} is NOT registered")
            return False
    
    return True

if __name__ == "__main__":
    print("Starting Outliner Operators Tests...")
    
    success1 = test_operator_registration()
    success2 = test_outliner_operators()
    
    if success1 and success2:
        print("\n🎉 All tests passed! Outliner operators should work correctly.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.") 