"""The agent brain engine against ground truth it does not compute itself.

Timed rules are checked against the analytic results for exponential waits
(survival, competing exits, two-state equilibrium), free motion against the
Stokes-Einstein coefficient computed here from physical constants, and touch
rules against geometry placed by hand.
"""

import math

import numpy as np
import pytest

from proteinblender.agents import engine as E

FPS = 24.0


def _world(*types, box_nm=200.0, seed=7, boundary="WALL", ns_per_frame=10.0, tumbling=0.25):
    return E.WorldSpec(types=tuple(types), box_nm=box_nm, boundary=boundary, seed=seed,
                       ns_per_frame=ns_per_frame, fps=FPS, tumbling=tumbling)


def _still(uid, name, count, states, rules=(), radius=1.0, **kw):
    """A type that does not move, so only its brain is under test."""
    return E.TypeSpec(uid=uid, name=name, count=count, radius_nm=radius, mobility=0.0,
                      states=tuple(states), rules=tuple(rules), **kw)


def _fraction(sim, type_uid, state_uid):
    counts = sim.counts()[type_uid]
    return counts[state_uid] / sum(counts.values())


def _run_seconds(sim, seconds):
    for _ in range(int(round(seconds * FPS))):
        sim.step_frame()


def test_a_timed_rule_empties_its_state_exponentially():
    """After one mean wait, e^-1 of the agents are still in the start state."""
    n = 800
    agent = _still(1, "A", n, [E.StateSpec(2, "On", start_share=100), E.StateSpec(3, "Off")],
                   [E.RuleSpec(4, E.TIMER, from_state=2, to_state=3, wait_s=2.0)])
    sim = E.Simulation(_world(agent, box_nm=2000.0))
    _run_seconds(sim, 2.0)
    expected = math.exp(-1.0)
    sigma = math.sqrt(expected * (1 - expected) / n)
    assert abs(_fraction(sim, 1, 2) - expected) < 4 * sigma


def test_competing_exits_split_in_the_ratio_of_their_rates():
    """Rates 9/s and 1/s out of one state send 90% one way, whatever the rule order."""
    n = 800
    slow_first = [
        E.RuleSpec(10, E.TIMER, from_state=2, to_state=4, wait_s=1.0),       # 1 per second
        E.RuleSpec(11, E.TIMER, from_state=2, to_state=3, wait_s=1.0 / 9.0),  # 9 per second
    ]
    agent = _still(1, "A", n, [E.StateSpec(2, "Start", start_share=100),
                               E.StateSpec(3, "Fast"), E.StateSpec(4, "Slow")], slow_first)
    sim = E.Simulation(_world(agent, box_nm=2000.0))
    _run_seconds(sim, 4.0)
    counts = sim.counts()[1]
    assert counts[2] == 0, "every agent should have left the start state"
    sigma = math.sqrt(0.9 * 0.1 / n)
    assert abs(counts[3] / n - 0.9) < 4 * sigma, counts


def test_a_two_state_switch_settles_at_the_ratio_of_its_dwell_times():
    """With mean dwells of 1 s in A and 3 s in B, a quarter of the time is spent in A."""
    n = 600
    agent = _still(1, "A", n, [E.StateSpec(2, "A", start_share=100), E.StateSpec(3, "B")], [
        E.RuleSpec(4, E.TIMER, from_state=2, to_state=3, wait_s=1.0),
        E.RuleSpec(5, E.TIMER, from_state=3, to_state=2, wait_s=3.0),
    ])
    sim = E.Simulation(_world(agent, box_nm=2000.0))
    _run_seconds(sim, 20.0)
    samples = []
    for _ in range(10):
        _run_seconds(sim, 1.0)
        samples.append(_fraction(sim, 1, 2))
    assert abs(np.mean(samples) - 0.25) < 0.03


def test_start_shares_split_a_small_population_exactly():
    agent = _still(1, "A", 10, [E.StateSpec(2, "On", start_share=70),
                                E.StateSpec(3, "Off", start_share=30)])
    sim = E.Simulation(_world(agent))
    assert sim.counts()[1] == {2: 7, 3: 3}


