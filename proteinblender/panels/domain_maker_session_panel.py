"""Sidebar menu for the interactive Domain Maker session.

Draws in the N-panel of the temporary session window's 3D viewport, so the
user sees the isolated chain on the left and this menu on the right. It only
polls visible while a session is active.
"""

import bpy
from bpy.types import Panel


class PROTEINBLENDER_PT_domain_maker_session(Panel):
    """Domain Maker menu shown alongside the live session viewport"""
    bl_label = "Domain Maker"
    bl_idname = "PROTEINBLENDER_PT_domain_maker_session"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Domain Maker"

    @classmethod
    def poll(cls, context):
        state = getattr(context.window_manager, "pb_domain_maker", None)
        return bool(state and state.active)

    def draw(self, context):
        layout = self.layout
        state = context.window_manager.pb_domain_maker

        # Which chain is being carved up.
        header = layout.box().column(align=True)
        header.label(text=state.chain_name or "Chain", icon='LINKED')

        # Build stage: pick how many domains, then lay them out.
        build = layout.column(align=True)
        row = build.row(align=True)
        row.prop(state, "num_domains", text="Number of Domains")
        build_row = build.row()
        build_row.scale_y = 1.3
        build_row.operator("proteinblender.domain_maker_build", text="Build Domains",
                           icon='MOD_ARRAY')

        if not state.built:
            info = layout.box()
            info.scale_y = 0.85
            info.label(text="Set the number of domains,", icon='INFO')
            info.label(text="then Build to edit their ranges.")
            self._draw_footer(layout, can_create=False)
            return

        layout.separator()

        # Range-editing stage.
        box = layout.box()
        box.label(text=f"{state.chain_name}: valid range "
                       f"{state.chain_start} - {state.chain_end}", icon='ARROW_LEFTRIGHT')

        col = box.column(align=True)
        for i, dom in enumerate(state.domains):
            is_active = (i == state.active_index)
            row = col.box().row(align=True) if is_active else col.row(align=True)

            sel = row.operator("proteinblender.domain_maker_select", text="",
                               icon='RESTRICT_SELECT_OFF' if is_active else 'DOT',
                               emboss=is_active)
            sel.index = i

            row.prop(dom, "name", text="")
            sub = row.row(align=True)
            sub.prop(dom, "start", text="Start")
            sub.prop(dom, "end", text="End")

        # Live validation echo.
        problem = _quick_validation(state)
        if problem:
            layout.label(text=problem, icon='ERROR')

        self._draw_footer(layout, can_create=not problem)

    def _draw_footer(self, layout, can_create):
        layout.separator()
        row = layout.row()
        row.scale_y = 1.4
        create = row.row()
        create.enabled = can_create
        create.operator("proteinblender.domain_maker_create", text="Create Domains",
                        icon='CHECKMARK')
        layout.operator("proteinblender.domain_maker_cancel", text="Cancel", icon='X')


def _quick_validation(state):
    """Short human-readable problem string for the current ranges, or ''."""
    ranges = sorted(((d.start, d.end, d.name) for d in state.domains), key=lambda r: r[0])
    for s, e, name in ranges:
        if s > e:
            return f"{name}: start past end"
        if s < state.chain_start or e > state.chain_end:
            return f"{name}: outside {state.chain_start}-{state.chain_end}"
    for (sa, ea, na), (sb, eb, nb) in zip(ranges, ranges[1:]):
        if sb <= ea:
            return f"{na} / {nb} overlap"
    return ""


CLASSES = (
    PROTEINBLENDER_PT_domain_maker_session,
)
