"""The Domain Splitter dialog - edit a chain's name and its domain layout.

Opened from the pencil button on a chain row in the Protein Outliner. The
dialog edits a *desired layout* (a list of named residue ranges) and hands it
to :mod:`core.domain_layout`, which reconciles it against the chain's current
domains rather than rebuilding them - see that module for why that matters.

The layout is kept **contiguous**: the rows never gap or overlap in the middle.
That is what makes the boundaries directly draggable - moving one domain's
start is the same edit as moving the previous domain's end, so the dialog
adjusts the neighbour to match instead of leaving the user to keep two numbers
in sync by hand.

Pulling the first domain's start off the beginning of the chain (or the last
domain's end off the end) leaves a stretch with no owner. That stretch is shown
as its own adjuster - a grid line above the first row, or below the last - and
`execute` turns it into a real domain.

The adjuster is drawn from plain operator properties, **not** from a row added
to the collection, and that is load-bearing rather than a shortcut. A row added
ahead of the one being dragged shifts it, and every row after it, down by one,
while Blender's number widget stays bound to the position. From the next drag
step on the user is dragging the row that was just inserted, which sits at the
chain's edge and has nowhere to go, so the drag dies one residue in and leaves
a one-residue domain behind. That happens whenever the row is added - on the
first edit, or on a timer once the value settles, since a real drag pauses for
longer than any sane debounce. Operator properties have no such problem.

While a range is being edited the viewport ghosts everything except the domain
being sized, so the user can see the piece they are defining instead of
guessing at residue numbers. The domain under the cursor is drawn solid, in
the colour its row carries; the rest of the chain - and the rest of the scene,
the whole protein included - stays visible but ghosted, so the piece being
sized is read against everything it lives amongst rather than floating on its
own. Only objects that cannot wear a ghost material are hidden instead. The
residue ranges, materials, colours and visibility this touches are all
restored when the dialog closes, whether it is confirmed or cancelled.

Nothing here mutates the domain model. `draw()` only reads, the row buttons
only touch the dialog's own rows, and the model is changed once, in `execute`.

The row buttons reach the live modal operator through ``_active_instance``. A
modal dialog is not in ``wm.operators``, so a button inside it cannot address
the instance any other way; this is the same workaround ``keyframe_operators``
uses.
"""

from __future__ import annotations

import colorsys
import json

import bpy
from bpy.props import (CollectionProperty, FloatVectorProperty, IntProperty,
                       StringProperty)
from bpy.types import Operator, PropertyGroup

from ..core import domain_layout
from ..utils.chain_utils import (chain_author_id, chain_token_from_item,
                                 default_domain_name, is_default_domain_name)
from ..utils.scene_manager import ProteinBlenderScene
from .visual_edit import VisualEditMixin

# Blender caps how tall a dialog can usefully get; past this the row list stops
# being readable and the user is better served splitting in stages.
MAX_DOMAINS = 32

# Preview bookkeeping lives on the scene rather than the operator instance so a
# preview can still be torn down if the dialog dies without running execute()
# or cancel() - otherwise the user would be left staring at a scene with
# everything but one domain hidden and no way to know why.
_PREVIEW_OBJECT = "pb_splitter_preview_object"
_PREVIEW_MODIFIER = "pb_splitter_preview_modifier"
_PREVIEW_NODE = "pb_splitter_preview_node"
# Everything the preview changed on an object, captured the first time that
# object is touched and restored verbatim afterwards:
# {object_name: {"range": [min, max], "material": name_or_"", "color": rgba}}.
# One map rather than one per property so an object is always put back whole,
# and so switching which domain is being sized still restores the others.
_PREVIEW_STATE = "pb_splitter_preview_state"
_PREVIEW_HIDDEN = "pb_splitter_preview_hidden"
# Objects outside the edited chain that were ghosted in place rather than
# hidden: {object_name: original_material_name}. Kept apart from
# _PREVIEW_STATE because these objects have no residue-range node to capture -
# the only thing borrowed from them is the material on their Style node.
_PREVIEW_GHOSTED = "pb_splitter_preview_ghosted"
# Objects the preview had to invent, because the domains they stand for do not
# exist yet. {object_name: True}; all of them are deleted on restore.
_PREVIEW_TEMPS = "pb_splitter_preview_temps"
_TEMP_PREFIX = "PB Splitter Preview "

# Object types worth ghosting (or, failing that, hiding) while a domain is
# sized. Cameras, lights and the puppet controller Empties are deliberately
# left alone: hiding the lights would just darken the very thing the user is
# trying to look at.
_ISOLATABLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}

# Per-surface opacity for the rest of the chain while one domain is sized.
#
# Much lower than the ~0.2 the finished effect looks like, and deliberately so.
# A space-filling chain stacks 20-odd sphere surfaces along any given view ray,
# and each one blends again, so per-surface alpha compounds: at 0.2 the chain
# still renders at 68% of its opaque brightness, which reads as "flat", not as
# "behind". Measured against an opaque reference of the same domain in a live
# Material Preview viewport, 0.1 with `show_transparent_back` off lands at 25%
# - dim enough to recede, solid enough to keep the chain's shape legible.
GHOST_ALPHA = 0.1

# Appended to the name of the material a ghosted domain normally wears.
_GHOST_SUFFIX = " (PB ghost)"


# Sentinels for the two grid lines that are not backed by a row: the stretches
# of chain before the first row and after the last one.
EDGE_HEAD = -1
EDGE_TAIL = -2


def grid_line_number(index: int, has_head: bool, row_count: int = 0) -> int:
    """The number shown in a grid line's index column, 1-based, top to bottom.

    The grid lists the chain in residue order: an optional leading stretch
    (the "head" edge), then the rows, then an optional trailing stretch (the
    "tail" edge). Edge lines are domains too - they are created on OK - so
    they are counted like any other line rather than flagged with a marker.

    ``index`` is a row's index in ``self.rows``; pass ``EDGE_HEAD`` or
    ``EDGE_TAIL`` for the edge lines (``row_count`` matters only for the
    tail, which comes after every row).
    """
    if index == EDGE_HEAD:
        return 1
    offset = 2 if has_head else 1
    if index == EDGE_TAIL:
        return row_count + offset
    return index + offset


def grid_line_total(row_count: int, has_head: bool, has_tail: bool) -> int:
    """How many lines the grid shows: its rows plus whichever edges are there.

    Every line becomes a domain on OK, so this is also how many domains the
    chain ends up with - which is what the header's count must report, or it
    contradicts the numbered lines directly beneath it.
    """
    return max(1, row_count + int(has_head) + int(has_tail))


def _active():
    return PROTEINBLENDER_OT_edit_chain_domains._active_instance


def _author_chain_label(molecule, chain_token, specs):
    """The author chain letter ("A") for a chain the outliner calls "2".

    Default domain names read "Chain A: 1-248", so they need the letter a user
    recognises, not the row's numeric index. An existing domain already stores
    the letter; otherwise fall back to the molecule's own index->letter map.
    """
    for spec in specs:
        domain = molecule.domains.get(spec.domain_id)
        letter = getattr(domain, "chain_id", None)
        if letter:
            return str(letter)
    return chain_author_id(molecule, chain_token)


