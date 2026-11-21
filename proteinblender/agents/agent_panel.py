"""The Agent Brains panel: agent types, each type's brain, and the live preview."""

import bpy
from bpy.types import Menu, Panel, UIList

from . import agent_preview, engine
from .agent_examples import EXAMPLE_ITEMS
from .agent_props import (
    TRIGGER_ICONS,
    describe_rule,
    find_type,
    enum_uid,
    rule_problem,
)


def _active(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


def _session(context):
    return agent_preview.session_for(context.scene)


def _usable_width(context, margin):
    """Pixels a row gets in this region, less ``margin`` (UI-scaled) for list chrome."""
    # system.ui_scale folds in the monitor's DPI, so it is 0 with no window
    # (a background run); the user's own scale setting stands in for it there.
    prefs = context.preferences
    scale = prefs.system.ui_scale or prefs.view.ui_scale or 1.0
    region = getattr(context, "region", None)
    width = getattr(region, "width", 0) or 400 * scale
    return max(width - margin * scale, 120 * scale), scale


def _strip(layout, factor):
    split = layout.split(factor=min(max(factor, 0.02), 0.9), align=True)
    return split.row(align=True), split.row(align=True)


def _fixed_left(layout, context, px, margin=70):
    """Split ``layout`` into a ``px``-wide strip and the rest.

    UILayout has no fixed-width option: ``ui_units_x`` only weights a row's
    share, so a colour swatch sized that way grows with a wide editor. A split
    factor worked out from the region's width keeps the strip the same size.
    """
    width, scale = _usable_width(context, margin)
    return _strip(layout, px * scale / width)


def _fixed_right(layout, context, px, used_px, margin=70):
    """Split off a ``px``-wide strip on the right, after ``used_px`` taken on the left."""
    width, scale = _usable_width(context, margin)
    rest = max(width - used_px * scale, 60 * scale)
    return _strip(layout, 1.0 - px * scale / rest)


def _live_count(session, type_uid, state_uid):
    if session is None:
        return None
    return session.sim.counts().get(type_uid, {}).get(state_uid)


class PB_AGENTS_MT_examples(Menu):
    bl_idname = "PB_AGENTS_MT_examples"
    bl_label = "Example Brains"

    def draw(self, context):
        layout = self.layout
        for key, label, _text in EXAMPLE_ITEMS:
            layout.operator("pb_agents.load_example", text=label).example = key


class PB_AGENTS_UL_types(UIList):
    bl_idname = "PB_AGENTS_UL_types"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="COMMUNITY")
        info = row.row()
        info.alignment = "RIGHT"
        info.label(text=f"{item.count} × {item.radius_nm:g} nm")


class PB_AGENTS_UL_states(UIList):
    bl_idname = "PB_AGENTS_UL_states"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        swatch, rest = _fixed_left(layout, context, 26)
        swatch.prop(item, "color", text="")
        middle, share = _fixed_right(rest, context, 64, 26)
        middle.prop(item, "name", text="", emboss=False)
        count = _live_count(_session(context), data.uid, item.uid)
        if count is not None:
            live = middle.row()
            live.alignment = "RIGHT"
            live.label(text=str(count))
        share.prop(item, "start_share", text="")


class PB_AGENTS_UL_rules(UIList):
    bl_idname = "PB_AGENTS_UL_rules"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        problem = rule_problem(data, item)
        text = describe_rule(data, item)
        sentence = row.row()
        sentence.active = item.enabled and not problem
        sentence.label(text=text, icon="ERROR" if problem else TRIGGER_ICONS[item.trigger])
        session = _session(context)
        if session is not None:
            stats = session.sim.stats.get(item.uid)
            if stats is not None:
                fired = row.row()
                fired.alignment = "RIGHT"
                fired.label(text=f"{stats.fired}×")


def _line(col, label):
    split = col.split(factor=0.34, align=True)
    left = split.row()
    left.alignment = "RIGHT"
    left.label(text=label)
    return split.row(align=True)


