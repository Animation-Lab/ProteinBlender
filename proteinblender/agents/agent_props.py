"""Scene-stored definition of agent types, their states and their rules.

Everything the user defines lives here, on ``scene.pb_agents``, so it is saved
in the .blend, undoable, and copied with the scene. The running preview is
runtime-only and reads these properties each tick (see ``agent_preview``).

States, rules and types carry a stable integer ``uid``. Rules point at states
and partner types through dynamic enums whose item *numbers* are those uids, so
renaming or reordering a state never breaks a rule that refers to it.
"""

import math
import re

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import engine

TRIGGER_ITEMS = [
    (engine.TIMER, "After a while",
     "Changes state on its own after a random wait (a Markov step)", "TIME", 0),
    (engine.MEET, "When it touches",
     "Changes state when it touches a chosen kind of agent", "MOD_PHYSICS", 1),
    (engine.BOUND, "While stuck to",
     "Changes state after a random wait while it is stuck to a partner", "LINKED", 2),
]

TRIGGER_ICONS = {identifier: icon for identifier, _n, _d, icon, _v in TRIGGER_ITEMS}

STATE_PALETTE = [
    (0.36, 0.56, 0.90), (0.96, 0.62, 0.22), (0.38, 0.75, 0.45), (0.86, 0.33, 0.36),
    (0.62, 0.48, 0.86), (0.30, 0.74, 0.78), (0.93, 0.80, 0.30), (0.62, 0.62, 0.64),
]

# Blender keeps only pointers to the strings an enum callback returns, so the
# item lists must stay referenced from Python until the next call replaces them.
_ENUM_CACHE = {}

_TYPE_PATH = re.compile(r"pb_agents\.types\[(\d+)\]")


def world_of(item):
    return item.id_data.pb_agents


def owner_type(item):
    """The AgentType that holds this state or rule, found from its RNA path."""
    try:
        match = _TYPE_PATH.match(item.path_from_id())
    except Exception:
        return None
    if not match:
        return None
    types = world_of(item).types
    index = int(match.group(1))
    return types[index] if index < len(types) else None


def find_type(world, uid):
    for agent_type in world.types:
        if agent_type.uid == uid:
            return agent_type
    return None


def find_state(agent_type, uid):
    if agent_type is None:
        return None
    for state in agent_type.states:
        if state.uid == uid:
            return state
    return None


def enum_uid(value):
    """'S12' or 'T5' -> 12 or 5; 'ANY'/'KEEP' -> 0; '' (dangling) -> None."""
    if not value:
        return None
    if value in {"ANY", "KEEP"}:
        return 0
    return int(value[1:])


def state_key(uid):
    return f"S{uid}"


def type_key(uid):
    return f"T{uid}"


def _cache(key, items):
    _ENUM_CACHE[key] = items
    return items


def _state_items(agent_type, first, key):
    items = [first] if first else []
    if agent_type is not None:
        for state in agent_type.states:
            items.append((state_key(state.uid), state.name or "(unnamed)",
                          f"The {state.name} state", state.uid))
    return _cache(key, items)


def _path(item):
    try:
        return item.path_from_id()
    except Exception:
        return ""


def _from_state_items(self, context):
    return _state_items(owner_type(self),
                        ("ANY", "Any state", "Whatever state it is in", 0), ("from", _path(self)))


def _to_state_items(self, context):
    return _state_items(owner_type(self),
                        ("KEEP", "Stays the same", "Its state does not change", 0), ("to", _path(self)))


def _partner_type_items(self, context):
    items = [("ANY", "Any agent", "Any kind of agent", 0)]
    try:
        for agent_type in world_of(self).types:
            items.append((type_key(agent_type.uid), agent_type.name or "(unnamed)",
                          f"A {agent_type.name}", agent_type.uid))
    except Exception:
        pass
    return _cache("partner_type", items)


def partner_type_of(rule):
    uid = enum_uid(rule.partner_type)
    if not uid:
        return None
    return find_type(world_of(rule), uid)


def _partner_state_items(self, context):
    return _state_items(partner_type_of(self),
                        ("ANY", "Any state", "Whatever state it is in", 0),
                        ("partner_state", _path(self)))


