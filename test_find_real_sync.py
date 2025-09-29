"""
Find what's actually making chains auto-sync since msgbus isn't working.
"""

import bpy

print("\n" + "="*60)
print("Finding the Real Sync Mechanism")
print("="*60)

# Check ALL handlers that might be updating selection
print("All registered handlers:")
handler_types = [
    'depsgraph_update_pre',
    'depsgraph_update_post',
    'frame_change_pre',
    'frame_change_post',
    'undo_pre',
    'undo_post',
    'redo_pre',
    'redo_post',
    'load_post',
    'save_pre',
    'save_post'
]

for handler_type in handler_types:
    if hasattr(bpy.app.handlers, handler_type):
        handlers = getattr(bpy.app.handlers, handler_type)
        if handlers:
            print(f"\n{handler_type}: {len(handlers)} handlers")
            for h in handlers:
                print(f"  - {h.__name__ if hasattr(h, '__name__') else h}")
                if hasattr(h, '__module__'):
                    print(f"    Module: {h.__module__}")

# Now let's test if selecting a chain triggers depsgraph update
print("\n" + "="*60)
print("Testing Chain Selection")
print("="*60)

# Find a chain
chain_item = None
for item in bpy.context.scene.outliner_items:
    if item.item_type == 'CHAIN' and item.object_name:
        chain_item = item
        break

if chain_item:
    chain_obj = bpy.data.objects.get(chain_item.object_name)
    if chain_obj:
        print(f"Testing with: {chain_item.name}")
        print(f"Object: {chain_obj.name}")

        # Deselect first
        bpy.ops.object.select_all(action='DESELECT')
        chain_item.is_selected = False

        print(f"\nBefore selection:")
        print(f"  Object selected: {chain_obj.select_get()}")
        print(f"  Checkbox state: {chain_item.is_selected}")

        # Select the chain
        chain_obj.select_set(True)

        print(f"\nAfter selection (immediate):")
        print(f"  Object selected: {chain_obj.select_get()}")
        print(f"  Checkbox state: {chain_item.is_selected}")

        # The depsgraph handler should have fired by now if it's working

print("\n" + "="*60)
print("Testing if there's a UI update trigger")
print("="*60)

# Maybe the sync happens during UI drawing?
# Check if there's any special handling in the outliner panel draw

try:
    # Check if there's a draw callback or update in the panel
    from bl_ext.vscode_development.proteinblender.panels import protein_outliner_panel

    if hasattr(protein_outliner_panel, 'PROTEINBLENDER_PT_outliner'):
        panel_class = protein_outliner_panel.PROTEINBLENDER_PT_outliner
        print(f"✓ Found outliner panel class")

        # Check if draw method does any sync
        if hasattr(panel_class, 'draw'):
            import inspect
            source = inspect.getsource(panel_class.draw)
            if 'sync' in source.lower() or 'update' in source.lower():
                print("  Panel draw method contains sync/update logic")
            else:
                print("  Panel draw method doesn't contain sync/update logic")

except Exception as e:
    print(f"✗ Could not check panel: {e}")

print("\n" + "="*60)