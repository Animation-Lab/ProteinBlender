# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator
from ..utils.scene_manager import ProteinBlenderScene

class PROTEIN_OT_import_protein(Operator):
    bl_idname = "protein.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein from PDB or AlphaFold"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.protein_props
        
        # Get the protein ID based on the import method
        molecule_id = props.pdb_id if props.import_method == 'PDB' else props.uniprot_id
        import_method = props.import_method
        
        if not molecule_id:
            self.report({'ERROR'}, "Please enter a valid ID")
            return {'CANCELLED'}
        
        # Get the singleton instance
        scene_manager = ProteinBlenderScene.get_instance()
        success = scene_manager.create_molecule_from_id(molecule_id, import_method=import_method)
        
        if success:
            self.report({'INFO'}, f"Successfully imported {molecule_id}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"Failed to import {molecule_id}")
            return {'CANCELLED'}

def register_operator_import_protein():
    bpy.utils.register_class(PROTEIN_OT_import_protein)

def unregister_operator_import_protein():
    bpy.utils.unregister_class(PROTEIN_OT_import_protein)