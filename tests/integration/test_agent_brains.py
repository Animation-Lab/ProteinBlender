"""Agent Brains (demo): the stored definition, its operators, the panel and the preview.

Examples are checked against their own source data (names in, names out), the
preview against invariants a correct run cannot break, and the panel by drawing
it into a recording layout that checks every property it asks for exists.
"""

import types

import bpy
import pytest

from proteinblender.agents import agent_examples, agent_preview, engine
from proteinblender.agents.agent_panel import (
    PB_AGENTS_MT_examples,
    PB_AGENTS_PT_brains,
    PB_AGENTS_UL_rules,
)
from proteinblender.agents.agent_props import (
    describe_rule,
    enum_uid,
    find_state,
    find_type,
    rule_problem,
)


def _world():
    return bpy.context.scene.pb_agents


def _load(key):
    assert bpy.ops.pb_agents.load_example("EXEC_DEFAULT", example=key) == {"FINISHED"}
    return _world()


def _type(name):
    return next(t for t in _world().types if t.name == name)


def _select_type(name):
    world = _world()
    world.active_type_index = next(k for k, t in enumerate(world.types) if t.name == name)


def _session():
    return agent_preview.session_for(bpy.context.scene)


def _resolves(agent_type, rule):
    fields = [rule.from_state, rule.to_state]
    if rule.trigger != engine.TIMER:
        fields += [rule.partner_type, rule.partner_state, rule.partner_to_state]
    return all(enum_uid(value) is not None for value in fields)


@pytest.mark.parametrize("key", list(agent_examples.EXAMPLES))
def test_every_example_loads_with_every_reference_resolving(key):
    world = _load(key)
    data = agent_examples.EXAMPLES[key]
    assert [t.name for t in world.types] == [t["name"] for t in data["types"]]
    for agent_type, spec in zip(world.types, data["types"]):
        assert [s.name for s in agent_type.states] == [s[0] for s in spec["states"]]
        assert len(agent_type.rules) == len(spec["rules"])
        for rule, wanted in zip(agent_type.rules, spec["rules"]):
            assert rule.trigger == wanted["trigger"]
            assert find_state(agent_type, enum_uid(rule.from_state)).name == wanted["from"]
            assert find_state(agent_type, enum_uid(rule.to_state)).name == wanted["to"]
            if "partner" in wanted:
                partner = find_type(world, enum_uid(rule.partner_type))
                assert partner.name == wanted["partner"]
                for field, key_name in (("partner_state", "partner_state"),
                                        ("partner_to_state", "partner_to")):
                    if key_name in wanted:
                        state = find_state(partner, enum_uid(getattr(rule, field)))
                        assert state.name == wanted[key_name]
            assert rule_problem(agent_type, rule) == ""


@pytest.mark.parametrize("key", list(agent_examples.EXAMPLES))
def test_every_rule_of_every_example_fires_within_ten_seconds(key):
    """An example that never shows one of its rules does not demonstrate it."""
    _load(key)
    fps = bpy.context.scene.render.fps
    assert bpy.ops.pb_agents.preview_step(frames=10 * fps) == {"FINISHED"}
    stats = _session().sim.stats
    for agent_type in _world().types:
        for rule in agent_type.rules:
            assert stats[rule.uid].fired > 0, (
                f"{agent_type.name}: '{describe_rule(agent_type, rule)}' never fired")


def test_a_chance_typed_as_a_percentage_reaches_the_engine_as_a_probability():
    _load("RECEPTOR_LIGAND")
    touch = _type("Ligand").rules[0]
    touch.chance = 35.0
    spec = agent_preview.spec_from_scene(bpy.context.scene)
    ligand = next(t for t in spec.types if t.name == "Ligand")
    assert next(r for r in ligand.rules if r.uid == touch.uid).chance == pytest.approx(0.35)
    assert describe_rule(_type("Ligand"), touch).endswith(", 35%, sticks")


def test_both_sides_of_every_bond_agree_in_the_receptor_example():
    _load("RECEPTOR_LIGAND")
    ligand, receptor = _type("Ligand"), _type("Receptor")
    bound = next(s.uid for s in ligand.states if s.name == "Bound")
    occupied = next(s.uid for s in receptor.states if s.name == "Occupied")
    seen = 0
    for _ in range(20):
        bpy.ops.pb_agents.preview_step(frames=12)
        sim = _session().sim
        counts = sim.counts()
        assert counts[ligand.uid][bound] == counts[receptor.uid][occupied] == len(sim.bonds())
        seen = max(seen, len(sim.bonds()))
    assert seen > 0, "nothing bound, so the invariant was not exercised"


