#!/usr/bin/env python3
"""
Test script to verify 2-way selection synchronization between viewport and checkboxes.
"""

import bpy
import time

def test_selection_sync():
    """Test that selection syncs correctly between viewport and UI checkboxes"""
    print("\n" + "="*60)
    print("2-WAY SELECTION SYNC TEST")
    print("="*60)

    # Get scene manager and scene
    from proteinblender.utils.scene_manager import ProteinBlenderScene
    scene_manager = ProteinBlenderScene.get_instance()
    scene = bpy.context.scene

    # Find a molecule to test with
    if not scene_manager.molecules:
        print("ERROR: No molecules loaded. Please load a protein first.")
        return False

    # Get the first molecule
    molecule_id = list(scene_manager.molecules.keys())[0]
    molecule = scene_manager.molecules[molecule_id]
    print(f"\nTesting with molecule: {molecule_id}")

    # Get domains
    if len(molecule.domains) < 2:
        print("ERROR: Need at least 2 domains to test selection sync.")
        return False

    # Get test domains
    domain_ids = list(molecule.domains.keys())[:2]
    domain1 = molecule.domains[domain_ids[0]]
    domain2 = molecule.domains[domain_ids[1]]

    print(f"Domain 1: {domain1.name} - Object: {domain1.object.name if domain1.object else 'None'}")
    print(f"Domain 2: {domain2.name} - Object: {domain2.object.name if domain2.object else 'None'}")

    # Find outliner items
    domain1_item = None
    domain2_item = None
    chain_item = None

    for item in scene.outliner_items:
        if item.item_type == 'DOMAIN':
            if item.object_name == domain1.object.name:
                domain1_item = item
            elif item.object_name == domain2.object.name:
                domain2_item = item
        elif item.item_type == 'CHAIN' and hasattr(domain1, 'chain_id'):
            if item.item_id.endswith(f"_chain_{domain1.chain_id}"):
                chain_item = item

    if not domain1_item or not domain2_item:
        print("ERROR: Could not find domain items in outliner")
        return False

    print("\n--- TEST 1: Viewport to Checkbox ---")

    # Clear all selections
    bpy.ops.object.select_all(action='DESELECT')
    for item in scene.outliner_items:
        item.is_selected = False

    # Select domain1 in viewport
    domain1.object.select_set(True)
    bpy.context.view_layer.objects.active = domain1.object

    # Force update
    bpy.context.view_layer.update()
    from proteinblender.handlers.selection_sync import update_outliner_from_blender_selection
    update_outliner_from_blender_selection()

    # Check checkbox
    if domain1_item.is_selected:
        print("✅ Domain 1 checkbox checked when selected in viewport")
    else:
        print("❌ Domain 1 checkbox NOT checked when selected in viewport")

    if not domain2_item.is_selected:
        print("✅ Domain 2 checkbox remains unchecked")
    else:
        print("❌ Domain 2 checkbox incorrectly checked")

    if chain_item and not chain_item.is_selected:
        print("✅ Chain checkbox remains unchecked (no cascade)")
    elif chain_item and chain_item.is_selected:
        print("❌ Chain checkbox auto-selected (cascade bug)")

    print("\n--- TEST 2: Checkbox to Viewport ---")

    # Clear selections
    bpy.ops.object.select_all(action='DESELECT')
    for item in scene.outliner_items:
        item.is_selected = False

    # Select domain2 via checkbox
    domain2_item.is_selected = True
    from proteinblender.handlers.selection_sync import sync_outliner_to_blender_selection
    sync_outliner_to_blender_selection(bpy.context, domain2_item.item_id)

    # Check viewport
    if domain2.object.select_get():
        print("✅ Domain 2 selected in viewport when checkbox checked")
    else:
        print("❌ Domain 2 NOT selected in viewport when checkbox checked")

    if not domain1.object.select_get():
        print("✅ Domain 1 remains unselected in viewport")
    else:
        print("❌ Domain 1 incorrectly selected in viewport")

    print("\n--- TEST 3: Deselection Sync ---")

    # Select both domains
    domain1.object.select_set(True)
    domain2.object.select_set(True)
    update_outliner_from_blender_selection()

    # Now deselect in viewport
    bpy.ops.object.select_all(action='DESELECT')
    update_outliner_from_blender_selection()

    # Check checkboxes are unchecked
    if not domain1_item.is_selected and not domain2_item.is_selected:
        print("✅ Checkboxes unchecked when deselected in viewport")
    else:
        print("❌ Checkboxes still checked after viewport deselection")

    print("\n--- TEST 4: Chain Independence ---")

    if chain_item:
        # Select chain checkbox
        chain_item.is_selected = True
        sync_outliner_to_blender_selection(bpy.context, chain_item.item_id)

        # Check that domains are selected
        if domain1.object.select_get() and domain1_item.is_selected:
            print("✅ Chain checkbox selects all domains")
        else:
            print("❌ Chain checkbox doesn't select domains")

        # Now deselect just one domain in viewport
        domain1.object.select_set(False)
        update_outliner_from_blender_selection()

        # Chain should be deselected since not all domains are selected
        if not chain_item.is_selected:
            print("✅ Chain unchecks when not all domains selected")
        else:
            print("⚠️  Chain remains checked with partial domain selection")

    print("\n" + "="*60)
    print("Selection sync test complete!")
    print("="*60)
    return True

# Run the test
if __name__ == "__main__":
    test_selection_sync()