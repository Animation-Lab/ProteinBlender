"""Animation panel: keyframe creation, navigation and deletion.

All keyframe state shown here is read directly from the actual F-Curves on the
keyframe targets (puppet controllers + DNA/RNA molecules) via
``get_keyframe_frames`` — there is no parallel keyframe list to drift out of
sync. Everything is reachable from this panel, so users never need Blender's
native timeline to manage ProteinBlender keyframes.
"""

import bpy
from bpy.types import Panel
from bpy.props import IntProperty
from ..utils.animation import (
    delete_transform_keyframes,
    remove_color_keyframes,
)
from ..operators.keyframe_operators import (
    get_keyframe_targets,
    get_keyframe_frames,
    get_keyframe_animated_objects,
    get_puppet_member_objects,
    delete_keyframe_metadata,
)


class PROTEINBLENDER_PT_animation(Panel):
    """Animation panel: create, navigate and delete keyframes."""
    bl_label = "Animate Scene"
    bl_idname = "PROTEINBLENDER_PT_animation"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 10  # After all Builder panels (DNA = 8, Membrane = 9)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        current = scene.frame_current
        frames = get_keyframe_frames(context)

        main_box = layout.box()
        main_box.label(text="Animate Scene", icon='PLAY')
        main_box.separator()
        col = main_box.column(align=True)

        # --- Keyframe tools:  |< prev  |  Create/Edit  |  next >|  ---
        tools = col.box().column(align=True)
        tools.label(text="Keyframe Tools", icon='KEYFRAME')
        tools.separator()

        nav = tools.row(align=True)
        nav.scale_y = 1.4

        prev_frames = [f for f in frames if f < current]
        next_frames = [f for f in frames if f > current]

        sub = nav.row(align=True)
        sub.enabled = bool(prev_frames)
        sub.operator("proteinblender.jump_to_keyframe", text="",
                     icon='PREV_KEYFRAME').frame = prev_frames[-1] if prev_frames else -1

        if current in frames:
            nav.operator("proteinblender.create_keyframe", text="Edit Keyframe", icon='KEYFRAME')
        else:
            nav.operator("proteinblender.create_keyframe", text="Create Keyframe", icon='KEYFRAME_HLT')

        sub = nav.row(align=True)
        sub.enabled = bool(next_frames)
        sub.operator("proteinblender.jump_to_keyframe", text="",
                     icon='NEXT_KEYFRAME').frame = next_frames[0] if next_frames else -1

        tools.separator()
        tools.label(text=f"Current Frame: {current}", icon='TIME')

        # --- Keyframe list: one row per frame, with jump + delete ---
        list_box = col.box()
        list_box.label(text=f"Keyframes ({len(frames)})", icon='KEYFRAME')
        if frames:
            for f in frames:
                r = list_box.row(align=True)
                is_cur = (f == current)
                op = r.operator("proteinblender.jump_to_keyframe",
                                text=f"Frame {f}",
                                icon='KEYFRAME_HLT' if is_cur else 'KEYFRAME',
                                depress=is_cur)
                op.frame = f
                r.operator("proteinblender.delete_keyframe", text="", icon='X').frame = f
        else:
            list_box.label(text="No keyframes yet", icon='INFO')

        layout.separator()


class PROTEINBLENDER_OT_jump_to_keyframe(bpy.types.Operator):
    """Move the playhead to this keyframe"""
    bl_idname = "proteinblender.jump_to_keyframe"
    bl_label = "Jump to Keyframe"

    frame: IntProperty(default=-1)

    def execute(self, context):
        if self.frame >= 0:
            context.scene.frame_set(self.frame)
        return {'FINISHED'}


class PROTEINBLENDER_OT_delete_keyframe(bpy.types.Operator):
    """Delete every ProteinBlender keyframe at this frame — across all puppets
    and DNA/RNA molecules, including puppet domain pose/colour keyframes"""
    bl_idname = "proteinblender.delete_keyframe"
    bl_label = "Delete Keyframe"
    bl_options = {'REGISTER', 'UNDO'}

    frame: IntProperty(default=-1)

    def execute(self, context):
        if self.frame < 0:
            return {'CANCELLED'}
        for _label, obj, kind, item_id in get_keyframe_targets(context):
            objs = list(get_keyframe_animated_objects(obj, kind))  # molecule + DNA bend nodes
            if kind == 'PUPPET':
                objs += get_puppet_member_objects(context, item_id)
            for o in objs:
                delete_transform_keyframes(o, self.frame)
                remove_color_keyframes(o, self.frame)
            delete_keyframe_metadata(obj, self.frame)

        for area in context.screen.areas:
            if area.type in ('PROPERTIES', 'VIEW_3D', 'DOPESHEET_EDITOR', 'TIMELINE'):
                area.tag_redraw()
        self.report({'INFO'}, f"Deleted keyframe at frame {self.frame}")
        return {'FINISHED'}


# Classes to register
CLASSES = [
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
