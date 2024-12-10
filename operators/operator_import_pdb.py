# protein_workspace/operators/operator_import_pdb.py
import bpy
from bpy.types import Operator
from ..utils import file_io

class OPERATOR_OT_ImportPDB(Operator):
    bl_idname = "protein.import_pdb"
    bl_label = "Import PDB"
    bl_description = "Fetch and import PDB from RCSB"

    def execute(self, context):
        scene = context.scene
        pdb_id = scene.protein_props.pdb_id.strip().upper()
        if not pdb_id:
            self.report({'WARNING'}, "No PDB ID provided.")
            return {'CANCELLED'}

        success, filepath = file_io.fetch_pdb_from_rcsb(pdb_id)
        if success:
            self.report({'INFO'}, f"PDB {pdb_id} fetched and stored at {filepath}.")
            print(f"PDB {pdb_id} downloaded and cached at: {filepath}")
        else:
            self.report({'ERROR'}, f"Failed to fetch PDB {pdb_id}.")

        return {'FINISHED'}

def register():
    bpy.utils.register_class(OPERATOR_OT_ImportPDB)

def unregister():
    bpy.utils.unregister_class(OPERATOR_OT_ImportPDB)