def test_free_agents_diffuse_with_the_stokes_einstein_coefficient():
    """Mean squared displacement grows as 6 D t, D = kT / (6 pi eta R) in water at 298 K."""
    k_b, temperature, eta, radius_nm = 1.380649e-23, 298.15, 0.00089, 2.0
    d_m2_per_s = k_b * temperature / (6 * math.pi * eta * radius_nm * 1e-9)
    d_nm2_per_ns = d_m2_per_s * 1e18 / 1e9
    n, frames, ns_per_frame = 400, 20, 10.0
    agent = E.TypeSpec(uid=1, name="A", count=n, radius_nm=radius_nm,
                       states=(E.StateSpec(2, "On", start_share=100),))
    sim = E.Simulation(_world(agent, box_nm=100000.0, ns_per_frame=ns_per_frame))
    start = sim.pos.copy()
    for _ in range(frames):
        sim.step_frame()
    msd = np.mean(np.sum((sim.pos - start) ** 2, axis=1))
    expected = 6 * d_nm2_per_ns * frames * ns_per_frame
    assert abs(msd / expected - 1.0) < 0.15, (msd, expected)


def _receptor_and_ligand(partner_facing=True, wait_s=100.0, chance=1.0):
    receptor = _still(1, "Receptor", 1, [E.StateSpec(2, "Empty", start_share=100),
                                         E.StateSpec(3, "Occupied")],
                      radius=4.0, has_site=True, site_cone_deg=30.0)
    ligand = _still(4, "Ligand", 1, [E.StateSpec(5, "Free", start_share=100),
                                     E.StateSpec(6, "Bound")], [
        E.RuleSpec(7, E.MEET, from_state=5, to_state=6, partner_type=1, partner_state=2,
                   partner_to_state=3, reach_nm=1.0, partner_facing=partner_facing,
                   chance=chance, bind=True),
        E.RuleSpec(8, E.BOUND, from_state=6, to_state=5, partner_type=1, partner_to_state=2,
                   wait_s=wait_s, release=True),
    ], radius=1.5)
    sim = E.Simulation(_world(receptor, ligand, box_nm=100.0, tumbling=0.0))
    centre = np.array([50.0, 50.0, 50.0])
    sim.place(0, centre, quat=[1.0, 0.0, 0.0, 0.0])  # receptor pocket points along +Z
    return sim, centre


def test_a_touch_in_front_of_the_pocket_binds_both_sides():
    sim, centre = _receptor_and_ligand()
    sim.place(1, centre + [0.0, 0.0, 4.0 + 1.5 + 0.5])  # 0.5 nm gap, on the pocket axis
    sim.step_frame()
    assert sim.partner[0] == 1 and sim.partner[1] == 0
    assert sim.counts() == {1: {2: 0, 3: 1}, 4: {5: 0, 6: 1}}


def test_a_touch_beside_the_pocket_does_not_bind():
    sim, centre = _receptor_and_ligand()
    sim.place(1, centre + [4.0 + 1.5 + 0.5, 0.0, 0.0])  # touching, 90 degrees off the pocket
    for _ in range(5):
        sim.step_frame()
    assert sim.partner[1] == -1
    stats = sim.stats[7]
    assert (stats.touches, stats.aligned, stats.fired) == (1, 0, 0)


def test_a_bound_pair_moves_as_one_docked_on_the_pocket():
    sim, centre = _receptor_and_ligand()
    sim.place(1, centre + [0.3, 0.0, 4.0 + 1.5 + 0.8])
    sim.step_frame()
    assert sim.partner[1] == 0
    moving = E.WorldSpec(**{**sim.spec.__dict__, "types": tuple(
        E.TypeSpec(**{**t.__dict__, "mobility": 1.0}) for t in sim.spec.types),
        "tumbling": 0.25})
    sim.update_spec(moving)
    start = sim.pos[0].copy()
    for _ in range(60):
        sim.step_frame()
        offset = sim.pos[1] - sim.pos[0]
        if sim.dock_t[1] >= 1.0:
            assert abs(np.linalg.norm(offset) - (4.0 + 1.5)) < 1e-6
            axis = E.quat_rotate(sim.quat[0], [0.0, 0.0, 1.0])
            assert np.dot(offset / np.linalg.norm(offset), axis) > 1 - 1e-6
    assert np.linalg.norm(sim.pos[0] - start) > 0.5, "the pair should have moved"


