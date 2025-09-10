"""
Test script for domain selection color/style synchronization fix.

This script tests that when a domain is selected in the Protein Outliner,
the Visual Setup panel correctly updates to show that domain's color and style.
"""

import bpy

def test_domain_selection_sync():
    """Test that selecting a domain updates the visual setup panel"""
    print("\n" + "="*60)
    print("Testing Domain Selection Color/Style Sync")
    print("="*60)
    
    scene = bpy.context.scene
    
    # Check if there are any outliner items
    if not hasattr(scene, 'outliner_items') or len(scene.outliner_items) == 0:
        print("ERROR: No proteins loaded. Please load a protein first.")
        return False
    
    # Find a domain item to test with
    domain_item = None
    for item in scene.outliner_items:
        if item.item_type == 'DOMAIN':
            domain_item = item
            break
    
    if not domain_item:
        print("ERROR: No domain items found in outliner.")
        return False
    
    print(f"\nFound domain to test: {domain_item.name}")
    print(f"Domain ID: {domain_item.item_id}")
    print(f"Object name: {domain_item.object_name}")
    
    # First, deselect all items
    print("\n1. Deselecting all items...")
    for item in scene.outliner_items:
        item.is_selected = False
    
    # Get the initial color and style values
    initial_color = tuple(scene.visual_setup_color)
    initial_style = scene.visual_setup_style
    print(f"\nInitial color: R={initial_color[0]:.2f}, G={initial_color[1]:.2f}, B={initial_color[2]:.2f}, A={initial_color[3]:.2f}")
    print(f"Initial style: {initial_style}")
    
    # Select the domain
    print(f"\n2. Selecting domain: {domain_item.name}")
    domain_item.is_selected = True
    
    # Trigger the sync manually (simulating what happens in the operator)
    from proteinblender.panels.visual_setup_panel import sync_color_to_selection
    sync_color_to_selection(bpy.context)
    
    # Check if the color and style were updated
    new_color = tuple(scene.visual_setup_color)
    new_style = scene.visual_setup_style
    print(f"\n3. After selection:")
    print(f"   Color: R={new_color[0]:.2f}, G={new_color[1]:.2f}, B={new_color[2]:.2f}, A={new_color[3]:.2f}")
    print(f"   Style: {new_style}")
    
    # Test selecting a different domain if available
    second_domain = None
    for item in scene.outliner_items:
        if item.item_type == 'DOMAIN' and item.item_id != domain_item.item_id:
            second_domain = item
            break
    
    if second_domain:
        print(f"\n4. Testing with second domain: {second_domain.name}")
        
        # Deselect first domain
        domain_item.is_selected = False
        
        # Select second domain
        second_domain.is_selected = True
        
        # Trigger sync again
        sync_color_to_selection(bpy.context)
        
        # Check the new values
        second_color = tuple(scene.visual_setup_color)
        second_style = scene.visual_setup_style
        print(f"   Color: R={second_color[0]:.2f}, G={second_color[1]:.2f}, B={second_color[2]:.2f}, A={second_color[3]:.2f}")
        print(f"   Style: {second_style}")
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)
    print("\nTo verify the fix works:")
    print("1. The color picker should update when selecting different domains")
    print("2. The style dropdown should update to match the selected domain's style")
    print("3. Check the console output above to see if colors/styles changed")
    print("\nNOTE: If you see 'sync_color_to_selection: Could not find object' errors,")
    print("      it means the domain objects aren't properly linked in the scene manager.")
    
    return True

# Run the test
if __name__ == "__main__":
    test_domain_selection_sync()