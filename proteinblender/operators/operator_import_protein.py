# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator

class PROTEIN_OT_import_protein(Operator):
    bl_idname = "protein.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein from PDB or AlphaFold"
    
    def execute(self, context):
        scene = context.scene
        props = scene.protein_props
        
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        if props.import_method == 'PDB':
            identifier = props.pdb_id
        else:
            identifier = props.uniprot_id
            
        success = scene_manager.create_molecule_from_id(
            identifier, 
            import_method=props.import_method
        )
        
        if not success:
            self.report({'ERROR'}, f"Failed to import {identifier}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

CLASSES = [
    PROTEIN_OT_import_protein,
]

def register_operator_import_protein():
    bpy.utils.register_class(PROTEIN_OT_import_protein)

def unregister_operator_import_protein():
    bpy.utils.unregister_class(PROTEIN_OT_import_protein)