# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator
from ..utils.scene_manager import ProteinBlenderScene

class PROTEIN_OT_import_protein(Operator):
    bl_idname = "protein.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein structure from PDB or AlphaFold"
    
    def execute(self, context):
        props = context.scene.protein_props
        
        # Get the protein ID based on the import method
        protein_id = props.pdb_id if props.import_method == 'PDB' else props.uniprot_id
        import_method = props.import_method
        
        if not protein_id:
            self.report({'ERROR'}, "Please enter a valid protein ID")
            def show_message(self, context):
                self.layout.label(text="Please enter a valid protein ID")
            bpy.context.window_manager.popup_menu(show_message, title="Error", icon='ERROR')
            return {'CANCELLED'}
        
        # Get the singleton instance
        scene_manager = ProteinBlenderScene.get_instance()
        success = scene_manager.create_protein_from_id(protein_id, import_method=import_method)
        
        if success:
            # Show success message in info area
            self.report({'INFO'}, f"Successfully imported protein {protein_id}")
            
            # Show success notification
            def show_success(self, context):
                self.layout.label(text=f"Successfully imported protein {protein_id}")
            bpy.context.window_manager.popup_menu(show_success, title="Success", icon='CHECKMARK')
            
            # Force UI refresh for all areas
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
                    
            return {'FINISHED'}
        else:
            # Show error message in info area
            self.report({'ERROR'}, f"Failed to import protein {protein_id}")
            
            # Show error notification
            def show_error(self, context):
                self.layout.label(text=f"Failed to import protein {protein_id}")
            bpy.context.window_manager.popup_menu(show_error, title="Error", icon='ERROR')
            return {'CANCELLED'}

def register_operator_import_protein():
    bpy.utils.register_class(PROTEIN_OT_import_protein)

def unregister_operator_import_protein():
    bpy.utils.unregister_class(PROTEIN_OT_import_protein)