# Dialog edit state. Module-level rather than attributes on the operator
# because Blender does not expose a plain (non-RNA) class attribute through an
# operator *instance* inside a property update callback - `instance.suspended`
# raises AttributeError even with `suspended = False` on the class. Only one
# Domain Splitter can be open at a time (it is modal), so a single set of
# module state is exactly right.
_state = {
    # Guards the update callbacks against re-entering while the dialog is
    # rewriting its own rows. Without it, adjusting a neighbour's boundary
    # fires that neighbour's callback, which adjusts the next one, and a single
    # click cascades down the whole chain.
    "suspended": False,
}


class _Suspend:
    """Context manager for the re-entrancy guard."""

    def __enter__(self):
        _state["suspended"] = True

    def __exit__(self, *exc_info):
        _state["suspended"] = False
        return False


# ---------------------------------------------------------------------------
# Viewport preview
#
# Module-level and scene-driven rather than methods on the dialog, for two
# reasons: a preview left behind by a dialog that died without closing can be
# cleared by anyone holding the scene, and the isolate/restore pair can be
# exercised directly by tests (a modal dialog cannot be driven headlessly, and
# an isolation that fails to restore leaves the user staring at an apparently
# empty scene).
# ---------------------------------------------------------------------------

def _range_node(obj):
    """The (modifier, node) pair driving a domain object's residue range."""
    if obj is None:
        return None, None
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        for node in modifier.node_group.nodes:
            if (node.type == 'GROUP' and node.node_tree
                    and "Select Res ID Range" in node.node_tree.name):
                return modifier, node
    return None, None


def _preview_node(context):
    """Re-resolve the range node of the domain currently being sized.

    Pointers into a node collection cannot be cached across edits, so the
    bookkeeping stores names and this resolves them at point of use.
    """
    scene = context.scene
    obj = bpy.data.objects.get(scene.get(_PREVIEW_OBJECT, ""))
    if obj is None:
        return None
    modifier = obj.modifiers.get(scene.get(_PREVIEW_MODIFIER, ""))
    if modifier is None or not modifier.node_group:
        return None
    return modifier.node_group.nodes.get(scene.get(_PREVIEW_NODE, ""))


def _style_material_socket(obj):
    """The Style node's Material input - what a domain is shaded with."""
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        for node in modifier.node_group.nodes:
            if (node.type == 'GROUP' and node.node_tree
                    and "Style" in node.node_tree.name):
                return node.inputs.get("Material")
    return None


def _color_sockets(obj):
    """The sockets holding a domain's colour, on whichever node drives it.

    Two node layouts reach "Set Color", and they store the colour differently.
    Import wires it from a per-domain copy of the "Color Common" group, which
    holds an RGBA "Carbon" socket. The Visual Set-up colour picker instead
    relinks it to a "Custom Combine Color" node holding three float channels.
    Both are handled, so a domain the user has already recoloured still
    highlights - and, more importantly, still gets its colour back afterwards.

    Links are compared with ``==``: Blender hands back a fresh wrapper on every
    access, so ``is`` would never match.
    """
    tree = next((m.node_group for m in obj.modifiers
                 if m.type == 'NODES' and m.node_group), None)
    if tree is None:
        return None

    set_color = tree.nodes.get("Set Color")
    if set_color is None:
        return None
    color_input = next((s for s in set_color.inputs if "Color" in s.name), None)
    if color_input is None:
        return None
    driver = next((link.from_node for link in tree.links
                   if link.to_socket == color_input), None)
    if driver is None:
        return None

    if driver.name == "Custom Combine Color":
        return [driver.inputs[channel]
                for channel in ("Red", "Green", "Blue")
                if channel in driver.inputs]
    # Prefix match: a range update rebuilds the selection nodes and the
    # re-added colour node comes back name-collided as "Color Common.001".
    if driver.name.startswith("Color Common"):
        # Import gives every domain its own copy of this group. Should one ever
        # be shared, highlighting through it would recolour the domain's
        # neighbours too, so leave that domain uncoloured rather than repaint
        # the wrong thing.
        if driver.node_tree is None or driver.node_tree.users > 1:
            return None
        carbon = driver.inputs.get("Carbon")
        return [carbon] if carbon is not None else None
    return None


def _read_color(obj):
    """The domain's current colour as RGBA, or None if nothing drives it."""
    sockets = _color_sockets(obj)
    if not sockets:
        return None
    if len(sockets) == 1:
        return list(sockets[0].default_value)
    return [s.default_value for s in sockets] + [1.0]


def _write_color(obj, color):
    """Set the domain's colour, skipping sockets that already hold it.

    The skip matters: this runs on every keystroke in the dialog's Start and
    End fields, and re-assigning an unchanged socket still tags the shader for
    a rebuild.
    """
    sockets = _color_sockets(obj)
    if not sockets:
        return
    if len(sockets) == 1:
        wanted = tuple(color)[:4]
        if tuple(sockets[0].default_value) != wanted:
            sockets[0].default_value = wanted
        return
    for socket, value in zip(sockets, color):
        if socket.default_value != value:
            socket.default_value = value


def _ghost_material(original):
    """A translucent twin of ``original`` - identical shading, less opacity.

    A *copy of the domain's own material*, not a material of our own. A
    hand-built stand-in does not reproduce how MolecularNodes shades: it reads
    colour through its own node group off the instancer, and a plain Attribute
    node fed into a fresh Principled BSDF renders the chain effectively opaque
    in the Material Preview viewport however low its alpha is set. Copying the
    real material and dialling alpha down changes exactly one thing, which is
    the only way the ghost is guaranteed to look like the domain it stands for.

    A copy is needed because every domain of a molecule shares "MN Default";
    alpha set on it in place would ghost the whole scene. The copy is swapped
    onto the Style node and swapped back when the preview ends, then dropped by
    `restore_preview` - so nothing survives the dialog.
    """
    if original is None:
        return None

    name = original.name + _GHOST_SUFFIX
    material = bpy.data.materials.get(name)
    if material is None:
        material = original.copy()
        material.name = name

    # True alpha blending, not EEVEE's default dithered transparency, which
    # renders a faint ghost as a sparse stipple rather than a wash.
    material.surface_render_method = 'BLENDED'
    # Draw only the surface nearest the camera. This is what makes the ghost a
    # ghost: with the far side left in, every sphere behind every other sphere
    # blends again and a space-filling chain comes back to near-opaque however
    # low the alpha goes. Turning it off cuts the same chain from 68% of its
    # opaque brightness to 42%, before alpha is lowered at all.
    material.show_transparent_back = False
    # Solid viewport shading reads this rather than the shader nodes.
    material.diffuse_color = (*original.diffuse_color[:3], GHOST_ALPHA)
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            node.inputs['Alpha'].default_value = GHOST_ALPHA
    return material


def _discard_ghost_materials():
    """Drop the ghost copies once nothing is wearing them any more."""
    for material in list(bpy.data.materials):
        if material.name.endswith(_GHOST_SUFFIX) and material.users == 0:
            bpy.data.materials.remove(material)


def _scene_map(scene, key):
    try:
        return json.loads(scene.get(key, "{}"))
    except (ValueError, TypeError):
        return {}


def _store_map(scene, key, data):
    scene[key] = json.dumps(data)


def _capture(scene, obj):
    """Record what the preview is about to change on ``obj``, once.

    Captured on first touch and never re-captured, so dragging a boundary
    cannot record the previewed state as if it were the user's own.
    """
    state = _scene_map(scene, _PREVIEW_STATE)
    if obj.name in state:
        return state[obj.name]

    _modifier, node = _range_node(obj)
    socket = _style_material_socket(obj)
    material = socket.default_value if socket is not None else None
    state[obj.name] = {
        "range": [int(node.inputs["Min"].default_value),
                  int(node.inputs["Max"].default_value)],
        "material": material.name if material is not None else "",
        "color": _read_color(obj),
    }
    _store_map(scene, _PREVIEW_STATE, state)
    return state[obj.name]


