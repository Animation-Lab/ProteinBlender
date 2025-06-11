import bpy
from bpy.types import Panel, Operator, UIList
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene, get_protein_blender_scene
from ..operators.domain_operators import MOLECULE_PB_OT_toggle_pivot_edit

# Ensure domain properties are registered
from ..core.domain import ensure_domain_properties_registered
ensure_domain_properties_registered()

class MOLECULE_UL_items(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        molecule = item
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(molecule, "name", text="", emboss=False, icon='OBJECT_DATA')
            
            # Add a delete button
            op = row.operator("molecule.delete", text="", icon='TRASH')
            op.molecule_id = molecule.identifier
            
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class MOLECULE_PT_molecule_list(Panel):
    bl_label = "Molecules"
    bl_idname = "MOLECULE_PT_molecule_list"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Draw the list of molecules
        layout.template_list(
            "MOLECULE_UL_items",
            "",
            scene,
            "molecule_list_items",
            scene,
            "molecule_list_index"
        )
        
        # Draw details for the selected molecule
        scene_manager = get_protein_blender_scene(context)
        active_molecule = scene_manager.active_molecule
        
        if active_molecule:
            box = layout.box()
            box.label(text=f"Domains for {active_molecule.name}")
            
            # List domains for the active molecule
            for domain_id, domain in active_molecule.domains.items():
                row = box.row()
                row.label(text=domain.name)
                op = row.operator("molecule.delete_domain", text="", icon='TRASH')
                op.domain_id = domain_id
            
            # Add a button to create a new domain
            box.operator("molecule.add_domain", text="Add Domain")

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
        scene_manager = get_protein_blender_scene(context)
        
        # Create box for list
        box = layout.box()
        
        if not scene_manager.molecules:
            box.label(text="No molecules in scene", icon='INFO')
            return
            
        # Create column for molecule entries
        col = box.column()
        
        # Draw each molecule entry
        for molecule_id, molecule in scene_manager.molecules.items():
            try:
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
                    
                    # New Undoable Delete button.
                    # The operator's poll method will automatically handle enabling/disabling
                    # based on whether the object is the active_object.
                    row.operator("pb.delete_protein_undoable", text="", icon='TRASH', emboss=False)
                
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
                    print(f"PANEL DEBUG: Molecule ID: {molecule_id}")
                    print(f"PANEL DEBUG: molecule.domains raw: {molecule.domains}")
                    # Use domain_items_list for debug prints
                    print(f"PANEL DEBUG: domain_items_list count: {len(domain_items_list)}")
                    for did, dmn in domain_items_list:
                        obj_status = "VALID" if dmn.object and hasattr(dmn.object, 'name') else "INVALID or None"
                        parent_id_val = getattr(dmn, 'parent_domain_id', 'N/A')
                        print(f"PANEL DEBUG: Domain ID: {did}, Name: {dmn.name}, Obj: {obj_status}, ParentID: {parent_id_val}")
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
                    def draw_domain_hierarchy(parent_layout, domain_id, domain, indent_level=0):
                        # Skip if domain object has been removed
                        try:
                            obj = domain.object
                        except ReferenceError:
                            return
                        if not obj:
                            return
                            
                        # Create a new box within the parent layout for this domain
                        domain_box = parent_layout.box()
                        header_row = domain_box.row()

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
                                # The children will be drawn inside the main domain_box for this level
                                # We don't need a sub-box here as the recursive call creates its own.
                                pass # No need to create another box, recursion handles it.

                        # Draw child domains recursively (if any)
                        if domain_id in child_domains:
                            for child_id, child_domain_obj_ref in child_domains[domain_id]: # Renamed to avoid conflict
                                    # Pass the CURRENT domain_box to the children
                                    draw_domain_hierarchy(domain_box, child_id, child_domain_obj_ref, indent_level + 1)
                    
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
                                    # Initial call passes the main container box.
                                    draw_domain_hierarchy(domain_box, domain_id, domain_obj_ref, indent_level=0)
                            except ReferenceError: # Should ideally not happen if list is clean
                                print(f"Warning: Stale reference to domain {domain_id} during UI draw.")
                                continue
                    # End of the domain drawing section

            except (ReferenceError, AttributeError, KeyError, NameError) as e:
                # This molecule's underlying Blender object has likely been deleted or is invalid.
                # This can happen during an undo operation where the object is removed
                # before the UI has a chance to redraw. We will draw a placeholder
                # and the sync handler will clean up the wrapper on the next pass.
                error_row = col.row(align=True)
                error_row.label(text=f"'{molecule_id}' is invalid. Will be removed.", icon='ERROR')
                print(f"Error drawing molecule '{molecule_id}': {e}. Likely removed by undo.")

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
        scene_manager = get_protein_blender_scene(context)
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

CLASSES = [
    MOLECULE_UL_items,
    MOLECULE_PT_molecule_list,
]

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.molecule_list_items = bpy.props.CollectionProperty(type=MoleculeListItem)
    bpy.types.Scene.molecule_list_index = bpy.props.IntProperty(name="Molecule List Index", default=0)

def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.molecule_list_items
    del bpy.types.Scene.molecule_list_index