def _partner_to_state_items(self, context):
    return _state_items(partner_type_of(self),
                        ("KEEP", "Stays the same", "Its state does not change", 0),
                        ("partner_to", _path(self)))


def _redraw(self, context):
    for window in getattr(context.window_manager, "windows", ()):
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()


class PB_AgentState(PropertyGroup):
    name: StringProperty(name="Name", default="State", update=_redraw)
    uid: IntProperty(options={"HIDDEN"})
    color: FloatVectorProperty(
        name="Color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(0.6, 0.6, 0.62), update=_redraw,
        description="How agents in this state look in the preview")
    start_share: FloatProperty(
        name="Start", subtype="PERCENTAGE", min=0.0, max=100.0, default=0.0,
        precision=0, step=100,
        description="Share of this type's agents that start in this state")


class PB_AgentRule(PropertyGroup):
    uid: IntProperty(options={"HIDDEN"})
    enabled: BoolProperty(name="On", default=True, description="Use this rule")
    trigger: EnumProperty(name="Trigger", items=TRIGGER_ITEMS, default=engine.TIMER)
    from_state: EnumProperty(name="From", items=_from_state_items, default=0,
                             description="The state this rule applies to")
    to_state: EnumProperty(name="Becomes", items=_to_state_items, default=0,
                           description="The state it changes to")
    wait_s: FloatProperty(
        name="Average wait", unit="TIME_ABSOLUTE", min=0.01, soft_max=60.0, default=3.0,
        description="Average time before this happens (an exponential wait, in seconds of animation)")
    partner_type: EnumProperty(name="Partner", items=_partner_type_items, default=0,
                               description="The kind of agent it has to touch or be stuck to")
    partner_state: EnumProperty(name="Partner state", items=_partner_state_items, default=0,
                                description="The state the partner has to be in")
    partner_to_state: EnumProperty(name="Partner becomes", items=_partner_to_state_items,
                                   default=0, description="The state the partner changes to")
    reach_nm: FloatProperty(
        name="Within", min=0.0, soft_max=10.0, default=1.0, precision=1,
        description="How close the two surfaces must come to count as a touch, in nanometres")
    self_facing: BoolProperty(
        name="Its site faces the partner", default=False,
        description="Only counts touches where this agent's binding site points at the partner")
    partner_facing: BoolProperty(
        name="Partner's site faces it", default=False,
        description="Only counts touches where the partner's binding site points at this agent")
    chance: FloatProperty(
        name="Chance per touch", subtype="PERCENTAGE", min=0.0, max=100.0, default=100.0,
        precision=0, step=100,
        description="Chance that a touch that meets every condition fires the rule")
    bind: BoolProperty(name="They stick together", default=True,
                       description="The two move as one until a rule lets them go")
    release: BoolProperty(name="They let go", default=True,
                          description="The two come apart when this rule fires")


class PB_AgentType(PropertyGroup):
    name: StringProperty(name="Name", default="Agent", update=_redraw)
    uid: IntProperty(options={"HIDDEN"})
    count: IntProperty(name="Count", min=0, soft_max=200, max=1000, default=20,
                       description="How many of this agent the preview makes")
    radius_nm: FloatProperty(name="Size", min=0.3, soft_max=20.0, default=2.5, precision=1,
                             description="Radius in nanometres; sets how fast it diffuses")
    mobility: FloatProperty(name="Mobility", min=0.0, soft_max=3.0, default=1.0,
                            description="Scales its diffusion (0 holds it still)")
    has_site: BoolProperty(name="Binding site", default=False, update=_redraw,
                           description="Give this agent one binding site, drawn as a cone")
    site_name: StringProperty(name="Site name", default="site")
    site_cone: FloatProperty(name="Cone", subtype="ANGLE", min=math.radians(1.0),
                             max=math.radians(180.0), default=math.radians(40.0),
                             description="How far off the site's axis a partner may be and still face it")
    states: CollectionProperty(type=PB_AgentState)
    active_state_index: IntProperty(default=0)
    rules: CollectionProperty(type=PB_AgentRule)
    active_rule_index: IntProperty(default=0)


