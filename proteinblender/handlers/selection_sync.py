"""Selection synchronization handler for two-way binding between Blender and ProteinBlender outliner"""

import bpy
from ..utils.scene_manager import ProteinBlenderScene


# Global variables for selection tracking
_last_selection = set()
_selection_update_depth = 0  # Use depth counter instead of boolean
_timer_handle = None
_skip_timer_until = 0  # Timestamp to skip timer updates until


def check_selection_changes():
    """Timer function to check for selection changes"""
    global _last_selection, _selection_update_depth, _skip_timer_until
    
    import time
    current_time = time.time()
    
    # Skip if we're within the skip window
    if current_time < _skip_timer_until:
        return 0.1
    
    if _selection_update_depth > 0:
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
    global _selection_update_depth
    
    # Prevent recursive updates
    if _selection_update_depth > 0:
        return
    
    _selection_update_depth += 1
    try:
        update_outliner_from_blender_selection()
    finally:
        _selection_update_depth -= 1


def update_outliner_from_blender_selection():
    """Update protein outliner selection based on Blender's selection"""
    scene = bpy.context.scene
    scene_manager = ProteinBlenderScene.get_instance()
    selected_objects = bpy.context.selected_objects
    
    # Build set of selected object names for quick lookup
    selected_names = {obj.name for obj in selected_objects}
    
    # First check if any puppet Empty controllers are selected
    for item in scene.outliner_items:
        if item.item_type == 'PUPPET' and item.controller_object_name:
            # Check if the Empty controller is selected
            if item.controller_object_name in selected_names:
                item.is_selected = True
            else:
                item.is_selected = False
    
    # Update outliner selection state for other items
    for item in scene.outliner_items:
        # Skip puppets - already handled above
        if item.item_type == 'PUPPET':
            continue
        # For items with direct objects, check if selected
        elif item.object_name and item.object_name in selected_names:
            item.is_selected = True
        elif item.item_type == 'CHAIN':
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
                    if domain.object:
                        try:
                            # Check if object is still valid before accessing it
                            obj_name = domain.object.name
                            if obj_name in selected_names:
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
                        except ReferenceError:
                            # Object has been removed, skip this domain
                            pass
                
                item.is_selected = chain_has_selection
            else:
                item.is_selected = False
        else:
            # For other items without objects, deselect
            item.is_selected = False
    
    # Update all reference items to match their originals
    # This is a one-way sync from original to reference only
    for item in scene.outliner_items:
        if "_ref_" in item.item_id and item.puppet_memberships:
            # Find the original item
            for orig_item in scene.outliner_items:
                if orig_item.item_id == item.puppet_memberships:
                    if item.is_selected != orig_item.is_selected:
                        item.is_selected = orig_item.is_selected
                    break
    
    # When a puppet Empty is selected/deselected, also update all its member items
    for puppet_item in scene.outliner_items:
        if puppet_item.item_type == 'PUPPET':
            # Get member IDs from the puppet
            member_ids = puppet_item.puppet_memberships.split(',') if puppet_item.puppet_memberships else []
            
            # Update all reference items under this puppet to match puppet's selection state
            for ref_item in scene.outliner_items:
                if ref_item.parent_id == puppet_item.item_id and "_ref_" in ref_item.item_id:
                    ref_item.is_selected = puppet_item.is_selected
            
            # Also update the original items to match puppet's selection state
            for member_id in member_ids:
                for item in scene.outliner_items:
                    if item.item_id == member_id:
                        item.is_selected = puppet_item.is_selected
                        break
    
    # Sync color picker to match selected item's color
    from ..panels.visual_setup_panel import sync_color_to_selection
    sync_color_to_selection(bpy.context)
    
    # Update UI - force redraw to show checkbox changes
    for area in bpy.context.screen.areas:
        if area.type in ['PROPERTIES', 'VIEW_3D']:
            area.tag_redraw()
    
    # Also force region redraw
    if bpy.context.region:
        bpy.context.region.tag_redraw()


