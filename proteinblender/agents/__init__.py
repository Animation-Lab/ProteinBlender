"""Agent Brains (demo): agents with Markov-state brains that react to each other.

Each agent type gets a brain made of states and rules. Rules fire after a
random wait, when the agent touches a chosen partner, or while it is stuck to
one, and can change both agents' states and make them stick or let go. The
panel lives in Properties > Scene; the preview draws in the 3D viewport.

``engine`` is the bpy-free simulation core; the other modules are the Blender
side (stored definition, operators, panel, viewport preview).
"""

from . import agent_operators, agent_panel, agent_preview, agent_props


def register():
    agent_props.register()
    agent_operators.register()
    agent_panel.register()
    agent_preview.register()


def unregister():
    agent_preview.unregister()
    agent_panel.unregister()
    agent_operators.unregister()
    agent_props.unregister()
