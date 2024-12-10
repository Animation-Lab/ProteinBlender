# protein_workspace/panels/panel_import_pdb.py
import bpy
from bpy.types import Panel

class PANEL_PT_PDBImport(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "PDB Import"
    bl_category = "Protein"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.protein_props

        layout.prop(props, "pdb_id", text="PDB ID")
        layout.operator("protein.import_pdb", text="Fetch PDB")

def register():
    bpy.utils.register_class(PANEL_PT_PDBImport)

def unregister():
    bpy.utils.unregister_class(PANEL_PT_PDBImport)
