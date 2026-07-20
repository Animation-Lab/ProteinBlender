"""Interactive Domain Maker session.

Replaces the old "Split Chain" modal popup with a dedicated split-window
workflow: a real, orbitable 3D viewport on the left (an isolated copy of the
chain being carved up) and the Domain Maker menu docked in that window's
N-panel on the right.

The user first picks how many domains to build, presses *Build Domains* to
lay out that many contiguous residue ranges, tweaks each range (watching the
active domain update live in the viewport), and finally presses *Create
Domains* to commit them through the same molecule model the old split used.

Blender genuinely cannot host a live viewport inside an ``invoke_props_dialog``
popup, so the "3D view attached to the menu" is implemented as a temporary
second window whose single 3D area carries the menu in its sidebar.
"""

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
    PointerProperty,
)

from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy
from ..utils.chain_utils import (
    chain_match_tokens,
    get_chain_objects,
    normalize_domain_residue_range,
)


# --------------------------------------------------------------------------- #
# Live preview
# --------------------------------------------------------------------------- #

def _find_res_range_node(obj):
    """Return (modifier, node) for the object's Select Res ID Range node.

    The isolated chain object carries a single geometry-nodes modifier whose
    tree contains a "Select Res ID Range" group node; driving its Min/Max
    inputs is exactly how the legacy split preview highlighted a range.
    """
    if not obj or not obj.modifiers:
        return None, None
    for modifier in obj.modifiers:
        if modifier.type == 'NODES' and modifier.node_group:
            for node in modifier.node_group.nodes:
                if (node.type == 'GROUP' and node.node_tree
                        and "Select Res ID Range" in node.node_tree.name):
                    return modifier, node
    return None, None


def _set_range(obj, min_val, max_val):
    """Push a residue range onto the object's Select Res ID Range node."""
    modifier, node = _find_res_range_node(obj)
    if not node:
        return False
    if "Min" in node.inputs:
        node.inputs["Min"].default_value = int(min_val)
    if "Max" in node.inputs:
        node.inputs["Max"].default_value = int(max_val)
    return True


def _tag_view3d_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def refresh_preview(context):
    """Isolate the active domain's residue range in the session viewport.

    Before the user builds any domains the whole chain is shown; afterwards the
    row selected in the menu drives the highlight, updating live as its Start/
    End are edited.
    """
    state = getattr(context.window_manager, "pb_domain_maker", None)
    if not state or not state.active:
        return
    obj = bpy.data.objects.get(state.preview_object)
    if not obj:
        return

    if state.built and len(state.domains) > 0:
        idx = max(0, min(state.active_index, len(state.domains) - 1))
        dom = state.domains[idx]
        _set_range(obj, dom.start, dom.end)
    else:
        _set_range(obj, state.chain_start, state.chain_end)

    if context.view_layer:
        context.view_layer.update()
    _tag_view3d_redraw()


def _on_range_update(self, context):
    refresh_preview(context)


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #

class PB_DomainRangeItem(PropertyGroup):
    """One planned domain: a name and an inclusive residue range."""
    name: StringProperty(name="Name", default="Domain")
    start: IntProperty(name="Start", default=1, min=1, update=_on_range_update)
    end: IntProperty(name="End", default=1, min=1, update=_on_range_update)


