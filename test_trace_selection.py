"""
Trace exactly what happens when selecting items to understand the difference.
"""

import bpy

print("\n" + "="*60)
print("Tracing Selection Mechanism")
print("="*60)

# Find test items
chain_item = None
puppet_item = None

for item in bpy.context.scene.outliner_items:
    if not chain_item and item.item_type == 'CHAIN' and item.object_name:
        chain_item = item
    if not puppet_item and item.item_type == 'PUPPET' and item.object_name:
        puppet_item = item
    if chain_item and puppet_item:
        break

print("\nTest Items:")
if chain_item:
    print(f"Chain: {chain_item.name}")
    print(f"  object_name: {chain_item.object_name}")
if puppet_item:
    print(f"Puppet: {puppet_item.name}")
    print(f"  object_name: {puppet_item.object_name}")
    print(f"  controller_object_name: {puppet_item.controller_object_name}")

# Check if the actual handler is checking object_name
print("\n--- Testing Handler Logic ---")

# Get selected object names
selected_names = {obj.name for obj in bpy.context.selected_objects}
print(f"Currently selected objects: {selected_names}")

# Simulate what the handler should do
print("\nSimulating sync logic:")
for item in bpy.context.scene.outliner_items[:10]:  # Just check first 10
    if item.object_name:
        should_be_selected = item.object_name in selected_names
        print(f"  {item.name} (type: {item.item_type}):")
        print(f"    object_name: {item.object_name}")
        print(f"    in selected_names: {item.object_name in selected_names}")
        print(f"    current is_selected: {item.is_selected}")
        print(f"    should be: {should_be_selected}")

        if item.item_type == 'PUPPET':
            print(f"    *** PUPPET FOUND - checking if object_name works ***")
            if item.object_name in selected_names:
                print(f"    ✓ Puppet SHOULD be selected based on object_name!")
            else:
                print(f"    ✗ Puppet NOT in selected objects")

# Try to access the actual module to see what's happening
print("\n--- Checking Module Access ---")
import sys

# Look for any proteinblender modules
pb_modules = [m for m in sys.modules.keys() if 'proteinblender' in m.lower()]
print(f"ProteinBlender modules in sys.modules: {len(pb_modules)}")
for m in pb_modules[:5]:  # Show first 5
    print(f"  - {m}")

# Try the bl_ext path
try:
    from bl_ext.vscode_development.proteinblender.handlers import selection_sync as bl_sel_sync
    print("\n✓ Successfully imported selection_sync via bl_ext path")

    # Check if update function exists
    if hasattr(bl_sel_sync, 'update_outliner_from_blender_selection'):
        print("✓ update_outliner_from_blender_selection exists")

        # Try calling it manually
        print("\n--- Manually calling sync function ---")
        bl_sel_sync.update_outliner_from_blender_selection()

        # Check puppet state after
        if puppet_item:
            print(f"Puppet is_selected after manual sync: {puppet_item.is_selected}")

except Exception as e:
    print(f"\n✗ Could not import via bl_ext: {e}")

print("\n" + "="*60)