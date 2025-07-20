"""
Test to verify if update functions are being called.
"""

import bpy

def test_update_function_call():
    """Test if update functions are actually being called."""
    
    print("=== Update Function Call Test ===")
    
    scene = bpy.context.scene
    
    if not hasattr(scene, 'protein_outliner_state'):
        print("❌ No protein_outliner_state found")
        return False
    
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) == 0:
        print("❌ No items found")
        return False
    
    # Find a domain item
    domain_item = None
    domain_index = -1
    for i, item in enumerate(outliner_state.items):
        if item.type == 'DOMAIN':
            domain_item = item
            domain_index = i
            break
    
    if not domain_item:
        print("❌ No domain items found")
        return False
    
    print(f"✅ Found domain item: {domain_item.name}")
    print(f"   Initial is_selected: {domain_item.is_selected}")
    
    # Try to create a simple update function test
    def test_update(self, context):
        print(f"🎯 TEST UPDATE CALLED for {self.name}")
    
    # Check if the property has an update function
    cls = domain_item.__class__
    if hasattr(cls, 'is_selected'):
        prop = getattr(cls, 'is_selected')
        print(f"Property: {prop}")
        if hasattr(prop, 'keywords'):
            keywords = prop.keywords
            print(f"Keywords: {keywords}")
            if 'update' in keywords:
                update_func = keywords['update']
                print(f"Update function: {update_func}")
                print(f"Update function type: {type(update_func)}")
                
                # Try to call it manually
                try:
                    update_func(domain_item, bpy.context)
                    print("✅ Manual update function call succeeded")
                except Exception as e:
                    print(f"❌ Manual update function call failed: {e}")
            else:
                print("❌ No update function found in keywords")
        else:
            print("❌ Property has no keywords")
    else:
        print("❌ is_selected property not found on class")
    
    return True

def test_simple_property_change():
    """Test a simple property change and see what happens."""
    
    print("\n=== Simple Property Change Test ===")
    
    scene = bpy.context.scene
    outliner_state = scene.protein_outliner_state
    
    if len(outliner_state.items) == 0:
        print("❌ No items found")
        return False
    
    # Find a domain item
    domain_item = None
    for item in outliner_state.items:
        if item.type == 'DOMAIN':
            domain_item = item
            break
    
    if not domain_item:
        print("❌ No domain items found")
        return False
    
    print(f"Testing with domain: {domain_item.name}")
    print(f"Before change: is_selected = {domain_item.is_selected}")
    
    # Change the property and immediately check
    domain_item.is_selected = True
    print(f"After setting True: is_selected = {domain_item.is_selected}")
    
    domain_item.is_selected = False  
    print(f"After setting False: is_selected = {domain_item.is_selected}")
    
    return True

if __name__ == "__main__":
    print("Starting Update Function Call Tests...")
    
    success1 = test_update_function_call()
    success2 = test_simple_property_change()
    
    if success1 and success2:
        print("\n✅ Tests completed")
    else:
        print("\n❌ Some tests failed") 