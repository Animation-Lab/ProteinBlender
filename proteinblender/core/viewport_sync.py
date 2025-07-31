"""Viewport synchronization utilities"""

import bpy


def force_viewport_sync(scene):
    """Force synchronization of outliner selection to viewport"""
    
    # Get the 3D viewport's view layer
    view_3d_area = None
    view_layer = None
    
    # Find a 3D viewport
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                view_3d_area = area
                # Get the window's view layer
                with bpy.context.temp_override(window=window, area=area):
                    view_layer = bpy.context.view_layer
                break
        if view_3d_area:
            break
    
    if not view_layer:
        view_layer = bpy.context.view_layer
    
    # Ensure we're in object mode
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except:
            pass
    
    # First deselect all objects
    for obj in bpy.data.objects:
        try:
            obj.select_set(False, view_layer=view_layer)
        except:
            pass
    
    # First, build a set of what should be selected based on outliner
    should_be_selected = set()
    
    for item in scene.outliner_items:
        if item.is_selected and item.object_name:
            should_be_selected.add(item.object_name)
        
        # For chains without domains, we need to select the protein object
        if item.is_selected and item.item_type == 'CHAIN':
            # Find all children (domains)
            has_children = False
            for child in scene.outliner_items:
                if child.parent_id == item.item_id and child.object_name:
                    should_be_selected.add(child.object_name)
                    has_children = True
            
            # If chain has no children, select the parent protein's object
            if not has_children and item.parent_id:
                # Find parent protein
                for parent in scene.outliner_items:
                    if parent.item_id == item.parent_id and parent.object_name:
                        should_be_selected.add(parent.object_name)
                        break
        
        # If a protein is selected, all its children's objects should be selected
        if item.is_selected and item.item_type == 'PROTEIN':
            # Add the protein's own object
            if item.object_name:
                should_be_selected.add(item.object_name)
            # Find all children and add their objects
            for child in scene.outliner_items:
                if child.parent_id == item.item_id and child.object_name:
                    should_be_selected.add(child.object_name)
    
    
    # Now select the objects that should be selected
    print(f"DEBUG: Objects to select: {should_be_selected}")
    print(f"DEBUG: Using view_layer: {view_layer}")
    
    for obj in bpy.data.objects:
        if obj.name in should_be_selected:
            print(f"DEBUG: Selecting {obj.name}")
            
            # Check if object is in view layer
            obj_in_vl = False
            try:
                # This will raise an exception if object is not in view layer
                _ = obj.select_get(view_layer=view_layer)
                obj_in_vl = True
            except:
                print(f"DEBUG: {obj.name} not in view layer!")
            
            if obj_in_vl:
                try:
                    obj.select_set(True, view_layer=view_layer)
                    # Double check it worked
                    selected = obj.select_get(view_layer=view_layer)
                    print(f"DEBUG: {obj.name} selected: {selected}")
                except Exception as e:
                    print(f"DEBUG: Error selecting {obj.name}: {e}")
    
    # Update active object if needed
    if view_layer.objects.active is None:
        # Find first selected object to make active
        for obj in bpy.data.objects:
            try:
                if obj.select_get(view_layer=view_layer):
                    view_layer.objects.active = obj
                    print(f"DEBUG: Set active object: {obj.name}")
                    break
            except:
                pass
    
    # Force update the 3D viewport
    if view_3d_area:
        view_3d_area.tag_redraw()
        # Also update all regions in the area
        for region in view_3d_area.regions:
            region.tag_redraw()
        
        # Ensure selection is visible in viewport
        with bpy.context.temp_override(window=bpy.context.window, area=view_3d_area):
            # Update the viewport to show selection
            bpy.context.view_layer.update()
            
            # Ensure overlays are enabled to show selection
            space_view3d = view_3d_area.spaces.active
            if hasattr(space_view3d, 'overlay'):
                space_view3d.overlay.show_overlays = True
                space_view3d.overlay.show_outline_selected = True
                print(f"DEBUG: Overlays enabled: {space_view3d.overlay.show_overlays}")
                print(f"DEBUG: Selection outline enabled: {space_view3d.overlay.show_outline_selected}")
    
    # Final check - what's actually selected in viewport
    with bpy.context.temp_override(view_layer=view_layer):
        selected_in_viewport = [obj.name for obj in bpy.context.selected_objects]
        print(f"DEBUG: Final selected objects in viewport: {selected_in_viewport}")
    
    # Force depsgraph update
    bpy.context.evaluated_depsgraph_get().update()
    
    # One more redraw for good measure
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def sync_selection_to_viewport(item_id, state, scene=None):
    """Sync a single item's selection to viewport"""
    if scene is None:
        scene = bpy.context.scene
    
    # Find the item
    item = None
    for outliner_item in scene.outliner_items:
        if outliner_item.item_id == item_id:
            item = outliner_item
            break
    
    if not item or not item.object_name:
        return
    
    obj = bpy.data.objects.get(item.object_name)
    if not obj:
        return
    
    view_layer = bpy.context.view_layer
    obj.select_set(state, view_layer=view_layer)