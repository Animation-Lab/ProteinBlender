"""
Minimal test to verify basic checkbox functionality works in the outliner.
"""

import bpy

def test_minimal_checkbox():
    """Test the most basic checkbox functionality."""
    
    print("=== Minimal Checkbox Test ===")
    
    scene = bpy.context.scene
    
    # Check if outliner state exists
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found")
        return False
    
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) == 0:
        print("❌ No items in outliner state")
        return False
    
    print(f"✅ Found {len(outliner_state.items)} items")
    
    # Test each item's properties
    for i, item in enumerate(outliner_state.items):
        print(f"\nItem {i}: {item.name} (type: {item.type})")
        print(f"  is_selected: {item.is_selected} (type: {type(item.is_selected)})")
        print(f"  is_visible: {item.is_visible} (type: {type(item.is_visible)})")
        
        # Try to access the property descriptors
        try:
            cls = item.__class__
            if hasattr(cls, 'is_selected'):
                sel_prop = getattr(cls, 'is_selected')
                print(f"  is_selected property: {sel_prop}")
            if hasattr(cls, 'is_visible'):
                vis_prop = getattr(cls, 'is_visible')
                print(f"  is_visible property: {vis_prop}")
        except Exception as e:
            print(f"  ❌ Error accessing property descriptors: {e}")
    
    return True

def test_update_function_access():
    """Test if we can access the update functions."""
    
    print("\n=== Update Function Access Test ===")
    
    try:
        from proteinblender.properties.outliner_properties import update_selection, update_visibility
        print("✅ Update functions imported successfully")
        
        # Check function signatures
        import inspect
        
        sel_sig = inspect.signature(update_selection)
        print(f"  update_selection signature: {sel_sig}")
        
        vis_sig = inspect.signature(update_visibility)
        print(f"  update_visibility signature: {vis_sig}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error accessing update functions: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting Minimal Checkbox Tests...")
    
    success1 = test_minimal_checkbox()
    success2 = test_update_function_access()
    
    if success1 and success2:
        print("\n✅ Basic setup looks correct")
    else:
        print("\n❌ There are fundamental issues with the setup") 