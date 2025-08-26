"""Animation panel for keyframe creation and management"""

import bpy
from bpy.types import Panel, UIList
from ..utils.scene_manager import ProteinBlenderScene


class PROTEINBLENDER_UL_keyframe_list(UIList):
    """UI List for displaying keyframes"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Frame number
            row.label(text=f"Frame {item.frame}", icon='KEYFRAME')
            
            # Keyframe name
            if item.name:
                row.label(text=item.name)
            else:
                row.label(text="(unnamed)")
            
            # Brownian motion indicator
            if item.use_brownian_motion:
                row.label(text="", icon='FORCE_TURBULENCE')
        
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=str(item.frame))


class PROTEINBLENDER_PT_animation(Panel):
    """Animation panel with keyframe creation tools"""
    bl_label = "Animate Scene"
    bl_idname = "PROTEINBLENDER_PT_animation"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 6  # After pose library
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Create a box for the entire panel content
        main_box = layout.box()
        
        # Add panel title inside the box
        main_box.label(text="Animate Scene", icon='PLAY')
        main_box.separator()
        
        # Main column
        col = main_box.column(align=True)
        
        # Keyframe Creation Section
        keyframe_box = col.box()
        keyframe_col = keyframe_box.column(align=True)
        
        # Section header
        keyframe_col.label(text="Keyframe Tools", icon='KEYFRAME')
        keyframe_col.separator()
        
        # Create Keyframe button - the main feature
        row = keyframe_col.row(align=True)
        row.scale_y = 1.5
        row.operator("proteinblender.create_keyframe", text="Create Keyframe", icon='KEYFRAME_HLT')
        
        keyframe_col.separator()
        
        # Current frame info
        row = keyframe_col.row(align=True)
        row.label(text=f"Current Frame: {scene.frame_current}", icon='TIME')
        
        col.separator()
        
        # Existing Keyframes Section
        keyframe_list_box = col.box()
        keyframe_list_col = keyframe_list_box.column(align=True)
        
        # Section header
        keyframe_list_col.label(text="Keyframe List", icon='ACTION')
        keyframe_list_col.separator()
        
        # Get active molecule
        molecule_item = None
        if scene.selected_molecule_id:
            for item in scene.molecule_list_items:
                if item.identifier == scene.selected_molecule_id:
                    molecule_item = item
                    break
        
        if molecule_item and len(molecule_item.keyframes) > 0:
            # Display keyframe list
            row = keyframe_list_col.row()
            row.template_list(
                "PROTEINBLENDER_UL_keyframe_list",
                "keyframe_list",
                molecule_item,
                "keyframes",
                molecule_item,
                "active_keyframe_index",
                rows=3
            )
            
            # Keyframe operations
            col_ops = row.column(align=True)
            col_ops.operator("proteinblender.delete_keyframe", text="", icon='REMOVE')
            col_ops.separator()
            col_ops.operator("proteinblender.jump_to_keyframe", text="", icon='FRAME_NEXT')
            
            # Selected keyframe details
            if 0 <= molecule_item.active_keyframe_index < len(molecule_item.keyframes):
                active_kf = molecule_item.keyframes[molecule_item.active_keyframe_index]
                
                detail_box = keyframe_list_col.box()
                detail_col = detail_box.column(align=True)
                
                # Brownian motion settings
                row = detail_col.row(align=True)
                row.prop(active_kf, "use_brownian_motion", text="Brownian Motion")
                
                if active_kf.use_brownian_motion:
                    detail_col.prop(active_kf, "intensity", text="Intensity")
                    detail_col.prop(active_kf, "frequency", text="Frequency")
                    detail_col.prop(active_kf, "seed", text="Seed")
        else:
            # No keyframes message
            keyframe_list_col.label(text="No keyframes created yet", icon='INFO')
            keyframe_list_col.label(text="Use 'Create Keyframe' to add keyframes")
        
        col.separator()
        
        # Animation Playback Section
        playback_box = col.box()
        playback_col = playback_box.column(align=True)
        
        # Section header
        playback_col.label(text="Timeline & Playback", icon='TIME')
        playback_col.separator()
        
        # Timeline range controls
        row = playback_col.row(align=True)
        row.label(text="Timeline Range:")
        row.prop(scene, "frame_start", text="Start")
        row.prop(scene, "frame_end", text="End")
        
        playback_col.separator()
        
        # Playback controls
        row = playback_col.row(align=True)
        row.scale_y = 1.2
        
        # Play/Pause button
        if context.screen.is_animation_playing:
            row.operator("screen.animation_play", text="", icon='PAUSE')
        else:
            row.operator("screen.animation_play", text="", icon='PLAY')
        
        # Frame navigation
        row.operator("screen.frame_jump", text="", icon='REW').end = False
        row.operator("screen.keyframe_jump", text="", icon='PREV_KEYFRAME').next = False
        row.operator("screen.keyframe_jump", text="", icon='NEXT_KEYFRAME').next = True
        row.operator("screen.frame_jump", text="", icon='FF').end = True
        
        # Frame rate
        row = playback_col.row(align=True)
        row.prop(scene.render, "fps", text="FPS")
        
        col.separator()
        
        # Tips Section
        tips_box = col.box()
        tips_col = tips_box.column(align=True)
        tips_col.scale_y = 0.8
        tips_col.label(text="Tips:", icon='INFO')
        tips_col.label(text="• Apply poses before creating keyframes")
        tips_col.label(text="• Select specific transforms per item")
        tips_col.label(text="• Use timeline to navigate frames")
        
        # Add bottom spacing
        layout.separator()


# Placeholder operators for future implementation
class PROTEINBLENDER_OT_delete_keyframe(bpy.types.Operator):
    """Delete selected keyframe"""
    bl_idname = "proteinblender.delete_keyframe"
    bl_label = "Delete Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Get active molecule
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                if 0 <= item.active_keyframe_index < len(item.keyframes):
                    item.keyframes.remove(item.active_keyframe_index)
                    
                    # Adjust index if needed
                    if item.active_keyframe_index >= len(item.keyframes) and item.active_keyframe_index > 0:
                        item.active_keyframe_index -= 1
                    
                    self.report({'INFO'}, "Keyframe deleted")
                break
        
        return {'FINISHED'}


class PROTEINBLENDER_OT_jump_to_keyframe(bpy.types.Operator):
    """Jump to selected keyframe"""
    bl_idname = "proteinblender.jump_to_keyframe"
    bl_label = "Jump to Keyframe"
    
    def execute(self, context):
        scene = context.scene
        
        # Get active molecule
        for item in scene.molecule_list_items:
            if item.identifier == scene.selected_molecule_id:
                if 0 <= item.active_keyframe_index < len(item.keyframes):
                    active_kf = item.keyframes[item.active_keyframe_index]
                    scene.frame_set(active_kf.frame)
                break
        
        return {'FINISHED'}


# Classes to register
CLASSES = [
    PROTEINBLENDER_UL_keyframe_list,
    PROTEINBLENDER_PT_animation,
    PROTEINBLENDER_OT_delete_keyframe,
    PROTEINBLENDER_OT_jump_to_keyframe,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)