def _restore_object(scene, obj):
    """Put back everything the preview changed on ``obj``, and forget it."""
    state = _scene_map(scene, _PREVIEW_STATE)
    entry = state.pop(obj.name, None)
    if entry is None:
        return
    _store_map(scene, _PREVIEW_STATE, state)

    _modifier, node = _range_node(obj)
    if node is not None:
        node.inputs["Min"].default_value = int(entry["range"][0])
        node.inputs["Max"].default_value = int(entry["range"][1])

    socket = _style_material_socket(obj)
    if socket is not None:
        socket.default_value = bpy.data.materials.get(entry["material"] or "")

    if entry["color"]:
        _write_color(obj, entry["color"])


def _show(scene, obj, start, end, ghosted, color=None):
    """Reveal ``obj`` showing residues ``start``-``end``, solid or ghosted.

    Exactly one domain is un-ghosted at a time - the one being sized - and the
    ghost/solid contrast alone is what picks it out. ``color`` is the colour
    the dialog's row carries for this domain; when given it is previewed here,
    which is how a swatch edit shows up live. Without one the domain keeps the
    colour it already had.
    """
    entry = _capture(scene, obj)

    _modifier, node = _range_node(obj)
    node.inputs["Min"].default_value = start
    node.inputs["Max"].default_value = end

    socket = _style_material_socket(obj)
    if socket is not None:
        own = bpy.data.materials.get(entry["material"] or "")
        wanted = _ghost_material(own) if ghosted else own
        # Compared with `!=`, never `is not`: a fresh wrapper comes back on
        # every access. Skipping an unchanged assignment avoids a shader
        # rebuild on every keystroke.
        if socket.default_value != wanted:
            socket.default_value = wanted

    if entry["color"]:
        _write_color(obj, color if color is not None else entry["color"])

    obj.hide_viewport = False


def _retire(scene, keep):
    """Hide and reset every object the preview showed that it no longer shows.

    Without this, moving between rows would leave the domain that lent its
    object to a previous row stuck at someone else's residue range.
    """
    for name in set(_scene_map(scene, _PREVIEW_STATE)) - keep:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        _restore_object(scene, obj)
        obj.hide_viewport = True


def _domain_object(molecule, domain_id):
    domain = molecule.domains.get(domain_id) if domain_id else None
    return getattr(domain, "object", None) if domain else None


def _current_domain_color(molecule, domain_id):
    """The RGBA a domain currently renders with, or None without an object.

    Read off the node graph (`_read_color`), falling back to the broader
    `visual_style.get_object_color` for a domain whose colour tree this module
    refuses to write to (a still-shared Color Common group).
    """
    obj = _domain_object(molecule, domain_id)
    if obj is None:
        return None
    color = _read_color(obj)
    if color is None:
        from ..core.visual_style import get_object_color
        color = list(get_object_color(obj))
    channels = [float(c) for c in list(color)[:4]]
    return channels + [1.0] * (4 - len(channels))


def _same_color(a, b, places=4):
    """Whether two colours agree, on the RGB channels the pickers share."""
    return all(round(float(x), places) == round(float(y), places)
               for x, y in zip(tuple(a)[:3], tuple(b)[:3]))


def _color_key(spec):
    """How a layout spec is matched to the colour chosen for it."""
    return (spec.start, spec.end, spec.domain_id or "")


def _fresh_color(index):
    """A distinct colour for the ``index``-th new domain.

    The same golden-ratio walk domain creation itself uses, so a piece added
    in this dialog is colour-separated from its siblings the way every other
    new domain is - but chosen here, deterministically, so the swatch shows
    the colour the domain will actually get before OK is pressed.
    """
    hue = (index * 0.618033988749895) % 1.0
    return (*colorsys.hsv_to_rgb(hue, 0.8, 0.9), 1.0)


def _apply_layout_colors(context, molecule, specs, colors_by_key, result):
    """Paint each domain of a just-committed layout with its chosen colour.

    Runs after ``apply_layout`` so the colours reach domains the commit
    created; those are resolved by their (start, end) range, which is exactly
    what their spec asked for. A colour the domain already shows is skipped -
    pressing OK without touching a swatch must change nothing, including for a
    domain whose colour tree is still shared and would be forked by a write.
    """
    if not colors_by_key:
        return

    created_by_range = {}
    for domain_id in result.created:
        domain = molecule.domains.get(domain_id)
        if domain is not None:
            created_by_range[(int(domain.start), int(domain.end))] = domain_id

    changed = False
    for spec in specs:
        color = colors_by_key.get(_color_key(spec))
        if color is None:
            continue
        domain_id = (spec.domain_id if spec.domain_id in molecule.domains
                     else created_by_range.get((spec.start, spec.end)))
        domain = molecule.domains.get(domain_id) if domain_id else None
        obj = getattr(domain, "object", None) if domain else None
        if obj is None:
            continue
        current = _current_domain_color(molecule, domain_id)
        if current is not None and _same_color(current, color):
            continue
        if molecule.update_domain_color(domain_id, tuple(color)[:4]):
            changed = True

    if changed:
        from ..core.outliner_colors import sync_outliner_colors
        sync_outliner_colors(context)


def _drivable(obj):
    """Can this object be driven to show an arbitrary stretch of its chain?"""
    return obj is not None and _range_node(obj)[1] is not None


def _any_chain_object(molecule, chain_token, objects):
    """Any object of the chain that can be driven to an arbitrary span.

    Every domain of a chain shares the mesh and the same "Select Chain" ->
    "Select Res ID Range" pair, so any one of them can show any stretch of that
    chain - which is what makes it usable as a template for the stand-ins.
    """
    for obj in objects:
        if _drivable(obj):
            return obj
    for spec in domain_layout.current_layout(molecule, chain_token):
        obj = _domain_object(molecule, spec.domain_id)
        if _drivable(obj):
            return obj
    return None


def _temp_object(scene, source, index):
    """A throwaway twin of ``source``, for a domain that has no object yet.

    Most rows in this dialog have no object. A chain is imported as a *single*
    domain, so the ordinary way in - open the splitter on a chain, set the
    count to 3, drag the boundaries - produces one row backed by a real object
    and two backed by nothing at all. Without stand-ins there was simply
    nothing to ghost in that case: the viewport showed one solid domain and
    otherwise nothing, which is the state this feature exists to improve on.
    Every domain the dialog is about is created when the user presses OK, long
    after the preview needs to draw it.

    The copy shares the mesh but must not share the node group: the residue
    range lives on the node group, so twins that share one would all jump to
    whichever span was written last.
    """
    name = f"{_TEMP_PREFIX}{index}"
    existing = bpy.data.objects.get(name)
    if existing is not None:
        return existing

    obj = source.copy()
    obj.name = name
    trees = []
    for modifier in obj.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group:
            continue
        modifier.node_group = modifier.node_group.copy()
        trees.append(modifier.node_group.name)
        # Copying a node group leaves its *group nodes* pointing at the
        # original's sub-trees, and the colour lives in one of those. A shared
        # colour tree is one this module refuses to write to, since writing
        # would repaint every domain sharing it - so leaving it shared silently
        # costs the highlight on the twin *and* on the domain it was copied
        # from, which is a much worse bug than it looks.
        for node in modifier.node_group.nodes:
            if (node.name.startswith("Color Common") and node.type == 'GROUP'
                    and node.node_tree):
                node.node_tree = node.node_tree.copy()
                trees.append(node.node_tree.name)
    for collection in source.users_collection:
        collection.objects.link(obj)

    temps = _scene_map(scene, _PREVIEW_TEMPS)
    temps[name] = trees
    _store_map(scene, _PREVIEW_TEMPS, temps)
    return obj


