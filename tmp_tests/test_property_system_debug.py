"""
Comprehensive test to diagnose property system issues.
"""

import bpy

def test_basic_property_access():
    """Test if we can access and modify properties directly."""
    
    print("=== Basic Property Access Test ===")
    
    scene = bpy.context.scene
    
    # Check if outliner state exists
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found on scene")
        return False
    
    outliner_state = scene.protein_outliner_state
    print(f"✅ Found outliner_state: {outliner_state}")
    print(f"   Type: {type(outliner_state)}")
    print(f"   Items count: {len(outliner_state.items)}")
    
    if len(outliner_state.items) == 0:
        print("❌ No items in outliner state")
        return False
    
    # Test the first item
    item = outliner_state.items[0]
    print(f"\n--- Testing item 0: {item.name} ---")
    print(f"   Type: {type(item)}")
    print(f"   Class: {item.__class__}")
    print(f"   Module: {item.__class__.__module__}")
    
    # Test property access
    try:
        print(f"   is_selected: {item.is_selected} (type: {type(item.is_selected)})")
        print(f"   is_visible: {item.is_visible} (type: {type(item.is_visible)})")
    except Exception as e:
        print(f"❌ Error accessing properties: {e}")
        return False
    
    # Test property modification
    try:
        original_selected = item.is_selected
        print(f"\n--- Testing property modification ---")
        print(f"   Original is_selected: {original_selected}")
        
        # Try to change it
        item.is_selected = not original_selected
        new_selected = item.is_selected
        print(f"   After change: {new_selected}")
        
        if new_selected == original_selected:
            print("❌ Property did not change!")
            return False
        else:
            print("✅ Property changed successfully")
            
        # Reset it
        item.is_selected = original_selected
        print(f"   Reset to: {item.is_selected}")
        
    except Exception as e:
        print(f"❌ Error modifying property: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_property_registration():
    """Test if the property classes are properly registered."""
    
    print("\n=== Property Registration Test ===")
    
    try:
        from proteinblender.properties.outliner_properties import OutlinerListItem, ProteinOutlinerState
        
        print(f"✅ OutlinerListItem: {OutlinerListItem}")
        print(f"✅ ProteinOutlinerState: {ProteinOutlinerState}")
        
        # Check if they're registered in Blender
        if hasattr(bpy.types, 'OutlinerListItem'):
            print("✅ OutlinerListItem is registered in bpy.types")
        else:
            print("❌ OutlinerListItem NOT found in bpy.types")
            
        if hasattr(bpy.types, 'ProteinOutlinerState'):
            print("✅ ProteinOutlinerState is registered in bpy.types")
        else:
            print("❌ ProteinOutlinerState NOT found in bpy.types")
        
        # Check scene property
        scene = bpy.context.scene
        if hasattr(bpy.types.Scene, 'protein_outliner_state'):
            print("✅ protein_outliner_state is registered on Scene")
        else:
            print("❌ protein_outliner_state NOT found on Scene")
            
        return True
        
    except Exception as e:
        print(f"❌ Error checking registration: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_property_descriptors():
    """Test the property descriptors on the class."""
    
    print("\n=== Property Descriptors Test ===")
    
    try:
        from proteinblender.properties.outliner_properties import OutlinerListItem
        
        print(f"OutlinerListItem class: {OutlinerListItem}")
        
        # Check class annotations
        annotations = getattr(OutlinerListItem, '__annotations__', {})
        print(f"Annotations: {annotations}")
        
        # Check specific properties
        for prop_name in ['is_selected', 'is_visible']:
            if hasattr(OutlinerListItem, prop_name):
                prop = getattr(OutlinerListItem, prop_name)
                print(f"✅ {prop_name}: {prop}")
                print(f"   Type: {type(prop)}")
                if hasattr(prop, 'keywords'):
                    print(f"   Keywords: {prop.keywords}")
            else:
                print(f"❌ {prop_name} not found on class")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking descriptors: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_context_and_scene():
    """Test if the context and scene are correct."""
    
    print("\n=== Context and Scene Test ===")
    
    context = bpy.context
    print(f"Context: {context}")
    print(f"Context type: {type(context)}")
    
    scene = context.scene
    print(f"Scene: {scene}")
    print(f"Scene name: {scene.name}")
    print(f"Scene type: {type(scene)}")
    
    # Check if we're in the right context for UI
    if hasattr(context, 'area'):
        print(f"Area: {context.area}")
        if context.area:
            print(f"Area type: {context.area.type}")
    
    return True

def test_simple_panel_rendering():
    """Test if we can create a simple panel with basic properties."""
    
    print("\n=== Simple Panel Rendering Test ===")
    
    # Create a simple test property
    bpy.types.Scene.test_bool = bpy.props.BoolProperty(name="Test Bool", default=False)
    
    scene = bpy.context.scene
    
    print(f"Test property initial value: {scene.test_bool}")
    
    # Try to change it
    scene.test_bool = True
    print(f"Test property after change: {scene.test_bool}")
    
    # Clean up
    del bpy.types.Scene.test_bool
    
    print("✅ Simple property test completed")
    return True

if __name__ == "__main__":
    print("Starting Property System Debug Tests...")
    
    success1 = test_basic_property_access()
    success2 = test_property_registration()
    success3 = test_property_descriptors()
    success4 = test_context_and_scene()
    success5 = test_simple_panel_rendering()
    
    print(f"\n=== Test Results ===")
    print(f"Basic Access: {'✅' if success1 else '❌'}")
    print(f"Registration: {'✅' if success2 else '❌'}")
    print(f"Descriptors: {'✅' if success3 else '❌'}")
    print(f"Context: {'✅' if success4 else '❌'}")
    print(f"Simple Panel: {'✅' if success5 else '❌'}")
    
    if all([success1, success2, success3, success4, success5]):
        print("\n🎉 All tests passed - the issue might be elsewhere")
    else:
        print("\n❌ Some fundamental issues found") 