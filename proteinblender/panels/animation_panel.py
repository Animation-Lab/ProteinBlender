"""Animation panel - placeholder for future implementation"""

import bpy
from bpy.types import Panel


class PROTEINBLENDER_PT_animation(Panel):
    """Animation panel - placeholder"""
    bl_label = "Animate Scene"
    bl_idname = "PROTEINBLENDER_PT_animation"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 6  # After pose library
    
    def draw(self, context):
        layout = self.layout
        
        # Create a box for the entire panel content
        main_box = layout.box()
        
        # Add panel title inside the box
        main_box.label(text="Animate Scene", icon='PLAY')
        main_box.separator()
        
        # Placeholder content
        col = main_box.column(align=True)
        
        # Coming soon message
        box = col.box()
        box_col = box.column(align=True)
        box_col.label(text="Coming Soon!", icon='INFO')
        box_col.separator()
        box_col.label(text="Animation features will")
        box_col.label(text="be available in a")
        box_col.label(text="future update.")
        
        # Add bottom spacing
        layout.separator()
        
        col.separator()
        
        # Mock UI elements (disabled)
        col.label(text="Animation Tools:", icon='ARMATURE_DATA')
        
        # Pivot section
        row = col.row(align=True)
        row.enabled = False
        row.label(text="Pivot:", icon='PIVOT_CURSOR')
        row.operator("proteinblender.placeholder", text="Move Pivot", icon='OBJECT_ORIGIN')
        row.operator("proteinblender.placeholder", text="Snap to Center", icon='SNAP_ON')
        
        col.separator()
        
        # Add Keyframe section
        col.label(text="Add Keyframe", icon='KEYFRAME')
        
        row = col.row(align=True)
        row.enabled = False
        
        # Mock Brownian Motion checkbox
        sub = row.row(align=True)
        sub.prop(context.scene, "placeholder_brownian", text="")
        sub.label(text="Brownian Motion")
        
        col.separator()
        
        # Info text
        info_box = col.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 0.8
        info_col.label(text="Must add keyframe after", icon='INFO')
        info_col.label(text="applying pose if you want")
        info_col.label(text="to animate between")
        info_col.label(text="two poses")


# Classes to register
CLASSES = [
    PROTEINBLENDER_PT_animation,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)