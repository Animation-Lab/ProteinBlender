"""Pivot point operators: the presets, and the interactive Edit Pivot mode.

Two ways to move what a protein, chain or domain rotates about.

**Presets** - First / Center / Last - compute a position from the item's alpha
carbons and write it straight away.

**Edit Pivot** is a *mode*, not an action. One click drops a helper Empty on
the item's current pivot and hands the user the move gizmo; the next click on
the same button takes the helper's position as the new pivot and clears the
helper away. It is a mode because the pivot is chosen by dragging in the
viewport, which takes as long as it takes: nothing else may decide the
placement is over. That is why it lives on the outliner row rather than inside
an edit dialog, and why there is no "click away to confirm" - clicking away is
how a user orbits the view.

Being a mode, it *owns* the viewport while it is open: the helper is the only
selectable object in the scene, and nothing else is selected. Without that the
molecule is still sitting under the cursor, so a click aimed at the helper
lands on the protein instead - the Move gizmo jumps onto the molecule and the
next drag slides the whole thing across the scene rather than placing the
pivot, and the molecule's row is left ticked in the Protein Outliner long after
the session is over. Everything the mode takes (the selection and each
object's selectability, the active tool, the viewport gizmo flags, the 3D
cursor, the transform orientation and pivot point) is recorded on the way in
and handed back on the way out.

``molecule.toggle_pivot_edit`` (domains) and
``molecule.toggle_protein_pivot_edit`` (proteins) predate the row button and
still exist as the scripted entry points. All three now share the one session
below, so there is a single implementation of enter-and-leave and chains work
the same way the other two always did.
"""

import json

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from mathutils import Vector

from ..core import domain_space
from ..utils.scene_manager import ProteinBlenderScene

# The one helper Empty. Resolved by name at every point of use and never
# cached: the user can delete it from the outliner mid-session, and a held
# pointer to a freed object crashes Blender rather than raising.
PIVOT_HELPER = "PB_PivotHelper"

# Session bookkeeping, on the scene rather than on the operator or a module
# dict. An operator instance is gone the moment it returns, and module state
# does not survive the add-on reload that a source edit triggers - either way
# a half-finished session would strand its helper in the scene with no way to
# finish it. The scene outlives both, and saves.
PIVOT_EDIT_KEY = "pb_pivot_edit_key"          # what is being edited
PIVOT_EDIT_TARGETS = "pb_pivot_edit_objects"  # object names, comma-joined
# What the mode borrowed from the user and has to hand back.
PIVOT_EDIT_CURSOR = "pb_pivot_edit_cursor"
PIVOT_EDIT_ORIENTATION = "pb_pivot_edit_orientation"
PIVOT_EDIT_PIVOT_POINT = "pb_pivot_edit_pivot_point"
# The objects the mode made unselectable, JSON-encoded. Only the ones it
# actually changed, so an object the user had locked themselves stays locked.
PIVOT_EDIT_LOCKED = "pb_pivot_edit_locked"
# The active tool and each 3D viewport's gizmo flags, JSON-encoded.
PIVOT_EDIT_VIEW = "pb_pivot_edit_view"

# The gizmo flags the mode overwrites, in the order they are stored.
_GIZMO_FLAGS = ("show_gizmo", "show_gizmo_tool", "show_gizmo_object_translate",
                "show_gizmo_object_rotate", "show_gizmo_object_scale")


def pivot_edit_key(scene):
    """What has an Edit Pivot session open, or "" if nothing does.

    Self-healing: a session whose helper has been deleted (by the user, by an
    undo, by a file reload) is not a session any more, so the bookkeeping is
    dropped rather than left to light up a button that can no longer finish.
    """
    key = scene.get(PIVOT_EDIT_KEY, "")
    if not key:
        return ""
    if bpy.data.objects.get(PIVOT_HELPER) is None:
        _forget_pivot_edit(scene)
        return ""
    return key


