import bpy
from bpy.types import Panel
from ..utils.scene_manager import ProteinBlenderScene

class PROTEIN_UL_protein_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        scene_manager = ProteinBlenderScene.get_instance()
        
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            is_active = (item.name == scene_manager.active_protein)
            layout.prop(item, "name", text="", emboss=False, icon='PROTEIN' if is_active else 'NONE')

class PROTEIN_PT_list(Panel):
    bl_label = "Proteins in Scene"
    bl_idname = "PROTEIN_PT_list"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    
    def draw(self, context):
        layout = self.layout
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Create box for protein list
        box = layout.box()
        
        if not scene_manager.proteins:
            box.label(text="No proteins in scene", icon='INFO')
            return
            
        # Create column for protein entries
        col = box.column()
        
        # Draw each protein entry
        for protein_id, protein in scene_manager.proteins.items():
            row = col.row(align=True)
            
            # Highlight active protein
            is_active = (protein_id == scene_manager.active_protein)
            
            # Create clickable operator for selection
            op = row.operator(
                "protein.select_protein",
                text=f"{protein.identifier}",
                depress=is_active,
                icon='RADIOBUT_ON' if is_active else 'RADIOBUT_OFF'
            )
            op.protein_id = protein_id
            
            # Show additional protein info
            sub_row = row.row()
            sub_row.alignment = 'RIGHT'
            sub_row.label(text=f"({protein.method})")

class PROTEIN_OT_select_protein(bpy.types.Operator):
    bl_idname = "protein.select_protein"
    bl_label = "Select Protein"
    bl_description = "Set the active protein"
    
    protein_id: bpy.props.StringProperty()
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        scene_manager.set_active_protein(self.protein_id)
        
        # Deselect all objects first
        bpy.ops.object.select_all(action='DESELECT')
        
        # Get the protein instance
        protein = scene_manager.proteins.get(self.protein_id)
        if protein and protein.model:
            # Select all objects associated with this protein
            for obj in protein.model.objects:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
                    # Make the last object active
                    context.view_layer.objects.active = obj
        
        # Show toast notification with valid icon
        protein_id = self.protein_id  # Store in local variable for closure
        def draw_message(self, context):
            self.layout.label(text=f"Selected protein: {protein_id}")
        
        bpy.context.window_manager.popup_menu(draw_message, title="Protein Selected", icon='MESH_UVSPHERE')
        
        # Force UI refresh
        for area in context.screen.areas:
            if area.type in ['PROPERTIES', 'VIEW_3D']:
                area.tag_redraw()
        
        return {'FINISHED'}

def register_protein_list_panel():
    bpy.utils.register_class(PROTEIN_UL_protein_list)
    bpy.utils.register_class(PROTEIN_PT_list)
    bpy.utils.register_class(PROTEIN_OT_select_protein)

def unregister_protein_list_panel():
    bpy.utils.unregister_class(PROTEIN_UL_protein_list)
    bpy.utils.unregister_class(PROTEIN_PT_list)
    bpy.utils.unregister_class(PROTEIN_OT_select_protein)