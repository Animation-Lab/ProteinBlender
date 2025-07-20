"""Domain Maker panel with conditional display"""

import bpy
from bpy.types import Panel
from bpy.props import IntProperty
from ..utils.scene_manager import ProteinBlenderScene


class PROTEINBLENDER_PT_domain_maker(Panel):
    """Domain Maker panel - only active when chain or domain selected"""
    bl_label = "Domain Maker"
    bl_idname = "PROTEINBLENDER_PT_domain_maker"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_order = 3  # After visual setup
    
    @classmethod
    def poll(cls, context):
        """Only show panel when a single chain or domain is selected"""
        scene = context.scene
        selected_items = [item for item in scene.outliner_items if item.is_selected]
        
        # Must have exactly one selection
        if len(selected_items) != 1:
            return False
        
        # Must be a chain or domain
        return selected_items[0].item_type in ['CHAIN', 'DOMAIN']
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected item
        selected_item = None
        for item in scene.outliner_items:
            if item.is_selected:
                selected_item = item
                break
        
        if not selected_item:
            return
        
        # Show what's selected
        box = layout.box()
        col = box.column(align=True)
        
        if selected_item.item_type == 'CHAIN':
            col.label(text=f"Chain: {selected_item.name}", icon='LINKED')
            
            # Get chain info
            molecule_id = selected_item.parent_id
            molecule = scene_manager.molecules.get(molecule_id)
            
            if molecule:
                # Show chain residue range
                # TODO: Get actual residue range from chain
                col.label(text="Residue range: 1-200", icon='INFO')
                
        elif selected_item.item_type == 'DOMAIN':
            col.label(text=f"Domain: {selected_item.name}", icon='GROUP_VERTEX')
            col.label(text=f"Residues: {selected_item.domain_start}-{selected_item.domain_end}")
        
        layout.separator()
        
        # Split Chain button
        if selected_item.item_type == 'CHAIN':
            col = layout.column(align=True)
            col.label(text="Create Domain", icon='MESH_PLANE')
            
            # Input fields for domain range
            row = col.row(align=True)
            
            # Store values in scene for persistence
            if not hasattr(scene, "domain_maker_start"):
                scene.domain_maker_start = 1
            if not hasattr(scene, "domain_maker_end"):
                scene.domain_maker_end = 50
            
            row.prop(scene, "domain_maker_start", text="Start")
            row.prop(scene, "domain_maker_end", text="End")
            
            # Split button
            row = col.row()
            row.scale_y = 1.5
            op = row.operator("proteinblender.split_domain", text="Split Chain", icon='MESH_PLANE')
            
            # Pass parameters to operator
            op.chain_id = selected_item.chain_id
            op.molecule_id = selected_item.parent_id
            op.split_start = scene.domain_maker_start
            op.split_end = scene.domain_maker_end
            
            # Info about auto-generation
            col.separator()
            info_box = col.box()
            info_col = info_box.column(align=True)
            info_col.scale_y = 0.8
            info_col.label(text="Auto-generates complementary", icon='INFO')
            info_col.label(text="domains to cover full chain")
            
        # Domain operations
        elif selected_item.item_type == 'DOMAIN':
            col = layout.column(align=True)
            
            # Rename domain
            row = col.row(align=True)
            row.label(text="Name:", icon='FONT_DATA')
            row.prop(selected_item, "name", text="")
            
            col.separator()
            
            # Adjust domain range
            col.label(text="Adjust Range", icon='ARROW_LEFTRIGHT')
            row = col.row(align=True)
            row.prop(selected_item, "domain_start", text="Start")
            row.prop(selected_item, "domain_end", text="End")
            
            # Update button
            row = col.row()
            row.operator("proteinblender.update_domain_range", text="Update Range", icon='FILE_REFRESH')
            
            col.separator()
            
            # Merge/Delete operations
            row = col.row(align=True)
            row.scale_y = 1.2
            row.operator("proteinblender.merge_domains", text="Merge", icon='AUTOMERGE_ON')
            row.operator("proteinblender.delete_domain", text="Delete", icon='X')


# Register properties
def register_props():
    """Register scene properties for domain maker"""
    
    bpy.types.Scene.domain_maker_start = IntProperty(
        name="Start",
        description="Start residue for new domain",
        min=1,
        default=1
    )
    
    bpy.types.Scene.domain_maker_end = IntProperty(
        name="End",
        description="End residue for new domain",
        min=1,
        default=50
    )


def unregister_props():
    """Unregister scene properties"""
    if hasattr(bpy.types.Scene, "domain_maker_start"):
        del bpy.types.Scene.domain_maker_start
    if hasattr(bpy.types.Scene, "domain_maker_end"):
        del bpy.types.Scene.domain_maker_end


# Classes to register
CLASSES = [
    PROTEINBLENDER_PT_domain_maker,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_props()


def unregister():
    unregister_props()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)