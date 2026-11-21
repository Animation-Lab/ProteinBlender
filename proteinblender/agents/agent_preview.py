"""Live preview of the agent brains in the 3D viewport.

The preview is runtime-only: it reads ``scene.pb_agents`` into an engine spec,
steps an ``engine.Simulation`` from a timer, and draws the agents with the
``gpu`` module in a viewport draw handler. Nothing is written to the scene, so
the preview adds no undo steps, no objects and no depsgraph updates.

Rule edits apply while the preview runs. Changing a count, a size or the seed
changes the population, which only happens on Run or Reset.
"""

import logging
import math
import time

import bpy
import numpy as np

from . import engine
from .agent_props import enum_uid

logger = logging.getLogger(__name__)

MAX_FRAMES_PER_TICK = 4


def spec_from_scene(scene):
    """The engine's frozen view of everything defined on ``scene.pb_agents``."""
    world = scene.pb_agents
    render = scene.render
    fps = render.fps / (render.fps_base or 1.0)
    types = []
    for agent_type in world.types:
        states = tuple(
            engine.StateSpec(state.uid, state.name, tuple(state.color), state.start_share)
            for state in agent_type.states)
        rules = []
        for rule in agent_type.rules:
            fields = [rule.from_state, rule.to_state]
            if rule.trigger != engine.TIMER:
                fields += [rule.partner_type, rule.partner_state, rule.partner_to_state]
            uids = [enum_uid(value) for value in fields]
            if any(uid is None for uid in uids):
                continue  # points at something deleted; the panel flags it
            uids += [0] * (5 - len(uids))
            rules.append(engine.RuleSpec(
                uid=rule.uid, trigger=rule.trigger,
                from_state=uids[0], to_state=uids[1], wait_s=rule.wait_s,
                partner_type=uids[2], partner_state=uids[3], partner_to_state=uids[4],
                reach_nm=rule.reach_nm, self_facing=rule.self_facing,
                partner_facing=rule.partner_facing, chance=rule.chance / 100.0,
                bind=rule.bind, release=rule.release, enabled=rule.enabled))
        types.append(engine.TypeSpec(
            uid=agent_type.uid, name=agent_type.name, count=agent_type.count,
            radius_nm=agent_type.radius_nm, mobility=agent_type.mobility,
            has_site=agent_type.has_site, site_name=agent_type.site_name,
            site_cone_deg=math.degrees(agent_type.site_cone),
            states=states, rules=tuple(rules)))
    return engine.WorldSpec(
        types=tuple(types), box_nm=world.box_nm, boundary=world.boundary,
        seed=world.seed, ns_per_frame=world.ns_per_frame, fps=fps,
        tumbling=world.tumbling)


class Session:
    def __init__(self, scene, spec):
        self.scene_pointer = scene.as_pointer()
        self.sim = engine.Simulation(spec)
        self.running = False
        self.stale = False
        self._clock = time.perf_counter()
        self._carry = 0.0


_session = None
_draw_handle = None


def session_for(scene):
    if _session is not None and scene is not None and _session.scene_pointer == scene.as_pointer():
        return _session
    return None


def _sync(scene, session):
    spec = spec_from_scene(scene)
    if engine.population_key(spec) != session.sim.key:
        session.stale = True
        return
    session.sim.update_spec(spec)
    session.stale = False


def ensure(scene, restart=False):
    """The scene's session, started (or restarted) as needed."""
    global _session
    spec = spec_from_scene(scene)
    session = session_for(scene)
    if session is None or restart or engine.population_key(spec) != session.sim.key:
        running = session.running if session is not None else False
        _session = Session(scene, spec)
        _session.running = running
        session = _session
    else:
        session.sim.update_spec(spec)
        session.stale = False
    _ensure_draw_handler()
    return session


def run(scene):
    session = ensure(scene)
    session.running = True
    session._clock = time.perf_counter()
    session._carry = 0.0
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0)
    redraw()
    return session


def pause(scene):
    session = session_for(scene)
    if session is not None:
        session.running = False
    redraw()


def reset(scene):
    session = ensure(scene, restart=True)
    session.running = False
    redraw()
    return session


def step(scene, frames=1):
    session = ensure(scene)
    for _ in range(frames):
        session.sim.step_frame()
    redraw()
    return session


def stop_all():
    """Drop the session, its timer and the draw handler."""
    global _session, _draw_handle
    _session = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _draw_handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
        _draw_handle = None
    redraw()


def _tick():
    session = _session
    if session is None or not session.running:
        return None
    scene = bpy.context.scene
    if scene is None or scene.as_pointer() != session.scene_pointer:
        session.running = False
        return None
    try:
        _sync(scene, session)
        world = scene.pb_agents
        now = time.perf_counter()
        session._carry += (now - session._clock) * session.sim.spec.fps * world.speed
        session._clock = now
        frames = min(int(session._carry), MAX_FRAMES_PER_TICK)
        session._carry = min(session._carry - frames, 1.0)
        for _ in range(frames):
            session.sim.step_frame()
        if frames:
            redraw()
    except Exception:
        logger.exception("Agent preview stopped")
        session.running = False
        return None
    return 1.0 / 60.0


def redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()


def frame_box(context):
    """Point every 3D view at the preview box."""
    size = context.scene.pb_agents.box_nm / engine.NM_PER_BU
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            rv3d = area.spaces.active.region_3d
            rv3d.view_location = (0.0, 0.0, 0.0)
            rv3d.view_distance = size * 1.9
            area.tag_redraw()


@bpy.app.handlers.persistent
def _stop_on_load(*_args):
    stop_all()


# ----------------------------------------------------------------- drawing

