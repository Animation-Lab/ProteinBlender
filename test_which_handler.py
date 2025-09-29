"""
Check which depsgraph handler is actually registered and working.
"""

import bpy

print("\n" + "="*60)
print("Checking Which Handler Is Active")
print("="*60)

# Check what's in depsgraph_update_post handlers
print("\nDepsgraph update post handlers:")
for handler in bpy.app.handlers.depsgraph_update_post:
    print(f"  Handler: {handler}")
    if hasattr(handler, '__module__'):
        print(f"    Module: {handler.__module__}")
    if hasattr(handler, '__name__'):
        print(f"    Name: {handler.__name__}")

# Try to import both handlers and check if they match
print("\n--- Checking handler sources ---")

# Check if selection_sync version is registered
try:
    from proteinblender.handlers import selection_sync
    if hasattr(selection_sync, 'on_depsgraph_update_post'):
        print("✓ selection_sync.on_depsgraph_update_post exists")
        for handler in bpy.app.handlers.depsgraph_update_post:
            if handler == selection_sync.on_depsgraph_update_post:
                print("  ✓ IT IS REGISTERED!")
                break
        else:
            print("  ✗ But it's NOT registered")
except Exception as e:
    print(f"✗ Can't check selection_sync: {e}")

# Check if depsgraph_handler version is registered
try:
    from proteinblender.handlers import depsgraph_handler
    if hasattr(depsgraph_handler, 'on_depsgraph_update'):
        print("✓ depsgraph_handler.on_depsgraph_update exists")
        # Note: different function name, so it won't be in depsgraph_update_post
        print("  (But it has different name, not _post)")
except Exception as e:
    print(f"✗ Can't check depsgraph_handler: {e}")

print("\n" + "="*60)