def sync_outliner_to_blender_selection(context, item_id):
    """Sync outliner selection to Blender objects"""
    global _selection_update_depth, _skip_timer_until
    
    # Set skip timer to prevent timer updates during this operation
    import time
    _skip_timer_until = time.time() + 0.1  # Reduced from 300ms to 100ms
    
    # Prevent recursive updates
    if _selection_update_depth > 2:  # Allow some depth for legitimate nested calls
        return
    
    _selection_update_depth += 1
    try:
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Check if this is a reference item and get the actual item ID
        actual_item_id = item_id
        if "_ref_" in item_id:
            # Find the reference item to get the actual ID
            for ref_item in scene.outliner_items:
                if ref_item.item_id == item_id and ref_item.puppet_memberships:
                    actual_item_id = ref_item.puppet_memberships
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
                        try:
                            # Check if object is still valid before accessing it
                            domain.object.name  # This will raise ReferenceError if invalid
                            domain.object.select_set(item.is_selected)
                        except ReferenceError:
                            # Object has been removed, try to refresh from name
                            if hasattr(domain, 'object_name') and domain.object_name:
                                fresh_obj = bpy.data.objects.get(domain.object_name)
                                if fresh_obj:
                                    domain.object = fresh_obj
                                    fresh_obj.select_set(item.is_selected)
                
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
            # Check if this is a chain copy (item_id is directly a domain_id)
            # or a regular chain (item_id is "molecule_id_chain_X")
            parent_molecule = scene_manager.molecules.get(item.parent_id)
            
            if parent_molecule:
                # First check if item_id is directly a domain_id (for chain copies)
                if item.item_id in parent_molecule.domains:
                    # This is a chain copy - select only this specific domain
                    target_domain = parent_molecule.domains[item.item_id]
                    
                    if target_domain and target_domain.object:
                        try:
                            # Check if object is still valid before accessing it
                            target_domain.object.name  # This will raise ReferenceError if invalid
                            target_domain.object.select_set(item.is_selected)
                            # Set as active if selected
                            if item.is_selected:
                                context.view_layer.objects.active = target_domain.object
                        except ReferenceError:
                            # Object has been removed, try to refresh from name
                            if hasattr(target_domain, 'object_name') and target_domain.object_name:
                                fresh_obj = bpy.data.objects.get(target_domain.object_name)
                                if fresh_obj:
                                    target_domain.object = fresh_obj
                                    fresh_obj.select_set(item.is_selected)
                                    if item.is_selected:
                                        context.view_layer.objects.active = fresh_obj
                
                else:
                    # Regular chain - select all non-copy domains belonging to this chain
                    # Extract chain identifier from item_id (format: "molecule_id_chain_X")
                    chain_id_str = item.item_id.split('_chain_')[-1]
                    try:
                        chain_id = int(chain_id_str)
                    except:
                        chain_id = chain_id_str
                    
                    # Select/deselect all non-copy domains of this chain
                    active_set = False
                    for domain_id, domain in parent_molecule.domains.items():
                        # Skip domain copies - they have their own chain items
                        if hasattr(domain, 'is_copy') and domain.is_copy:
                            continue
                            
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
                                    try:
                                        # Check if object is still valid before accessing it
                                        domain.object.name  # This will raise ReferenceError if invalid
                                        domain.object.select_set(item.is_selected)
                                        # Set the first selected domain as active
                                        if item.is_selected and not active_set:
                                            context.view_layer.objects.active = domain.object
                                            active_set = True
                                    except ReferenceError:
                                        # Object has been removed, try to refresh from name
                                        if hasattr(domain, 'object_name') and domain.object_name:
                                            fresh_obj = bpy.data.objects.get(domain.object_name)
                                            if fresh_obj:
                                                domain.object = fresh_obj
                                                fresh_obj.select_set(item.is_selected)
                                                if item.is_selected and not active_set:
                                                    context.view_layer.objects.active = fresh_obj
                                                    active_set = True
        
        elif item.item_type == 'PUPPET':
            # Select/deselect the puppet's Empty controller if it exists
            puppet_item = item
            if puppet_item.controller_object_name:
                empty_obj = bpy.data.objects.get(puppet_item.controller_object_name)
                if empty_obj:
                    empty_obj.select_set(item.is_selected)
                    
                    # Make Empty the active object if selected
                    if item.is_selected:
                        context.view_layer.objects.active = empty_obj
            
            # Don't cascade to members - the Empty's parent-child relationship handles that
            return
    
    finally:
        _selection_update_depth -= 1


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