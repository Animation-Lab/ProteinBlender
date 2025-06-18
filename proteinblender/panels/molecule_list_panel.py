import bpy
from bpy.types import Panel, Operator
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene
from ..operators.domain_operators import MOLECULE_PB_OT_toggle_pivot_edit

# Ensure domain properties are registered
from ..core.domain import ensure_domain_properties_registered
ensure_domain_properties_registered()

class MOLECULE_PB_PT_list(Panel):
    bl_label = "Molecules in Scene"
    bl_idname = "MOLECULE_PB_PT_list"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    
    @classmethod
    def poll(cls, context):
        return True
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # (Removed early sync hack; rely on undo_post handler for restoration)
        
        # Create box for list
        box = layout.box()
        # Gather valid molecule entries (object still exists)
        valid_molecules = []
        for molecule_id, molecule in scene_manager.molecules.items():
            try:
                obj = molecule.object
                if obj and obj.name in bpy.data.objects:
                    valid_molecules.append((molecule_id, molecule))
            except ReferenceError:
                continue
        # If none, show message
        if not valid_molecules:
            box.label(text="No molecules in scene", icon='INFO')
            return
        # Create column for valid molecule entries
        col = box.column()
        for molecule_id, molecule in valid_molecules:
            row = col.row(align=True)
            
            # Create clickable operator for selection
            name_op = row.operator(
                "molecule.select",
                text=molecule.identifier,
                depress=(molecule_id == scene.selected_molecule_id)
            )
            name_op.molecule_id = molecule_id
            
            if molecule.object:
                # Add select object button
                select_op = row.operator(
                    "molecule.select_object",
                    text="",
                    icon='RESTRICT_SELECT_OFF'
                )
                select_op.object_id = molecule_id
                select_op.is_domain = False
                
                # Visibility toggle
                vis_row = row.row()
                # Toggle visibility of molecule and its domains
                toggle_vis = vis_row.operator(
                    "molecule.toggle_visibility",
                    text="",
                    emboss=False,
                    icon='HIDE_OFF' if not molecule.object.hide_viewport else 'HIDE_ON'
                )
                toggle_vis.molecule_id = molecule_id
                
                # Delete button
                delete_op = row.operator("molecule.delete", text="", icon='X')
                if delete_op:
                    delete_op.molecule_id = molecule_id
            
            # If this molecule is selected, show its settings
            if molecule_id == scene.selected_molecule_id:
                settings_box = col.box()
                settings_box.separator()
                
                # Identifier editor
                id_row = settings_box.row(align=True)
                id_row.prop(scene, "edit_molecule_identifier", text="Identifier")
                id_row.operator("molecule.update_identifier", text="", icon='CHECKMARK')
                
                # Style selector
                style_row = settings_box.row()
                style_row.label(text="Style:")
                style_row.prop(scene, "molecule_style", text="")
                
                # --- Protein Pivot Controls ---
                if molecule.object:
                    pivot_box = settings_box.box()
                    pivot_box.label(text="Protein Pivot", icon='PIVOT_BOUNDBOX')
                    pivot_row = pivot_box.row(align=True)
                    # Interactive Move/Set Pivot button
                    is_editing = False
                    helper_name = f"PB_PivotHelper_{molecule_id}"
                    if helper_name in bpy.data.objects:
                        is_editing = True
                    button_text = "Set Pivot" if is_editing else "Move Pivot"
                    button_icon = 'CHECKMARK' if is_editing else 'PIVOT_CURSOR'
                    move_pivot_op = pivot_row.operator(
                        "molecule.toggle_protein_pivot_edit",
                        text=button_text,
                        icon=button_icon,
                        depress=is_editing
                    )
                    if move_pivot_op:
                        move_pivot_op.molecule_id = molecule_id
                    snap_center_op = pivot_row.operator(
                        "molecule.snap_protein_pivot_center",
                        text="Snap to Center",
                        icon='PIVOT_BOUNDBOX'
                    )
                    if snap_center_op:
                        snap_center_op.molecule_id = molecule_id
                
                # Chain selector UI removed per user request
                
                # Poses Section - Add this before Domain Creation
                settings_box.separator()
                poses_box = settings_box.box()
                poses_box.label(text="Protein Poses:", icon='ARMATURE_DATA')
                
                # Get molecule item for poses
                molecule_item = None
                for item in scene.molecule_list_items:
                    if item.identifier == molecule_id:
                        molecule_item = item
                        break
                
                if molecule_item:
                    # Create New Pose button
                    row = poses_box.row(align=True)
                    row.scale_y = 1.2
                    row.operator("molecule.create_pose", text="Save Current State as Pose", icon='ADD')
                    
                    # If no poses, show message
                    if not molecule_item.poses or len(molecule_item.poses) == 0:
                        poses_box.label(text="No poses saved", icon='INFO')
                    else:
                        # List of poses with management options
                        poses_box.separator()
                        
                        # Create a grid layout for poses
                        grid_flow = poses_box.grid_flow(row_major=True, columns=1, even_columns=True, even_rows=False)
                        
                        for idx, pose in enumerate(molecule_item.poses):
                            # Create a box for each pose to contain everything
                            pose_box = grid_flow.box()
                            
                            # Create a label row for the pose name
                            label_row = pose_box.row()
                            label_row.label(text=pose.name, icon='POSE_HLT')
                            
                            # Create row with all action buttons as requested
                            btn_row = pose_box.row(align=True)
                            
                            # Apply button
                            apply_op = btn_row.operator(
                                "molecule.apply_pose", 
                                text="Apply Pose",
                                icon='OUTLINER_OB_ARMATURE',
                                depress=(idx == molecule_item.active_pose_index)
                            )
                            apply_op.pose_index = str(idx)
                            
                            # Set/Update button (creates a new pose with the same name, replacing the existing one)
                            update_btn = btn_row.operator(
                                "molecule.update_pose", 
                                text="Update Pose",
                                icon='FILE_REFRESH'
                            )
                            update_btn.pose_index = str(idx)
                            
                            # Rename button
                            rename_op = btn_row.operator(
                                "molecule.rename_pose", 
                                text="Rename",
                                icon='GREASEPENCIL'
                            )
                            
                            # Delete button
                            delete_op = btn_row.operator(
                                "molecule.delete_pose", 
                                text="Delete",
                                icon='X'
                            )
                            
                            # Show domain transform count as info text
                            info_row = pose_box.row()
                            info_text = f"Contains {len(pose.domain_transforms)} domain transforms"
                            if pose.has_protein_transform:
                                info_text += " + protein position"
                            info_row.label(text=info_text, icon='INFO')

                # Keyframes Section
                settings_box.separator()
                kf_box = settings_box.box()
                kf_box.label(text="Protein Keyframes:", icon='KEYFRAME')
                if molecule_item:
                    # Add new keyframe button
                    row = kf_box.row(align=True)
                    row.scale_y = 1.2
                    row.operator("molecule.keyframe_protein", text="Add Keyframe", icon='KEYFRAME')
                    # List existing keyframes
                    if not molecule_item.keyframes or len(molecule_item.keyframes) == 0:
                        kf_box.label(text="No keyframes saved", icon='INFO')
                    else:
                        for idx, kf in enumerate(molecule_item.keyframes):
                            kf_row = kf_box.row(align=True)
                            # Jump to keyframe
                            select_op = kf_row.operator(
                                "molecule.select_keyframe",
                                text=kf.name,
                                depress=(idx == molecule_item.active_keyframe_index)
                            )
                            select_op.keyframe_index = idx
                            # Edit keyframe parameters
                            edit_op = kf_row.operator(
                                "molecule.edit_keyframe",
                                text="",
                                icon='GREASEPENCIL'
                            )
                            edit_op.keyframe_index = idx
                            # Delete keyframe
                            delete_op = kf_row.operator(
                                "molecule.delete_keyframe",
                                text="",
                                icon='X'
                            )
                            delete_op.keyframe_index = idx

                # Domain Creation Section
                settings_box.separator()
                domain_box = settings_box.box()
                domain_box.label(text="Domains")

                # Temporarily disable domain preview section until it's fully implemented
                #preview_row = domain_box.row(align=True)
                #preview_row.prop(scene, "show_domain_preview", text="Show Selection")
                
                # Add separator after creation controls
                domain_box.separator()
                
                # Display existing domains - safely handle sorted domains
                try:
                    # Ensure domain_items is a list immediately
                    domain_items_list = list(molecule.get_sorted_domains().items())
                except AttributeError:
                    # Fall back to sorting domains manually if the method doesn't exist
                    domain_items_list = sorted(
                        list(molecule.domains.items()), # Ensure this is also list if .items() is an iterator
                        key=lambda x: (x[1].chain_id, x[1].start)
                    )
                
                # --- DEBUG PRINTS ---
                try:
                    print(f"PANEL DEBUG: Molecule ID: {molecule_id}")
                    print(f"PANEL DEBUG: molecule.domains raw: {molecule.domains}")
                    print(f"PANEL DEBUG: domain_items_list count: {len(domain_items_list)}")
                    for did, dmn in domain_items_list:
                        try:
                            obj = dmn.object
                            # Check if object still exists in Blender data
                            obj_status = "VALID" if (obj and obj.name in bpy.data.objects) else "INVALID or None"
                        except ReferenceError:
                            obj_status = "INVALID or None"
                        except Exception as e:
                            obj_status = f"ERROR: {e}"
                        parent_id_val = getattr(dmn, 'parent_domain_id', 'N/A')
                        name_val = getattr(dmn, 'name', 'N/A')
                        print(f"PANEL DEBUG: Domain ID: {did}, Name: {name_val}, Obj: {obj_status}, ParentID: {parent_id_val}")
                except Exception as debug_e:
                    print(f"PANEL DEBUG: Error during domain debug printing: {debug_e}")
                # --- END DEBUG PRINTS ---
                
                # Create a hierarchical representation of domains
                top_level_domains = []
                child_domains = {}
                
                # Iterate over the list
                for domain_id, domain in domain_items_list: 
                    parent_id = getattr(domain, 'parent_domain_id', None)
                    if not parent_id or parent_id not in molecule.domains:
                        top_level_domains.append((domain_id, domain))
                    else:
                        if parent_id not in child_domains:
                            child_domains[parent_id] = []
                        child_domains[parent_id].append((domain_id, domain))
                
                # Helper function to recursively draw domains with proper indentation
                def draw_domain_hierarchy(domain_id, domain, indent_level=0):
                    # Skip if domain object has been removed
                    try:
                        obj = domain.object
                    except ReferenceError:
                        return
                    if not obj:
                        return
                    # Create box for each domain
                    domain_header = domain_box.box()
                    header_row = domain_header.row()

                    # Add indentation based on hierarchy level
                    if indent_level > 0:
                        # Add indentation using blank labels
                        for _ in range(indent_level):
                             header_row.label(text="", icon='BLANK1')

                    # Add expand/collapse triangle
                    is_expanded = getattr(obj, "domain_expanded", False)
                    expand_icon = "TRIA_DOWN" if is_expanded else "TRIA_RIGHT"

                    # Try to use the custom operator, but fall back to direct property if not available
                    try:
                        expand_op = header_row.operator(
                            "molecule.toggle_domain_expanded",
                            text="",
                            icon=expand_icon,
                            emboss=False
                        )
                        if expand_op:  # Check if operator was created successfully
                            expand_op.domain_id = domain_id
                            expand_op.is_expanded = not is_expanded
                        else:
                            # Fallback to direct property toggle
                            header_row.prop(obj, "domain_expanded",
                                         icon=expand_icon,
                                         icon_only=True,
                                         emboss=False)
                    except Exception:
                        # Fallback to direct property toggle if operator fails
                        header_row.prop(obj, "domain_expanded",
                                     icon=expand_icon,
                                     icon_only=True,
                                     emboss=False)

                        # If expanding, update UI values to match domain
                        if not is_expanded and obj.domain_expanded:
                            # Add a hidden operator to update UI values
                            hidden_row = header_row.row()
                            hidden_row.scale_x = 0.01
                            hidden_row.scale_y = 0.01
                            hidden_row.operator("molecule.update_domain_ui_values", text="", emboss=False).domain_id = domain_id

                    # Add domain name in bold
                    name_row = header_row.row()
                    name_row.scale_y = 1.1
                    name_row.label(text=domain.name)
                    
                    # Add chain and residue info in a smaller, less prominent format
                    info_row = header_row.row()
                    info_row.scale_x = 0.9
                    info_row.scale_y = 0.8
                    info_row.alignment = 'RIGHT'
                    info_row.label(text=f"Chain {domain.chain_id} ({domain.start}-{domain.end})")

                    # Add select object button
                    if obj:
                        select_op = header_row.operator(
                            "molecule.select_object",
                            text="",
                            icon='RESTRICT_SELECT_OFF'
                        )
                        select_op.object_id = domain_id
                        select_op.is_domain = True

                    # Add visibility toggle
                    if obj:
                        # Keep visibility toggle compact
                        vis_row = header_row.row(align=True)
                        vis_row.prop(obj, "hide_viewport", text="", emboss=False,
                                 icon='HIDE_OFF' if not obj.hide_viewport else 'HIDE_OFF')

                    # Add delete button - check if it should be enabled
                    # Count domains on the same chain
                    domains_on_same_chain = 0
                    for d_id, d_obj in molecule.domains.items():
                        if d_obj.chain_id == domain.chain_id:
                            domains_on_same_chain += 1
                    
                    delete_op_row = header_row.row(align=True)
                    delete_op = delete_op_row.operator(
                        "molecule.delete_domain",
                        text="",
                        icon='X'
                    )
                    delete_op.domain_id = domain_id
                    if domains_on_same_chain <= 1:
                        delete_op_row.enabled = False # Disable the row containing the operator

                    # If expanded, show domain controls
                    if is_expanded:
                        # Use a box inside the domain_header for controls
                        control_box = domain_header.box()
                        
                        # Add Domain Name field at the top with proper layout
                        name_row = control_box.row(align=True)
                        
                        # Label on the left
                        label_col = name_row.column()
                        label_col.scale_x = 0.4
                        label_col.label(text="Domain Name:")
                        
                        # Text field in the middle
                        text_col = name_row.column()
                        text_col.scale_x = 0.7
                        
                        # Check if we have the temp property and it has a value
                        has_temp_name = (hasattr(obj, "temp_domain_name") and 
                                        obj.temp_domain_name)
                        
                        if has_temp_name:
                            # Normal case - just show the property
                            text_col.prop(obj, "temp_domain_name", text="")
                        else:
                            # When temp_domain_name is not available or is empty
                            text_col.label(text=domain.name)
                            
                            # Add a hidden row to trigger initialization
                            hidden_row = text_col.row()
                            hidden_row.scale_y = 0.01
                            hidden_row.scale_x = 0.01
                            init_op = hidden_row.operator(
                                "molecule.initialize_domain_temp_name",
                                text="", 
                                emboss=False
                            )
                            init_op.domain_id = domain_id
                        
                        # Confirm button on the right - made to stand out
                        btn_col = name_row.column()
                        btn_col.scale_x = 1.0  # Adjust width to match screenshot
                        btn_col.scale_y = 1.0   # Ensure standard height
                        
                        # Add padding space to align with text field
                        btn_row = btn_col.row()
                        btn_row.alignment = 'CENTER'  # Center the button
                        
                        # The actual button
                        confirm_op = btn_row.operator(
                            "molecule.update_domain_name",
                            text="",
                            icon='CHECKMARK',
                            emboss=True
                        )
                        confirm_op.domain_id = domain_id
                        confirm_op.name = obj.temp_domain_name if has_temp_name else domain.name
                        
                        # Add separator after name field
                        control_box.separator()
                        
                        # Parent domain info (if applicable) - moved up from below
                        if hasattr(domain, 'parent_domain_id') and domain.parent_domain_id:
                            parent_box = control_box.box()
                            parent_box.label(text="Parent Domain")
                            parent_row = parent_box.row()
                            # Need to access molecule from the outer scope, make sure it's available
                            # or pass it to draw_domain_hierarchy
                            parent_domain_obj = molecule.domains.get(domain.parent_domain_id)
                            if parent_domain_obj:
                                parent_row.label(text=f"{parent_domain_obj.name}: Chain {parent_domain_obj.chain_id} ({parent_domain_obj.start}-{parent_domain_obj.end})")
                            else:
                                parent_row.label(text=f"ID: {domain.parent_domain_id} (Not Found)")
                        
                        # Parent domain selector - moved up from below
                        parent_box = control_box.box()
                        parent_box.label(text="Set Parent Domain")
                        parent_dropdown = parent_box.row()
                        
                        # Create parent selection operator
                        parent_op = parent_dropdown.operator(
                            "molecule.set_parent_domain",
                            text="Select Parent Domain"
                        )
                        if parent_op:
                            parent_op.domain_id = domain_id
                        
                        # Add separator after parent domain sections
                        control_box.separator()
                        
                        # Combined row for Domain Color and Style
                        props_row = control_box.row()

                        # Left side - Domain color picker
                        color_col = props_row.column()
                        color_col.label(text="Domain Color")
                        color_col.prop(obj, "domain_color", text="")
                        
                        # Right side - Domain style dropdown
                        style_col = props_row.column()
                        style_col.label(text="Domain Style")
                        
                        # Get style name for display
                        try:
                            # Try to get style from domain definition first
                            style_display = domain.style.capitalize()
                        except (AttributeError, TypeError):
                            # Try to get from object property
                            try:
                                style_display = obj.domain_style.capitalize()
                            except (AttributeError, TypeError):
                                # Fall back to custom property
                                if hasattr(obj, "__getitem__") and "domain_style" in obj:
                                    style_display = str(obj["domain_style"]).capitalize()
                                else:
                                    style_display = "Style"
                                    
                        # Display the dropdown
                        style_col.prop_menu_enum(
                            obj, 
                            "domain_style", 
                            text=style_display,
                            icon='MATERIAL'
                        )
                        
                        # Transform controls
                        transform_box = control_box.box()
                        transform_box.label(text="Transform")

                        # Add Reset Transform button
                        reset_row = transform_box.row()
                        reset_op = reset_row.operator(
                            "molecule.reset_domain_transform", # New operator ID
                            text="Snap Back To Original Position"
                        )
                        if reset_op:
                           reset_op.domain_id = domain_id

                        # --- Pivot Buttons Row ---
                        pivot_row = transform_box.row(align=True) # Use align=True for compactness
                        
                        # Button 1: Move/Set Pivot
                        try:
                            is_editing = obj.get("is_pivot_editing", False)
                            button_text = "Set Pivot" if is_editing else "Move Pivot"
                            button_icon = 'CHECKMARK' if is_editing else 'PIVOT_BOUNDBOX'

                            move_pivot_op = pivot_row.operator(
                                "molecule.toggle_pivot_edit",
                                text=button_text,
                                icon=button_icon,
                                depress=is_editing
                            )
                            if move_pivot_op:
                                move_pivot_op.domain_id = domain_id
                        except Exception as e:
                            print(f"Error creating move pivot button: {str(e)}")
                            pivot_row.label(text="Move Pivot", icon='ERROR') # Fallback label on error

                        # Button 2: Snap to Start AA
                        snap_start_op = pivot_row.operator(
                            "molecule.snap_pivot_to_residue",
                            text="Start AA", 
                            icon='TRIA_LEFT_BAR' # Icon suggesting start/beginning
                        )
                        if snap_start_op:
                            snap_start_op.domain_id = domain_id
                            snap_start_op.target_residue = 'START'

                        # Button 3: Snap to End AA
                        snap_end_op = pivot_row.operator(
                            "molecule.snap_pivot_to_residue",
                            text="End AA", 
                            icon='TRIA_RIGHT_BAR' # Icon suggesting end
                        )
                        if snap_end_op:
                            snap_end_op.domain_id = domain_id
                            snap_end_op.target_residue = 'END'

                        # --- End Pivot Buttons Row ---

                        # Location
                        loc_row = transform_box.row(align=True)
                        loc_row.prop(obj, "location", text="")
                        
                        # Rotation
                        rot_row = transform_box.row(align=True)
                        rot_row.prop(obj, "rotation_euler", text="")
                        
                        # Scale
                        scale_row = transform_box.row(align=True)
                        scale_row.prop(obj, "scale", text="")

                        # --- Domain Splitting UI ---
                        split_box = control_box.box()
                        split_box.label(text="Split Domain")

                        # New start and end inputs
                        split_inputs_row = split_box.row(align=True)
                        split_inputs_row.prop(scene, "split_domain_new_start", text="New Start")
                        split_inputs_row.prop(scene, "split_domain_new_end", text="New End")
                        
                        # Split button
                        split_button_row = split_box.row()
                        split_op = split_button_row.operator(
                            "molecule.split_domain", 
                            text="Split This Domain", 
                            icon='MOD_EDGESPLIT'
                        )
                        if split_op:
                            split_op.domain_id = domain_id
                        # --- End Domain Splitting UI ---

                    # Draw child domains recursively (if any)
                    if domain_id in child_domains:
                        for child_id, child_domain_obj_ref in child_domains[domain_id]: # Renamed to avoid conflict
                            draw_domain_hierarchy(child_id, child_domain_obj_ref, indent_level + 1)
                
                # --- Main loop to draw top-level domains and their children ---
                if not domain_items_list: # Check the list
                    domain_box.label(text="No domains defined for this molecule.", icon='INFO')
                else:
                    # Add a debug print for top_level_domains count
                    print(f"PANEL DEBUG: top_level_domains count: {len(top_level_domains)}")
                    if not top_level_domains and domain_items_list: # If no top-level but domains exist
                         domain_box.label(text="Domains exist but none are top-level. Check parenting.", icon='ERROR')
                    
                    for domain_id, domain_obj_ref in top_level_domains: # Renamed to avoid conflict
                        try:
                            # The draw_domain_hierarchy function will handle its own object checks
                            # and recursively draw its children.
                            draw_domain_hierarchy(domain_id, domain_obj_ref, indent_level=0)
                        except ReferenceError: # Should ideally not happen if list is clean
                            print(f"Warning: Stale reference to domain {domain_id} during UI draw.")
                            continue
                # End of the domain drawing section

class MOLECULE_PB_OT_toggle_chain_selection(Operator):
    bl_idname = "molecule.toggle_chain_selection"
    bl_label = "Toggle Chain"
    bl_description = "Toggle selection state of this chain"
    
    chain_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        
        # Find and toggle the selected state for this chain
        for chain_item in scene.chain_selections:
            if chain_item.chain_id == self.chain_id:
                chain_item.is_selected = not chain_item.is_selected
                break
                
        # Update the molecule visualization
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if molecule and molecule.object:
            # Get all selected chain IDs
            selected_chains = [item.chain_id for item in scene.chain_selections 
                             if item.is_selected]
            # Update the molecule's chain selection
            molecule.select_chains(selected_chains)
        
        return {'FINISHED'}

class MOLECULE_PB_OT_delete_selected_object(Operator):
    bl_idname = "molecule.delete_selected_object"
    bl_label = "Delete Selected Object"
    bl_description = "Delete the selected object"
    
    def execute(self, context):
        scene = context.scene
        
        # Find and delete the selected object
        selected_object = scene.selected_object
        if selected_object:
            bpy.data.objects.remove(selected_object, do_unlink=True)
        
        return {'FINISHED'}
