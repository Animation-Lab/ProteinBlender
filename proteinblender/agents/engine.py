"""Agent brain engine: Markov states, touch rules and binding, in plain NumPy.

This module has no ``bpy`` import on purpose.
It takes a frozen spec (``WorldSpec``) and advances a population of agents one
animation frame at a time, so the same code runs in Blender, in pytest and in a
notebook.

The model, in the words the panel uses:

* An **agent type** (Receptor, Ligand) is a sphere of a given size that wanders
  by Brownian motion. It may have one **binding site**: a direction on its
  surface (local +Z) with a cone of acceptance.
* Each type has a **brain**: a list of **states** (Free, Bound) and **rules**
  that move an agent from one state to another. The states and the timed rules
  form a continuous-time Markov chain; the start shares are its initial
  distribution.
* A rule fires in one of three ways:
    - ``TIMER``  "after a while": an exponential wait with the given mean.
    - ``MEET``   "when it touches": on a new touch of a chosen partner type
      (and partner state), optionally only when the sites face each other,
      with a chance per touch. It can change the partner's state too, and can
      make the two stick together.
    - ``BOUND``  "while stuck to": an exponential wait while bound to a chosen
      partner, optionally letting go.
* Competing events are arbitrated by sampled event times, so rates compete in
  their true ratio, and each agent takes part in at most one event per substep.

Units: lengths in nm, motion time in ns, rule waits in seconds of animation
(the "time map" of the plan: diffusion runs on a physical clock, events on the
shot clock). Positions live in the box ``[0, L)^3``; ``display_*`` helpers map
them to Blender units centred on the origin (1 BU = 10 nm).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Stokes-Einstein for a sphere in water at 298 K, R in nm:
# D_t = kT / (6 pi eta R) = 0.245 / R nm^2/ns, D_r = kT / (8 pi eta R^3) = 0.184 / R^3 rad^2/ns.
TRANSLATION_CONSTANT = 0.245
ROTATION_CONSTANT = 0.184

NM_PER_BU = 10.0

TIMER = "TIMER"
MEET = "MEET"
BOUND = "BOUND"

ANY = 0   # "any state" / "any agent type" in a condition
KEEP = 0  # "stays the same" in an outcome

DOCK_FRAMES = 6          # frames a newly bound partner takes to settle into its docked pose
MAX_SUBSTEPS = 12
SUBSTEP_FRACTION = 0.35  # largest RMS step per substep, as a fraction of the smallest radius
EVENT_LOG_LIMIT = 200


@dataclass(frozen=True)
class StateSpec:
    uid: int
    name: str
    color: tuple = (0.8, 0.8, 0.8)
    start_share: float = 0.0


@dataclass(frozen=True)
class RuleSpec:
    uid: int
    trigger: str
    from_state: int = ANY
    to_state: int = KEEP
    wait_s: float = 1.0
    partner_type: int = ANY
    partner_state: int = ANY
    partner_to_state: int = KEEP
    reach_nm: float = 1.0
    self_facing: bool = False
    partner_facing: bool = False
    chance: float = 1.0
    bind: bool = False
    release: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class TypeSpec:
    uid: int
    name: str
    count: int
    radius_nm: float
    mobility: float = 1.0
    has_site: bool = False
    site_name: str = "site"
    site_cone_deg: float = 30.0
    states: tuple = ()
    rules: tuple = ()


@dataclass(frozen=True)
class WorldSpec:
    types: tuple
    box_nm: float = 100.0
    boundary: str = "WALL"     # "WALL" or "WRAP"
    seed: int = 1
    ns_per_frame: float = 10.0
    fps: float = 24.0
    tumbling: float = 0.25     # rotational diffusion multiplier, slowed for legibility


@dataclass
class RuleStats:
    touches: int = 0   # new touches with both states matching (MEET only)
    aligned: int = 0   # of those, touches where the required sites faced each other
    fired: int = 0


@dataclass
class Event:
    frame: int
    time_s: float
    rule_uid: int
    text: str
    agents: tuple = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Quaternion helpers, (..., 4) arrays in (w, x, y, z) order.

def quat_mul(a, b):
    aw, ax, ay, az = np.moveaxis(np.asarray(a, dtype=float), -1, 0)
    bw, bx, by, bz = np.moveaxis(np.asarray(b, dtype=float), -1, 0)
    return np.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], axis=-1)


def quat_conj(q):
    return np.asarray(q, dtype=float) * np.array([1.0, -1.0, -1.0, -1.0])


def quat_rotate(q, v):
    q = np.asarray(q, dtype=float)
    v = np.asarray(v, dtype=float)
    w = q[..., :1]
    u = q[..., 1:]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def quat_normalize(q):
    q = np.asarray(q, dtype=float)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def quat_from_rotvec(rv):
    rv = np.asarray(rv, dtype=float)
    angle = np.linalg.norm(rv, axis=-1, keepdims=True)
    half = 0.5 * angle
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = np.where(angle > 1e-12, np.sin(half) / angle, 0.5)
    return np.concatenate([np.cos(half), rv * scale], axis=-1)


def quat_between(a, b):
    """Smallest rotation taking unit vector ``a`` onto unit vector ``b``."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    dot = float(np.dot(a, b))
    if dot < -0.999999:
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis /= np.linalg.norm(axis)
        return np.array([0.0, *axis])
    q = np.array([1.0 + dot, *np.cross(a, b)])
    return q / np.linalg.norm(q)


