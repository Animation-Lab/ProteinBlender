# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator

class PROTEIN_OT_import_protein(Operator):
    bl_idname = "protein.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein from PDB or AlphaFold"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        props = scene.protein_props
        
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Determine identifier, method, and format for import
        if props.import_method == 'PDB':
            identifier = props.pdb_id
            method = 'PDB'
            fmt = props.remote_format
        elif props.import_method == 'ALPHAFOLD':
            identifier = props.uniprot_id
            method = 'ALPHAFOLD'
            fmt = props.remote_format
        elif props.import_method == 'MMCIF':
            # Remote mmCIF download uses the same PDB code but requests .cif format
            identifier = props.pdb_id
            method = 'PDB'
            fmt = 'cif'
        else:
            self.report({'ERROR'}, f"Unknown import method: {props.import_method}")
            return {'CANCELLED'}

        success = scene_manager.create_molecule_from_id(
            identifier,
            import_method=method,
            remote_format=fmt
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