class PB_AgentWorld(PropertyGroup):
    types: CollectionProperty(type=PB_AgentType)
    active_type_index: IntProperty(default=0)
    next_uid: IntProperty(default=1, options={"HIDDEN"})
    box_nm: FloatProperty(name="Box", min=10.0, soft_max=500.0, default=80.0, precision=0,
                          description="Edge of the cubic box the agents live in, in nanometres")
    boundary: EnumProperty(
        name="Edges", default="WALL",
        items=[("WALL", "Walls", "Agents bounce off the faces of the box"),
               ("WRAP", "Wrap around", "Agents leaving one face come back through the opposite one")])
    seed: IntProperty(name="Seed", min=0, default=1,
                      description="The same seed replays the same preview")
    ns_per_frame: FloatProperty(
        name="Motion per frame", min=0.1, soft_max=100.0, default=10.0, precision=1,
        description="Physical diffusion time each frame shows, in nanoseconds")
    tumbling: FloatProperty(
        name="Tumbling", subtype="FACTOR", min=0.0, max=1.0, default=0.25,
        description="Slows rotation below the physical rate so orientations stay readable")
    speed: FloatProperty(name="Speed", min=0.1, max=8.0, default=1.0,
                         description="Preview playback speed")
    show_box: BoolProperty(name="Show box", default=True, update=_redraw)


def new_uid(world):
    uid = world.next_uid
    world.next_uid = uid + 1
    return uid


def describe_rule(agent_type, rule):
    """One line saying what the rule does, as the rule list shows it."""
    world = world_of(rule)
    from_uid = enum_uid(rule.from_state)
    to_uid = enum_uid(rule.to_state)
    if from_uid is None or to_uid is None:
        return "Points at a state that no longer exists"
    from_state = find_state(agent_type, from_uid)
    to_state = find_state(agent_type, to_uid)
    from_name = from_state.name if from_state else "Any"
    to_name = to_state.name if to_state else "same"
    head = f"{from_name} → {to_name}"
    if rule.trigger == engine.TIMER:
        return f"{head}: after ~{rule.wait_s:g} s"
    partner_uid = enum_uid(rule.partner_type)
    partner = find_type(world, partner_uid) if partner_uid else None
    partner_name = partner.name if partner else "any agent"
    pstate_uid = enum_uid(rule.partner_state)
    pstate = find_state(partner, pstate_uid) if pstate_uid else None
    who = f"{partner_name} ({pstate.name})" if pstate else partner_name
    if rule.trigger == engine.MEET:
        text = f"{head}: touches {who}"
        if rule.chance < 100.0:
            text += f", {rule.chance:.0f}%"
        if rule.bind:
            text += ", sticks"
        return text
    text = f"{head}: ~{rule.wait_s:g} s stuck to {who}"
    if rule.release:
        text += ", lets go"
    return text


def rule_problem(agent_type, rule):
    """Why the rule cannot do anything, or '' when it is fine."""
    if enum_uid(rule.from_state) is None or enum_uid(rule.to_state) is None:
        return "It points at a state that no longer exists"
    if rule.trigger == engine.TIMER:
        if enum_uid(rule.to_state) == 0:
            return "It does not change the state"
        if rule.from_state == rule.to_state:
            return "It changes the state to the one it is already in"
        return ""
    if enum_uid(rule.partner_type) is None:
        return "Its partner type no longer exists"
    if enum_uid(rule.partner_state) is None or enum_uid(rule.partner_to_state) is None:
        return "It points at a partner state that no longer exists"
    if rule.trigger == engine.MEET:
        partner = partner_type_of(rule)
        if rule.self_facing and not agent_type.has_site:
            return f"{agent_type.name} has no binding site to face with"
        if rule.partner_facing and partner is not None and not partner.has_site:
            return f"{partner.name} has no binding site to face with"
    return ""


CLASSES = (
    PB_AgentState,
    PB_AgentRule,
    PB_AgentType,
    PB_AgentWorld,
)


def register():
    for cls in CLASSES:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.pb_agents = PointerProperty(type=PB_AgentWorld)


def unregister():
    if hasattr(bpy.types.Scene, "pb_agents"):
        del bpy.types.Scene.pb_agents
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