def quat_slerp(q0, q1, t):
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(q0 + t * (q1 - q0))
    theta = math.acos(min(1.0, dot))
    s = math.sin(theta)
    return (math.sin((1 - t) * theta) / s) * q0 + (math.sin(t * theta) / s) * q1


SITE_AXIS = np.array([0.0, 0.0, 1.0])


def random_quats(rng, n):
    return quat_normalize(rng.normal(size=(n, 4)))


def _swing(p0, p1, s):
    """Move from p0 to p1 around the origin: direction slerps, distance lerps.

    A straight line between two points on a sphere's surface cuts through the
    sphere, so a partner sliding into its docked pose that way would pass
    through the agent it docks onto.
    """
    l0 = np.linalg.norm(p0)
    l1 = np.linalg.norm(p1)
    if l0 < 1e-9 or l1 < 1e-9:
        return (1 - s) * p0 + s * p1
    u0 = p0 / l0
    u1 = p1 / l1
    cos_t = min(1.0, max(-1.0, float(np.dot(u0, u1))))
    theta = math.acos(cos_t)
    if theta < 1e-6:
        u = u0
    else:
        u = (math.sin((1 - s) * theta) * u0 + math.sin(s * theta) * u1) / math.sin(theta)
    return u * ((1 - s) * l0 + s * l1)