def _forget_pivot_edit(scene):
    """Drop the session, releasing everything that can be released from here.

    The selection lock and the gizmo flags are plain RNA writes, so they are
    given back here rather than only in :func:`end_pivot_edit` - this also runs
    from ``pivot_edit_key``'s self-heal, and a scene left permanently
    unselectable because a helper was deleted by hand would be far worse than
    the leak it is healing. The active *tool* is the one thing that cannot be
    restored here: only ``wm.tool_set_by_id`` can set it, and the self-heal
    fires from panel draw code, where calling an operator is not allowed.
    """
    _unlock_scene_selection(scene)
    _restore_viewport_gizmos(scene)
    for key in (PIVOT_EDIT_KEY, PIVOT_EDIT_TARGETS, PIVOT_EDIT_CURSOR,
                PIVOT_EDIT_ORIENTATION, PIVOT_EDIT_PIVOT_POINT,
                PIVOT_EDIT_LOCKED, PIVOT_EDIT_VIEW):
        if key in scene:
            del scene[key]


def _view3d_areas(context=None):
    """Every 3D viewport on the current screen, in a stable order."""
    screen = getattr(context or bpy.context, "screen", None)
    if screen is None:
        return []
    return [area for area in screen.areas if area.type == 'VIEW_3D']


def _stash(scene, key, value):
    scene[key] = json.dumps(value)


def _unstash(scene, key, default):
    try:
        return json.loads(scene.get(key, "")) if key in scene else default
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Borrowing the viewport: the tool, the gizmos, and the selection itself
# --------------------------------------------------------------------------

def _borrow_viewport(context):
    """Record the active tool and gizmo flags, then switch to Move.

    Recorded *before* anything is changed so :func:`end_pivot_edit` can hand
    the viewport back exactly as it was found. Leaving the tool on Move means
    the Rotate tool a user was working with is silently replaced - and the
    forced object-translate gizmo then draws a move handle on every protein
    they select afterwards, which reads as the pivot gizmo following them
    around.
    """
    scene = context.scene
    areas = _view3d_areas(context)
    if not areas:
        return False

    tool = context.workspace.tools.from_space_view3d_mode('OBJECT',
                                                          create=False)
    _stash(scene, PIVOT_EDIT_VIEW, {
        "tool": tool.idname if tool is not None else None,
        "gizmos": [[getattr(area.spaces.active, flag) for flag in _GIZMO_FLAGS]
                   for area in areas],
    })
    return _activate_translation_gizmo(context)


def _activate_translation_gizmo(context):
    """Activate Move in every live 3D viewport with a valid WINDOW context."""
    screen = context.screen
    window = context.window
    if screen is None:
        return False

    activated = False
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = next((candidate for candidate in area.regions
                       if candidate.type == 'WINDOW'), None)
        if region is None:
            continue
        override = {'area': area, 'region': region}
        if window is not None:
            override['window'] = window
            override['screen'] = screen
        with context.temp_override(**override):
            result = bpy.ops.wm.tool_set_by_id(name="builtin.move")
            activated = activated or result == {'FINISHED'}

        space = area.spaces.active
        space.show_gizmo = True
        space.show_gizmo_tool = True
        space.show_gizmo_object_translate = True
        space.show_gizmo_object_rotate = False
        space.show_gizmo_object_scale = False
        area.tag_redraw()
    return activated


def _restore_viewport_gizmos(scene):
    """Put each 3D viewport's gizmo flags back as they were found."""
    stored = _unstash(scene, PIVOT_EDIT_VIEW, None) or {}
    for area, flags in zip(_view3d_areas(), stored.get("gizmos") or []):
        space = area.spaces.active
        for name, value in zip(_GIZMO_FLAGS, flags):
            setattr(space, name, bool(value))
        area.tag_redraw()


def _restore_active_tool(context):
    """Put the workspace tool back to whatever was active before the mode.

    Only callable from an operator - ``wm.tool_set_by_id`` is an operator, so
    this cannot run from ``pivot_edit_key``'s draw-time self-heal.
    """
    stored = _unstash(context.scene, PIVOT_EDIT_VIEW, None) or {}
    tool = stored.get("tool")
    if not tool:
        return
    window = context.window
    screen = context.screen
    for area in _view3d_areas(context):
        region = next((candidate for candidate in area.regions
                       if candidate.type == 'WINDOW'), None)
        if region is None:
            continue
        override = {'area': area, 'region': region}
        if window is not None:
            override['window'] = window
            override['screen'] = screen
        with context.temp_override(**override):
            bpy.ops.wm.tool_set_by_id(name=tool)
        area.tag_redraw()


