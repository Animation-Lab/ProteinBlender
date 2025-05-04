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
        
        # Create box for list
        box = layout.box()
        
        if not scene_manager.molecules:
            box.label(text="No molecules in scene", icon='INFO')
            return
            
        # Create column for molecule entries
        col = box.column()
        
        # Draw each molecule entry
        for molecule_id, molecule in scene_manager.molecules.items():
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
                vis_row.prop(molecule.object, "hide_viewport", text="", emboss=False, icon='HIDE_OFF' if not molecule.object.hide_viewport else 'HIDE_OFF')
                
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
                style_row.operator("molecule.change_style", text="Change Style")
                
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
                            select_op = kf_row.operator(
                                "molecule.select_keyframe",
                                text=kf.name,
                                depress=(idx == molecule_item.active_keyframe_index)
                            )
                            select_op.keyframe_index = idx
                            delete_op = kf_row.operator(
                                "molecule.delete_keyframe",
                                text="",
                                icon='X'
                            )
                            delete_op.keyframe_index = idx

                # Domain Creation Section
                settings_box.separator()
                domain_box = settings_box.box()
                domain_box.label(text="Domains:")
                
                # Domain creation controls with chain and range inputs
                creation_box = domain_box.box()
                creation_box.label(text="Create New Domain")
                
                # Chain selection dropdown
                chain_row = creation_box.row()
                chain_row.prop(scene, "new_domain_chain", text="Chain")
                
                # Residue range inputs
                range_row = creation_box.row(align=True)
                range_row.prop(scene, "new_domain_start", text="Start")
                range_row.prop(scene, "new_domain_end", text="End")
                
                # Domain creation button
                domain_row = creation_box.row(align=True)
                domain_row.scale_y = 1.2
                create_op = domain_row.operator(
                    "molecule.create_domain",
                    text="Create Domain",
                    icon='ADD'
                )
                
                # Add separator after creation controls
                domain_box.separator()
                
                # Display existing domains - safely handle sorted domains
                try:
                    # Try to use the get_sorted_domains method if it exists
                    domain_items = molecule.get_sorted_domains().items()
                except AttributeError:
                    # Fall back to sorting domains manually if the method doesn't exist
                    domain_items = sorted(
                        molecule.domains.items(),
                        key=lambda x: (x[1].chain_id, x[1].start)
                    )
                
                # Create a hierarchical representation of domains
                # First, gather the top-level domains (those without parents or with parents outside current domains)
                top_level_domains = []
                child_domains = {}
                
                for domain_id, domain in domain_items:
                    parent_id = getattr(domain, 'parent_domain_id', None)
                    # Check if this is a top-level domain (no parent or parent not in current domains)
                    if not parent_id or parent_id not in molecule.domains:
                        top_level_domains.append((domain_id, domain))
                    else:
                        # Add to child domains dictionary
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

                    # Add delete button
                    delete_op = header_row.operator(
                        "molecule.delete_domain",
                        text="",
                        icon='X'
                    )
                    delete_op.domain_id = domain_id

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
                            parent_domain = molecule.domains.get(domain.parent_domain_id)
                            if parent_domain:
                                parent_row.label(text=f"{parent_domain.name}: Chain {parent_domain.chain_id} ({parent_domain.start}-{parent_domain.end})")
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
                    
                    # Draw child domains recursively (if any)
                    if domain_id in child_domains:
                        for child_id, child_domain in child_domains[domain_id]:
                            draw_domain_hierarchy(child_id, child_domain, indent_level + 1)
                
                # Draw the domain hierarchy starting with top-level domains
                for domain_id, domain in top_level_domains:
                    try:
                        draw_domain_hierarchy(domain_id, domain)
                    except ReferenceError:
                        # Domain object was removed, skip drawing
                        continue
                    draw_domain_hierarchy(domain_id, domain)

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
