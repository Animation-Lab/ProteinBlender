"""Operators that edit agent brains and drive the preview."""

import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from . import agent_preview, engine
from .agent_examples import EXAMPLE_ITEMS, apply_example
from .agent_props import (
    STATE_PALETTE,
    TRIGGER_ITEMS,
    enum_uid,
    new_uid,
    state_key,
    type_key,
)


def _world(context):
    return context.scene.pb_agents


def _active_type(context):
    world = _world(context)
    if 0 <= world.active_type_index < len(world.types):
        return world.types[world.active_type_index]
    return None


def _add_state(world, agent_type, name, share=0.0):
    state = agent_type.states.add()
    state.uid = new_uid(world)
    state.name = name
    used = {tuple(round(c, 3) for c in s.color) for s in agent_type.states}
    color = next((c for c in STATE_PALETTE if tuple(round(v, 3) for v in c) not in used),
                 STATE_PALETTE[len(agent_type.states) % len(STATE_PALETTE)])
    state.color = color
    state.start_share = share
    return state


def _unique_name(existing, base):
    names = set(existing)
    if base not in names:
        return base
    k = 2
    while f"{base} {k}" in names:
        k += 1
    return f"{base} {k}"


class PB_AGENTS_OT_add_type(Operator):
    """Add a kind of agent with its own brain"""
    bl_idname = "pb_agents.add_type"
    bl_label = "Add Agent Type"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        world = _world(context)
        agent_type = world.types.add()
        agent_type.uid = new_uid(world)
        agent_type.name = _unique_name((t.name for t in world.types if t != agent_type), "Agent")
        _add_state(world, agent_type, "Normal", 100.0)
        world.active_type_index = len(world.types) - 1
        return {"FINISHED"}


class PB_AGENTS_OT_remove_type(Operator):
    """Remove the selected agent type and switch off the rules that needed it"""
    bl_idname = "pb_agents.remove_type"
    bl_label = "Remove Agent Type"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_type(context) is not None

    def execute(self, context):
        world = _world(context)
        name = _active_type(context).name
        world.types.remove(world.active_type_index)
        world.active_type_index = max(0, min(world.active_type_index, len(world.types) - 1))
        switched = 0
        for other in world.types:
            for rule in other.rules:
                if rule.trigger != engine.TIMER and enum_uid(rule.partner_type) is None:
                    rule.partner_type = "ANY"
                    rule.partner_state = "ANY"
                    rule.partner_to_state = "KEEP"
                    rule.enabled = False
                    switched += 1
        if switched:
            self.report({"WARNING"},
                        f"Switched off {switched} rule(s) that involved {name}")
        return {"FINISHED"}


class PB_AGENTS_OT_add_state(Operator):
    """Add a state to this agent type's brain"""
    bl_idname = "pb_agents.add_state"
    bl_label = "Add State"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_type(context) is not None

    def execute(self, context):
        world = _world(context)
        agent_type = _active_type(context)
        name = _unique_name((s.name for s in agent_type.states), "State")
        _add_state(world, agent_type, name, 0.0 if len(agent_type.states) else 100.0)
        agent_type.active_state_index = len(agent_type.states) - 1
        return {"FINISHED"}


class PB_AGENTS_OT_remove_state(Operator):
    """Remove the selected state and switch off the rules that used it"""
    bl_idname = "pb_agents.remove_state"
    bl_label = "Remove State"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        agent_type = _active_type(context)
        return agent_type is not None and len(agent_type.states) > 1

    def execute(self, context):
        world = _world(context)
        agent_type = _active_type(context)
        index = agent_type.active_state_index
        if not 0 <= index < len(agent_type.states):
            return {"CANCELLED"}
        name = agent_type.states[index].name
        agent_type.states.remove(index)
        agent_type.active_state_index = max(0, min(index, len(agent_type.states) - 1))
        switched = 0
        for owner in world.types:
            for rule in owner.rules:
                broken = False
                if enum_uid(rule.from_state) is None:
                    rule.from_state = "ANY"
                    broken = True
                if enum_uid(rule.to_state) is None:
                    rule.to_state = "KEEP"
                    broken = True
                if rule.trigger != engine.TIMER:
                    if enum_uid(rule.partner_state) is None:
                        rule.partner_state = "ANY"
                        broken = True
                    if enum_uid(rule.partner_to_state) is None:
                        rule.partner_to_state = "KEEP"
                        broken = True
                if broken:
                    rule.enabled = False
                    switched += 1
        if switched:
            self.report({"WARNING"}, f"Switched off {switched} rule(s) that used {name}")
        return {"FINISHED"}