def _lock_scene_selection(context, helper):
    """Make the helper the only thing in the scene a click can select.

    Edit Pivot is a mode, and this is what makes it one. Without it the
    molecule is still sitting under the cursor: a click meant for the helper
    lands on the protein, Blender moves the selection (and therefore the Move
    gizmo) onto it, and the next drag slides the whole molecule across the
    scene instead of placing the pivot.

    Objects the user had already locked are left out of the record, so
    unlocking on the way out gives back only what this took.
    """
    locked = []
    for obj in context.view_layer.objects:
        if obj.name == helper.name or obj.hide_select:
            continue
        obj.hide_select = True
        locked.append(obj.name)
    _stash(context.scene, PIVOT_EDIT_LOCKED, locked)


def _unlock_scene_selection(scene):
    for name in _unstash(scene, PIVOT_EDIT_LOCKED, []):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_select = False


def _deselect_everything(context):
    """Clear the viewport selection and the Protein Outliner together.

    Done by hand rather than through ``object.select_all``: this runs from a
    Properties-editor button and from headless tests, and a plain RNA write
    needs no context to poll against. Clearing the outliner rows here too
    means the checkboxes are right the instant the panel redraws, instead of
    up to a poll interval later - and at all in headless, where the
    selection-sync timer never runs.
    """
    view_layer = context.view_layer
    for obj in view_layer.objects:
        obj.select_set(False)
    view_layer.objects.active = None
    for item in context.scene.outliner_items:
        item.is_selected = False


def _apply_origin_to_cursor(obj, world_pos):
    """Move ``obj``'s origin to ``world_pos`` (world space).

    Delegates to ``core.domain_space``, which carries the pivot as a
    geometry-nodes input rather than baking it into mesh vertices. That
    keeps domain meshes shareable, and it means this touches only ``obj``
    by construction: there is no selection to isolate, because nothing
    operator-driven and scene-wide is involved any more.

    (This used to snapshot selection/active/mode/cursor and isolate ``obj``
    purely because ``bpy.ops.object.origin_set`` operates on *every*
    selected object — so the First/Center/Last buttons would otherwise
    also move the parent protein's and sibling domains' origins whenever
    they happened to be selected, which is exactly the state the outliner
    leaves behind after toggling a PROTEIN row.)

    Also stamps ``initial_matrix_local`` so Reset Transform respects the
    new pivot.
    """
    if not domain_space.set_pivot_world(obj, world_pos):
        return False
    bpy.context.view_layer.update()
    obj["initial_matrix_local"] = [list(row) for row in obj.matrix_local]
    return True


def _chain_index_for_item(scene, item):
    """Return the int chain index a CHAIN or DOMAIN outliner row belongs to.

    The protein outliner identifies chains by their numeric index in
    item_ids of the form ``<mol>_chain_<idx>``; DOMAIN rows carry the
    chain LETTER on their object name but their ``parent_id`` points at
    the chain row, so we resolve through the hierarchy rather than
    parsing names. This sidesteps two trap doors: (1) author chain IDs
    are letters that don't map to indices via alphabet math when the
    chain set is gapped (chain T is index 9 in a 10-chain assembly, not
    19), and (2) MN copies the full protein mesh into every domain
    object, so every chain's atoms are present in a domain's mesh and
    must be filtered by index — not by name.
    Returns None if the hierarchy doesn't fit the convention.
    """
    if item.item_type == 'DOMAIN':
        parent_id = item.parent_id or ""
        item = next((it for it in scene.outliner_items
                     if it.item_id == parent_id), None)
        if item is None:
            return None
    if item.item_type != 'CHAIN':
        return None
    item_id = item.item_id or ""
    if "_chain_" in item_id:
        try:
            return int(item_id.rsplit("_chain_", 1)[-1])
        except ValueError:
            return None
    return None


