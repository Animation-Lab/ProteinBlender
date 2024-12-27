import bpy
from bpy.types import Panel

class PT_pdb_import(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'  # Changed from NAVIGATION_BAR
    bl_context = "scene"  # Must be a valid context
    bl_label = "PDB Import"
    bl_idname = "PT_pdb_import"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}  # This helps it look more like a main section
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.protein_props

        # Create a nice box layout
        box = layout.box()
        col = box.column(align=True)
        
        # Add the method selector
        col.prop(props, "import_method", text="Method")
        
        # Add the appropriate ID field based on method
        if props.import_method == 'PDB':
            col.prop(props, "pdb_id", text="PDB:")
        else:
            col.prop(props, "uniprot_id", text="UniProt ID:")
            
        col.operator("protein.import_pdb", text="Add to Scene")

def register_panel_import_pdb():
    bpy.utils.register_class(PT_pdb_import)

def unregister_panel_import_pdb():
    bpy.utils.unregister_class(PT_pdb_import)