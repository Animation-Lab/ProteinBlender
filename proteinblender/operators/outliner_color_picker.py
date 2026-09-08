"""Click a mixed outliner swatch to choose a shared color."""

import bpy
from bpy.props import BoolProperty, FloatVectorProperty, StringProperty

from ..core.outliner_colors import palette_description, row_has_swatch


def _target(context, properties):
    # Re-resolve on every draw: outliner rebuilds invalidate RNA row pointers.
    return next((item for item in context.scene.outliner_items
                 if item.item_id == properties.item_id
                 and item.item_type == properties.item_type
                 and row_has_swatch(item)), None)


def _color_edited(self, context):
    self.color_edited = True


class PROTEINBLENDER_OT_outliner_color_picker(bpy.types.Operator):
    bl_idname = "proteinblender.outliner_color_picker"
    bl_label = "Set Shared Color"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    item_id: StringProperty(options={'HIDDEN'})
    item_type: StringProperty(default='PROTEIN', options={'HIDDEN'})
    color: FloatVectorProperty(
        name='Color', subtype='COLOR', size=4, min=0, max=1,
        default=(0.5, 0.5, 0.5, 1), update=_color_edited)
    color_edited: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        item = _target(context, properties)
        return palette_description(item) if item else "Set a shared color"

    def invoke(self, context, event):
        item = _target(context, self)
        if item is None:
            return {'CANCELLED'}
        self.color = item.row_color
        self.color_edited = False
        # The automatic operator popup records a reversible color operation.
        # A plain invoke_popup with a scene-bound wheel omits that undo step.
        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        item = _target(context, self)
        if item is None:
            self.layout.label(text="Item no longer available")
            return
        self.layout.template_color_picker(self, "color", value_slider=True)
        self.layout.prop(self, "color", text="Color")

    def execute(self, context):
        item = _target(context, self)
        if item is None:
            return {'CANCELLED'}
        if self.color_edited:
            item.row_color = self.color
        return {'FINISHED'}


CLASSES = (PROTEINBLENDER_OT_outliner_color_picker,)
