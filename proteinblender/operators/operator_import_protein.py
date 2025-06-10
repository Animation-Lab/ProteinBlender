# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator
from ..utils.scene_manager import get_protein_blender_scene

class PROTEIN_OT_import_protein(Operator):
    bl_idname = "protein.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein from PDB or AlphaFold"
    # No UNDO flag needed here anymore, as state is managed on the scene
    bl_options = {'REGISTER'} 
    
    def execute(self, context):
        scene = context.scene
        props = scene.protein_props
        
        # Get the scene manager for the current context
        scene_manager = get_protein_blender_scene(context)
        
        # Determine identifier, method, and format for import
        if props.import_method == 'PDB':
            identifier = props.pdb_id
            if not identifier:
                self.report({'ERROR'}, "PDB ID is required.")
                return {'CANCELLED'}
            
            # Use the scene manager to perform the import
            wrapper = scene_manager.import_molecule(
                pdb_id=identifier, 
                molecule_id=f"{identifier}_001" # Example ID
            )

        elif props.import_method == 'AlphaFold':
            identifier = props.alphafold_id
            if not identifier:
                self.report({'ERROR'}, "AlphaFold DB ID is required.")
                return {'CANCELLED'}
            
            wrapper = scene_manager.import_molecule(
                pdb_id=identifier, 
                molecule_id=f"{identifier}_001",
                source='alphafold'
            )
        
        else: # Local file
            identifier = props.local_path
            if not identifier:
                self.report({'ERROR'}, "File path is required.")
                return {'CANCELLED'}
            
            wrapper = scene_manager.import_molecule(filepath=identifier)

        if wrapper:
            self.report({'INFO'}, f"Successfully imported {wrapper.identifier}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"Failed to import {identifier}")
            return {'CANCELLED'}

CLASSES = [
    PROTEIN_OT_import_protein,
]

def register_operator_import_protein():
    bpy.utils.register_class(PROTEIN_OT_import_protein)

def unregister_operator_import_protein():
    bpy.utils.unregister_class(PROTEIN_OT_import_protein)