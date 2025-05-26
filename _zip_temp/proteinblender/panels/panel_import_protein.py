import bpy
from bpy.types import Panel

class PROTEIN_PB_PT_import_protein(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "Protein Import"
    bl_idname = "PROTEIN_PB_PT_import_protein"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.protein_props

        # Create a box layout with some padding
        box = layout.box()
        box.separator(factor=0.5)  # Add some top padding
        
        # Create main column with spacing
        col = box.column(align=True)
        col.use_property_split = False  # Keep False for full-width controls
        col.use_property_decorate = False
        
        # Add the method selector as a dropdown
        row = col.row()
        row.prop(props, "import_method", text="Method")
        col.separator(factor=1.0)
        
        # Add the appropriate ID field based on method with full width
        row = col.row()
        if props.import_method == 'PDB':
            row.prop(props, "pdb_id", text="PDB")
        else:
            row.prop(props, "uniprot_id", text="UniProt ID")
        
        col.separator(factor=1.5)
        
        # Find the execute button and add a local import button next to it
        button_row = box.row(align=True)
        button_row.scale_y = 1.2
        button_row.operator("protein.import_protein", text="Download From PDB")

        # Add a local file import button
        local_op = button_row.operator("protein.import_local", text="Import Local File")
        
        box.separator(factor=0.5)