def test_rule_edits_reach_a_running_preview_without_restarting_it():
    _load("RECEPTOR_LIGAND")
    bpy.ops.pb_agents.preview_step(frames=48)
    session = _session()
    touch_rule = _type("Ligand").rules[0]
    touch_rule.enabled = False
    fired = session.sim.stats[touch_rule.uid].fired
    bpy.ops.pb_agents.preview_step(frames=96)
    assert _session() is session and session.sim.frame == 144
    assert session.sim.stats[touch_rule.uid].fired == fired


def test_a_new_count_waits_for_reset():
    _load("SWITCH")
    bpy.ops.pb_agents.preview_step(frames=2)
    session = _session()
    before = session.sim.n
    _type("Channel").count = before + 5
    agent_preview._sync(bpy.context.scene, session)
    assert session.stale and session.sim.n == before
    assert bpy.ops.pb_agents.preview_reset() == {"FINISHED"}
    assert _session().sim.n == before + 5 and not _session().stale


def test_removing_a_state_switches_off_the_rules_that_used_it():
    _load("RECEPTOR_LIGAND")
    _select_type("Receptor")
    receptor = _type("Receptor")
    receptor.active_state_index = next(k for k, s in enumerate(receptor.states) if s.name == "Occupied")
    assert bpy.ops.pb_agents.remove_state() == {"FINISHED"}
    touch, stuck = _type("Ligand").rules
    assert not touch.enabled and touch.partner_to_state == "KEEP"
    assert stuck.enabled, "the while-stuck rule never named Occupied"
    for agent_type in _world().types:
        for rule in agent_type.rules:
            assert _resolves(agent_type, rule)


def test_removing_a_type_switches_off_the_rules_that_needed_it():
    _load("RECEPTOR_LIGAND")
    _select_type("Receptor")
    assert bpy.ops.pb_agents.remove_type() == {"FINISHED"}
    ligand = _type("Ligand")
    assert [rule.enabled for rule in ligand.rules] == [False, False]
    assert all(rule.partner_type == "ANY" for rule in ligand.rules)


def test_a_new_rule_starts_from_the_selected_state_and_names_another_type():
    _load("RECEPTOR_LIGAND")
    _select_type("Ligand")
    ligand = _type("Ligand")
    ligand.active_state_index = 1
    assert bpy.ops.pb_agents.add_rule(trigger=engine.MEET) == {"FINISHED"}
    rule = ligand.rules[ligand.active_rule_index]
    assert find_state(ligand, enum_uid(rule.from_state)).name == "Bound"
    assert find_state(ligand, enum_uid(rule.to_state)).name == "Free"
    assert find_type(_world(), enum_uid(rule.partner_type)).name == "Receptor"


def test_a_renamed_state_keeps_every_rule_that_points_at_it():
    _load("RECEPTOR_LIGAND")
    receptor = _type("Receptor")
    next(s for s in receptor.states if s.name == "Empty").name = "Vacant"
    touch = _type("Ligand").rules[0]
    assert find_state(receptor, enum_uid(touch.partner_state)).name == "Vacant"
    assert "Receptor (Vacant)" in describe_rule(_type("Ligand"), touch)