def _discard_temp_objects(scene):
    """Delete the stand-ins, and the node groups copied for them."""
    for name, trees in _scene_map(scene, _PREVIEW_TEMPS).items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        for tree_name in trees:
            tree = bpy.data.node_groups.get(tree_name)
            if tree is not None and tree.users == 0:
                bpy.data.node_groups.remove(tree)


def preview_layout(context, molecule, chain_token, specs, edited_index,
                   colors=None):
    """Ghost the scene, with the domain being sized picked out solid.

    ``specs[edited_index]`` is drawn solid; the other domains of the chain are
    shown at their own ranges but ghosted, and so is everything else in the
    scene - the rest of the protein included - so the piece being carved out is
    read against everything it lives amongst rather than floating alone. Only
    objects that cannot wear a ghost material (no Style node to hang it on)
    are hidden instead.

    ``colors`` is an optional per-spec list of RGBA row colours; entries are
    previewed on their domains, ``None`` entries keep the domain's own colour.

    The original scene state is captured once, on the first call, so dragging
    a boundary never re-captures the previewed scene as if the user had
    chosen it.
    """
    scene = context.scene
    if not specs or not (0 <= edited_index < len(specs)):
        return None

    objects = [_domain_object(molecule, spec.domain_id) for spec in specs]
    template = _any_chain_object(molecule, chain_token, objects)
    if template is None:
        return None

    # Capture the rest of the scene before inventing any stand-in, so the
    # stand-ins are never recorded as objects the user had chosen to show.
    # The chain's own objects are hidden here and re-shown by the row loop
    # below; everything else that was visible is ghosted in place, falling
    # back to hiding whatever has no Style material to swap.
    if _PREVIEW_OBJECT not in scene:
        chain_names = {obj.name for obj in objects if obj is not None}
        for spec in domain_layout.current_layout(molecule, chain_token):
            obj = _domain_object(molecule, spec.domain_id)
            if obj is not None:
                chain_names.add(obj.name)

        hidden = {}
        ghosted = {}
        for other in bpy.data.objects:
            if other.type not in _ISOLATABLE_TYPES:
                continue
            hidden[other.name] = bool(other.hide_viewport)
            if other.name in chain_names:
                other.hide_viewport = True
                continue
            if other.hide_viewport:
                continue
            socket = _style_material_socket(other)
            original = socket.default_value if socket is not None else None
            if original is not None:
                socket.default_value = _ghost_material(original)
                ghosted[other.name] = original.name
            else:
                other.hide_viewport = True
        _store_map(scene, _PREVIEW_HIDDEN, hidden)
        _store_map(scene, _PREVIEW_GHOSTED, ghosted)

    # Every row gets something to be drawn with, real or invented, so the chain
    # is always shown whole no matter how few of its domains exist yet.
    for index, obj in enumerate(objects):
        if not _drivable(obj):
            objects[index] = _temp_object(scene, template, index)

    edited_obj = objects[edited_index]
    if not _drivable(edited_obj):
        return None

    def color_for(index):
        if colors is None or index >= len(colors):
            return None
        return colors[index]

    shown = set()
    for index, (spec, obj) in enumerate(zip(specs, objects)):
        # The edited domain is placed last, and an object lent to it cannot
        # also show its own span.
        if index == edited_index or not _drivable(obj):
            continue
        if obj.name == edited_obj.name:
            continue
        _show(scene, obj, spec.start, spec.end, ghosted=True,
              color=color_for(index))
        shown.add(obj.name)

    edited = specs[edited_index]
    _show(scene, edited_obj, edited.start, edited.end, ghosted=False,
          color=color_for(edited_index))
    shown.add(edited_obj.name)
    _retire(scene, shown)

    modifier, node = _range_node(edited_obj)
    scene[_PREVIEW_OBJECT] = edited_obj.name
    scene[_PREVIEW_MODIFIER] = modifier.name
    scene[_PREVIEW_NODE] = node.name

    if context.view_layer:
        context.view_layer.update()
    _tag_redraw(context, {'VIEW_3D', 'NODE_EDITOR'})
    return edited_obj


def restore_preview(context):
    """Undo the isolation and put every object the preview touched back."""
    scene = context.scene
    if _PREVIEW_OBJECT not in scene:
        return

    for name in list(_scene_map(scene, _PREVIEW_STATE)):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            _restore_object(scene, obj)

    # Objects outside the chain that were ghosted in place get their own
    # material back on the Style node.
    for name, material_name in _scene_map(scene, _PREVIEW_GHOSTED).items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        socket = _style_material_socket(obj)
        if socket is not None:
            socket.default_value = bpy.data.materials.get(material_name or "")

    for name, was_hidden in _scene_map(scene, _PREVIEW_HIDDEN).items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_viewport = was_hidden

    _discard_temp_objects(scene)

    for key in (_PREVIEW_OBJECT, _PREVIEW_MODIFIER, _PREVIEW_NODE,
                _PREVIEW_STATE, _PREVIEW_HIDDEN, _PREVIEW_GHOSTED,
                _PREVIEW_TEMPS):
        if key in scene:
            del scene[key]

    # After the sockets are back on the real materials, nothing wears a ghost.
    _discard_ghost_materials()

    if context.view_layer:
        context.view_layer.update()
    _tag_redraw(context, {'VIEW_3D', 'NODE_EDITOR'})


def _on_start_edited(row, context):
    instance = _active()
    if instance is not None:
        instance.range_edited(row, moved_start=True)


def _on_end_edited(row, context):
    instance = _active()
    if instance is not None:
        instance.range_edited(row, moved_start=False)


def _on_row_color_edited(row, context):
    instance = _active()
    if instance is not None:
        instance.row_color_edited(row)


def _on_edge_end_edited(_operator, context):
    """The head adjuster's End moved: it is the first domain's Start, minus one."""
    if _state["suspended"]:
        return
    instance = _active()
    if instance is not None and len(instance.rows):
        instance.rows[0].start = instance.head_end + 1


def _on_edge_start_edited(_operator, context):
    """The tail adjuster's Start moved: it is the last domain's End, plus one."""
    if _state["suspended"]:
        return
    instance = _active()
    if instance is not None and len(instance.rows):
        instance.rows[-1].end = instance.tail_start - 1


def _on_head_color_edited(_operator, context):
    instance = _active()
    if instance is not None:
        instance.edge_color_edited(head=True)


def _on_tail_color_edited(_operator, context):
    instance = _active()
    if instance is not None:
        instance.edge_color_edited(head=False)


def _on_count_edited(_operator, context):
    """Redistribute the chain evenly whenever the domain count changes.

    This replaces the old explicit "Build Domains" button: the count spinner
    *is* the build control, and OK commits.

    Routed through ``_active()`` rather than the ``self`` RNA hands this
    callback: that wrapper does not expose the operator's own methods, so
    calling ``redistribute()`` on it raises AttributeError - the same
    limitation that makes plain class attributes unreachable here.
    """
    if _state["suspended"]:
        return
    instance = _active()
    if instance is not None:
        instance.redistribute()