def _collect_chain_filtered_alphas(targets):
    """Return ``[(world_pos, order_key), ...]`` for every alpha carbon
    across ``targets``, optionally filtered to one chain per target.

    ``order_key`` is ``(chain_idx, res_id)``, so sorting it walks the
    structure the way a sequence does: chain by chain, residue by residue.
    A chain- or domain-scoped read is filtered to a single chain, which
    makes the first element constant and the key equivalent to the plain
    residue number it used to be. A whole-protein read is not filtered,
    and there the chain component is what makes "first residue" mean the
    N-terminus of the first chain rather than the lowest residue number
    anywhere in the assembly.

    ``targets``: iterable of ``(obj, chain_idx, residue_start, residue_end)``.
    When chain_idx is set
    we restrict to atoms whose ``chain_id`` attribute equals chain_idx —
    essential because every domain object shares the whole molecule's
    mesh, so every chain's atoms live in a domain's mesh. Without
    filtering, an "any alpha carbon" pick would always land on chain 0
    residue 1 and First/Last would pick from the wrong chain.

    Positions come from the *raw* mesh, so they must be mapped with
    ``domain_space.local_to_world`` rather than ``obj.matrix_world @ co``:
    the pivot is applied inside geometry nodes, and raw mesh coordinates
    have not been through it.

    Skips objects without ``is_alpha_carbon``. If ``res_id`` is missing,
    falls back to a per-position running counter so first/last still
    have a stable ordering.
    """
    import numpy as np

    results = []
    counter = 0
    for obj, chain_idx, residue_start, residue_end in targets:
        if obj is None:
            continue
        mesh = getattr(obj, "data", None)
        if mesh is None or not hasattr(mesh, "attributes"):
            continue
        if "is_alpha_carbon" not in mesh.attributes:
            continue
        try:
            n = len(mesh.vertices)
            is_alpha = np.zeros(n, dtype=bool)
            mesh.attributes["is_alpha_carbon"].data.foreach_get("value", is_alpha)

            mask = is_alpha
            chain_ids = None
            if "chain_id" in mesh.attributes:
                chain_ids = np.zeros(n, dtype=np.int32)
                mesh.attributes["chain_id"].data.foreach_get("value", chain_ids)
                if chain_idx is not None:
                    mask = is_alpha & (chain_ids == chain_idx)

            # Domain objects share the parent molecule's complete raw mesh;
            # their visible residue range is applied later by geometry nodes.
            # Filtering only by chain therefore makes a 1-50 domain's Last
            # pivot land on the chain terminus. Apply the outliner domain bounds
            # to the raw-mesh alpha carbons before choosing First/Center/Last.
            res_ids_arr = None
            if "res_id" in mesh.attributes:
                res_ids_arr = np.zeros(n, dtype=np.int32)
                mesh.attributes["res_id"].data.foreach_get("value", res_ids_arr)
                if residue_start is not None:
                    mask = mask & (res_ids_arr >= residue_start)
                if residue_end is not None:
                    mask = mask & (res_ids_arr <= residue_end)

            positions = np.zeros(n * 3)
            mesh.vertices.foreach_get("co", positions)
            positions = positions.reshape(-1, 3)
            alpha_positions = positions[mask]
            if len(alpha_positions) == 0:
                continue

            world = domain_space.local_to_world_many(obj, alpha_positions)

            if res_ids_arr is not None:
                alpha_res_ids = res_ids_arr[mask]
                alpha_chains = (chain_ids[mask] if chain_ids is not None
                                else np.zeros(len(alpha_res_ids), dtype=np.int32))
                for pos, cid, rid in zip(world, alpha_chains, alpha_res_ids):
                    results.append((Vector(pos.tolist()), (int(cid), int(rid))))
            else:
                for pos in world:
                    counter += 1
                    results.append((Vector(pos.tolist()), (0, counter)))
        except Exception as e:
            print(f"Error collecting alpha carbons for {obj.name}: {e}")

    return results


def _resolve_pivot_targets(scene, selected_items):
    """Map rows to ``[(obj, chain_idx, range_start, range_end), ...]``.

    Skips rows that aren't CHAIN/DOMAIN, lack an ``object_name``, or
    whose object no longer exists in bpy.data.
    """
    targets = []
    for item in selected_items:
        if item.item_type not in ('DOMAIN', 'CHAIN'):
            continue
        if not item.object_name:
            continue
        obj = bpy.data.objects.get(item.object_name)
        if obj is None:
            continue
        residue_start = residue_end = None
        if item.item_type == 'DOMAIN':
            # These fields are populated directly from Domain.start/end when
            # the outliner hierarchy is built, and copied to puppet references.
            # Zero is the PropertyGroup sentinel for "not a domain range".
            start = int(getattr(item, 'domain_start', 0))
            end = int(getattr(item, 'domain_end', 0))
            if start > 0 and end >= start:
                residue_start, residue_end = start, end
        targets.append((obj, _chain_index_for_item(scene, item),
                        residue_start, residue_end))
    return targets