def _series(a, b):
    """1 / (1/a + 1/b), and 0 where both are 0."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    total = a + b
    return np.where(total > 0, a * b / np.where(total > 0, total, 1.0), 0.0)


def _smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def _shares_to_counts(shares, total):
    """Largest-remainder split of ``total`` agents by percentage shares."""
    shares = np.asarray(shares, dtype=float)
    if total <= 0 or len(shares) == 0:
        return np.zeros(len(shares), dtype=int)
    if shares.sum() <= 0:
        shares = np.zeros(len(shares))
        shares[0] = 1.0
    exact = shares / shares.sum() * total
    counts = np.floor(exact).astype(int)
    rest = total - counts.sum()
    order = np.argsort(-(exact - counts), kind="stable")
    counts[order[:rest]] += 1
    return counts


def population_key(spec: WorldSpec):
    """What a running preview cannot change without starting over."""
    return (spec.seed, round(spec.box_nm, 6),
            tuple((t.uid, t.count, round(t.radius_nm, 6)) for t in spec.types))


class Simulation:
    """A population of agents advancing one animation frame per ``step_frame``."""

    def __init__(self, spec: WorldSpec):
        self.spec = spec
        self.key = population_key(spec)
        self.rng = np.random.default_rng(spec.seed)
        self.frame = 0
        self.events: list[Event] = []
        self.stats: dict[int, RuleStats] = {}
        self._touching: dict[int, set] = {}
        self._separating: set = set()
        self._build_population()
        self._refresh_type_arrays()

    # ------------------------------------------------------------------ setup

    def _build_population(self):
        spec = self.spec
        types = spec.types
        self.type_index = np.concatenate(
            [np.full(t.count, k, dtype=int) for k, t in enumerate(types)]
        ) if types else np.zeros(0, dtype=int)
        self.local_index = np.concatenate(
            [np.arange(1, t.count + 1) for t in types]) if types else np.zeros(0, dtype=int)
        n = len(self.type_index)
        self.n = n
        self.radius = np.array([types[k].radius_nm for k in self.type_index], dtype=float)
        self.state = np.zeros(n, dtype=int)
        for k, t in enumerate(types):
            idx = np.flatnonzero(self.type_index == k)
            if not t.states or len(idx) == 0:
                continue
            counts = _shares_to_counts([s.start_share for s in t.states], len(idx))
            uids = np.repeat([s.uid for s in t.states], counts)
            self.rng.shuffle(uids)
            self.state[idx] = uids
        self.pos = self._place()
        self.quat = random_quats(self.rng, n)
        self.partner = np.full(n, -1, dtype=int)
        self.is_anchor = np.zeros(n, dtype=bool)
        self.rel_pos0 = np.zeros((n, 3))
        self.rel_pos1 = np.zeros((n, 3))
        self.rel_q0 = np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
        self.rel_q1 = np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
        self.dock_t = np.ones(n)

    def _place(self):
        """Random sequential placement, largest first, rejecting overlaps."""
        L = self.spec.box_nm
        pos = np.zeros((self.n, 3))
        placed = []
        order = np.argsort(-self.radius, kind="stable")
        for i in order:
            r = self.radius[i]
            lo, hi = min(r, L / 2), max(L - r, L / 2)
            best = None
            for _ in range(200):
                p = self.rng.uniform(lo, hi, size=3)
                if not placed:
                    best = p
                    break
                others = np.array(placed)
                d = self._delta(others[:, :3], p[None, :])
                if np.all(np.linalg.norm(d, axis=1) >= others[:, 3] + r):
                    best = p
                    break
            if best is None:  # crowded: accept an overlap, the relaxation pass resolves it
                best = self.rng.uniform(lo, hi, size=3)
            pos[i] = best
            placed.append([*best, r])
        return pos

    def update_spec(self, spec: WorldSpec):
        """Take new rules, colours and settings without restarting the population."""
        if population_key(spec) != self.key:
            raise ValueError("population changed; start a new Simulation")
        self.spec = spec
        self._refresh_type_arrays()
        for k, t in enumerate(spec.types):
            idx = np.flatnonzero(self.type_index == k)
            valid = {s.uid for s in t.states}
            if not valid:
                self.state[idx] = 0
                continue
            lost = idx[~np.isin(self.state[idx], list(valid))]
            self.state[lost] = t.states[0].uid

    def _refresh_type_arrays(self):
        types = self.spec.types
        ti = self.type_index
        self.mobility = np.array([types[k].mobility for k in ti], dtype=float)
        self.has_site = np.array([types[k].has_site for k in ti], dtype=bool)
        self.cone_cos = np.array([math.cos(math.radians(types[k].site_cone_deg)) for k in ti])
        self.d_t = TRANSLATION_CONSTANT / self.radius * self.mobility
        self.d_r = ROTATION_CONSTANT / self.radius ** 3 * self.mobility * self.spec.tumbling
        self.type_by_uid = {t.uid: k for k, t in enumerate(types)}
        self.rules = [(k, r) for k, t in enumerate(types) for r in t.rules if r.enabled]
        for _k, r in self.rules:
            self.stats.setdefault(r.uid, RuleStats())

    # --------------------------------------------------------------- geometry

    def _delta(self, a, b):
        """b - a, using the nearest periodic image when the box wraps."""
        d = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
        if self.spec.boundary == "WRAP":
            L = self.spec.box_nm
            d -= L * np.round(d / L)
        return d

    def site_axis(self, idx=None):
        q = self.quat if idx is None else self.quat[idx]
        return quat_rotate(q, np.broadcast_to(SITE_AXIS, np.shape(q)[:-1] + (3,)))

    def _follow_anchors(self):
        members = np.flatnonzero((self.partner >= 0) & ~self.is_anchor)
        if len(members) == 0:
            return
        anchors = self.partner[members]
        for j, i in zip(members, anchors):
            s = _smoothstep(self.dock_t[j])
            rel_p = _swing(self.rel_pos0[j], self.rel_pos1[j], s)
            rel_q = quat_slerp(self.rel_q0[j], self.rel_q1[j], s)
            self.pos[j] = self.pos[i] + quat_rotate(self.quat[i], rel_p)
            self.quat[j] = quat_normalize(quat_mul(self.quat[i], rel_q))

    def _apply_boundary(self):
        L = self.spec.box_nm
        movers = (self.partner < 0) | self.is_anchor
        if self.spec.boundary == "WRAP":
            self.pos[movers] = np.mod(self.pos[movers], L)
            self._follow_anchors()
            return
        r = self.radius[:, None]
        shift = np.maximum(0.0, r - self.pos) + np.minimum(0.0, (L - r) - self.pos)
        members = np.flatnonzero((self.partner >= 0) & ~self.is_anchor)
        for j in members:
            i = self.partner[j]
            pick = np.abs(shift[j]) > np.abs(shift[i])
            shift[i] = np.where(pick, shift[j], shift[i])
        self.pos[movers] += shift[movers]
        self._follow_anchors()

    def _pair_geometry(self):
        d = self._delta(self.pos[:, None, :], self.pos[None, :, :])
        dist = np.linalg.norm(d, axis=-1)
        gap = dist - (self.radius[:, None] + self.radius[None, :])
        return d, dist, gap

    def _separate_once(self):
        """One projection pass pushing overlapping pairs apart; returns the deepest overlap."""
        n = self.n
        if n < 2:
            return 0.0
        d, dist, gap = self._pair_geometry()
        over = gap < 0
        np.fill_diagonal(over, False)
        bound = np.flatnonzero(self.partner >= 0)
        over[bound, self.partner[bound]] = False
        if not over.any():
            return 0.0
        ii, jj = np.nonzero(np.triu(over))
        depth = -gap[ii, jj]
        u = d[ii, jj] / np.maximum(dist[ii, jj], 1e-12)[:, None]
        u[dist[ii, jj] < 1e-12] = [1.0, 0.0, 0.0]
        wi = self._group_mobility(ii)
        wj = self._group_mobility(jj)
        total = wi + wj
        share_i = np.where(total > 0, wi / np.where(total > 0, total, 1.0), 0.5)
        push = np.zeros((n, 3))
        np.add.at(push, ii, -u * (depth * share_i)[:, None])
        np.add.at(push, jj, u * (depth * (1 - share_i))[:, None])
        members = np.flatnonzero((self.partner >= 0) & ~self.is_anchor)
        np.add.at(push, self.partner[members], push[members])
        movers = (self.partner < 0) | self.is_anchor
        self.pos[movers] += push[movers]
        self._follow_anchors()
        return float(depth.max())

    def _relax(self, iterations=12, tolerance=0.005):
        """Separate overlaps and respect the walls together, so neither undoes the other."""
        for _ in range(iterations):
            deepest = self._separate_once()
            self._apply_boundary()
            if deepest < tolerance:
                return

    def _group_mobility(self, idx):
        d = self.d_t[idx].copy()
        bound = self.partner[idx] >= 0
        other = self.partner[idx][bound]
        d[bound] = _series(self.d_t[idx][bound], self.d_t[other])
        return d

    # ------------------------------------------------------------------ motion

    def _brownian(self, dt_ns):
        n = self.n
        free = self.partner < 0
        anchors = np.flatnonzero(self.is_anchor & (self.partner >= 0))
        d_t = self.d_t.copy()
        d_r = self.d_r.copy()
        if len(anchors):
            # Frictions add, so a bound pair diffuses like springs in series.
            j = self.partner[anchors]
            d_t[anchors] = _series(self.d_t[anchors], self.d_t[j])
            d_r[anchors] = _series(self.d_r[anchors], self.d_r[j])
        step = self.rng.normal(size=(n, 3)) * np.sqrt(2.0 * d_t * dt_ns)[:, None]
        spin = self.rng.normal(size=(n, 3)) * np.sqrt(2.0 * d_r * dt_ns)[:, None]
        dq = quat_from_rotvec(spin)

        self.pos[free] += step[free]
        self.quat[free] = quat_normalize(quat_mul(dq[free], self.quat[free]))

        if len(anchors):
            j = self.partner[anchors]
            wa = self.radius[anchors] ** 3
            wb = self.radius[j] ** 3
            com = (self.pos[anchors] * wa[:, None] + self.pos[j] * wb[:, None]) / (wa + wb)[:, None]
            arm = self.pos[anchors] - com
            self.pos[anchors] = com + quat_rotate(dq[anchors], arm) + step[anchors]
            self.quat[anchors] = quat_normalize(quat_mul(dq[anchors], self.quat[anchors]))
        self._follow_anchors()

    # ------------------------------------------------------------------ rules

    def _state_matches(self, idx, uid):
        return np.ones(len(idx), dtype=bool) if uid == ANY else self.state[idx] == uid

    def _type_members(self, type_uid):
        if type_uid == ANY:
            return np.arange(self.n)
        k = self.type_by_uid.get(type_uid)
        if k is None:
            return np.zeros(0, dtype=int)
        return np.flatnonzero(self.type_index == k)

    def _collect_events(self, dt_s, gap, d, dist):
        candidates = []
        for k, rule in self.rules:
            owners = np.flatnonzero(self.type_index == k)
            owners = owners[self._state_matches(owners, rule.from_state)]
            if len(owners) == 0:
                if rule.trigger == MEET:
                    self._touching[rule.uid] = (set(), set())
                continue
            if rule.trigger == TIMER:
                times = self.rng.exponential(max(rule.wait_s, 1e-6), size=len(owners))
                for i, t in zip(owners[times < dt_s], times[times < dt_s]):
                    candidates.append((t, self.rng.random(), rule, k, int(i), -1))
            elif rule.trigger == BOUND:
                owners = owners[self.partner[owners] >= 0]
                if len(owners) == 0:
                    continue
                partners = self.partner[owners]
                ok = np.ones(len(owners), dtype=bool)
                if rule.partner_type != ANY:
                    pk = self.type_by_uid.get(rule.partner_type, -1)
                    ok &= self.type_index[partners] == pk
                if rule.partner_state != ANY:
                    ok &= self.state[partners] == rule.partner_state
                owners, partners = owners[ok], partners[ok]
                times = self.rng.exponential(max(rule.wait_s, 1e-6), size=len(owners))
                hit = times < dt_s
                for i, j, t in zip(owners[hit], partners[hit], times[hit]):
                    candidates.append((t, self.rng.random(), rule, k, int(i), int(j)))
            elif rule.trigger == MEET:
                candidates.extend(self._meet_candidates(rule, k, owners, dt_s, gap, d, dist))
        return candidates

    def _meet_candidates(self, rule, k, owners, dt_s, gap, d, dist):
        partners = self._type_members(rule.partner_type)
        partners = partners[self._state_matches(partners, rule.partner_state)]
        found = []
        if len(partners) == 0:
            self._touching[rule.uid] = (set(), set())
            return found
        sub = gap[np.ix_(owners, partners)] <= rule.reach_nm
        oi, pj = np.nonzero(sub)
        ii, jj = owners[oi], partners[pj]
        keep = (ii != jj) & (self.partner[ii] != jj)
        ii, jj = ii[keep], jj[keep]
        if rule.bind:
            free = (self.partner[ii] < 0) & (self.partner[jj] < 0)
            ii, jj = ii[free], jj[free]
        pairs = [(int(i), int(j)) for i, j in zip(ii, jj)
                 if frozenset((int(i), int(j))) not in self._separating]
        previous = self._touching.get(rule.uid)
        current_touch = set(pairs)
        aligned_now = set()
        if pairs:
            pi = np.array([p[0] for p in pairs])
            pjj = np.array([p[1] for p in pairs])
            u = d[pi, pjj] / np.maximum(dist[pi, pjj], 1e-9)[:, None]
            facing = np.ones(len(pairs), dtype=bool)
            if rule.self_facing:
                own = self.has_site[pi]
                cosang = np.einsum("ij,ij->i", self.site_axis(pi), u)
                facing &= ~own | (cosang >= self.cone_cos[pi])
            if rule.partner_facing:
                own = self.has_site[pjj]
                cosang = np.einsum("ij,ij->i", self.site_axis(pjj), -u)
                facing &= ~own | (cosang >= self.cone_cos[pjj])
            aligned_now = {p for p, f in zip(pairs, facing) if f}
        stats = self.stats.setdefault(rule.uid, RuleStats())
        prev_touch, prev_aligned = previous if previous else (set(), set())
        stats.touches += len(current_touch - prev_touch)
        new_aligned = aligned_now - prev_aligned
        stats.aligned += len(new_aligned)
        self._touching[rule.uid] = (current_touch, aligned_now)
        for i, j in sorted(new_aligned):
            if self.rng.random() < rule.chance:
                found.append((self.rng.uniform(0.0, dt_s), self.rng.random(), rule, k, i, j))
        return found

    def _apply_events(self, candidates):
        used = np.zeros(self.n, dtype=bool)
        candidates.sort(key=lambda c: (c[0], c[1]))
        for t, _tie, rule, k, i, j in candidates:
            touches_partner = j >= 0 and (
                rule.bind or rule.release or rule.partner_to_state != KEEP)
            if used[i] or (touches_partner and used[j]):
                continue
            if rule.trigger == MEET and rule.bind and (self.partner[i] >= 0 or self.partner[j] >= 0):
                continue
            if rule.trigger == BOUND and self.partner[i] != j:
                continue
            before_i = self.state[i]
            if rule.to_state != KEEP:
                self.state[i] = rule.to_state
            if j >= 0 and rule.partner_to_state != KEEP:
                self.state[j] = rule.partner_to_state
            if rule.trigger == MEET and rule.bind:
                self._bind(i, j)
            if rule.trigger == BOUND and rule.release:
                self._release(i, j)
            used[i] = True
            if touches_partner:
                used[j] = True
            self.stats.setdefault(rule.uid, RuleStats()).fired += 1
            self._log(rule, i, j, before_i)

    def _bind(self, i, j):
        """Dock the smaller of i and j onto the larger, settling over DOCK_FRAMES."""
        a, m = (i, j) if self.radius[i] >= self.radius[j] else (j, i)
        u = self._delta(self.pos[a], self.pos[m])
        dist = np.linalg.norm(u)
        if self.has_site[a]:
            u = self.site_axis(a)
        elif self.has_site[m]:
            u = -self.site_axis(m)
        elif dist > 1e-9:
            u = u / dist
        else:
            u = SITE_AXIS.copy()
        target_pos = self.pos[a] + u * (self.radius[a] + self.radius[m])
        target_q = self.quat[m]
        if self.has_site[m]:
            target_q = quat_normalize(quat_mul(quat_between(self.site_axis(m), -u), self.quat[m]))
        inv_a = quat_conj(self.quat[a])
        self.rel_pos0[m] = quat_rotate(inv_a, self._delta(self.pos[a], self.pos[m]))
        self.rel_pos1[m] = quat_rotate(inv_a, target_pos - self.pos[a])
        self.rel_q0[m] = quat_mul(inv_a, self.quat[m])
        self.rel_q1[m] = quat_mul(inv_a, target_q)
        self.dock_t[m] = 0.0
        self.partner[a] = m
        self.partner[m] = a
        self.is_anchor[a] = True
        self.is_anchor[m] = False

    def _release(self, i, j):
        for a in (i, j):
            self.partner[a] = -1
            self.is_anchor[a] = False
            self.dock_t[a] = 1.0
        self._separating.add(frozenset((i, j)))

    def _forget_separated(self, gap):
        if not self._separating:
            return
        reach = max((r.reach_nm for _k, r in self.rules if r.trigger == MEET), default=0.0)
        self._separating = {p for p in self._separating
                            if gap[tuple(p)] <= reach + 0.5}

    # --------------------------------------------------------------- stepping

    def substeps(self):
        if self.n == 0:
            return 1
        dt_ns = self.spec.ns_per_frame
        rms = np.sqrt(6.0 * self.d_t * dt_ns).max()
        return int(min(MAX_SUBSTEPS, max(1, math.ceil(rms / (SUBSTEP_FRACTION * self.radius.min())))))

    def step_frame(self):
        spec = self.spec
        n_sub = self.substeps()
        dt_ns = spec.ns_per_frame / n_sub
        dt_s = 1.0 / spec.fps / n_sub
        dock_step = 1.0 / (DOCK_FRAMES * n_sub)
        for _ in range(n_sub):
            if self.n:
                docking = (self.partner >= 0) & ~self.is_anchor & (self.dock_t < 1.0)
                self.dock_t[docking] = np.minimum(1.0, self.dock_t[docking] + dock_step)
                self._brownian(dt_ns)
                self._apply_boundary()
                self._relax()
                d, dist, gap = self._pair_geometry()
                self._forget_separated(gap)
                self._apply_events(self._collect_events(dt_s, gap, d, dist))
        self.frame += 1

    # ----------------------------------------------------------------- output

    @property
    def time_s(self):
        return self.frame / self.spec.fps

    def agent_name(self, i):
        return f"{self.spec.types[self.type_index[i]].name} {self.local_index[i]}"

    def state_name(self, k, uid):
        for s in self.spec.types[k].states:
            if s.uid == uid:
                return s.name
        return "?"

    def _change_text(self, i, before, after):
        k = self.type_index[i]
        if after == KEEP or after == before:
            return ""
        return f"{self.state_name(k, before)} → {self.state_name(k, after)}"

    def _log(self, rule, i, j, before_i):
        """One short line per event: who did what, and its own state change.

        The partner's change is left out on purpose: it shows in the partner's
        colour and in the counts, and a line long enough to carry both gets cut
        off in the middle by the panel.
        """
        who = self.agent_name(i)
        mine = self._change_text(i, before_i, rule.to_state)
        if rule.trigger == TIMER:
            text = f"{who}: {mine or 'no change'}"
        else:
            if rule.trigger == MEET:
                verb = "stuck to" if rule.bind else "touched"
            else:
                verb = "let go of" if rule.release else "changed while stuck to"
            text = f"{who} {verb} {self.agent_name(j)}"
            if mine:
                text += f": {mine}"
        self.events.append(Event(self.frame, self.time_s, rule.uid, text,
                                 (i,) if j < 0 else (i, j)))
        if len(self.events) > EVENT_LOG_LIMIT:
            del self.events[:len(self.events) - EVENT_LOG_LIMIT]

    def counts(self):
        """{type uid: {state uid: number of agents}} in spec order."""
        out = {}
        for k, t in enumerate(self.spec.types):
            states = self.state[self.type_index == k]
            out[t.uid] = {s.uid: int(np.count_nonzero(states == s.uid)) for s in t.states}
        return out

    def bonds(self):
        return [(int(i), int(self.partner[i])) for i in np.flatnonzero(self.is_anchor & (self.partner >= 0))]

    def colors(self):
        out = np.full((self.n, 3), 0.6)
        for k, t in enumerate(self.spec.types):
            of_type = self.type_index == k
            for s in t.states:
                out[of_type & (self.state == s.uid)] = s.color[:3]
        return out

    def display_positions(self):
        """Centres in Blender units, box centred on the world origin."""
        return (self.pos - self.spec.box_nm / 2.0) / NM_PER_BU

    def display_radii(self):
        return self.radius / NM_PER_BU

    # --------------------------------------------------------------- testing

    def place(self, i, pos_nm, quat=None):
        """Put agent ``i`` at a chosen pose (tests and scripted scenes)."""
        self.pos[i] = np.asarray(pos_nm, dtype=float)
        if quat is not None:
            self.quat[i] = quat_normalize(np.asarray(quat, dtype=float))
        self._touching.clear()
