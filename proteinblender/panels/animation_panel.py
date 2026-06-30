"""Animation panel: keyframe creation, navigation and deletion.

All keyframe state shown here is read directly from the actual F-Curves on the
keyframe targets (puppet controllers + DNA/RNA molecules) via
``get_keyframe_frames`` — there is no parallel keyframe list to drift out of
sync. Everything is reachable from this panel, so users never need Blender's
native timeline to manage ProteinBlender keyframes.
"""

import bpy
from bpy.types import Panel, PropertyGroup, UIList
from bpy.props import IntProperty, BoolProperty, CollectionProperty
from ..utils.animation import (
    delete_transform_keyframes,
    remove_color_keyframes,
)
from ..operators.keyframe_operators import (
    get_keyframe_targets,
    get_filtered_keyframe_targets,
    get_keyframe_frames,
    get_keyframe_animated_objects,
    get_puppet_member_objects,
    delete_keyframe_metadata,
    delete_lattice_deformation_keyframes,
)


# ---------------------------------------------------------------------------
# Scrolling keyframe list — backed by a CollectionProperty so we can use
# template_list (the only native widget that gives us a fixed-row scroll
# region; a plain column() of boxes just expands as long as there are
# items, which gets ugly past ~10 keyframes).
# ---------------------------------------------------------------------------

class PROTEINBLENDER_KeyframeListItem(PropertyGroup):
    """One row in the keyframe scroll list. We mirror the computed frames
    list into this collection on each draw — the source of truth is still
    the F-Curves; this is a UI cache."""
    frame: IntProperty(default=-1)


class PROTEINBLENDER_UL_keyframes(UIList):
    """Scrolling list of ProteinBlender keyframes.

    template_list (which renders this UIList) caps the visible area at
    ``rows=N`` and scrolls beyond that. Each row shows the frame
    number + jump / edit / delete buttons — identical to the old
    per-frame ``row()`` layout, just inside a scrolling container.
    """

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            current = context.scene.frame_current
            is_cur = (item.frame == current)
            row = layout.row(align=True)
            jump_op = row.operator(
                "proteinblender.jump_to_keyframe",
                text=f"Frame {item.frame}",
                icon='KEYFRAME_HLT' if is_cur else 'KEYFRAME',
                depress=is_cur,
            )
            jump_op.frame = item.frame
            row.operator(
                "proteinblender.edit_keyframe", text="",
                icon='GREASEPENCIL',
            ).frame = item.frame
            row.operator(
                "proteinblender.delete_keyframe", text="",
                icon='X',
            ).frame = item.frame
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=f"Frame {item.frame}")


def _sync_keyframe_collection(scene, frames):
    """Mirror *frames* into ``scene.pb_keyframe_list`` only if the contents
    differ. Re-running this every draw is fine because the no-change
    fast-path avoids the touch that would otherwise schedule another
    redraw and risk an oscillation."""
    kf_list = scene.pb_keyframe_list
    current = [it.frame for it in kf_list]
    if current == frames:
        return
    kf_list.clear()
    for f in frames:
        kf_list.add().frame = f


class PROTEINBLENDER_PT_animation(Panel):
    """Animation panel: create, navigate and delete keyframes."""
    bl_label = "Animate Scene"
    bl_idname = "PROTEINBLENDER_PT_animation"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 10  # Last of the addon's panels

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        current = scene.frame_current

        # Selection scoping is now opt-in via a toggle on the keyframe
        # list header. Default ON — same behaviour as before. When OFF,
        # the panel always shows every keyframe in the scene.
        filter_on = scene.pb_keyframe_filter_by_selection
        if filter_on:
            targets, n_selected = get_filtered_keyframe_targets(context)
        else:
            targets = get_keyframe_targets(context)
            n_selected = 0
        frames = get_keyframe_frames(context, targets=targets)

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

        # --- Keyframe list: scrolling once past 10 entries ---
        list_box = col.box()

        # Header: title on the left, "filter by selection" toggle on the
        # right. The toggle pinches to icon-only (FILTER) and depresses
        # when active so it reads as a stateful button.
        header_row = list_box.row(align=True)
        header_row.label(text=f"Keyframes ({len(frames)})", icon='KEYFRAME')
        header_row.prop(
            scene, "pb_keyframe_filter_by_selection",
            text="", icon='FILTER', toggle=True,
        )

        if filter_on and n_selected > 0:
            obj_word = "object" if n_selected == 1 else "objects"
            list_box.label(
                text=f"Filtered to {n_selected} selected {obj_word}",
                icon='RESTRICT_SELECT_OFF',
            )

        if frames:
            _sync_keyframe_collection(scene, frames)
            list_box.template_list(
                "PROTEINBLENDER_UL_keyframes", "pb_keyframes",
                scene, "pb_keyframe_list",
                scene, "pb_keyframe_list_index",
                rows=min(10, len(frames)),
                maxrows=10,
            )
        else:
            empty_msg = (
                "No keyframes for the selected object"
                if filter_on and n_selected > 0 else "No keyframes yet"
            )
            list_box.label(text=empty_msg, icon='INFO')

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