def find_row(scene, item_id):
    """The outliner row with this item_id, or None."""
    return next((it for it in scene.outliner_items if it.item_id == item_id),
                None)


def row_objects(context, row):
    """Every object the row draws through.

    A DOMAIN row owns one object. A CHAIN row owns one when it is whole and
    one per domain once it has been split - which is why this goes through
    ``get_chain_objects`` rather than reading ``object_name``: a split chain
    has no single backing object and its row leaves that field empty. A
    PROTEIN row owns the molecule mesh *and* every domain hanging off it.

    This is the set a colour or a style has to reach. It is **not** the set a
    pivot may be written to - see :func:`row_pivot_objects`.

    Ordering is stable and duplicate-free (keyed by name, because a ``bpy``
    struct is a fresh wrapper on every access and cannot be put in a set).
    """
    from ..utils.chain_utils import get_chain_objects

    scene_manager = ProteinBlenderScene.get_instance()
    found = {}

    def keep(obj):
        if obj is not None and obj.name not in found:
            found[obj.name] = obj

    if row.item_type in ('PROTEIN', 'DNA_RNA'):
        molecule = scene_manager.molecules.get(row.item_id)
        if molecule is not None:
            keep(getattr(molecule, 'object', None))
            for domain in getattr(molecule, 'domains', {}).values():
                keep(getattr(domain, 'object', None))
    elif row.item_type == 'CHAIN':
        molecule = scene_manager.molecules.get(row.parent_id)
        for obj in get_chain_objects(molecule, row):
            keep(obj)
    elif row.item_type == 'DOMAIN':
        if row.object_name:
            keep(bpy.data.objects.get(row.object_name))

    return list(found.values())


def row_pivot_objects(context, row):
    """The objects whose pivot the row's controls may write - a narrower set.

    For a chain or a domain it is everything the row draws. For a PROTEIN it
    is **only the molecule object**, even though the protein draws through its
    domains, and for two reasons:

    * every chain domain is *parented* to the molecule object, so the protein
      already rotates as one about that object's origin. That origin is what
      "the protein's pivot" means; the domains need no pivot of their own for
      it to work.
    * writing it to each domain as well silently overwrites the pivot the user
      set on that domain from its own row.

    (Rehoming the parent's origin would still drag its children, which is what
    made the whole molecule slide across the scene. That part is fixed in
    ``domain_space.set_pivot_world``, which holds children still.)
    """
    if row.item_type in ('PROTEIN', 'DNA_RNA'):
        molecule = ProteinBlenderScene.get_instance().molecules.get(row.item_id)
        obj = getattr(molecule, 'object', None) if molecule is not None else None
        if obj is not None:
            return [obj]
        # No molecule object to hang the pivot on. Its domains are then
        # unparented, so they *are* the protein and each takes the pivot.
    return row_objects(context, row)


def _row_alpha_source(context, row, objects):
    """The ``(obj, chain_idx, start, end)`` tuple to read alpha carbons from
    when computing one shared pivot for ``row``.

    Every molecule and domain object shares the parent molecule's complete
    mesh, so any one of them can answer for the whole row; the first is used
    so the answer does not depend on which domain happens to come back first
    from a dict. What differs is the *filter*: a protein reads unfiltered, a
    chain restricts to its own chain index, and a domain narrows further to
    its residue span.
    """
    if not objects:
        return None
    if row.item_type in ('PROTEIN', 'DNA_RNA'):
        return (objects[0], None, None, None)

    residue_start = residue_end = None
    if row.item_type == 'DOMAIN':
        start = int(getattr(row, 'domain_start', 0))
        end = int(getattr(row, 'domain_end', 0))
        if start > 0 and end >= start:
            residue_start, residue_end = start, end
    return (objects[0], _chain_index_for_item(context.scene, row),
            residue_start, residue_end)


