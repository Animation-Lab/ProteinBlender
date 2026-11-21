"""Ready-made brains to start from.

Each example is plain data: agent types, their states, and rules written with
state and type *names*. ``apply_example`` turns the names into the uids the
properties use, so the data stays readable.
"""

import math

from . import engine
from .agent_props import new_uid, state_key, type_key

EXAMPLES = {
    "RECEPTOR_LIGAND": {
        "label": "Receptor and ligand",
        "description": "Ligands stick to a receptor's pocket when it faces them, then let go",
        "box_nm": 60.0,
        "types": [
            {"name": "Receptor", "count": 8, "radius_nm": 4.0, "site": "pocket", "cone": 50,
             "states": [("Empty", (0.36, 0.56, 0.90), 100), ("Occupied", (0.96, 0.62, 0.22), 0)],
             "rules": []},
            {"name": "Ligand", "count": 40, "radius_nm": 1.5, "site": "tip", "cone": 60,
             "states": [("Free", (0.72, 0.72, 0.74), 100), ("Bound", (0.86, 0.33, 0.36), 0)],
             "rules": [
                 {"trigger": engine.MEET, "from": "Free", "to": "Bound",
                  "partner": "Receptor", "partner_state": "Empty", "partner_to": "Occupied",
                  "reach_nm": 1.0, "partner_facing": True, "chance": 70, "bind": True},
                 {"trigger": engine.BOUND, "from": "Bound", "to": "Free",
                  "partner": "Receptor", "partner_to": "Empty", "wait_s": 4.0, "release": True},
             ]},
        ],
    },
    "ENZYME": {
        "label": "Enzyme cuts a substrate",
        "description": "Substrates dock in an idle enzyme's active site and leave cut",
        "box_nm": 60.0,
        "types": [
            {"name": "Enzyme", "count": 6, "radius_nm": 3.5, "site": "active site", "cone": 50,
             "states": [("Idle", (0.38, 0.75, 0.45), 100), ("Working", (0.93, 0.80, 0.30), 0)],
             "rules": []},
            {"name": "Substrate", "count": 30, "radius_nm": 1.8,
             "states": [("Intact", (0.62, 0.48, 0.86), 100), ("Docked", (0.93, 0.55, 0.75), 0),
                        ("Cut", (0.55, 0.55, 0.57), 0)],
             "rules": [
                 {"trigger": engine.MEET, "from": "Intact", "to": "Docked",
                  "partner": "Enzyme", "partner_state": "Idle", "partner_to": "Working",
                  "reach_nm": 1.0, "partner_facing": True, "chance": 80, "bind": True},
                 {"trigger": engine.BOUND, "from": "Docked", "to": "Cut",
                  "partner": "Enzyme", "partner_to": "Idle", "wait_s": 2.0, "release": True},
             ]},
        ],
    },
    "SIGNAL": {
        "label": "Signal relay (touch, no sticking)",
        "description": "Active kinases switch targets on by touch; targets switch off again on their own",
        "box_nm": 60.0,
        "types": [
            {"name": "Kinase", "count": 4, "radius_nm": 3.0,
             "states": [("Active", (0.86, 0.33, 0.36), 100)], "rules": []},
            {"name": "Target", "count": 40, "radius_nm": 2.0,
             "states": [("Off", (0.55, 0.55, 0.57), 100), ("On", (0.93, 0.80, 0.30), 0)],
             "rules": [
                 {"trigger": engine.MEET, "from": "Off", "to": "On",
                  "partner": "Kinase", "partner_state": "Active",
                  "reach_nm": 1.0, "chance": 50, "bind": False},
                 {"trigger": engine.TIMER, "from": "On", "to": "Off", "wait_s": 3.0},
             ]},
        ],
    },
    "SWITCH": {
        "label": "Three-state switch (Markov only)",
        "description": "A channel cycles Closed, Open, Inactive on timers alone; Open has two ways out",
        "box_nm": 60.0,
        "types": [
            {"name": "Channel", "count": 30, "radius_nm": 3.0,
             "states": [("Closed", (0.36, 0.56, 0.90), 100), ("Open", (0.38, 0.75, 0.45), 0),
                        ("Inactive", (0.55, 0.55, 0.57), 0)],
             "rules": [
                 {"trigger": engine.TIMER, "from": "Closed", "to": "Open", "wait_s": 3.0},
                 {"trigger": engine.TIMER, "from": "Open", "to": "Inactive", "wait_s": 1.5},
                 {"trigger": engine.TIMER, "from": "Open", "to": "Closed", "wait_s": 3.0},
                 {"trigger": engine.TIMER, "from": "Inactive", "to": "Closed", "wait_s": 4.0},
             ]},
        ],
    },
    "DIMER": {
        "label": "Dimers (same-type pairs)",
        "description": "Monomers pair up face to face and split again",
        "box_nm": 60.0,
        "types": [
            {"name": "Monomer", "count": 40, "radius_nm": 2.5, "site": "face", "cone": 45,
             "states": [("Single", (0.30, 0.74, 0.78), 100), ("Paired", (0.86, 0.33, 0.36), 0)],
             "rules": [
                 {"trigger": engine.MEET, "from": "Single", "to": "Paired",
                  "partner": "Monomer", "partner_state": "Single", "partner_to": "Paired",
                  "reach_nm": 1.0, "self_facing": True, "partner_facing": True,
                  "chance": 90, "bind": True},
                 {"trigger": engine.BOUND, "from": "Paired", "to": "Single",
                  "partner": "Monomer", "partner_to": "Single", "wait_s": 5.0, "release": True},
             ]},
        ],
    },
}

