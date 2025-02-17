import bpy
from bpy.types import Panel, Operator
from ..utils.scene_manager import ProteinBlenderScene
from bpy.props import StringProperty
from ..properties.molecule_props import get_chain_mapping_from_str

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
                vis_row.prop(molecule.object, "hide_viewport", text="", emboss=False)
                
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
                
                # Add before the domain creation controls
                preview_row = domain_box.row()
                preview_row.prop(scene, "show_domain_preview")
                domain_box.separator()
                
                # Domain creation row
                domain_row = domain_box.row(align=True)
                
                # Chain dropdown
                if molecule.object and "chain_id" in molecule.object.data.attributes:
                    # Chain dropdown
                    domain_row.prop(scene, "selected_chain_for_domain", text="")
                    
                    # Start and end residue inputs
                    domain_row.prop(scene, "domain_start", text="Start")
                    domain_row.prop(scene, "domain_end", text="End")
                    
                    # Create domain button
                    create_op = domain_row.operator(
                        "molecule.create_domain",
                        text="Create Domain",
                        icon='ADD'
                    )
                    
                    # Add separator after creation controls
                    domain_box.separator()
                    
                    # Get the molecule list item that corresponds to this molecule
                    for item in scene.molecule_list_items:
                        if item.identifier == molecule_id:
                            # Display existing domains in reverse order (newest first)
                            for domain in reversed(item.domains):
                                # Create box for each domain
                                domain_header = domain_box.box()
                                header_row = domain_header.row()
                                
                                # Add expand/collapse triangle
                                header_row.prop(
                                    domain, "is_expanded",
                                    icon="TRIA_DOWN" if domain.is_expanded else "TRIA_RIGHT",
                                    icon_only=True,
                                    emboss=False
                                )
                                
                                # Add domain label
                                chain_label = domain.chain_id
                                
                                header_row.label(
                                    text=f"Chain {chain_label}: {domain.start} - {domain.end}"
                                )
                                
                                # If expanded, show domain settings
                                if domain.is_expanded:
                                    domain_content = domain_header.column()
                                    # We'll add more settings here later
                            break

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