def test_a_while_stuck_rule_lets_go_and_restores_both_states():
    sim, centre = _receptor_and_ligand(wait_s=0.05)
    sim.place(1, centre + [0.0, 0.0, 4.0 + 1.5 + 0.5])
    sim.step_frame()
    for _ in range(int(FPS)):
        sim.step_frame()
        if sim.partner[1] == -1:
            break
    assert sim.partner[0] == -1 and sim.partner[1] == -1
    assert sim.counts() == {1: {2: 1, 3: 0}, 4: {5: 1, 6: 0}}
    assert sim.stats[8].fired == 1


def _crowd(seed=3, boundary="WALL"):
    receptor = E.TypeSpec(uid=1, name="Receptor", count=10, radius_nm=4.0, has_site=True,
                          site_cone_deg=60.0,
                          states=(E.StateSpec(2, "Empty", start_share=100), E.StateSpec(3, "Occupied")))
    ligand = E.TypeSpec(uid=4, name="Ligand", count=60, radius_nm=1.5, has_site=True,
                        states=(E.StateSpec(5, "Free", start_share=100), E.StateSpec(6, "Bound")),
                        rules=(
                            E.RuleSpec(7, E.MEET, from_state=5, to_state=6, partner_type=1,
                                       partner_state=2, partner_to_state=3, reach_nm=1.0,
                                       partner_facing=True, chance=1.0, bind=True),
                            E.RuleSpec(8, E.BOUND, from_state=6, to_state=5, partner_type=1,
                                       partner_to_state=2, wait_s=1.0, release=True)))
    return E.Simulation(_world(receptor, ligand, box_nm=50.0, seed=seed, boundary=boundary))


@pytest.mark.parametrize("boundary", ["WALL", "WRAP"])
def test_a_crowded_run_never_leaves_agents_overlapping(boundary):
    """No two agents clip, bound partners included: a partner swinging into its
    docked pose must go around the agent it docks onto, not through it."""
    sim = _crowd(boundary=boundary)
    worst = 0.0
    docked_while_measuring = 0
    for _ in range(240):
        sim.step_frame()
        _d, _dist, gap = sim._pair_geometry()
        np.fill_diagonal(gap, np.inf)
        worst = min(worst, gap.min())
        docked_while_measuring += int(np.count_nonzero((sim.partner >= 0) & (sim.dock_t < 1.0)))
    assert docked_while_measuring, "no pair was ever caught mid-dock, so docking was not exercised"
    assert worst > -0.05, f"agents overlapped by {-worst:.3f} nm"


def test_walls_keep_every_agent_inside_the_box():
    sim = _crowd()
    for _ in range(120):
        sim.step_frame()
        r = sim.radius[:, None]
        assert np.all(sim.pos >= r - 1e-9) and np.all(sim.pos <= sim.spec.box_nm - r + 1e-9)


def test_both_sides_of_every_bond_agree():
    sim = _crowd()
    seen_bound = False
    for _ in range(240):
        sim.step_frame()
        counts = sim.counts()
        bonds = sim.bonds()
        assert counts[4][6] == counts[1][3] == len(bonds)
        seen_bound |= bool(bonds)
        for i, j in bonds:
            assert sim.partner[j] == i
    assert seen_bound, "nothing ever bound, so the invariant was not exercised"


def test_the_same_seed_replays_and_another_seed_does_not():
    a, b, c = _crowd(seed=5), _crowd(seed=5), _crowd(seed=6)
    for _ in range(30):
        a.step_frame()
        b.step_frame()
        c.step_frame()
    assert np.array_equal(a.pos, b.pos) and np.array_equal(a.state, b.state)
    assert not np.allclose(a.pos, c.pos)