def draw_rule_editor(layout, agent_type, rule, session):
    box = layout.box()
    col = box.column(align=False)
    name = agent_type.name

    _line(col, f"{name} in").prop(rule, "from_state", text="")
    _line(col, "Changes").prop(rule, "trigger", text="")

    partner = None
    if rule.trigger != engine.TIMER:
        partner_uid = enum_uid(rule.partner_type)
        partner = find_type(agent_type.id_data.pb_agents, partner_uid) if partner_uid else None
        row = _line(col, "Touching" if rule.trigger == engine.MEET else "Stuck to")
        row.prop(rule, "partner_type", text="")
        row.prop(rule, "partner_state", text="")

    if rule.trigger == engine.MEET:
        _line(col, "Within (nm)").prop(rule, "reach_nm", text="")
        facing = _line(col, "Only if").column(align=True)
        own = facing.row()
        own.active = agent_type.has_site
        own.prop(rule, "self_facing",
                 text=(f"Its {agent_type.site_name} faces the partner" if agent_type.has_site
                       else "Its site faces the partner (no site)"))
        theirs = facing.row()
        has_partner_site = partner is not None and partner.has_site
        theirs.active = has_partner_site or partner is None
        if partner is None:
            label = "The partner's site faces it"
        elif partner.has_site:
            label = f"The {partner.name}'s {partner.site_name} faces it"
        else:
            label = f"The {partner.name}'s site faces it (no site)"
        theirs.prop(rule, "partner_facing", text=label)
        _line(col, "Chance per touch").prop(rule, "chance", text="", slider=True)
    else:
        _line(col, "Average wait").prop(rule, "wait_s", text="")

    col.separator()
    _line(col, "It becomes").prop(rule, "to_state", text="")
    if rule.trigger != engine.TIMER:
        partner_label = f"{partner.name} becomes" if partner else "Partner becomes"
        _line(col, partner_label).prop(rule, "partner_to_state", text="")
        if rule.trigger == engine.MEET:
            _line(col, "").prop(rule, "bind")
        else:
            _line(col, "").prop(rule, "release")

    problem = rule_problem(agent_type, rule)
    if problem:
        col.separator()
        col.label(text=problem, icon="ERROR")

    if session is not None:
        stats = session.sim.stats.get(rule.uid)
        if stats is not None:
            col.separator()
            if rule.trigger == engine.MEET:
                text = (f"Preview: {stats.touches} touches, {stats.aligned} facing right, "
                        f"{stats.fired} fired")
            else:
                text = f"Preview: fired {stats.fired} times"
            col.label(text=text, icon="INFO")


def draw_types(layout, world):
    row = layout.row()
    row.template_list("PB_AGENTS_UL_types", "", world, "types", world, "active_type_index", rows=3)
    side = row.column(align=True)
    side.operator("pb_agents.add_type", text="", icon="ADD")
    side.operator("pb_agents.remove_type", text="", icon="REMOVE")

    agent_type = _active(world.types, world.active_type_index)
    if agent_type is None:
        layout.label(text="Add an agent type, or load an example brain", icon="INFO")
        return None
    col = layout.column(align=True)
    row = col.row(align=True)
    row.prop(agent_type, "count")
    row.prop(agent_type, "radius_nm", text="Size (nm)")
    col.prop(agent_type, "mobility")
    row = layout.row(align=True)
    row.prop(agent_type, "has_site", text="Binding site")
    sub = row.row(align=True)
    sub.active = agent_type.has_site
    sub.prop(agent_type, "site_name", text="")
    sub.prop(agent_type, "site_cone")
    return agent_type


def draw_brain(layout, context, agent_type, session):
    # Column headings over the states list, split the same way as its rows,
    # with a blank where the list has its + / - buttons.
    head = layout.row()
    swatch, rest = _fixed_left(head.row(), context, 26)
    swatch.label(text="")
    middle, share = _fixed_right(rest, context, 64, 26)
    middle.label(text="States")
    if session is not None:
        now = middle.row()
        now.alignment = "RIGHT"
        now.label(text="now")
    share.alignment = "CENTER"
    share.label(text="start")
    head.label(text="", icon="BLANK1")
    row = layout.row()
    row.template_list("PB_AGENTS_UL_states", "", agent_type, "states", agent_type,
                      "active_state_index", rows=3)
    side = row.column(align=True)
    side.operator("pb_agents.add_state", text="", icon="ADD")
    side.operator("pb_agents.remove_state", text="", icon="REMOVE")

    layout.separator()
    layout.label(text=f"Rules: what changes a {agent_type.name}")
    row = layout.row()
    row.template_list("PB_AGENTS_UL_rules", "", agent_type, "rules", agent_type,
                      "active_rule_index", rows=3)
    side = row.column(align=True)
    side.operator_menu_enum("pb_agents.add_rule", "trigger", text="", icon="ADD")
    side.operator("pb_agents.remove_rule", text="", icon="REMOVE")

    rule = _active(agent_type.rules, agent_type.active_rule_index)
    if rule is not None:
        draw_rule_editor(layout, agent_type, rule, session)
    elif not len(agent_type.rules):
        layout.label(text="No rules yet: add one with +", icon="INFO")