def test_the_definition_is_saved_with_the_file(tmp_path):
    _load("ENZYME")
    path = str(tmp_path / "agents.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    name = bpy.context.scene.name
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.scenes = [name]
    copy = dst.scenes[0]
    try:
        saved = copy.pb_agents
        assert [t.name for t in saved.types] == [t.name for t in _world().types]
        for here, there in zip(_world().types, saved.types):
            assert [describe_rule(there, r) for r in there.rules] == \
                   [describe_rule(here, r) for r in here.rules]
    finally:
        bpy.data.scenes.remove(copy)


class _Layout:
    """Stands in for a UILayout and records what a draw call asks for."""

    def __init__(self, log=None):
        self.log = log if log is not None else {"labels": [], "props": [], "operators": [],
                                                "lists": [], "menus": []}

    def _child(self, *args, **kwargs):
        return _Layout(self.log)

    row = column = box = split = _child

    def panel(self, idname, default_closed=False):
        return _Layout(self.log), _Layout(self.log)

    def label(self, text="", icon="NONE", **kwargs):
        self.log["labels"].append((text, icon))

    def prop(self, data, name, **kwargs):
        self.log["props"].append((data, name))

    def operator(self, idname, **kwargs):
        self.log["operators"].append(idname)
        return types.SimpleNamespace()

    def operator_menu_enum(self, idname, prop, **kwargs):
        self.log["operators"].append(idname)

    def menu(self, name, **kwargs):
        self.log["menus"].append(name)

    def template_list(self, *args, **kwargs):
        self.log["lists"].append(args[0])

    def progress(self, **kwargs):
        self.log["labels"].append((kwargs.get("text", ""), "PROGRESS"))

    def separator(self, *args, **kwargs):
        pass


def _draw_panel():
    panel = types.SimpleNamespace(layout=_Layout())
    PB_AGENTS_PT_brains.draw(panel, bpy.context)
    return panel.layout.log


def _assert_props_exist(log):
    missing = [f"{type(data).__name__}.{name}" for data, name in log["props"]
               if name not in data.bl_rna.properties]
    assert not missing, f"panel draws properties that do not exist: {missing}"


def test_the_panel_draws_every_kind_of_rule_with_real_properties():
    _load("RECEPTOR_LIGAND")
    _select_type("Ligand")
    ligand = _type("Ligand")
    bpy.ops.pb_agents.add_rule(trigger=engine.TIMER)
    labels_by_rule = {}
    for index, rule in enumerate(ligand.rules):
        ligand.active_rule_index = index
        log = _draw_panel()
        _assert_props_exist(log)
        drawn = {name for _data, name in log["props"]}
        assert {"from_state", "trigger", "to_state"} <= drawn
        if rule.trigger == engine.MEET:
            assert {"partner_type", "partner_state", "reach_nm", "chance", "bind"} <= drawn
        elif rule.trigger == engine.BOUND:
            assert {"partner_type", "wait_s", "release"} <= drawn
        else:
            assert "wait_s" in drawn and "partner_type" not in drawn
        labels_by_rule[rule.trigger] = [text for text, _icon in log["labels"]]
    assert set(labels_by_rule) == {engine.MEET, engine.BOUND, engine.TIMER}
    assert "Brain: Ligand" in labels_by_rule[engine.MEET]
    assert {"PB_AGENTS_UL_types", "PB_AGENTS_UL_states", "PB_AGENTS_UL_rules"} <= set(
        _draw_panel()["lists"])


def test_the_panel_shows_live_counts_events_and_rule_statistics():
    _load("RECEPTOR_LIGAND")
    _select_type("Ligand")
    bpy.ops.pb_agents.preview_step(frames=240)
    log = _draw_panel()
    _assert_props_exist(log)
    texts = [text for text, _icon in log["labels"]]
    assert any(text.startswith("Preview:") and "touches" in text for text in texts)
    assert "Recent events" in texts
    sim = _session().sim
    assert any(sim.events[-1].text in text for text in texts)
    progress = [text for text, icon in log["labels"] if icon == "PROGRESS"]
    counts = sim.counts()
    expected = [str(counts[t.uid][s.uid]) for t in _world().types for s in t.states]
    assert progress == expected


def test_each_rule_row_reads_as_its_sentence():
    _load("RECEPTOR_LIGAND")
    ligand = _type("Ligand")
    bpy.ops.pb_agents.preview_step(frames=240)
    stats = _session().sim.stats
    for rule in ligand.rules:
        layout = _Layout()
        PB_AGENTS_UL_rules.draw_item(types.SimpleNamespace(), bpy.context, layout, ligand, rule,
                                     0, ligand, "active_rule_index")
        assert layout.log["labels"] == [
            (describe_rule(ligand, rule), "MOD_PHYSICS" if rule.trigger == engine.MEET else "LINKED"),
            (f"{stats[rule.uid].fired}×", "NONE"),
        ]
    touch, stuck = ligand.rules
    assert describe_rule(ligand, touch) == "Free → Bound: touches Receptor (Empty), 70%, sticks"
    assert describe_rule(ligand, stuck) == "Bound → Free: ~4 s stuck to Receptor, lets go"


def test_the_examples_menu_offers_every_example():
    layout = _Layout()
    PB_AGENTS_MT_examples.draw(types.SimpleNamespace(layout=layout), bpy.context)
    assert layout.log["operators"] == ["pb_agents.load_example"] * len(agent_examples.EXAMPLES)
