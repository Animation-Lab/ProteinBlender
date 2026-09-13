"""One dialog for setting up and refreshing the scene's molecular light rig."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty

from ..core.lighting import setup_lighting


class PROTEINBLENDER_OT_setup_lighting(bpy.types.Operator):
    bl_idname = "proteinblender.setup_lighting"
    bl_label = "Set Up Lighting"
    bl_description = "Fit soft, neutral lights to the visible scene at the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name="Style", items=[
        ('STUDIO', "Soft Studio", "Balanced depth and gentle shadows for most molecular scenes"),
        ('SURFACE', "Surface Detail", "Stronger directional shading for pockets and molecular surfaces"),
        ('ILLUSTRATION', "Bright Illustration", "Flat colors and dark contours for a 2D illustration"),
    ], default='STUDIO')
    brightness: FloatProperty(name="Brightness", default=1, min=0.1, max=5,
                              description="Scale the brightness of the lighting setup")
    alignment: EnumProperty(name="Orient From", items=[
        ('AUTO', "Camera / View", "Use the render camera, or the current view when there is no camera"),
        ('VIEW', "Current View", "Use the current 3D viewport orientation"),
    ], default='AUTO')
    mute_existing: BoolProperty(name="Mute Other Lights", default=True,
        description="Hide other lights without deleting them; uncheck and apply again to restore them")
    preview: BoolProperty(name="Show Lighting in Viewport", default=True,
        description="Show Material Preview using the scene's lights and world")
    outlines: BoolProperty(name="Outlines", default=True,
        description="Add dark contours to Bright Illustration")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'preset')
        hints = {
            'STUDIO': "Balanced depth with soft shadows.",
            'SURFACE': "Emphasize pockets and surface shape.",
            'ILLUSTRATION': "Flat colors with optional dark contours.",
        }
        layout.label(text=hints[self.preset])
        layout.prop(self, 'brightness', slider=True)
        if self.preset == 'ILLUSTRATION':
            layout.prop(self, 'outlines')
        layout.prop(self, 'alignment')
        layout.prop(self, 'mute_existing')
        layout.prop(self, 'preview')
        row = layout.row()
        row.operator_context = 'EXEC_DEFAULT'
        apply = row.operator('proteinblender.apply_lighting', text='Apply', icon='CHECKMARK')
        for name in ('preset', 'brightness', 'alignment', 'mute_existing', 'preview', 'outlines'):
            setattr(apply, name, getattr(self, name))
        layout.separator()
        layout.label(text="Fits visible geometry at the current frame.", icon='INFO')
        layout.label(text="Run again after moving or adding models.")

    def execute(self, context):
        try:
            setup_lighting(context, self.preset, self.brightness, self.alignment,
                           self.mute_existing, self.preview, self.outlines)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "Scene lighting updated")
        return {'FINISHED'}

    def cancel(self, context):
        """Applied settings are committed; closing only discards pending fields."""


class PROTEINBLENDER_OT_apply_lighting(bpy.types.Operator):
    bl_idname = 'proteinblender.apply_lighting'
    bl_label = 'Apply Lighting'
    bl_options = {'REGISTER', 'UNDO'}
    __annotations__ = PROTEINBLENDER_OT_setup_lighting.__annotations__.copy()
    execute = PROTEINBLENDER_OT_setup_lighting.execute


CLASSES = (PROTEINBLENDER_OT_setup_lighting, PROTEINBLENDER_OT_apply_lighting)
