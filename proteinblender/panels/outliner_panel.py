import bpy
from bpy.types import Panel

class PROTEIN_PB_PT_outliner(Panel):
    bl_label = "Protein Outliner"
    bl_idname = "PROTEIN_PB_PT_outliner"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_order = 1
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        outliner_state = scene.protein_outliner_state

        box = layout.box()
        box.label(text="Protein Outliner")

        for i, item in enumerate(outliner_state.items):
            row = box.row(align=True)
            
            # Add indentation
            row.separator(factor=item.depth * 2.0)
            
            # Name (left side)
            row.prop(item, "name", text="", emboss=False)
            
            # Rename button (small icon next to name)
            rename_op = row.operator("protein_pb.rename_outliner_item", text="", icon='GREASEPENCIL', emboss=False)
            rename_op.item_index = i
            
            # Manage Domains button (small icon next to name)
            manage_op = row.operator("protein_pb.manage_domains", text="", icon='MOD_BUILD', emboss=False)
            manage_op.item_index = i
            
            # Push buttons to the right
            row.separator()
            
            # Selection toggle (right side)
            row.prop(item, "is_selected", text="", icon='CHECKBOX_HLT' if item.is_selected else 'CHECKBOX_DEHLT', emboss=False)

            # Visibility toggle (right side)
            icon = 'HIDE_OFF' if item.is_visible else 'HIDE_ON'
            row.prop(item, "is_visible", text="", icon=icon, emboss=False) 