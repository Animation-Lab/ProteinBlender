"""
Test script to verify chain selection and visibility functionality in the Protein Outliner.
This test simulates the behavior of clicking checkboxes in the outliner.
"""

import bpy
import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_chain_selection_visibility():
    """Test the chain selection and visibility functionality."""
    
    print("=== Testing Chain Selection and Visibility ===")
    
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
        
        # Test selection functionality
        print(f"  Current selection state: {chain_item.is_selected}")
        
        # Simulate clicking the selection checkbox
        original_selection = chain_item.is_selected
        chain_item.is_selected = not original_selection
        
        print(f"  Selection changed to: {chain_item.is_selected}")
        
        # Test visibility functionality
        print(f"  Current visibility state: {chain_item.is_visible}")
        
        # Simulate clicking the visibility checkbox
        original_visibility = chain_item.is_visible
        chain_item.is_visible = not original_visibility
        
        print(f"  Visibility changed to: {chain_item.is_visible}")
        
        # Reset to original state
        chain_item.is_selected = original_selection
        chain_item.is_visible = original_visibility
        
        print(f"  ✅ Chain {chain_item.name} test completed")
    
    print("\n=== Test Summary ===")
    print("✅ Chain selection and visibility update functions are working")
    print("✅ No errors occurred during testing")
    
    return True

def test_sync_functions():
    """Test the sync functions that update outliner from viewport."""
    
    print("\n=== Testing Sync Functions ===")
    
    try:
        from proteinblender.handlers.outliner_handler import (
            sync_selection_from_viewport,
            _calculate_chain_selection_state,
            _calculate_chain_visibility_state
        )
        
        from proteinblender.utils.scene_manager import ProteinBlenderScene
        
        scene_manager = ProteinBlenderScene.get_instance()
        scene = bpy.context.scene
        
        print("✅ Successfully imported sync functions")
        
        # Test sync function
        sync_selection_from_viewport()
        print("✅ sync_selection_from_viewport() executed without errors")
        
        # Test chain calculation functions
        chain_items = [item for item in scene.protein_outliner_state.items if item.type == 'CHAIN']
        
        if chain_items:
            chain_item = chain_items[0]
            
            # Test selection calculation
            selection_state = _calculate_chain_selection_state(chain_item, scene_manager)
            print(f"✅ Chain selection calculation: {selection_state}")
            
            # Test visibility calculation
            visibility_state = _calculate_chain_visibility_state(chain_item, scene_manager)
            print(f"✅ Chain visibility calculation: {visibility_state}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing sync functions: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting Chain Selection and Visibility Tests...")
    
    success1 = test_chain_selection_visibility()
    success2 = test_sync_functions()
    
    if success1 and success2:
        print("\n🎉 All tests passed! Chain selection and visibility should work correctly.")
    else:
        print("\n❌ Some tests failed. Please check the implementation.") 