class PROTEINBLENDER_DomainLayoutRow(PropertyGroup):
    """One editable domain row inside the Domain Splitter dialog."""
    name: StringProperty(name="Name", description="Name for this domain")
    color: FloatVectorProperty(
        name="Color",
        description="This domain's colour. Changing it recolours the domain "
                    "when the dialog is confirmed, and previews live in the "
                    "viewport",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.8, 0.8, 0.8, 1.0),
        update=_on_row_color_edited)
    start: IntProperty(
        name="Start",
        description="First residue in this domain. Moving it moves the "
                    "boundary with the domain above",
        update=_on_start_edited)
    end: IntProperty(
        name="End",
        description="Last residue in this domain. Moving it moves the "
                    "boundary with the domain below",
        update=_on_end_edited)
    # The existing domain this row stands for, empty for a row the user added.
    # Carrying it is what lets the layout be reconciled instead of rebuilt, so
    # an untouched domain keeps its puppet membership, linkers and animation.
    domain_id: StringProperty()


class PROTEINBLENDER_OT_edit_chain_domains(VisualEditMixin, Operator):
    """Rename this chain, restyle it, and edit how it is split into domains"""
    bl_idname = "proteinblender.edit_chain_domains"
    bl_label = "Edit Chain"
    bl_options = {'REGISTER', 'UNDO'}

    # The live modal instance, so the in-dialog row buttons can edit its rows.
    # Read through the class, never through an instance - see the note on
    # `_state` above for why instance attribute lookup is not reliable here.
    _active_instance = None

    item_id: StringProperty(
        name="Chain Row",
        description="item_id of the chain row in the Protein Outliner")
    chain_name: StringProperty(
        name="Chain Name",
        description="Display name for this chain in the Protein Outliner")
    domain_count: IntProperty(
        name="Number of Domains",
        description="How many domains to divide this chain into. Changing "
                    "this re-divides the chain evenly",
        default=1, min=1, max=MAX_DOMAINS, update=_on_count_edited)
    rows: CollectionProperty(type=PROTEINBLENDER_DomainLayoutRow)

    # Chain bounds, cached on the instance so draw() and the edit callbacks do
    # not have to re-derive them on every redraw. Named because the edge
    # adjusters draw them (disabled) as the fixed ends of the grid.
    chain_min: IntProperty(
        name="Chain Start",
        description="The chain's first residue - fixed by the structure",
        default=1)
    chain_max: IntProperty(
        name="Chain End",
        description="The chain's last residue - fixed by the structure",
        default=1)
    # The author chain letter ("A"), used to build default domain names. The
    # outliner row carries the chain *index*, which is not what a user reading
    # "Chain A: 1-248" expects to see.
    chain_label: StringProperty(default="")

    # The two domains-to-be at the ends of the chain. When a boundary is
    # dragged off the start or end of the chain the residues beyond it have no
    # row, and a row cannot be conjured for them: adding one ahead of the row
    # being dragged shifts it out from under the cursor, and Blender's number
    # widget stays bound to the position, so the user ends up dragging the row
    # that was just inserted. It sits at the chain's edge and cannot move, so
    # the drag dies. That is the "snaps to 2 and creates a 1-1 domain" bug, and
    # it comes back however cleverly the insertion is timed.
    #
    # So these are drawn as an extra grid line from plain operator properties
    # instead. They look and behave like a row - the range tracks the drag, the
    # boundary is editable, the name is the name the domain will be created
    # with - but they are not CollectionProperty elements, so no drag can be
    # stolen. execute() turns them into real domains.
    head_name: StringProperty(name="Name")
    head_end: IntProperty(
        name="End",
        description="Last residue of the domain that will be created for the "
                    "start of the chain. This is the boundary below the first "
                    "domain",
        update=_on_edge_end_edited)
    head_color: FloatVectorProperty(
        name="Color",
        description="Colour for the domain that will be created for the "
                    "start of the chain",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.8, 0.8, 0.8, 1.0),
        update=_on_head_color_edited)
    tail_name: StringProperty(name="Name")
    tail_start: IntProperty(
        name="Start",
        description="First residue of the domain that will be created for the "
                    "end of the chain. This is the boundary above the last "
                    "domain",
        update=_on_edge_start_edited)
    tail_color: FloatVectorProperty(
        name="Color",
        description="Colour for the domain that will be created for the "
                    "end of the chain",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.8, 0.8, 0.8, 1.0),
        update=_on_tail_color_edited)

    # Headless escape hatch: a JSON list of {name, start, end, domain_id}. When
    # set, execute() uses it instead of the dialog rows, so the operator is
    # driveable from tests and scripts without a UI.
    layout_json: StringProperty(default="")

    # ------------------------------------------------------------------
    # The domains-to-be at the ends of the chain
    # ------------------------------------------------------------------

    def has_head(self):
        return bool(len(self.rows)) and self.rows[0].start > self.chain_min

    def has_tail(self):
        return bool(len(self.rows)) and self.rows[-1].end < self.chain_max

    def grid_line_count(self):
        """How many domains the grid describes: its rows plus its edge lines."""
        return grid_line_total(len(self.rows), self.has_head(), self.has_tail())

    def _sync_edges(self):
        """Point the edge adjusters at the boundaries the rows currently have.

        Suspended, because writing these fires their own update callbacks,
        which write straight back into the rows.
        """
        if not len(self.rows):
            return
        with _Suspend():
            self.head_end = self.rows[0].start - 1
            self.tail_start = self.rows[-1].end + 1
            if self.has_head() and is_default_domain_name(self.head_name):
                self.head_name = default_domain_name(
                    self.chain_label, self.chain_min, self.head_end)
            if self.has_tail() and is_default_domain_name(self.tail_name):
                self.tail_name = default_domain_name(
                    self.chain_label, self.tail_start, self.chain_max)
            # The header counts what the grid lists, edges included.
            self.domain_count = self.grid_line_count()

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _chain_row(self, context):
        for item in context.scene.outliner_items:
            if item.item_id == self.item_id:
                return item
        return None

    # The Visual Set-up block edits whatever the chain row resolves to: one
    # object while the chain is whole, one per domain once it is split.
    def visual_row(self, context):
        return self._chain_row(context)

    def before_visual_edit(self, context):
        """Drop any live preview before a colour or style lands.

        The preview ghosts the chain and re-colours the domain being sized,
        remembering the real colours so it can put them back on close. A
        colour set while that is in flight would be restored straight back
        off again on the way out. Clearing first makes the edit the real
        state; the preview rebuilds itself on the next boundary drag.
        """
        restore_preview(context)

    def apply_visual_color(self, context):
        """A chain-wide colour pick also repaints every row's swatch.

        Without this the rows keep their seeded colours, and committing the
        dialog would paint those straight back over the colour the user just
        chose - the per-row apply skips only colours the domain already shows.
        """
        super().apply_visual_color(context)
        with _Suspend():
            chosen = tuple(self.vs_color)
            for row in self.rows:
                row.color = chosen
            self.head_color = chosen
            self.tail_color = chosen

    def _molecule(self, context, chain_row):
        if chain_row is None:
            return None
        return ProteinBlenderScene.get_instance().molecules.get(chain_row.parent_id)

    def _index_of(self, row):
        """Position of ``row`` in the collection.

        Compared with ``==``, never ``is``: Blender hands out a fresh
        ``bpy_struct`` wrapper on each access, so identity comparison is False
        even for the same element.
        """
        for index, candidate in enumerate(self.rows):
            if candidate == row:
                return index
        return -1

    # ------------------------------------------------------------------
    # Row editing
    # ------------------------------------------------------------------

    def load_rows(self, specs):
        """Replace the dialog's rows with ``specs``."""
        self.rows.clear()
        for spec in specs:
            row = self.rows.add()
            row.name = spec.name
            row.start = spec.start
            row.end = spec.end
            row.domain_id = spec.domain_id or ""

    def current_specs(self):
        return [domain_layout.DomainSpec(
                    name=row.name, start=row.start, end=row.end,
                    domain_id=row.domain_id or None)
                for row in self.rows]

    def redistribute(self):
        """Divide the chain evenly into ``domain_count`` rows.

        Existing domains are re-assigned to rows positionally, so reshaping a
        chain from 4 domains to 3 keeps three real domains (with their puppet
        membership, linkers and animation) and deletes only the fourth, rather
        than replacing all of them.
        """
        previous = [(r.domain_id, r.name, tuple(r.color))
                    for r in self.rows if r.domain_id]
        ranges = domain_layout.even_split(self.chain_min, self.chain_max,
                                          self.domain_count)
        with _Suspend():
            self.rows.clear()
            for i, (start, end) in enumerate(ranges):
                row = self.rows.add()
                row.start = start
                row.end = end
                # A name the user typed survives a re-divide; an auto-generated
                # one is re-derived from the row's new range. The colour rides
                # with the domain the row is re-assigned to; a brand-new row
                # gets a fresh, distinct colour of its own.
                if i < len(previous):
                    row.domain_id, kept, color = previous[i]
                    row.name = "" if is_default_domain_name(kept) else kept
                    row.color = color
                else:
                    row.color = self._next_fresh_color()
            self._refresh_default_names()

    def range_edited(self, row, moved_start):
        """Re-tile the layout around a boundary the user just moved.

        Values are written back **immediately**, here in the update callback.
        Only *resizing* the row collection is unsafe from inside a property
        write (it reallocates the collection Blender is mid-write on), so just
        that part is deferred to check(). Deferring the values too meant the
        neighbour only followed if Blender happened to call check() for an edit
        to a collection *element*, which is not something to rely on - and when
        it did not fire, the boundary silently failed to move and the viewport
        preview never updated either.
        """
        if _state["suspended"]:
            return
        index = self._index_of(row)
        if index < 0:
            return

        retiled, new_index = domain_layout.retile_after_edit(
            self.current_specs(), index, self.chain_min, self.chain_max,
            moved_start)
        if len(retiled) > MAX_DOMAINS:
            return

        with _Suspend():
            if len(retiled) == len(self.rows):
                # The common case: a boundary moved between two existing
                # domains. Write every value now, the neighbour included.
                for existing, spec in zip(self.rows, retiled):
                    existing.start = spec.start
                    existing.end = spec.end
                # Both domains either side of the boundary changed size, so any
                # auto-generated name on them is now advertising the wrong span.
                self._refresh_default_names()
            else:
                # The edit pushed a boundary off the end of the chain and
                # orphaned the residues beyond it. Write the edited row's own
                # clamped value and stop: growing the row list here would move
                # this row, and every row after it, down by one - out from
                # under the cursor of the user who is still dragging it. The
                # orphaned stretch gets its own domain when the dialog is
                # committed, and the preview below already shows it forming.
                edited = retiled[new_index]
                row.start = edited.start
                row.end = edited.end
                self._refresh_default_names()

        self._sync_edges()
        self._preview_layout(retiled, new_index)

    def row_color_edited(self, row):
        """Show a colour just picked on a row, live, on its domain."""
        if _state["suspended"]:
            return
        index = self._index_of(row)
        if index < 0:
            return
        self._preview_layout(self.current_specs(), index)

    def edge_color_edited(self, head):
        """Show a colour just picked on an edge adjuster, on its domain-to-be."""
        if _state["suspended"]:
            return
        if (head and not self.has_head()) or (not head and not self.has_tail()):
            return
        specs = self._completed_specs()
        for index, spec in enumerate(specs):
            if spec.domain_id:
                continue
            if head and spec.start == self.chain_min:
                self._preview_layout(specs, index)
                return
            if not head and spec.end == self.chain_max:
                self._preview_layout(specs, index)
                return

    def _next_fresh_color(self):
        """A distinct colour for a row that stands for a brand-new domain.

        The counter lives in module ``_state`` (an operator instance behind a
        props dialog cannot be trusted to keep plain attributes - see the note
        on ``_state``).
        """
        index = _state.get("fresh_color_index", 0)
        _state["fresh_color_index"] = index + 1
        return _fresh_color(index)

    def _seed_row_colors(self, molecule, specs):
        """Paint each row with the colour its domain currently renders with."""
        _state["fresh_color_index"] = len(specs)
        for row, spec in zip(self.rows, specs):
            color = _current_domain_color(molecule, spec.domain_id)
            row.color = color if color is not None else self._next_fresh_color()
        self.head_color = self._next_fresh_color()
        self.tail_color = self._next_fresh_color()

    def _completed_specs(self):
        """The dialog's rows, plus a domain for whatever they leave uncovered.

        The row list is allowed to stop short of either end of the chain while
        a boundary is being dragged - see domain_layout.complete_layout for why
        filling it in on the spot breaks the drag - so it is completed here,
        once, on the way out.
        """
        def name_for(start, end):
            if start == self.chain_min and self.head_name.strip():
                return self.head_name
            if end == self.chain_max and self.tail_name.strip():
                return self.tail_name
            return default_domain_name(self.chain_label, start, end)

        return domain_layout.complete_layout(
            self.current_specs(), self.chain_min, self.chain_max,
            name_for=name_for)

    def _refresh_default_names(self):
        """Re-derive every auto-generated row name from its current range.

        A name the user typed is never touched. An auto-generated one tracks
        the range, so a domain the user re-sized is not left advertising the
        span it used to cover.
        """
        for row in self.rows:
            if is_default_domain_name(row.name):
                row.name = default_domain_name(self.chain_label, row.start,
                                               row.end)

    def split_row(self, index):
        """Cut one row in half, giving the new half a fresh (unassigned) row."""
        if not (0 <= index < len(self.rows)) or len(self.rows) >= MAX_DOMAINS:
            return
        row = self.rows[index]
        if row.end - row.start < 1:
            return
        with _Suspend():
            midpoint = row.start + (row.end - row.start) // 2
            tail_start, tail_end = midpoint + 1, row.end
            row.end = midpoint

            new_row = self.rows.add()
            new_row.start = tail_start
            new_row.end = tail_end
            new_row.color = self._next_fresh_color()
            self.rows.move(len(self.rows) - 1, index + 1)
            self._refresh_default_names()
            self.domain_count = self.grid_line_count()

    def merge_row(self, index):
        """Absorb the following row into this one."""
        if not (0 <= index < len(self.rows) - 1):
            return
        with _Suspend():
            row, following = self.rows[index], self.rows[index + 1]
            row.start = min(row.start, following.start)
            row.end = max(row.end, following.end)
            self.rows.remove(index + 1)
            self._refresh_default_names()
            self.domain_count = self.grid_line_count()

    # ------------------------------------------------------------------
    # Viewport preview
    # ------------------------------------------------------------------

    def _preview_layout(self, specs, edited_index):
        """Show the layout the user is heading towards, in the viewport.

        The whole layout is handed over, not just the edited row: the domains
        either side of a boundary move with it, and seeing them move is the
        point of previewing the chain rather than the one domain. Each spec is
        previewed in its row's colour, so a swatch edit shows up too.
        """
        context = bpy.context
        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if molecule is None:
            return
        preview_layout(context, molecule, chain_token_from_item(chain_row),
                       specs, edited_index, colors=self._spec_colors(specs))

    def _spec_colors(self, specs):
        """The dialog's colours, matched to ``specs`` for the preview.

        Matched by domain identity first and by span second. A spec no row
        backs yet - a boundary dragged off the end of the chain - takes the
        matching edge adjuster's colour, so the domain forming at the chain's
        edge previews in the colour it will be created with.
        """
        rows = list(self.rows)
        taken = set()
        colors = []
        for spec in specs:
            match = None
            for i, row in enumerate(rows):
                if i in taken:
                    continue
                if spec.domain_id and row.domain_id == spec.domain_id:
                    match = i
                    break
            if match is None:
                for i, row in enumerate(rows):
                    if i in taken or row.domain_id:
                        continue
                    if (row.start, row.end) == (spec.start, spec.end):
                        match = i
                        break
            if match is None:
                colors.append(None)
            else:
                taken.add(match)
                colors.append(tuple(rows[match].color))

        for index, (spec, color) in enumerate(zip(specs, colors)):
            if color is not None or spec.domain_id:
                continue
            if spec.start == self.chain_min:
                colors[index] = tuple(self.head_color)
            elif spec.end == self.chain_max:
                colors[index] = tuple(self.tail_color)
        return colors

    # ------------------------------------------------------------------
    # Invoke / draw / execute
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if chain_row is None or molecule is None:
            self.report({'ERROR'}, "Could not resolve the chain to edit")
            return {'CANCELLED'}

        # Clear any preview a previous dialog left behind before recording a
        # new "original" visibility set, or the leftover hidden state would be
        # captured as if the user had chosen it.
        restore_preview(context)

        token = chain_token_from_item(chain_row)
        self.chain_min, self.chain_max = domain_layout.chain_residue_range(
            molecule, token)
        self.chain_name = chain_row.name

        with _Suspend():
            specs = domain_layout.current_layout(molecule, token)
            self.chain_label = _author_chain_label(molecule, token, specs)
            self.load_rows(specs)
            self._seed_row_colors(molecule, specs)
            self.domain_count = max(1, len(specs))
            self._refresh_default_names()
        self._sync_edges()

        type(self)._active_instance = self
        self.begin_visual_edit(context)
        return context.window_manager.invoke_props_dialog(self, width=520)

    def check(self, context):
        """Force the dialog to re-layout after something changed the rows.

        Blender only re-runs a dialog's draw() for property edits unless
        check() asks for it, and the row buttons add and remove rows rather
        than editing a property. Nothing structural is deferred to here: for an
        edit to a CollectionProperty *element* - which is what every row field
        is - Blender does not call check() at all, so anything parked here for
        a boundary drag would be applied at some unrelated moment later, or
        never.
        """
        return True

    def draw(self, context):
        layout = self.layout
        type(self)._active_instance = self

        header = layout.box()
        header.prop(self, "chain_name", text="Chain Name")
        header.prop(self, "domain_count")

        body = layout.box()
        body.label(text=f"Chain valid range: {self.chain_min} - {self.chain_max}")

        grid = body.column(align=True)
        self._draw_columns(grid.row(align=True), header=True)
        if self.has_head():
            self._draw_edge(grid.row(align=True), head=True)
        for index, row in enumerate(self.rows):
            self._draw_columns(grid.row(align=True), row=row, index=index)
        if self.has_tail():
            self._draw_edge(grid.row(align=True), head=False)

        self._draw_feedback(layout)
        self.draw_visual_setup(layout, context)

    # Column widths, shared by the header and every row so they line up
    # exactly. Blender lays a row out proportionally unless told otherwise, so
    # without fixed units the header labels drift away from their fields as the
    # name column grows.
    _COL_INDEX = 1.2
    _COL_COLOR = 1.1
    _COL_NUMBER = 3.4
    _COL_TOOLS = 2.4

    def _draw_columns(self, line, row=None, index=0, header=False):
        """Draw one grid line: index, colour, name, start, end, tools.

        Exactly one control per intent: the count spinner re-divides the whole
        chain evenly, the row's split button cuts that row in two, and its
        merge button joins it with the row below. (There used to be an "Add
        Domain" button and a per-row X as well - four ways to change the count
        - and they were cut, not hidden.)
        """
        cell = line.row()
        cell.ui_units_x = self._COL_INDEX
        cell.label(text="" if header else
                   f"{grid_line_number(index, self.has_head())}.")

        cell = line.row()
        cell.ui_units_x = self._COL_COLOR
        if header:
            cell.label(text="")
        else:
            cell.prop(row, "color", text="")

        if header:
            line.label(text="Name")
        else:
            line.prop(row, "name", text="")

        for field, label in (("start", "Start"), ("end", "End")):
            cell = line.row()
            cell.ui_units_x = self._COL_NUMBER
            if header:
                cell.label(text=label)
            else:
                cell.prop(row, field, text="")

        tools = line.row(align=True)
        tools.ui_units_x = self._COL_TOOLS
        if header:
            tools.label(text="")
            return

        from ..utils import icons
        split = tools.row(align=True)
        split.enabled = len(self.rows) < MAX_DOMAINS and row.end > row.start
        op = split.operator("proteinblender.domain_splitter_split", text="",
                            **icons.button_icon("split_domain", 'MOD_ARRAY'))
        op.index = index
        merge = tools.row(align=True)
        merge.enabled = index < len(self.rows) - 1
        op = merge.operator("proteinblender.domain_splitter_merge", text="",
                            **icons.button_icon("merge_domains", 'AUTOMERGE_ON'))
        op.index = index

    def _draw_edge(self, line, head):
        """Draw the domain that will be created for one end of the chain.

        Cell for cell the same widgets as a real row, so the grid stays a
        grid: the fixed number - the head's Start is the chain's first
        residue, the tail's End its last - is a *disabled field*, not a label
        (a label sits at its own indent and width, which is what used to
        push these numbers off their columns), and the tools column holds
        the same two buttons, disabled. The editable number *is* the boundary
        the neighbouring row is dragging, and editing it here moves that row.

        It is numbered like every other line rather than marked as new: it
        becomes a domain on OK either way, and where it sits in the chain is
        the useful thing to read off the column.
        """
        # A text label, exactly like the numbered rows' "1." cells: an *icon*
        # label pads differently and shifted every later column off the grid.
        number = grid_line_number(EDGE_HEAD if head else EDGE_TAIL,
                                  self.has_head(), len(self.rows))
        cell = line.row()
        cell.ui_units_x = self._COL_INDEX
        cell.label(text=f"{number}.")

        cell = line.row()
        cell.ui_units_x = self._COL_COLOR
        cell.prop(self, "head_color" if head else "tail_color", text="")

        line.prop(self, "head_name" if head else "tail_name", text="")

        columns = ((("chain_min", False), ("head_end", True)) if head
                   else (("tail_start", True), ("chain_max", False)))
        for prop, editable in columns:
            cell = line.row()
            cell.ui_units_x = self._COL_NUMBER
            cell.enabled = editable
            cell.prop(self, prop, text="")

        from ..utils import icons
        tools = line.row(align=True)
        tools.ui_units_x = self._COL_TOOLS
        tools.enabled = False
        op = tools.operator("proteinblender.domain_splitter_split", text="",
                            **icons.button_icon("split_domain", 'MOD_ARRAY'))
        op.index = -1
        op = tools.operator("proteinblender.domain_splitter_merge", text="",
                            **icons.button_icon("merge_domains", 'AUTOMERGE_ON'))
        op.index = -1

    def _draw_feedback(self, layout):
        specs = self.current_specs()
        errors = domain_layout.validate_layout(specs, self.chain_min,
                                               self.chain_max)
        if errors:
            box = layout.box()
            box.alert = True
            for message in errors:
                box.label(text=message, icon='ERROR')
            return

        # Residues no row claims are not an error: dragging a boundary off the
        # end of the chain is how you carve a domain off it, and the grid now
        # shows those stretches as their own rows, so there is nothing left to
        # announce here.

    def execute(self, context):
        restore_preview(context)

        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if chain_row is None or molecule is None:
            self.report({'ERROR'}, "Could not resolve the chain to edit")
            type(self)._active_instance = None
            self.end_visual_edit()
            return {'CANCELLED'}

        token = chain_token_from_item(chain_row)
        colors_by_key = {}
        if self.layout_json:
            try:
                specs = []
                for entry in json.loads(self.layout_json):
                    spec = domain_layout.DomainSpec(
                        name=entry.get("name", ""),
                        start=int(entry["start"]), end=int(entry["end"]),
                        domain_id=entry.get("domain_id") or None)
                    specs.append(spec)
                    # Optional per-domain colour, the scripted counterpart of
                    # the dialog rows' swatches.
                    if entry.get("color") is not None:
                        colors_by_key[_color_key(spec)] = [
                            float(c) for c in entry["color"]][:4]
            except (ValueError, KeyError, TypeError) as exc:
                self.report({'ERROR'}, f"Bad layout_json: {exc}")
                type(self)._active_instance = None
                self.end_visual_edit()
                return {'CANCELLED'}
        else:
            # The rows may stop short of either end of the chain: a boundary
            # dragged off the end orphans the residues beyond it, and those are
            # given their own domain here rather than mid-drag. layout_json is
            # taken exactly as written - it is the explicit escape hatch.
            specs = self._completed_specs()
            colors_by_key = {
                (row.start, row.end, row.domain_id or ""): tuple(row.color)
                for row in self.rows}
            # The gap fillers at the chain's ends are created with the colour
            # their edge adjuster shows, like every other row.
            for spec in specs:
                key = _color_key(spec)
                if spec.domain_id or key in colors_by_key:
                    continue
                if spec.start == self.chain_min:
                    colors_by_key[key] = tuple(self.head_color)
                elif spec.end == self.chain_max:
                    colors_by_key[key] = tuple(self.tail_color)

        # Validate before touching anything, so a rejected layout leaves the
        # chain name unchanged too rather than half-applying the dialog.
        chain_min, chain_max = domain_layout.chain_residue_range(molecule, token)
        errors = domain_layout.validate_layout(specs, chain_min, chain_max)
        if errors:
            for message in errors:
                self.report({'ERROR'}, message)
            type(self)._active_instance = None
            self.end_visual_edit()
            return {'CANCELLED'}

        # Store the chain name first: apply_layout rebuilds the outliner, and
        # the rebuild re-derives every chain label from the persisted custom
        # names, so a name written afterwards would not reach the row.
        self._store_chain_name(context, chain_row)

        result = domain_layout.apply_layout(context, molecule, token, specs)
        type(self)._active_instance = None

        if result.errors:
            for message in result.errors:
                self.report({'ERROR'}, message)
            self.end_visual_edit()
            return {'CANCELLED'}

        # After the layout, so a colour or style the user picked also reaches
        # the domains this run just created. Untouched fields apply nothing —
        # see VisualEditMixin.commit_visual_edit.
        self.commit_visual_edit(context)
        self.end_visual_edit()

        # Per-domain colours last: they are the most specific choice, so they
        # win over the chain-wide Visual Set-up colour (whose pick also
        # rewrote the row swatches - see apply_visual_color).
        _apply_layout_colors(context, molecule, specs, colors_by_key, result)

        _tag_redraw(context)

        self.report(
            {'INFO'},
            f"{len(result.created)} created, {len(result.updated)} updated, "
            f"{len(result.deleted)} removed")
        return {'FINISHED'}

    def _store_chain_name(self, context, chain_row):
        """Persist the chain's display name the same way rename_domain does.

        Custom chain names live as JSON on the molecule's list item so they
        survive an outliner rebuild and a .blend round-trip; a blank name pops
        the entry and restores the default "Chain X".
        """
        list_item = next((it for it in context.scene.molecule_list_items
                          if it.identifier == chain_row.parent_id), None)
        if list_item is None:
            return

        try:
            names = json.loads(list_item.chain_custom_names or "{}")
        except (ValueError, TypeError):
            names = {}

        key = str(chain_row.chain_id)
        new_name = self.chain_name.strip()
        if new_name:
            names[key] = new_name
        else:
            names.pop(key, None)
        list_item.chain_custom_names = json.dumps(names)

    def cancel(self, context):
        restore_preview(context)
        type(self)._active_instance = None
        self.end_visual_edit()