class PROTEINBLENDER_OT_edit_keyframe(bpy.types.Operator):
    """Jump to this keyframe and open the keyframe editor for it"""
    bl_idname = "proteinblender.edit_keyframe"
    bl_label = "Edit Keyframe"
    bl_options = {'REGISTER', 'UNDO'}

    frame: IntProperty(default=-1)
    # Headless / automated-test escape hatch: skip the modal dialog and just
    # jump the playhead. Hidden + SKIP_SAVE so it never sticks across UI
    # invocations — only a deliberate scripted caller sets it.
    skip_dialog: BoolProperty(
        default=False, options={'HIDDEN', 'SKIP_SAVE'},
        description="Skip the modal dialog (used by MCP / automated tests)",
    )

    def execute(self, context):
        if self.frame < 0:
            return {'CANCELLED'}
        # Move the playhead first — the create_keyframe operator's invoke()
        # seeds its dialog from scene.frame_current and loads each puppet's
        # stored metadata for that frame, so it has to be set BEFORE we
        # invoke. Calling with 'INVOKE_DEFAULT' makes it pop its dialog
        # exactly like clicking the tools row's "Edit Keyframe" button.
        context.scene.frame_set(self.frame)
        if self.skip_dialog:
            return {'FINISHED'}
        return bpy.ops.proteinblender.create_keyframe('INVOKE_DEFAULT')


class PROTEINBLENDER_OT_dismiss_dialogs(bpy.types.Operator):
    """Dismiss any open modal popups by simulating Esc on every window.

    Primarily a safety/testing tool — Blender exposes no public API to
    introspect or cancel a running modal popup (``invoke_props_dialog``),
    so automated callers that accidentally trigger one have no clean way
    to recover. This operator sends a synthetic Esc keypress to each
    window, which Blender treats the same as the user pressing Esc: the
    topmost modal popup dismisses, normal viewport input resumes.

    **Blender 5.x gotcha:** ``window.event_simulate`` is gated behind the
    ``--enable-event-simulate`` command-line flag, NOT user preferences.
    Without that flag the call raises RuntimeError and this operator can
    only warn — the caller still has to dismiss the popup manually. To
    enable: launch Blender as ``blender --enable-event-simulate``.

    **Preferred path for MCP / scripted tests:** invoke the underlying
    operator with the ``skip_dialog=True`` property (e.g.
    ``bpy.ops.proteinblender.edit_keyframe(frame=N, skip_dialog=True)``)
    so the modal never opens. The dismiss path is a recovery tool for
    callers that didn't anticipate the modal."""
    bl_idname = "proteinblender.dismiss_dialogs"
    bl_label = "Dismiss ProteinBlender Dialogs"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        dispatched = 0
        gated = 0
        last_err = None
        for window in context.window_manager.windows:
            try:
                window.event_simulate(type='ESC', value='PRESS')
                window.event_simulate(type='ESC', value='RELEASE')
                dispatched += 1
            except RuntimeError as e:
                # event_simulate is gated unless Blender was started with
                # the --enable-event-simulate flag. Surface that as a
                # single explicit warning so the caller knows what to do
                # rather than seeing a per-window stack trace.
                gated += 1
                last_err = str(e).strip()

        if dispatched:
            self.report({'INFO'},
                        f"Dispatched Esc to {dispatched} window(s)")
        if gated:
            self.report(
                {'WARNING'},
                f"event_simulate disabled on {gated} window(s) — relaunch "
                f"Blender with --enable-event-simulate to use this "
                f"operator (or pass skip_dialog=True to the operator that "
                f"opens the modal). Last error: {last_err!r}"
            )
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
            objs = list(get_keyframe_animated_objects(obj, kind))  # molecule + DNA bend nodes, or membrane + holes
            if kind == 'PUPPET':
                objs += get_puppet_member_objects(context, item_id)
            for o in objs:
                delete_transform_keyframes(o, self.frame)
                remove_color_keyframes(o, self.frame)
            # Membrane lattice deformation keys live on the lattice DATA, not
            # any object transform — they need their own teardown call.
            if kind == 'MEMBRANE':
                delete_lattice_deformation_keyframes(obj, self.frame)
            delete_keyframe_metadata(obj, self.frame)

        for area in context.screen.areas:
            if area.type in ('PROPERTIES', 'VIEW_3D', 'DOPESHEET_EDITOR', 'TIMELINE'):
                area.tag_redraw()
        self.report({'INFO'}, f"Deleted keyframe at frame {self.frame}")
        return {'FINISHED'}


# Class registration is owned by ``proteinblender.panels.__init__``'s
# central CLASSES list. This module only exposes a ``register_props`` /
# ``unregister_props`` pair (called from the same central place) for the
# scene-level keyframe-list state.

def register_props():
    bpy.types.Scene.pb_keyframe_list = CollectionProperty(
        type=PROTEINBLENDER_KeyframeListItem,
    )
    bpy.types.Scene.pb_keyframe_list_index = IntProperty(default=0)
    bpy.types.Scene.pb_keyframe_filter_by_selection = BoolProperty(
        name="Filter Keyframes by Selection",
        description=(
            "When on, the keyframe list only shows frames belonging to the "
            "currently selected object(s) — clicking a chain, hole, or "
            "bend node scopes the list to that target. When off, every "
            "scene keyframe is shown regardless of selection."
        ),
        default=True,
    )


def unregister_props():
    for attr in ("pb_keyframe_list", "pb_keyframe_list_index",
                 "pb_keyframe_filter_by_selection"):
        if hasattr(bpy.types.Scene, attr):
            try:
                delattr(bpy.types.Scene, attr)
            except Exception:
                pass
