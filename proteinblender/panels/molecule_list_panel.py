import bpy
from bpy.types import Panel
from ..utils.scene_manager import ProteinBlenderScene

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