def draw_preview(layout, context, world, session):
    row = layout.row(align=True)
    row.scale_y = 1.3
    if session is not None and session.running:
        row.operator("pb_agents.preview_pause", text="Pause", icon="PAUSE")
    else:
        row.operator("pb_agents.preview_run", text="Run", icon="PLAY")
    row.operator("pb_agents.preview_step", text="", icon="FRAME_NEXT")
    row.operator("pb_agents.preview_reset", text="", icon="FILE_REFRESH")
    row.operator("pb_agents.preview_frame", text="", icon="VIEWZOOM")

    if session is None:
        layout.label(text="Run to watch the brains in the 3D viewport", icon="INFO")
        return
    sim = session.sim
    layout.label(text=f"{sim.time_s:.1f} s  ·  frame {sim.frame}", icon="TIME")
    if session.stale:
        layout.label(text="Counts, sizes or seed changed: Reset to use them", icon="ERROR")

    counts = sim.counts()
    for agent_type in world.types:
        type_counts = counts.get(agent_type.uid)
        if type_counts is None:
            continue
        total = max(1, sum(type_counts.values()))
        col = layout.column(align=True)
        col.label(text=agent_type.name)
        for state in agent_type.states:
            n = type_counts.get(state.uid, 0)
            swatch, rest = _fixed_left(col.row(align=True), context, 26, margin=40)
            swatch.prop(state, "color", text="")
            name, bar = _fixed_left(rest, context, 96, margin=40 + 26)
            name.label(text=state.name)
            bar.progress(factor=n / total, type="BAR", text=str(n))

    if sim.events:
        layout.label(text="Recent events")
        box = layout.box()
        events = box.column(align=True)
        for event in reversed(sim.events[-6:]):
            events.label(text=f"{event.time_s:5.1f} s   {event.text}")


def draw_settings(layout, world):
    col = layout.column(align=True)
    col.prop(world, "box_nm", text="Box (nm)")
    col.row(align=True).prop(world, "boundary", expand=True)
    col = layout.column(align=True)
    col.prop(world, "ns_per_frame", text="Motion per frame (ns)")
    col.prop(world, "tumbling")
    col.prop(world, "speed")
    row = layout.row(align=True)
    row.prop(world, "seed")
    row.prop(world, "show_box", toggle=True)


class PB_AGENTS_PT_brains(Panel):
    """Define agent types, give each a brain of states and rules, and preview it."""
    bl_idname = "PB_AGENTS_PT_brains"
    bl_label = "Agent Brains"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_options = {"HIDE_HEADER", "HEADER_LAYOUT_EXPAND"}
    bl_order = 9

    def draw(self, context):
        world = context.scene.pb_agents
        session = _session(context)
        main = self.layout.box()
        title = main.row()
        title.label(text="Agent Brains (demo)", icon="COMMUNITY")
        title.menu("PB_AGENTS_MT_examples", text="Examples", icon="PRESET")

        header, body = main.panel("PB_AGENTS_types", default_closed=False)
        header.label(text="Agent types")
        agent_type = draw_types(body, world) if body else _active(world.types, world.active_type_index)

        if agent_type is not None:
            header, body = main.panel("PB_AGENTS_brain", default_closed=False)
            header.label(text=f"Brain: {agent_type.name}", icon="NODETREE")
            if body:
                draw_brain(body, context, agent_type, session)

        header, body = main.panel("PB_AGENTS_preview", default_closed=False)
        header.label(text="Preview", icon="PLAY")
        if body:
            draw_preview(body, context, world, session)
            sub_header, sub_body = body.panel("PB_AGENTS_settings", default_closed=True)
            sub_header.label(text="Preview settings")
            if sub_body:
                draw_settings(sub_body, world)


CLASSES = (
    PB_AGENTS_MT_examples,
    PB_AGENTS_UL_types,
    PB_AGENTS_UL_states,
    PB_AGENTS_UL_rules,
    PB_AGENTS_PT_brains,
)


def register():
    for cls in CLASSES:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
