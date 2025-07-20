"""Selection synchronization handler for two-way binding between Blender and ProteinBlender outliner"""

import bpy
from ..utils.scene_manager import ProteinBlenderScene


# Global variables for selection tracking
_last_selection = set()
_selection_update_in_progress = False
_timer_handle = None


def check_selection_changes():
    """Timer function to check for selection changes"""
    global _last_selection, _selection_update_in_progress
    
    if _selection_update_in_progress:
        return 0.1  # Check again in 0.1 seconds
    
    # Ensure we have a valid context
    try:
        if not hasattr(bpy.context, 'selected_objects'):
            return 0.1  # Context not ready, check again
            
        # Get current selection
        current_selection = set(obj.name for obj in bpy.context.selected_objects)
        
        # Check if selection has changed
        if current_selection != _last_selection:
            _last_selection = current_selection
            on_blender_selection_change()
    except Exception:
        # Context not available, just continue
        pass
    
    return 0.1  # Check again in 0.1 seconds


def clear_selection_handlers():
    """Clear timer for selection checking"""
    global _timer_handle
    if _timer_handle is not None:
        try:
            bpy.app.timers.unregister(_timer_handle)
        except Exception:
            pass
        _timer_handle = None


def on_blender_selection_change():
    """Called when user selects objects in viewport/native outliner"""
    global _selection_update_in_progress
    
    # Prevent recursive updates
    if _selection_update_in_progress:
        return
    
    _selection_update_in_progress = True
    try:
        update_outliner_from_blender_selection()
    finally:
        _selection_update_in_progress = False


def update_outliner_from_blender_selection():
    """Update protein outliner selection based on Blender's selection"""
    scene = bpy.context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    selected_objects = bpy.context.selected_objects
    
    # Build set of selected object names for quick lookup
    selected_names = {obj.name for obj in selected_objects}
    
    # Update outliner selection state
    for item in scene.outliner_items:
        # Check if this item's object is selected
        if item.object_name and item.object_name in selected_names:
            item.is_selected = True
        else:
            item.is_selected = False
        
        # For protein items, check if any of their domains are selected
        if item.item_type == 'PROTEIN':
            molecule = scene_manager.molecules.get(item.item_id)
            if molecule:
                # Check if any domain is selected
                any_domain_selected = False
                for domain in molecule.domains.values():
                    if domain.object and domain.object.name in selected_names:
                        any_domain_selected = True
                        break
                
                # If any domain is selected, select the protein too
                if any_domain_selected:
                    item.is_selected = True
    
    # Update UI
    for area in bpy.context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def sync_outliner_to_blender_selection(context, item_id):
    """Sync outliner selection to Blender objects"""
    global _selection_update_in_progress
    
    # Prevent recursive updates
    if _selection_update_in_progress:
        return
    
    _selection_update_in_progress = True
    try:
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find the item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == item_id:
                item = outliner_item
                break
        
        if not item:
            return
        
        # Handle selection based on item type
        if item.item_type == 'PROTEIN':
            # Select/deselect protein and all its domains
            molecule = scene_manager.molecules.get(item_id)
            if molecule and molecule.object:
                molecule.object.select_set(item.is_selected)
                
                # Update all domains
                for domain in molecule.domains.values():
                    if domain.object:
                        domain.object.select_set(item.is_selected)
                
                # Make protein the active object if selected
                if item.is_selected:
                    context.view_layer.objects.active = molecule.object
                    
        elif item.item_type == 'DOMAIN':
            # Select/deselect just the domain
            if item.object_name:
                obj = bpy.data.objects.get(item.object_name)
                if obj:
                    obj.select_set(item.is_selected)
                    
                    # Make domain the active object if selected
                    if item.is_selected:
                        context.view_layer.objects.active = obj
                        
        elif item.item_type == 'CHAIN':
            # Select all domains belonging to this chain
            # First, find the parent protein
            parent_molecule = None
            for outliner_item in scene.outliner_items:
                if outliner_item.item_id == item.parent_id:
                    parent_molecule = scene_manager.molecules.get(outliner_item.item_id)
                    break
            
            if parent_molecule:
                # For now, select the main protein object
                # TODO: Implement proper chain-to-domain mapping
                if parent_molecule.object:
                    parent_molecule.object.select_set(item.is_selected)
                    if item.is_selected:
                        context.view_layer.objects.active = parent_molecule.object
    
    finally:
        _selection_update_in_progress = False


def update_outliner_selection_display(context):
    """Update outliner to show current selection state"""
    # Force redraw of properties panel
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            area.tag_redraw()


def register():
    """Register all selection sync handlers"""
    global _timer_handle
    # Clear any existing timer
    clear_selection_handlers()
    
    # Register timer to check for selection changes
    _timer_handle = bpy.app.timers.register(check_selection_changes, first_interval=0.1)


def unregister():
    """Unregister all selection sync handlers"""
    # Clear timer
    clear_selection_handlers()