class PB_DomainMakerState(PropertyGroup):
    """Transient UI state for an in-progress Domain Maker session.

    Lives on the WindowManager so it is never written into the .blend file.
    """
    active: BoolProperty(default=False)

    # What is being split.
    item_id: StringProperty()
    molecule_id: StringProperty()
    chain_id: StringProperty()
    chain_name: StringProperty()
    chain_start: IntProperty(default=1)
    chain_end: IntProperty(default=1)

    # Build stage.
    num_domains: IntProperty(name="Number of Domains", default=4, min=1, max=50)
    built: BoolProperty(default=False)
    domains: CollectionProperty(type=PB_DomainRangeItem)
    active_index: IntProperty(default=0, update=_on_range_update)

    # Live-preview target (the isolated chain object + session window screen).
    preview_object: StringProperty()
    session_screen: StringProperty()
    finished: BoolProperty(default=False)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _resolve_chain_context(context, item_id):
    """Resolve the selected outliner item to (molecule, chain_id, range, obj).

    Returns a dict or None. Works for both a CHAIN row and a DOMAIN row (a
    domain row resolves to its parent chain, matching the old split popup).
    """
    scene = context.scene
    scene_manager = ProteinBlenderScene.get_instance()

    selected_item = None
    for item in scene.outliner_items:
        if item.item_id == item_id:
            selected_item = item
            break
    if not selected_item:
        return None

    if selected_item.item_type == 'CHAIN':
        molecule_id = selected_item.parent_id
        chain_id = selected_item.chain_id
        chain_name = selected_item.name
        min_val = selected_item.chain_start
        max_val = selected_item.chain_end
        molecule = scene_manager.molecules.get(molecule_id)
        chain_objects = get_chain_objects(molecule, selected_item) if molecule else []
        target_object = chain_objects[0] if chain_objects else None
    else:  # DOMAIN row -> split its parent chain
        parent_chain = None
        for chain_item in scene.outliner_items:
            if chain_item.item_id == selected_item.parent_id:
                parent_chain = chain_item
                break
        if not parent_chain:
            return None
        molecule_id = parent_chain.parent_id
        chain_id = parent_chain.chain_id
        chain_name = parent_chain.name
        min_val = parent_chain.chain_start
        max_val = parent_chain.chain_end
        molecule = scene_manager.molecules.get(molecule_id)
        chain_objects = get_chain_objects(molecule, parent_chain) if molecule else []
        target_object = chain_objects[0] if chain_objects else None

    if not molecule or not target_object:
        return None

    # Fall back to the molecule's own chain ranges when the outliner row has no
    # residue span recorded on it.
    if not (min_val and max_val and max_val >= min_val):
        rng = _chain_range_from_molecule(molecule, chain_id)
        if rng:
            min_val, max_val = rng

    min_val, max_val = normalize_domain_residue_range((min_val, max_val))

    return {
        "molecule": molecule,
        "molecule_id": molecule_id,
        "chain_id": chain_id,
        "chain_name": chain_name,
        "chain_start": min_val,
        "chain_end": max_val,
        "object": target_object,
    }


def _chain_range_from_molecule(molecule, chain_id):
    """Best-effort residue range for a chain from the molecule model."""
    if not hasattr(molecule, 'chain_residue_ranges') or not molecule.chain_residue_ranges:
        return None
    chain_id_str = str(chain_id)
    chain_id_int = int(chain_id_str) if chain_id_str.isdigit() else None
    if (chain_id_int is not None and hasattr(molecule, 'idx_to_label_asym_id_map')
            and chain_id_int in molecule.idx_to_label_asym_id_map):
        label = molecule.idx_to_label_asym_id_map[chain_id_int]
        if label in molecule.chain_residue_ranges:
            return molecule.chain_residue_ranges[label]
    if chain_id_str in molecule.chain_residue_ranges:
        return molecule.chain_residue_ranges[chain_id_str]
    return None


def _even_ranges(start, end, count):
    """Split [start, end] into `count` contiguous inclusive ranges."""
    count = max(1, count)
    total = end - start + 1
    if count >= total:
        # More domains than residues: one residue each until we run out.
        ranges = []
        for i in range(count):
            s = start + i
            if s > end:
                s = end
            ranges.append((s, s))
        return ranges
    base = total // count
    rem = total % count
    ranges = []
    cursor = start
    for i in range(count):
        size = base + (1 if i < rem else 0)
        s = cursor
        e = cursor + size - 1
        ranges.append((s, e))
        cursor = e + 1
    return ranges


# --------------------------------------------------------------------------- #
# Window management
# --------------------------------------------------------------------------- #

def seed_session(context, item_id):
    """Seed session state for `item_id` (chain/domain), without any windowing.

    Shared by the operator's ``invoke`` and by headless callers/tests: it
    resolves the chain, records its residue span and the object to preview, and
    marks the session active. Returns the resolved-context dict, or None if the
    item could not be resolved. The caller opens the window (or not).
    """
    state = context.window_manager.pb_domain_maker
    info = _resolve_chain_context(context, item_id)
    if info is None:
        return None

    span = max(1, info["chain_end"] - info["chain_start"] + 1)
    state.item_id = item_id
    state.molecule_id = info["molecule_id"]
    state.chain_id = str(info["chain_id"])
    state.chain_name = info["chain_name"]
    state.chain_start = info["chain_start"]
    state.chain_end = info["chain_end"]
    state.num_domains = min(max(2, state.num_domains or 2), span)
    state.built = False
    state.finished = False
    state.domains.clear()
    state.active_index = 0
    state.preview_object = info["object"].name
    state.session_screen = ""
    state.active = True
    return info


def _session_window(context):
    """Return the session window (by its screen name) if still open."""
    state = context.window_manager.pb_domain_maker
    if not state.session_screen:
        return None
    for window in context.window_manager.windows:
        if window.screen.name == state.session_screen:
            return window
    return None


