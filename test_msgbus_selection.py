"""
Test script to verify Message Bus selection detection works in Blender.

This script demonstrates how to use both Message Bus and timers to detect 
selection changes from different sources (Scene Collection, 3D viewport, etc.)

To test:
1. Run this script in Blender
2. Select objects in the Scene Collection outliner
3. Select objects in the 3D viewport
4. Watch the console for messages

The script will output which method caught each selection change.
"""

import bpy

# Global state tracking
_last_selected_objects = set()
_timer_running = False

def msgbus_selection_callback(*args):
    """Called by message bus when selection-related properties change."""
    current_selected = set(obj.name for obj in bpy.context.selected_objects)
    print(f"[MSG BUS] Selection detected: {current_selected}")

def timer_selection_check():
    """Timer-based selection monitoring as fallback."""
    global _last_selected_objects
    
    try:
        current_selected = set(obj.name for obj in bpy.context.selected_objects)
        
        if current_selected != _last_selected_objects:
            print(f"[TIMER] Selection changed: {_last_selected_objects} -> {current_selected}")
            _last_selected_objects = current_selected
            
    except Exception as e:
        print(f"Timer error: {e}")
    
    return 0.2  # Check every 200ms

def setup_selection_monitoring():
    """Set up both message bus and timer monitoring."""
    global _timer_running
    
    # Clear any existing subscriptions
    try:
        bpy.msgbus.clear_by_owner(msgbus_selection_callback)
    except:
        pass
    
    # Set up message bus subscriptions
    try:
        # Subscribe to object selection changes
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Object, "select"),
            owner=msgbus_selection_callback,
            notify=msgbus_selection_callback,
        )
        print("✓ Registered Message Bus for Object.select")
        
        # Subscribe to active object changes  
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.LayerObjects, "active"),
            owner=msgbus_selection_callback,
            notify=msgbus_selection_callback,
        )
        print("✓ Registered Message Bus for LayerObjects.active")
        
        # Subscribe to view layer object changes
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.ViewLayer, "objects"),
            owner=msgbus_selection_callback,
            notify=msgbus_selection_callback,
        )
        print("✓ Registered Message Bus for ViewLayer.objects")
        
    except Exception as e:
        print(f"❌ Failed to register message bus: {e}")
    
    # Set up timer as fallback
    if not _timer_running:
        try:
            bpy.app.timers.register(timer_selection_check)
            _timer_running = True
            print("✓ Registered selection timer")
        except Exception as e:
            print(f"❌ Failed to register timer: {e}")

def cleanup_selection_monitoring():
    """Clean up monitoring."""
    global _timer_running
    
    # Clear message bus
    try:
        bpy.msgbus.clear_by_owner(msgbus_selection_callback)
        print("✓ Cleared message bus subscriptions")
    except:
        pass
    
    # Stop timer
    if _timer_running:
        try:
            bpy.app.timers.unregister(timer_selection_check)
            _timer_running = False
            print("✓ Stopped selection timer")
        except:
            pass

# Initialize monitoring
print("Setting up selection monitoring...")
setup_selection_monitoring()

print("\n" + "="*60)
print("SELECTION MONITORING TEST")
print("="*60)
print("Now test selection changes:")
print("1. Click objects in the Scene Collection outliner")
print("2. Click objects in the 3D viewport") 
print("3. Use Box Select, etc.")
print("4. Watch console output to see which method detects changes")
print("\nRun cleanup_selection_monitoring() when done testing")
print("="*60) 