EXAMPLE_ITEMS = [(key, data["label"], data["description"]) for key, data in EXAMPLES.items()]


def apply_example(world, key):
    """Replace every agent type in ``world`` with the named example."""
    data = EXAMPLES[key]
    world.types.clear()
    world.box_nm = data["box_nm"]
    state_uids = {}
    type_uids = {}
    created = []
    for spec in data["types"]:
        agent_type = world.types.add()
        agent_type.uid = new_uid(world)
        agent_type.name = spec["name"]
        agent_type.count = spec["count"]
        agent_type.radius_nm = spec["radius_nm"]
        agent_type.has_site = "site" in spec
        agent_type.site_name = spec.get("site", "site")
        agent_type.site_cone = math.radians(spec.get("cone", 40))
        type_uids[spec["name"]] = agent_type.uid
        for name, color, share in spec["states"]:
            state = agent_type.states.add()
            state.uid = new_uid(world)
            state.name = name
            state.color = color
            state.start_share = share
            state_uids[(spec["name"], name)] = state.uid
        created.append((agent_type, spec))
    for agent_type, spec in created:
        for rule_data in spec["rules"]:
            rule = agent_type.rules.add()
            rule.uid = new_uid(world)
            rule.trigger = rule_data["trigger"]
            rule.from_state = state_key(state_uids[(spec["name"], rule_data["from"])])
            rule.to_state = state_key(state_uids[(spec["name"], rule_data["to"])])
            rule.wait_s = rule_data.get("wait_s", 3.0)
            partner = rule_data.get("partner")
            if partner:
                rule.partner_type = type_key(type_uids[partner])
                if "partner_state" in rule_data:
                    rule.partner_state = state_key(state_uids[(partner, rule_data["partner_state"])])
                if "partner_to" in rule_data:
                    rule.partner_to_state = state_key(state_uids[(partner, rule_data["partner_to"])])
            rule.reach_nm = rule_data.get("reach_nm", 1.0)
            rule.self_facing = rule_data.get("self_facing", False)
            rule.partner_facing = rule_data.get("partner_facing", False)
            rule.chance = rule_data.get("chance", 100.0)
            rule.bind = rule_data.get("bind", False)
            rule.release = rule_data.get("release", False)
        agent_type.active_rule_index = 0
        agent_type.active_state_index = 0
    world.active_type_index = len(world.types) - 1