def _tag_redraw(context, area_types=frozenset({'VIEW_3D', 'PROPERTIES'})):
    """Redraw the areas showing domains, headless-safe."""
    if getattr(context, "area", None) is not None:
        context.area.tag_redraw()
    for window in getattr(context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type in area_types:
                area.tag_redraw()


# ---------------------------------------------------------------------------
# Row buttons. Each edits the live dialog instance and nothing else.
# ---------------------------------------------------------------------------

class _RowEdit:
    """Shared body for the dialog's row buttons.

    Deliberately not an ``Operator`` subclass: it is a mixin that is never
    registered, and a bare unregistered Operator subclass trips the repository
    contract that every first-party operator appears in a CLASSES inventory.
    Blender collects property annotations across the whole MRO, so ``index``
    still registers on each concrete operator below.
    """
    bl_options = {'INTERNAL'}
    index: IntProperty(default=0)

    def execute(self, context):
        instance = _active()
        if instance is None:
            return {'CANCELLED'}
        self.edit(instance)
        _tag_redraw(context)
        return {'FINISHED'}

    def edit(self, instance):
        raise NotImplementedError


class PROTEINBLENDER_OT_domain_splitter_split(_RowEdit, Operator):
    """Split this domain into two at its midpoint"""
    bl_idname = "proteinblender.domain_splitter_split"
    bl_label = "Split Domain"

    def edit(self, instance):
        instance.split_row(self.index)


class PROTEINBLENDER_OT_domain_splitter_merge(_RowEdit, Operator):
    """Merge this domain and the one below it into one"""
    bl_idname = "proteinblender.domain_splitter_merge"
    bl_label = "Merge With Next"

    def edit(self, instance):
        instance.merge_row(self.index)


CLASSES = [
    PROTEINBLENDER_DomainLayoutRow,
    PROTEINBLENDER_OT_edit_chain_domains,
    PROTEINBLENDER_OT_domain_splitter_split,
    PROTEINBLENDER_OT_domain_splitter_merge,
]
