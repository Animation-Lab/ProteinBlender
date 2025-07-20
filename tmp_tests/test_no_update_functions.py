"""
Test version with properties that don't have update functions to isolate the issue.
"""

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty

def test_temporary_properties():
    """Create temporary properties without update functions."""
    
    print("=== Testing Properties Without Update Functions ===")
    
    # Define a simple property group without update functions
    class TestOutlinerItem(bpy.types.PropertyGroup):
        """Test version of OutlinerListItem without update functions."""
        name: StringProperty(name="Name", description="Display name of the item")
        identifier: StringProperty(name="Identifier", description="Unique identifier for the item")
        type: EnumProperty(
            name="Type",
            items=[
                ('PROTEIN', "Protein", "A top-level protein/molecule"),
                ('CHAIN', "Chain", "A chain within a protein"),
                ('DOMAIN', "Domain", "A sub-region of a chain"),
                ('GROUP', "Group", "A collection of proteins/domains")
            ]
        )
        # These properties DON'T have update functions
        is_selected: BoolProperty(name="Selected", default=False)
        is_visible: BoolProperty(name="Visible", default=True)
        is_expanded: BoolProperty(name="Expanded", default=True)
        depth: IntProperty(name="Depth", description="Indentation level in the outliner", default=0)
    
    try:
        # Register the test class
        bpy.utils.register_class(TestOutlinerItem)
        print("✅ Test property group registered")
        
        # Create a test instance
        test_item = TestOutlinerItem()
        test_item.name = "Test Chain A"
        test_item.type = 'CHAIN'
        test_item.is_selected = False
        test_item.is_visible = True
        
        print(f"✅ Test item created: {test_item.name}")
        print(f"   is_selected: {test_item.is_selected}")
        print(f"   is_visible: {test_item.is_visible}")
        
        # Test changing properties
        print("\n--- Testing property changes ---")
        test_item.is_selected = True
        print(f"✅ Selection changed to: {test_item.is_selected}")
        
        test_item.is_visible = False
        print(f"✅ Visibility changed to: {test_item.is_visible}")
        
        # Clean up
        bpy.utils.unregister_class(TestOutlinerItem)
        print("✅ Test class unregistered")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in test: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to clean up
        try:
            bpy.utils.unregister_class(TestOutlinerItem)
        except:
            pass
        
        return False

def test_property_comparison():
    """Compare the working properties with the outliner properties."""
    
    print("\n=== Property Comparison Test ===")
    
    scene = bpy.context.scene
    
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found")
        return False
    
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) == 0:
        print("❌ No items in outliner state")
        return False
    
    # Get the first item
    item = outliner_state.items[0]
    
    print(f"✅ Testing with item: {item.name}")
    print(f"   Class: {item.__class__.__name__}")
    print(f"   Module: {item.__class__.__module__}")
    
    # Check if properties have update functions
    try:
        import inspect
        cls = item.__class__
        
        # Get the property descriptors
        annotations = getattr(cls, '__annotations__', {})
        
        for prop_name in ['is_selected', 'is_visible']:
            if prop_name in annotations:
                prop_def = annotations[prop_name]
                print(f"   {prop_name}: {prop_def}")
                
                # Try to get the actual property
                if hasattr(cls, prop_name):
                    actual_prop = getattr(cls, prop_name)
                    print(f"     Actual: {actual_prop}")
                    if hasattr(actual_prop, 'keywords'):
                        keywords = actual_prop.keywords
                        if 'update' in keywords:
                            update_func = keywords['update']
                            print(f"     Update function: {update_func}")
                        else:
                            print(f"     No update function")
    
    except Exception as e:
        print(f"❌ Error inspecting properties: {e}")
        import traceback
        traceback.print_exc()
    
    return True

if __name__ == "__main__":
    print("Starting No Update Functions Tests...")
    
    success1 = test_temporary_properties()
    success2 = test_property_comparison()
    
    if success1 and success2:
        print("\n✅ Tests completed")
    else:
        print("\n❌ Some tests failed") 