class PB_AGENTS_OT_add_rule(Operator):
    """Add a rule that changes this agent's state"""
    bl_idname = "pb_agents.add_rule"
    bl_label = "Add Rule"
    bl_options = {"REGISTER", "UNDO"}

    trigger: EnumProperty(name="Trigger", items=TRIGGER_ITEMS, default=engine.TIMER)

    @classmethod
    def poll(cls, context):
        agent_type = _active_type(context)
        return agent_type is not None and len(agent_type.states) > 0

    def execute(self, context):
        world = _world(context)
        agent_type = _active_type(context)
        states = agent_type.states
        current = max(0, min(agent_type.active_state_index, len(states) - 1))
        rule = agent_type.rules.add()
        rule.uid = new_uid(world)
        rule.trigger = self.trigger
        rule.from_state = state_key(states[current].uid)
        if len(states) > 1:
            rule.to_state = state_key(states[(current + 1) % len(states)].uid)
        if self.trigger != engine.TIMER:
            others = [t for t in world.types if t != agent_type]
            partner = others[0] if others else agent_type
            rule.partner_type = type_key(partner.uid)
            rule.bind = self.trigger == engine.MEET
            rule.release = True
            rule.wait_s = 4.0
        agent_type.active_rule_index = len(agent_type.rules) - 1
        return {"FINISHED"}


class PB_AGENTS_OT_remove_rule(Operator):
    """Remove the selected rule"""
    bl_idname = "pb_agents.remove_rule"
    bl_label = "Remove Rule"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        agent_type = _active_type(context)
        return agent_type is not None and len(agent_type.rules) > 0

    def execute(self, context):
        agent_type = _active_type(context)
        index = agent_type.active_rule_index
        if not 0 <= index < len(agent_type.rules):
            return {"CANCELLED"}
        agent_type.rules.remove(index)
        agent_type.active_rule_index = max(0, min(index, len(agent_type.rules) - 1))
        return {"FINISHED"}


class PB_AGENTS_OT_load_example(Operator):
    """Replace the agent types with a ready-made example brain"""
    bl_idname = "pb_agents.load_example"
    bl_label = "Load Example"
    bl_options = {"REGISTER", "UNDO"}

    example: EnumProperty(name="Example", items=EXAMPLE_ITEMS)

    @classmethod
    def description(cls, context, properties):
        for key, label, text in EXAMPLE_ITEMS:
            if key == properties.example:
                return f"{label}: {text}. Replaces the current agent types"
        return cls.__doc__

    def invoke(self, context, event):
        if len(_world(context).types):
            label = dict((k, n) for k, n, _d in EXAMPLE_ITEMS)[self.example]
            return context.window_manager.invoke_confirm(
                self, event, title="Replace agent types?",
                message=f"Load “{label}” in place of the current agent types.",
                confirm_text="Replace")
        return self.execute(context)

    def execute(self, context):
        apply_example(_world(context), self.example)
        agent_preview.reset(context.scene)
        return {"FINISHED"}


class PB_AGENTS_OT_preview_run(Operator):
    """Play the agents in the 3D viewport; rule changes apply while it plays"""
    bl_idname = "pb_agents.preview_run"
    bl_label = "Run Preview"

    @classmethod
    def poll(cls, context):
        return len(_world(context).types) > 0

    def execute(self, context):
        agent_preview.run(context.scene)
        return {"FINISHED"}


class PB_AGENTS_OT_preview_pause(Operator):
    """Pause the preview"""
    bl_idname = "pb_agents.preview_pause"
    bl_label = "Pause Preview"

    def execute(self, context):
        agent_preview.pause(context.scene)
        return {"FINISHED"}


class PB_AGENTS_OT_preview_reset(Operator):
    """Start the preview over from new positions, using the current counts, sizes and seed"""
    bl_idname = "pb_agents.preview_reset"
    bl_label = "Reset Preview"

    @classmethod
    def poll(cls, context):
        return len(_world(context).types) > 0

    def execute(self, context):
        agent_preview.reset(context.scene)
        return {"FINISHED"}


class PB_AGENTS_OT_preview_step(Operator):
    """Advance the preview by a number of frames"""
    bl_idname = "pb_agents.preview_step"
    bl_label = "Step Preview"

    frames: IntProperty(name="Frames", min=1, max=10000, default=1)

    @classmethod
    def poll(cls, context):
        return len(_world(context).types) > 0

    def execute(self, context):
        agent_preview.step(context.scene, self.frames)
        return {"FINISHED"}


class PB_AGENTS_OT_preview_frame(Operator):
    """Point the 3D views at the preview box"""
    bl_idname = "pb_agents.preview_frame"
    bl_label = "Frame Box"

    def execute(self, context):
        agent_preview.frame_box(context)
        return {"FINISHED"}


CLASSES = (
    PB_AGENTS_OT_add_type,
    PB_AGENTS_OT_remove_type,
    PB_AGENTS_OT_add_state,
    PB_AGENTS_OT_remove_state,
    PB_AGENTS_OT_add_rule,
    PB_AGENTS_OT_remove_rule,
    PB_AGENTS_OT_load_example,
    PB_AGENTS_OT_preview_run,
    PB_AGENTS_OT_preview_pause,
    PB_AGENTS_OT_preview_reset,
    PB_AGENTS_OT_preview_step,
    PB_AGENTS_OT_preview_frame,
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