def _open_session_window(context, target_object):
    """Open a second window, isolate the chain in it, and dock the menu."""
    wm = context.window_manager
    existing = {w.screen.name for w in wm.windows}
    bpy.ops.wm.window_new()
    new_window = None
    for window in wm.windows:
        if window.screen.name not in existing:
            new_window = window
            break
    if new_window is None:
        new_window = wm.windows[-1]

    screen = new_window.screen
    area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        area = screen.areas[0]
        area.type = 'VIEW_3D'
    space = area.spaces.active
    space.show_region_ui = True        # sidebar hosts the Domain Maker menu
    space.show_region_toolbar = False  # keep the left toolbar out of the way

    region = next((r for r in area.regions if r.type == 'WINDOW'), None)

    # Isolate the chain object in this window only (local view is per-space).
    view_layer = context.view_layer
    for obj in bpy.data.objects:
        obj.select_set(False)
    target_object.select_set(True)
    view_layer.objects.active = target_object

    if region is not None:
        try:
            with context.temp_override(window=new_window, area=area,
                                       region=region, screen=screen):
                bpy.ops.view3d.localview()
                bpy.ops.view3d.view_selected()
        except Exception as exc:  # pragma: no cover - viewport framing is best effort
            print(f"[Domain Maker] Could not frame session view: {exc}")

    return new_window


def _close_session_window(context):
    window = _session_window(context)
    if window is None:
        return
    try:
        with context.temp_override(window=window):
            bpy.ops.wm.window_close()
    except Exception as exc:  # pragma: no cover
        print(f"[Domain Maker] Could not close session window: {exc}")


def _restore_object_range(state):
    """Return the isolated chain object to showing its full residue span."""
    obj = bpy.data.objects.get(state.preview_object)
    if obj:
        _set_range(obj, state.chain_start, state.chain_end)


def _end_session(context, close_window=True):
    """Tear down a session: restore the chain, close the window, clear state."""
    state = context.window_manager.pb_domain_maker
    _restore_object_range(state)
    if close_window:
        _close_session_window(context)
    state.active = False
    state.built = False
    state.finished = True
    state.domains.clear()
    state.session_screen = ""
    state.preview_object = ""
    _tag_view3d_redraw()


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #

class PROTEINBLENDER_OT_domain_maker_session(Operator):
    """Open the interactive Domain Maker (real 3D view + menu)"""
    bl_idname = "proteinblender.domain_maker_session"
    bl_label = "Domain Maker"
    bl_options = {'REGISTER'}

    item_id: StringProperty()
    item_type: StringProperty()

    _timer = None

    def invoke(self, context, event):
        wm = context.window_manager
        state = wm.pb_domain_maker

        if state.active:
            self.report({'WARNING'}, "A Domain Maker session is already open")
            return {'CANCELLED'}

        info = seed_session(context, self.item_id)
        if info is None:
            self.report({'ERROR'}, "Could not resolve the selected chain")
            return {'CANCELLED'}

        _open_session_window(context, info["object"])
        state.session_screen = _newest_screen_name(context)
        refresh_preview(context)

        # Watch the session lifetime from the invoking (main) window.
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        state = context.window_manager.pb_domain_maker
        if event.type == 'TIMER':
            # Finished by a menu button, or the user closed the session window.
            if not state.active or _session_window(context) is None:
                self._finish(context)
                return {'FINISHED'}
        return {'PASS_THROUGH'}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        state = wm.pb_domain_maker
        if state.active:
            # Window was closed manually: restore without a redundant close.
            _end_session(context, close_window=_session_window(context) is not None)


def _newest_screen_name(context):
    """Screen name of the most recently opened (temp) window."""
    for window in reversed(context.window_manager.windows):
        if window.screen.name.startswith("temp"):
            return window.screen.name
    return context.window_manager.windows[-1].screen.name


class PROTEINBLENDER_OT_domain_maker_build(Operator):
    """Lay out the requested number of contiguous domains"""
    bl_idname = "proteinblender.domain_maker_build"
    bl_label = "Build Domains"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state = context.window_manager.pb_domain_maker
        if not state.active:
            return {'CANCELLED'}

        ranges = _even_ranges(state.chain_start, state.chain_end, state.num_domains)
        state.domains.clear()
        for i, (s, e) in enumerate(ranges):
            item = state.domains.add()
            item.name = f"Domain {i + 1}"
            item.start = s
            item.end = e
        state.built = True
        state.active_index = 0
        refresh_preview(context)
        return {'FINISHED'}


class PROTEINBLENDER_OT_domain_maker_select(Operator):
    """Make a domain row active (drives the live viewport highlight)"""
    bl_idname = "proteinblender.domain_maker_select"
    bl_label = "Select Domain"
    bl_options = {'REGISTER', 'INTERNAL'}

    index: IntProperty(default=0)

    def execute(self, context):
        state = context.window_manager.pb_domain_maker
        if 0 <= self.index < len(state.domains):
            state.active_index = self.index
            refresh_preview(context)
        return {'FINISHED'}