def _icosphere(subdivisions=2):
    t = (1.0 + 5 ** 0.5) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
             (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    verts = [np.array(v, dtype=float) / np.linalg.norm(v) for v in verts]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(subdivisions):
        cache = {}
        new_faces = []

        def midpoint(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces
    return np.array(verts), np.array(faces, dtype=np.int32)


def _cone(segments=16, base_z=0.88, tip_z=1.42, radius=0.34):
    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    ring = np.stack([radius * np.cos(angles), radius * np.sin(angles),
                     np.full(segments, base_z)], axis=1)
    slope = radius / (tip_z - base_z)
    ring_normals = np.stack([np.cos(angles), np.sin(angles), np.full(segments, slope)], axis=1)
    ring_normals /= np.linalg.norm(ring_normals, axis=1, keepdims=True)
    verts = np.vstack([ring, [[0.0, 0.0, tip_z]]])
    normals = np.vstack([ring_normals, [[0.0, 0.0, 1.0]]])
    faces = [(k, (k + 1) % segments, segments) for k in range(segments)]
    return verts, normals, np.array(faces, dtype=np.int32)


_SPHERE_V, _SPHERE_F = _icosphere(2)
_CONE_V, _CONE_N, _CONE_F = _cone()
_BOX_EDGES = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
              (0, 4), (1, 5), (2, 6), (3, 7)]


def _shade(normals, light, colors):
    lambert = np.clip(normals @ light, 0.0, 1.0)
    shade = 0.30 + 0.70 * lambert
    rgb = np.clip(colors * shade[..., None], 0.0, 1.0)
    return np.concatenate([rgb, np.ones(rgb.shape[:-1] + (1,))], axis=-1)


def build_mesh(sim, light):
    """Triangles for every agent: (positions, RGBA colours, indices) in BU."""
    n = sim.n
    if n == 0:
        return None
    centres = sim.display_positions()
    radii = sim.display_radii()
    colors = sim.colors()
    nv = len(_SPHERE_V)
    pos = centres[:, None, :] + radii[:, None, None] * _SPHERE_V[None]
    col = _shade(np.broadcast_to(_SPHERE_V, (n, nv, 3)), light,
                 np.broadcast_to(colors[:, None, :], (n, nv, 3)))
    idx = (_SPHERE_F[None] + (np.arange(n) * nv)[:, None, None]).reshape(-1, 3)
    positions = [pos.reshape(-1, 3)]
    rgba = [col.reshape(-1, 4)]
    indices = [idx]
    sited = np.flatnonzero(sim.has_site)
    if len(sited):
        m = len(sited)
        nc = len(_CONE_V)
        q = sim.quat[sited][:, None, :]
        cpos = centres[sited][:, None, :] + radii[sited][:, None, None] * engine.quat_rotate(
            np.broadcast_to(q, (m, nc, 4)), np.broadcast_to(_CONE_V, (m, nc, 3)))
        cnorm = engine.quat_rotate(np.broadcast_to(q, (m, nc, 4)), np.broadcast_to(_CONE_N, (m, nc, 3)))
        tint = 0.45 * colors[sited] + 0.55
        ccol = _shade(cnorm, light, np.broadcast_to(tint[:, None, :], (m, nc, 3)))
        base = n * nv
        cidx = (_CONE_F[None] + (base + np.arange(m) * nc)[:, None, None]).reshape(-1, 3)
        positions.append(cpos.reshape(-1, 3))
        rgba.append(ccol.reshape(-1, 4))
        indices.append(cidx)
    return (np.vstack(positions).astype(np.float32), np.vstack(rgba).astype(np.float32),
            np.vstack(indices).astype(np.int32))


def _draw():
    session = session_for(bpy.context.scene)
    if session is None:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader

    rv3d = bpy.context.region_data
    if rv3d is None:
        return
    view_rot = np.array(rv3d.view_matrix.to_3x3())
    light = view_rot.T @ np.array([0.35, 0.45, 0.82])
    light /= np.linalg.norm(light)
    sim = session.sim
    mesh = build_mesh(sim, light)

    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(True)
    try:
        if mesh is not None:
            shader = gpu.shader.from_builtin("SMOOTH_COLOR")
            batch = batch_for_shader(shader, "TRIS", {"pos": mesh[0], "color": mesh[1]},
                                     indices=mesh[2])
            batch.draw(shader)
        if bpy.context.scene.pb_agents.show_box:
            half = sim.spec.box_nm / engine.NM_PER_BU / 2.0
            corners = [(x, y, z) for x in (-half, half) for y in (-half, half) for z in (-half, half)]
            lines = [corners[k] for edge in _BOX_EDGES for k in edge]
            shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
            region = bpy.context.region
            shader.uniform_float("viewportSize", (region.width, region.height))
            shader.uniform_float("lineWidth", 1.5)
            shader.uniform_float("color", (0.62, 0.64, 0.68, 0.75))
            gpu.state.blend_set("ALPHA")
            batch_for_shader(shader, "LINES", {"pos": lines}).draw(shader)
    finally:
        gpu.state.blend_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")


def _ensure_draw_handler():
    global _draw_handle
    if _draw_handle is None and not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def _remove_load_handler():
    # Match by name as well as identity: a source reload makes a new function
    # object, and the old one must not stay behind as a duplicate.
    for handler in list(bpy.app.handlers.load_pre):
        if (getattr(handler, "__module__", "") == __name__
                and getattr(handler, "__name__", "") == _stop_on_load.__name__):
            bpy.app.handlers.load_pre.remove(handler)


def register():
    _remove_load_handler()
    bpy.app.handlers.load_pre.append(_stop_on_load)


def unregister():
    stop_all()
    _remove_load_handler()