def _pivot_position(mode, source, fallback_obj):
    """Where ``mode`` puts the pivot for one alpha-carbon read, or None."""
    alphas = _collect_chain_filtered_alphas([source])
    if alphas:
        if mode == 'FIRST':
            # min() returns the first occurrence on ties — matches np.argmin.
            return min(alphas, key=lambda pair: pair[1])[0]
        if mode == 'LAST':
            return max(alphas, key=lambda pair: pair[1])[0]
        # All alpha carbons have the same atomic mass (12.01), so a
        # mass-weighted centroid collapses to a simple mean.
        return sum((pos for pos, _ in alphas), Vector()) / len(alphas)

    if mode != 'CENTER':
        return None
    bbox_pts = [fallback_obj.matrix_world @ Vector(corner)
                for corner in fallback_obj.bound_box]
    if not bbox_pts:
        return None
    return sum(bbox_pts, Vector()) / len(bbox_pts)


# What each mode is called when it fails, and in the report on success.
_MODE_LABELS = {
    'FIRST': ("first residue", "Could not find alpha carbons"),
    'LAST': ("last residue", "Could not find alpha carbons"),
    'CENTER': ("center", "Could not calculate center"),
}


def run_pivot_mode(operator, context, mode):
    """Body shared by the First / Center / Last operators.

    Two routes in. With ``item_id`` set the operator acts on that one
    outliner row and gives everything the row owns a *single* shared pivot,
    which is what "set the pivot for this protein" has to mean when the
    protein is a dozen separate domain objects. Without it the operator falls
    back to the outliner selection and treats each chain or domain
    independently, exactly as it always has. PROTEIN rows stay excluded from
    the selection route on purpose: toggling a protein row also selects every
    chain and domain under it, so honouring both would have the per-chain
    pivots immediately overwrite the protein-wide one.
    """
    scene = context.scene
    label, empty_message = _MODE_LABELS[mode]

    # Read before the session is closed: closing it clears the outliner, which
    # is where the no-item_id route reads its targets from.
    selected_items = [it for it in scene.outliner_items if it.is_selected]

    # A preset supersedes a hand placement in progress, so the helper goes
    # away *without* committing - otherwise it would still be sitting there
    # ready to overwrite the preset on the next click of Edit Pivot.
    if pivot_edit_key(scene):
        end_pivot_edit(context, commit=False)

    if operator.item_id:
        row = find_row(scene, operator.item_id)
        if row is None:
            operator.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        objects = row_pivot_objects(context, row)
        source = _row_alpha_source(context, row, objects)
        if source is None:
            operator.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        jobs = [(source, objects)]
    else:
        if not selected_items:
            operator.report({'WARNING'}, "No items selected")
            return {'CANCELLED'}
        targets = _resolve_pivot_targets(scene, selected_items)
        if not targets:
            operator.report({'WARNING'}, "No valid objects found")
            return {'CANCELLED'}
        jobs = [(target, [target[0]]) for target in targets]

    applied = 0
    for source, objects in jobs:
        pivot_pos = _pivot_position(mode, source, source[0])
        if pivot_pos is None:
            continue
        for obj in objects:
            if _apply_origin_to_cursor(obj, pivot_pos):
                applied += 1
    if not applied:
        operator.report({'WARNING'}, empty_message)
        return {'CANCELLED'}

    operator.report({'INFO'}, f"Set pivot to {label} for {applied} object(s)")
    return {'FINISHED'}


class _PivotModeOperator:
    """Shared property surface for the First / Center / Last operators.

    Deliberately not an ``Operator`` subclass: it is a mixin that is never
    registered, and a bare unregistered Operator subclass trips the
    repository contract that every first-party operator appears in a CLASSES
    inventory. Blender collects property annotations across the whole MRO, so
    ``item_id`` still registers on each concrete operator below.
    """

    item_id: StringProperty(
        name="Item",
        description="Outliner row to act on. Left empty the operator falls "
                    "back to the outliner selection",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )


class PROTEINBLENDER_OT_set_pivot_first(_PivotModeOperator, Operator):
    """Set pivot point to first residue (N-terminal)"""
    bl_idname = "proteinblender.set_pivot_first"
    bl_label = "Set Pivot to First Residue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return run_pivot_mode(self, context, 'FIRST')


