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
        # For items with direct objects, check if selected
        if item.object_name and item.object_name in selected_names:
            item.is_selected = True
        else:
            # For chain items, check if any of their domains are selected
            if item.item_type == 'CHAIN':
                # Extract chain info
                chain_id_str = item.item_id.split('_chain_')[-1]
                try:
                    chain_id = int(chain_id_str)
                except:
                    chain_id = chain_id_str
                
                # Get parent molecule
                parent_molecule = scene_manager.molecules.get(item.parent_id)
                if parent_molecule:
                    # Check if any domain of this chain is selected
                    chain_has_selection = False
                    for domain in parent_molecule.domains.values():
                        if domain.object and domain.object.name in selected_names:
                            # Check if domain belongs to this chain
                            domain_chain_id = getattr(domain, 'chain_id', None)
                            
                            # Extract chain from domain name if needed
                            if domain_chain_id is None and hasattr(domain, 'name'):
                                import re
                                match = re.search(r'Chain_([A-Z])', domain.name)
                                if match:
                                    domain_chain_id = match.group(1)
                                elif '_' in domain.name:
                                    match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                                    if match2:
                                        domain_chain_id = int(match2.group(1))
                            
                            # Check if this domain belongs to the chain
                            if domain_chain_id is not None:
                                domain_chain_str = str(domain_chain_id)
                                chain_str = str(chain_id)
                                
                                if domain_chain_str == chain_str or domain_chain_id == chain_id:
                                    chain_has_selection = True
                                    break
                    
                    item.is_selected = chain_has_selection
            else:
                # For other items without objects, deselect
                item.is_selected = False
    
    # Update all reference items to match their originals
    for item in scene.outliner_items:
        if "_ref_" in item.item_id and item.group_memberships:
            # Find the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == item.group_memberships:
                    item.is_selected = orig_item.is_selected
                    break
    
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
        
        # Check if this is a reference item and get the actual item ID
        actual_item_id = item_id
        if "_ref_" in item_id:
            # Find the reference item to get the actual ID
            for ref_item in scene.outliner_items:
                if ref_item.item_id == item_id and ref_item.group_memberships:
                    actual_item_id = ref_item.group_memberships
                    break
        
        # Find the item
        item = None
        for outliner_item in scene.outliner_items:
            if outliner_item.item_id == actual_item_id:
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
            parent_molecule = scene_manager.molecules.get(item.parent_id)
            
            if parent_molecule:
                # Extract chain identifier from item_id (format: "molecule_id_chain_X")
                chain_id_str = item.item_id.split('_chain_')[-1]
                try:
                    chain_id = int(chain_id_str)
                except:
                    chain_id = chain_id_str
                
                # Select/deselect all domains of this chain
                active_set = False
                for domain_id, domain in parent_molecule.domains.items():
                    # Check if domain belongs to this chain
                    domain_chain_id = getattr(domain, 'chain_id', None)
                    
                    # Extract chain from domain name if needed
                    if domain_chain_id is None and hasattr(domain, 'name'):
                        import re
                        match = re.search(r'Chain_([A-Z])', domain.name)
                        if match:
                            domain_chain_id = match.group(1)
                        elif '_' in domain.name:
                            match2 = re.match(r'[^_]+_[^_]+_(\d+)_', domain.name)
                            if match2:
                                domain_chain_id = int(match2.group(1))
                    
                    # Check if this domain belongs to the chain
                    if domain_chain_id is not None:
                        domain_chain_str = str(domain_chain_id)
                        chain_str = str(chain_id)
                        
                        if domain_chain_str == chain_str or domain_chain_id == chain_id:
                            if domain.object:
                                domain.object.select_set(item.is_selected)
                                # Set the first selected domain as active
                                if item.is_selected and not active_set:
                                    context.view_layer.objects.active = domain.object
                                    active_set = True
        
        elif item.item_type == 'GROUP':
            # Select all members of the group
            member_ids = item.group_memberships.split(',') if item.group_memberships else []
            active_set = False
            
            for member_id in member_ids:
                # Find the member item
                member_item = None
                for outliner_item in scene.outliner_items:
                    if outliner_item.item_id == member_id:
                        member_item = outliner_item
                        break
                
                if member_item:
                    # Update the member's selection state to match the group
                    member_item.is_selected = item.is_selected
                    # Update all references to this member
                    for ref_item in scene.outliner_items:
                        if "_ref_" in ref_item.item_id and ref_item.group_memberships == member_id:
                            ref_item.is_selected = item.is_selected
                    # Recursively sync the member
                    sync_outliner_to_blender_selection(context, member_id)
    
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