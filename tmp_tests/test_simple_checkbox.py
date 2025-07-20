"""
Simple test to check if the outliner properties work with direct assignment.
This will help isolate whether the issue is with the operators or the properties themselves.
"""

import bpy

def test_direct_property_assignment():
    """Test direct property assignment to see if the update functions work."""
    
    print("=== Testing Direct Property Assignment ===")
    
    scene = bpy.context.scene
    
    # Check if outliner state exists
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found")
        return False
    
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) == 0:
        print("❌ No items in outliner state")
        return False
    
    print(f"✅ Found {len(outliner_state.items)} items in outliner")
    
    # Find a chain item to test
    chain_item = None
    chain_index = -1
    for i, item in enumerate(outliner_state.items):
        if item.type == 'CHAIN':
            chain_item = item
            chain_index = i
            break
    
    if not chain_item:
        print("❌ No chain items found")
        return False
    
    print(f"✅ Found chain item: {chain_item.name}")
    print(f"   Current selection: {chain_item.is_selected}")
    print(f"   Current visibility: {chain_item.is_visible}")
    
    # Test direct assignment
    print("\n--- Testing direct selection assignment ---")
    original_selection = chain_item.is_selected
    try:
        chain_item.is_selected = not original_selection
        print(f"✅ Selection changed to: {chain_item.is_selected}")
    except Exception as e:
        print(f"❌ Error changing selection: {e}")
        return False
    
    print("\n--- Testing direct visibility assignment ---")
    original_visibility = chain_item.is_visible
    try:
        chain_item.is_visible = not original_visibility
        print(f"✅ Visibility changed to: {chain_item.is_visible}")
    except Exception as e:
        print(f"❌ Error changing visibility: {e}")
        return False
    
    # Reset to original values
    chain_item.is_selected = original_selection
    chain_item.is_visible = original_visibility
    
    print(f"\n✅ Reset to original values")
    print(f"   Selection: {chain_item.is_selected}")
    print(f"   Visibility: {chain_item.is_visible}")
    
    return True

def test_update_functions():
    """Test if the update functions are being called."""
    
    print("\n=== Testing Update Function Calls ===")
    
    try:
        from proteinblender.properties.outliner_properties import update_selection, update_visibility
        print("✅ Successfully imported update functions")
        
        # Test calling the functions directly
        scene = bpy.context.scene
        outliner_state = scene.protein_outliner_state
        
        if len(outliner_state.items) > 0:
            chain_item = None
            for item in outliner_state.items:
                if item.type == 'CHAIN':
                    chain_item = item
                    break
            
            if chain_item:
                print(f"✅ Testing update functions on: {chain_item.name}")
                
                try:
                    update_selection(chain_item, bpy.context)
                    print("✅ update_selection called successfully")
                except Exception as e:
                    print(f"❌ Error in update_selection: {e}")
                
                try:
                    update_visibility(chain_item, bpy.context)
                    print("✅ update_visibility called successfully")
                except Exception as e:
                    print(f"❌ Error in update_visibility: {e}")
            else:
                print("❌ No chain item found for testing")
        else:
            print("❌ No items found for testing")
            
    except Exception as e:
        print(f"❌ Error importing update functions: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("Starting Simple Checkbox Tests...")
    
    success1 = test_direct_property_assignment()
    success2 = test_update_functions()
    
    if success1 and success2:
        print("\n🎉 Direct property assignment works! The issue might be with operator registration.")
    else:
        print("\n❌ There are issues with the basic property functionality.") 