class PROTEINBLENDER_OT_set_pivot_last(_PivotModeOperator, Operator):
    """Set pivot point to last residue (C-terminal)"""
    bl_idname = "proteinblender.set_pivot_last"
    bl_label = "Set Pivot to Last Residue"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return run_pivot_mode(self, context, 'LAST')


class PROTEINBLENDER_OT_set_pivot_center(_PivotModeOperator, Operator):
    """Set pivot point to geometric center"""
    bl_idname = "proteinblender.set_pivot_center"
    bl_label = "Set Pivot to Center"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return run_pivot_mode(self, context, 'CENTER')


def _redraw(context, area_types=frozenset({'PROPERTIES', 'VIEW_3D'})):
    """Redraw the given editors, headless-safe (context.screen can be None)."""
    screen = getattr(context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            if area.type in area_types:
                area.tag_redraw()
        return
    for window in getattr(context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type in area_types:
                area.tag_redraw()


# --------------------------------------------------------------------------
# Edit Pivot: the interactive mode
# --------------------------------------------------------------------------

def begin_pivot_edit(context, key, objects):
    """Open an Edit Pivot session on ``objects`` and drop the helper.

    The helper starts on the first target's current origin, which is where the
    pivot is now - so a user who opens the mode and closes it again without
    dragging changes nothing.

    Everything the mode borrows from the user (the 3D cursor, the transform
    orientation, the transform pivot point, the active tool, the viewport
    gizmo flags and the rest of the scene's selectability) is recorded first
    and handed back by :func:`end_pivot_edit`. Leaving a scene in Global/Median
    when the user had it in Local/3D-Cursor is the sort of change nobody
    connects to the button they pressed three actions ago.
    """
    scene = context.scene
    if not objects:
        return None

    # Any previous helper is a leftover, not a session - pivot_edit_key would
    # have found it. Clear it so two can never be on screen at once.
    stale = bpy.data.objects.get(PIVOT_HELPER)
    if stale is not None:
        bpy.data.objects.remove(stale, do_unlink=True)

    scene[PIVOT_EDIT_CURSOR] = list(scene.cursor.location)
    scene[PIVOT_EDIT_ORIENTATION] = scene.transform_orientation_slots[0].type
    scene[PIVOT_EDIT_PIVOT_POINT] = context.tool_settings.transform_pivot_point

    context.view_layer.update()
    helper = bpy.data.objects.new(PIVOT_HELPER, None)
    # ARROWS rather than SPHERE: a sphere Empty draws three wire circles that
    # read as a rotation gizmo sitting beside the Move arrows.
    helper.empty_display_type = 'ARROWS'
    helper.empty_display_size = 1.0
    helper.show_in_front = True
    helper.hide_select = False
    helper.color = (1.0, 0.5, 0.0, 1.0)
    helper.location = objects[0].matrix_world.translation.copy()
    context.collection.objects.link(helper)

    scene[PIVOT_EDIT_KEY] = key
    scene[PIVOT_EDIT_TARGETS] = ','.join(obj.name for obj in objects)

    _deselect_everything(context)
    _lock_scene_selection(context, helper)
    helper.select_set(True)
    context.view_layer.objects.active = helper

    scene.transform_orientation_slots[0].type = 'GLOBAL'
    context.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    # Headless has no screen and therefore no gizmo to activate; the session
    # itself works fine without one, which is what makes it testable offline.
    if getattr(context, "screen", None) is not None:
        _borrow_viewport(context)

    for obj in objects:
        obj["is_pivot_editing"] = True
    return helper


def end_pivot_edit(context, commit=True):
    """Close the open session. Returns how many objects took the new pivot.

    ``commit`` is what the second button click does: whatever the helper is
    sitting on becomes the pivot of every object in the session. Every object,
    one position - so a protein, or a chain that has been split into domains,
    ends up swinging about the single point the user placed.

    The mode leaves nothing selected. It began by clearing the selection, so
    ending with it clear is the symmetric answer, and it is the only one that
    holds whatever happened in between: a session that ended with the molecule
    ticked in the Protein Outliner left the user with a selection they never
    made.
    """
    scene = context.scene
    helper = bpy.data.objects.get(PIVOT_HELPER)
    position = helper.matrix_world.translation.copy() if helper else None

    applied = 0
    if commit and position is not None:
        for name in (scene.get(PIVOT_EDIT_TARGETS, "") or "").split(','):
            obj = bpy.data.objects.get(name) if name else None
            if obj is None:
                continue
            if _apply_origin_to_cursor(obj, position):
                applied += 1

    for name in (scene.get(PIVOT_EDIT_TARGETS, "") or "").split(','):
        obj = bpy.data.objects.get(name) if name else None
        if obj is not None and "is_pivot_editing" in obj:
            del obj["is_pivot_editing"]

    if helper is not None:
        bpy.data.objects.remove(helper, do_unlink=True)

    if PIVOT_EDIT_CURSOR in scene:
        scene.cursor.location = Vector(scene[PIVOT_EDIT_CURSOR])
    if PIVOT_EDIT_ORIENTATION in scene:
        scene.transform_orientation_slots[0].type = scene[PIVOT_EDIT_ORIENTATION]
    if PIVOT_EDIT_PIVOT_POINT in scene:
        context.tool_settings.transform_pivot_point = scene[PIVOT_EDIT_PIVOT_POINT]

    # Before _forget_pivot_edit, which drops the record this reads.
    _restore_active_tool(context)
    _forget_pivot_edit(scene)
    # After the unlock inside _forget_pivot_edit: a locked object is not
    # selected, but it is also not the outliner's business to still show it as
    # though it were.
    _deselect_everything(context)
    return applied


def toggle_pivot_edit(operator, context, key, objects):
    """The shared body: one click in, the next click out.

    A click while *another* item's session is open closes that one first,
    committing it. Two helpers on screen would be ambiguous, and silently
    discarding the first item's placement would be worse.
    """
    scene = context.scene
    open_key = pivot_edit_key(scene)

    if open_key == key:
        applied = end_pivot_edit(context, commit=True)
        operator.report({'INFO'}, f"Pivot set on {applied} object(s)")
        _redraw(context)
        return {'FINISHED'}

    if open_key:
        end_pivot_edit(context, commit=True)

    if not objects:
        operator.report({'WARNING'}, "No valid objects found")
        return {'CANCELLED'}

    if begin_pivot_edit(context, key, objects) is None:
        operator.report({'WARNING'}, "Could not start the pivot helper")
        return {'CANCELLED'}

    operator.report(
        {'INFO'},
        "Move the pivot helper, then click Edit Pivot again to apply.")
    _redraw(context)
    return {'FINISHED'}


class PROTEINBLENDER_OT_set_pivot_custom(Operator):
    """Move this item's pivot by hand. Click again to apply it"""
    bl_idname = "proteinblender.set_pivot_custom"
    bl_label = "Edit Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    item_id: StringProperty(
        name="Item",
        description="Outliner row to act on. Left empty the operator falls "
                    "back to the outliner selection",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def description(cls, context, properties):
        key = getattr(properties, "item_id", "")
        if key and pivot_edit_key(context.scene) == key:
            return "Apply the pivot where you left the helper, and finish"
        return "Move this item's pivot by hand. Click again to apply it"

    def execute(self, context):
        scene = context.scene
        key = self.item_id
        if key:
            row = find_row(scene, key)
            objects = row_pivot_objects(context, row) if row is not None else []
        else:
            # No row named: fall back to the outliner selection, keyed so the
            # toggle still closes the session it opened.
            key = "__selection__"
            objects = _selection_pivot_objects(scene)
        return toggle_pivot_edit(self, context, key, objects)


def _selection_pivot_objects(scene):
    """The chain/domain objects the outliner selection resolves to.

    The fallback for an Edit Pivot started without an explicit row, kept so
    the operator stays driveable from a script or a menu.
    """
    objects = {}
    for item in scene.outliner_items:
        if not item.is_selected:
            continue
        if item.item_type not in ('DOMAIN', 'CHAIN'):
            continue
        obj = bpy.data.objects.get(item.object_name) if item.object_name else None
        if obj is not None:
            objects[obj.name] = obj
    return list(objects.values())


def set_object_origin_static(obj, new_origin):
    """Module-level wrapper retained for external callers; delegates to
    the shared isolation-safe helper."""
    _apply_origin_to_cursor(obj, new_origin)