class PROTEINBLENDER_OT_domain_maker_create(Operator):
    """Create the planned domains and close the session"""
    bl_idname = "proteinblender.domain_maker_create"
    bl_label = "Create Domains"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        state = context.window_manager.pb_domain_maker
        if not state.active or not state.built:
            self.report({'WARNING'}, "Build domains first")
            return {'CANCELLED'}

        ranges = [(d.name, int(d.start), int(d.end)) for d in state.domains]
        problem = _validate_ranges(ranges, state.chain_start, state.chain_end)
        if problem:
            self.report({'ERROR'}, problem)
            return {'CANCELLED'}

        created = _commit_domains(context, state, ranges)
        # Restore the chain object range before it may be replaced, then close.
        _end_session(context, close_window=True)

        if not created:
            self.report({'ERROR'}, "No domains were created")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Created {created} domain(s)")
        return {'FINISHED'}


class PROTEINBLENDER_OT_domain_maker_cancel(Operator):
    """Discard the session without creating domains"""
    bl_idname = "proteinblender.domain_maker_cancel"
    bl_label = "Cancel"
    bl_options = {'REGISTER'}

    def execute(self, context):
        _end_session(context, close_window=True)
        return {'FINISHED'}


# --------------------------------------------------------------------------- #
# Validation + commit
# --------------------------------------------------------------------------- #

def _validate_ranges(ranges, chain_start, chain_end):
    """Return an error string if the planned ranges are invalid, else ''."""
    if not ranges:
        return "No domains to create"
    ordered = sorted(ranges, key=lambda r: r[1])
    for name, s, e in ordered:
        if s > e:
            return f"{name}: start {s} is past end {e}"
        if s < chain_start or e > chain_end:
            return f"{name}: {s}-{e} is outside chain range {chain_start}-{chain_end}"
    for (na, sa, ea), (nb, sb, eb) in zip(ordered, ordered[1:]):
        if sb <= ea:
            return f"{na} and {nb} overlap"
    return ""


def _commit_domains(context, state, ranges):
    """Create the planned domains on the molecule (mirrors split_domain)."""
    scene_manager = ProteinBlenderScene.get_instance()
    molecule = scene_manager.molecules.get(state.molecule_id)
    if not molecule:
        return 0

    chain_id = state.chain_id
    chain_tokens = chain_match_tokens(molecule, chain_id)

    # Snapshot for undo/redo safety, exactly like the destructive split path.
    scene_manager.refresh_domain_refs_before_destructive_op(state.molecule_id)

    # Capture the style of the chain's current (full-chain) domain so the new
    # domains inherit the look, then remove every existing domain on the chain.
    parent_style = None
    to_remove = []
    for domain_id, domain in molecule.domains.items():
        if hasattr(domain, 'chain_id') and str(domain.chain_id) in chain_tokens:
            if parent_style is None and hasattr(domain, 'style'):
                parent_style = domain.style
                if domain.object and (not parent_style or parent_style in ['ribbon', 'surface']):
                    try:
                        from ..panels.visual_setup_panel import get_object_style
                        actual = get_object_style(domain.object)
                        if actual:
                            parent_style = actual
                    except Exception:
                        pass
            to_remove.append(domain_id)

    for domain_id in to_remove:
        domain = molecule.domains.get(domain_id)
        if domain and getattr(domain, 'object', None):
            try:
                bpy.data.objects.remove(domain.object, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        molecule.domains.pop(domain_id, None)

    created_ids = []
    for name, start, end in ranges:
        ids = molecule._create_domain_with_params(
            chain_id, start, end, name, False, None
        )
        if ids:
            created_ids.extend(ids)
            if parent_style:
                for did in ids:
                    dom = molecule.domains.get(did)
                    if dom is not None:
                        dom.style = parent_style
                        if getattr(dom, 'object', None):
                            try:
                                from ..panels.visual_setup_panel import apply_style_to_object
                                apply_style_to_object(dom.object, parent_style)
                            except Exception:
                                pass

    if len(created_ids) >= 2:
        try:
            molecule.set_domain_split_pivots(bpy.context, created_ids, chain_id)
        except Exception as exc:  # pragma: no cover
            print(f"[Domain Maker] Could not set split pivots: {exc}")

    build_outliner_hierarchy(context)
    return len(created_ids)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

CLASSES = (
    PB_DomainRangeItem,
    PB_DomainMakerState,
    PROTEINBLENDER_OT_domain_maker_session,
    PROTEINBLENDER_OT_domain_maker_build,
    PROTEINBLENDER_OT_domain_maker_select,
    PROTEINBLENDER_OT_domain_maker_create,
    PROTEINBLENDER_OT_domain_maker_cancel,
)


def register_props():
    bpy.types.WindowManager.pb_domain_maker = PointerProperty(type=PB_DomainMakerState)


def unregister_props():
    if hasattr(bpy.types.WindowManager, "pb_domain_maker"):
        del bpy.types.WindowManager.pb_domain_maker
