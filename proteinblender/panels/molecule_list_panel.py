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
                
                settings_box.separator()

                # Chain selector
                chain_row = settings_box.row()
                flow = settings_box.column_flow(columns=0)
                flow.alignment = 'CENTER'
                
                # Create a grid flow that will wrap buttons
                grid = flow.grid_flow(row_major=True, columns=10, even_columns=True, even_rows=True, align=True)
                
                for chain_item in scene.chain_selections:
                    # Create sub-row for scaling
                    btn_row = grid.row(align=True)
                    btn_row.scale_x = 1.2
                    btn_row.scale_y = 0.8
                    
                    # Create button in scaled row
                    btn = btn_row.operator(
                        "molecule.toggle_chain_selection",
                        text=chain_item.chain_id,
                        depress=chain_item.is_selected
                    )
                    btn.chain_id = chain_item.chain_id

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
                    # Create box for each domain
                    domain_header = domain_box.box()
                    header_row = domain_header.row()
                    
                    # Add indentation based on hierarchy level
                    if indent_level > 0:
                        for i in range(indent_level):
                            indent = header_row.row()
                            indent.scale_x = 0.5
                            indent.label(text="")
                    
                    # Add expand/collapse triangle
                    is_expanded = getattr(domain.object, "domain_expanded", False)
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
                            header_row.prop(domain.object, "domain_expanded", 
                                         icon=expand_icon, 
                                         icon_only=True,
                                         emboss=False)
                    except Exception:
                        # Fallback to direct property toggle if operator fails
                        header_row.prop(domain.object, "domain_expanded", 
                                     icon=expand_icon, 
                                     icon_only=True,
                                     emboss=False)
                        
                        # If expanding, update UI values to match domain
                        if not is_expanded and domain.object.domain_expanded:
                            # Add a hidden operator to update UI values
                            hidden_row = header_row.row()
                            hidden_row.scale_x = 0.01
                            hidden_row.scale_y = 0.01
                            hidden_row.operator("molecule.update_domain_ui_values", text="", emboss=False).domain_id = domain_id
                    
                    # Add domain label and info
                    info_row = header_row.row()
                    info_row.label(text=f"{domain.name}: Chain {domain.chain_id} ({domain.start}-{domain.end})")
                    
                    # Add visibility toggle
                    if domain.object:
                        vis_row = header_row.row()
                        vis_row.prop(domain.object, "hide_viewport", text="", emboss=False, 
                                 icon='HIDE_OFF' if not domain.object.hide_viewport else 'HIDE_OFF')
                    
                    # Add delete button
                    delete_op = header_row.operator(
                        "molecule.delete_domain",
                        text="",
                        icon='X'
                    )
                    delete_op.domain_id = domain_id
                    
                    # If expanded, show domain controls
                    if is_expanded:
                        control_box = domain_header.box()
                        
                        # Combined row for Domain Color and Style
                        props_row = control_box.row()
                        
                        # Left side - Domain color picker
                        color_col = props_row.column()
                        color_col.label(text="Domain Color")
                        color_col.prop(domain.object, "domain_color", text="")
                        
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
                                style_display = domain.object.domain_style.capitalize()
                            except (AttributeError, TypeError):
                                # Fall back to custom property
                                if hasattr(domain.object, "__getitem__") and "domain_style" in domain.object:
                                    style_display = str(domain.object["domain_style"]).capitalize()
                                else:
                                    style_display = "Style"
                                    
                        # Display the dropdown
                        style_col.prop_menu_enum(
                            domain.object, 
                            "domain_style", 
                            text=style_display,
                            icon='MATERIAL'
                        )
                        
                        # Parent domain info (if applicable)
                        if hasattr(domain, 'parent_domain_id') and domain.parent_domain_id:
                            parent_box = control_box.box()
                            parent_box.label(text="Parent Domain")
                            parent_row = parent_box.row()
                            parent_domain = molecule.domains.get(domain.parent_domain_id)
                            if parent_domain:
                                parent_row.label(text=f"{parent_domain.name}: Chain {parent_domain.chain_id} ({parent_domain.start}-{parent_domain.end})")
                            else:
                                parent_row.label(text=f"ID: {domain.parent_domain_id} (Not Found)")
                        
                        # Transform controls
                        transform_box = control_box.box()
                        transform_box.label(text="Transform")
                        
                        # Add pivot edit button
                        pivot_row = transform_box.row()
                        try:
                            pivot_op = pivot_row.operator(
                                "molecule.toggle_pivot_edit",
                                text="Move Pivot",
                                icon='PIVOT_BOUNDBOX'
                            )
                            if pivot_op:  # Only set domain_id if operator was created successfully
                                pivot_op.domain_id = domain_id
                        except Exception as e:
                            print(f"Error creating pivot operator: {str(e)}")
                            # Add a label instead if operator creation fails
                            pivot_row.label(text="Move Pivot", icon='PIVOT_BOUNDBOX')
                        
                        # Location
                        loc_row = transform_box.row(align=True)
                        loc_row.prop(domain.object, "location", text="")
                        
                        # Rotation
                        rot_row = transform_box.row(align=True)
                        rot_row.prop(domain.object, "rotation_euler", text="")
                        
                        # Scale
                        scale_row = transform_box.row(align=True)
                        scale_row.prop(domain.object, "scale", text="")
                        
                        # Animation controls
                        anim_box = control_box.box()
                        anim_box.label(text="Animation")
                        anim_row = anim_box.row()
                        anim_row.operator("molecule.keyframe_domain_location", text="Keyframe Location")
                        anim_row.operator("molecule.keyframe_domain_rotation", text="Keyframe Rotation")
                    
                    # Draw child domains recursively (if any)
                    if domain_id in child_domains:
                        for child_id, child_domain in child_domains[domain_id]:
                            draw_domain_hierarchy(child_id, child_domain, indent_level + 1)
                
                # Draw the domain hierarchy starting with top-level domains
                for domain_id, domain in top_level_domains:
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
