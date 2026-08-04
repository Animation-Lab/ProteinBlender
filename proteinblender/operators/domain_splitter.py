"""The Domain Splitter dialog - edit a chain's name and its domain layout.

Opened from the pencil button on a chain row in the Protein Outliner. The
dialog edits a *desired layout* (a list of named residue ranges) and hands it
to :mod:`core.domain_layout`, which reconciles it against the chain's current
domains rather than rebuilding them - see that module for why that matters.

The layout is kept **contiguous**: the rows always tile the chain end to end,
with no gaps and no overlaps. That is what makes the boundaries directly
draggable - moving one domain's start is the same edit as moving the previous
domain's end, so the dialog adjusts the neighbour to match instead of leaving
the user to keep two numbers in sync by hand. Pulling the first domain's start
off the beginning of the chain (or the last domain's end off the end) leaves a
stretch with no owner, so a new domain is created there to keep the tiling
whole.

While a range is being edited the viewport isolates the chain being edited, so
the user can see the piece they are defining instead of guessing at residue
numbers. The domain under the cursor is drawn solid and in a highlight colour;
the rest of the chain stays visible but ghosted, so the piece being sized is
read against the whole it is being carved out of rather than floating on its
own. Everything outside the chain is hidden. The residue ranges, materials,
colours and visibility this touches are all restored when the dialog closes,
whether it is confirmed or cancelled.

Nothing here mutates the domain model. `draw()` only reads, the row buttons
only touch the dialog's own rows, and the model is changed once, in `execute`.

The row buttons reach the live modal operator through ``_active_instance``. A
modal dialog is not in ``wm.operators``, so a button inside it cannot address
the instance any other way; this is the same workaround ``keyframe_operators``
uses.
"""

from __future__ import annotations

import json

import bpy
from bpy.props import (CollectionProperty, IntProperty, StringProperty)
from bpy.types import Operator, PropertyGroup

from ..core import domain_layout
from ..utils.chain_utils import (chain_match_tokens, chain_token_from_item,
                                 default_domain_name, is_default_domain_name)
from ..utils.scene_manager import ProteinBlenderScene

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

# Object types worth hiding while isolating a domain. Cameras, lights and the
# puppet controller Empties are deliberately left alone: hiding the lights
# would just darken the very thing the user is trying to look at.
_ISOLATABLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}

# How opaque the rest of the chain stays while one of its domains is sized.
# Low enough that the solid domain reads as the subject at a glance, high
# enough that the chain's shape is still legible behind it.
GHOST_ALPHA = 0.2

# The colour the domain being sized takes for as long as it is being sized. A
# fixed colour rather than a brightened version of the domain's own: derived
# highlights barely move for a domain that is already vivid, whereas "the gold
# one is the one you are editing" holds however the chain happens to be
# coloured. The domain's real colour is written back when the dialog closes.
HIGHLIGHT_COLOR = (1.0, 0.62, 0.05, 1.0)

# Appended to the name of the material a ghosted domain normally wears.
_GHOST_SUFFIX = " (PB ghost)"


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
    for candidate in chain_match_tokens(molecule, chain_token):
        if not str(candidate).isdigit():
            return str(candidate)
    return str(chain_token)


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
    # Layout computed by a range edit, applied in check(). The row collection
    # must not be resized from inside a property update callback: that
    # reallocates the collection Blender is mid-write on.
    "pending_layout": None,
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
    if driver.name == "Color Common":
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
    # renders a 20%-opaque ghost as a sparse stipple rather than a wash.
    material.surface_render_method = 'BLENDED'
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


def _show(scene, obj, start, end, ghosted):
    """Reveal ``obj`` showing residues ``start``-``end``, solid or ghosted.

    Solid also means highlighted: exactly one domain is un-ghosted at a time -
    the one being sized - so the two go together.
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
        _write_color(obj, entry["color"] if ghosted else HIGHLIGHT_COLOR)

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


def _drivable(obj):
    """Can this object be driven to show an arbitrary stretch of its chain?"""
    return obj is not None and _range_node(obj)[1] is not None


def _stand_in(molecule, chain_token, objects):
    """An object to show the edited domain's span when it has none of its own.

    A row the user has just added has no object yet. Every domain of a chain
    shares the mesh and the same "Select Chain" -> "Select Res ID Range" pair,
    so any of them can be driven to show any stretch of that chain. The lender
    stands in for the new domain instead of showing its own span.
    """
    for obj in objects:
        if _drivable(obj):
            return obj
    for spec in domain_layout.current_layout(molecule, chain_token):
        obj = _domain_object(molecule, spec.domain_id)
        if _drivable(obj):
            return obj
    return None


def preview_layout(context, molecule, chain_token, specs, edited_index):
    """Isolate the chain, with the domain being sized picked out from it.

    ``specs[edited_index]`` is drawn solid and in the highlight colour; the
    other domains of the chain are shown at their own ranges but ghosted, so
    the piece being carved out is read against the whole chain rather than
    floating alone. Everything outside the chain is hidden.

    The hidden set is captured once, on the first call, so dragging a boundary
    never re-captures the isolated scene as if the user had chosen it.
    """
    scene = context.scene
    if not specs or not (0 <= edited_index < len(specs)):
        return None

    objects = [_domain_object(molecule, spec.domain_id) for spec in specs]
    edited_obj = objects[edited_index]
    if not _drivable(edited_obj):
        edited_obj = _stand_in(molecule, chain_token, objects)
    if edited_obj is None:
        return None

    if _PREVIEW_OBJECT not in scene:
        hidden = {}
        for other in bpy.data.objects:
            if other.type not in _ISOLATABLE_TYPES:
                continue
            hidden[other.name] = bool(other.hide_viewport)
            other.hide_viewport = True
        _store_map(scene, _PREVIEW_HIDDEN, hidden)

    shown = set()
    for index, (spec, obj) in enumerate(zip(specs, objects)):
        # The edited domain is placed last, and an object lent to it cannot
        # also show its own span.
        if index == edited_index or not _drivable(obj):
            continue
        if obj.name == edited_obj.name:
            continue
        _show(scene, obj, spec.start, spec.end, ghosted=True)
        shown.add(obj.name)

    edited = specs[edited_index]
    _show(scene, edited_obj, edited.start, edited.end, ghosted=False)
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

    for name, was_hidden in _scene_map(scene, _PREVIEW_HIDDEN).items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_viewport = was_hidden

    for key in (_PREVIEW_OBJECT, _PREVIEW_MODIFIER, _PREVIEW_NODE,
                _PREVIEW_STATE, _PREVIEW_HIDDEN):
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


class PROTEINBLENDER_OT_edit_chain_domains(Operator):
    """Rename this chain and edit how it is split into domains"""
    bl_idname = "proteinblender.edit_chain_domains"
    bl_label = "Domain Splitter"
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
    # not have to re-derive them on every redraw.
    chain_min: IntProperty(default=1)
    chain_max: IntProperty(default=1)
    # The author chain letter ("A"), used to build default domain names. The
    # outliner row carries the chain *index*, which is not what a user reading
    # "Chain A: 1-248" expects to see.
    chain_label: StringProperty(default="")

    # Headless escape hatch: a JSON list of {name, start, end, domain_id}. When
    # set, execute() uses it instead of the dialog rows, so the operator is
    # driveable from tests and scripts without a UI.
    layout_json: StringProperty(default="")

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _chain_row(self, context):
        for item in context.scene.outliner_items:
            if item.item_id == self.item_id:
                return item
        return None

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
        previous = [(r.domain_id, r.name) for r in self.rows if r.domain_id]
        ranges = domain_layout.even_split(self.chain_min, self.chain_max,
                                          self.domain_count)
        with _Suspend():
            self.rows.clear()
            for i, (start, end) in enumerate(ranges):
                row = self.rows.add()
                row.start = start
                row.end = end
                # A name the user typed survives a re-divide; an auto-generated
                # one is re-derived from the row's new range.
                if i < len(previous):
                    row.domain_id, kept = previous[i]
                    row.name = "" if is_default_domain_name(kept) else kept
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
                # A domain has to be created to own the residues this edit
                # orphaned. Apply the edited row's own (clamped) value now so
                # the field shows what it will keep, and let check() do the
                # structural part.
                edited = retiled[new_index]
                row.start = edited.start
                row.end = edited.end
                _state["pending_layout"] = retiled

        self._preview_layout(retiled, new_index)

    def _apply_pending_layout(self):
        """Write the re-tiled layout back onto the dialog's rows."""
        pending = _state["pending_layout"]
        _state["pending_layout"] = None
        if not pending:
            return

        with _Suspend():
            while len(self.rows) > len(pending):
                self.rows.remove(len(self.rows) - 1)
            while len(self.rows) < len(pending):
                self.rows.add()
            for row, spec in zip(self.rows, pending):
                row.name = spec.name
                row.start = spec.start
                row.end = spec.end
                row.domain_id = spec.domain_id or ""
            self._refresh_default_names()
            self.domain_count = len(self.rows)

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
            self.rows.move(len(self.rows) - 1, index + 1)
            self._refresh_default_names()
            self.domain_count = len(self.rows)

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
            self.domain_count = len(self.rows)

    def remove_row(self, index):
        """Delete a row, handing its residues to a neighbour.

        The residues have to go somewhere or the layout stops tiling the chain
        and a stretch silently belongs to no domain.
        """
        if not (0 <= index < len(self.rows)) or len(self.rows) <= 1:
            return
        with _Suspend():
            row = self.rows[index]
            if index > 0:
                self.rows[index - 1].end = row.end
            else:
                self.rows[index + 1].start = row.start
            self.rows.remove(index)
            self._refresh_default_names()
            self.domain_count = len(self.rows)

    def add_row(self):
        """Add a domain by halving the largest one, keeping the chain tiled."""
        if len(self.rows) >= MAX_DOMAINS:
            return
        widest = max(range(len(self.rows)),
                     key=lambda i: self.rows[i].end - self.rows[i].start)
        self.split_row(widest)

    # ------------------------------------------------------------------
    # Viewport preview
    # ------------------------------------------------------------------

    def _preview_layout(self, specs, edited_index):
        """Show the layout the user is heading towards, in the viewport.

        The whole layout is handed over, not just the edited row: the domains
        either side of a boundary move with it, and seeing them move is the
        point of previewing the chain rather than the one domain.
        """
        context = bpy.context
        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if molecule is None:
            return
        preview_layout(context, molecule, chain_token_from_item(chain_row),
                       specs, edited_index)

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
            self.domain_count = max(1, len(specs))
            self._refresh_default_names()

        _state["pending_layout"] = None
        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=520)

    def check(self, context):
        """Apply the deferred re-tile and force the dialog to re-layout.

        Blender only re-runs a dialog's draw() for property edits unless
        check() asks for it, and the row buttons add and remove rows rather
        than editing a property. This is also the safe place to rewrite the row
        collection after a boundary edit re-tiled the layout - see
        range_edited.
        """
        self._apply_pending_layout()
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
        for index, row in enumerate(self.rows):
            self._draw_columns(grid.row(align=True), row=row, index=index)

        add = body.row()
        add.enabled = len(self.rows) < MAX_DOMAINS
        add.operator("proteinblender.domain_splitter_add",
                     text="Add Domain", icon='ADD')

        self._draw_feedback(layout)

    # Column widths, shared by the header and every row so they line up
    # exactly. Blender lays a row out proportionally unless told otherwise, so
    # without fixed units the header labels drift away from their fields as the
    # name column grows.
    _COL_INDEX = 1.2
    _COL_NUMBER = 3.4
    _COL_TOOLS = 3.6

    def _draw_columns(self, line, row=None, index=0, header=False):
        """Draw one grid line: index, name, start, end, tools."""
        cell = line.row()
        cell.ui_units_x = self._COL_INDEX
        cell.label(text="" if header else f"{index + 1}.")

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

        op = tools.operator("proteinblender.domain_splitter_split",
                            text="", icon='MOD_ARRAY')
        op.index = index
        merge = tools.row(align=True)
        merge.enabled = index < len(self.rows) - 1
        op = merge.operator("proteinblender.domain_splitter_merge",
                            text="", icon='AUTOMERGE_ON')
        op.index = index
        remove = tools.row(align=True)
        remove.enabled = len(self.rows) > 1
        op = remove.operator("proteinblender.domain_splitter_remove",
                             text="", icon='X')
        op.index = index

    def _draw_feedback(self, layout):
        errors = domain_layout.validate_layout(self.current_specs(),
                                               self.chain_min, self.chain_max)
        if not errors:
            return
        box = layout.box()
        box.alert = True
        for message in errors:
            box.label(text=message, icon='ERROR')

    def execute(self, context):
        restore_preview(context)

        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if chain_row is None or molecule is None:
            self.report({'ERROR'}, "Could not resolve the chain to edit")
            type(self)._active_instance = None
            return {'CANCELLED'}

        token = chain_token_from_item(chain_row)
        if self.layout_json:
            try:
                specs = [domain_layout.DomainSpec(
                            name=entry.get("name", ""),
                            start=int(entry["start"]), end=int(entry["end"]),
                            domain_id=entry.get("domain_id") or None)
                         for entry in json.loads(self.layout_json)]
            except (ValueError, KeyError, TypeError) as exc:
                self.report({'ERROR'}, f"Bad layout_json: {exc}")
                type(self)._active_instance = None
                return {'CANCELLED'}
        else:
            specs = self.current_specs()

        # Validate before touching anything, so a rejected layout leaves the
        # chain name unchanged too rather than half-applying the dialog.
        chain_min, chain_max = domain_layout.chain_residue_range(molecule, token)
        errors = domain_layout.validate_layout(specs, chain_min, chain_max)
        if errors:
            for message in errors:
                self.report({'ERROR'}, message)
            type(self)._active_instance = None
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
            return {'CANCELLED'}

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


class PROTEINBLENDER_OT_domain_splitter_add(_RowEdit, Operator):
    """Add another domain by halving the largest one"""
    bl_idname = "proteinblender.domain_splitter_add"
    bl_label = "Add Domain"

    def edit(self, instance):
        instance.add_row()


class PROTEINBLENDER_OT_domain_splitter_split(_RowEdit, Operator):
    """Split this domain in half"""
    bl_idname = "proteinblender.domain_splitter_split"
    bl_label = "Split Domain"

    def edit(self, instance):
        instance.split_row(self.index)


class PROTEINBLENDER_OT_domain_splitter_merge(_RowEdit, Operator):
    """Merge this domain with the one below it"""
    bl_idname = "proteinblender.domain_splitter_merge"
    bl_label = "Merge With Next"

    def edit(self, instance):
        instance.merge_row(self.index)


class PROTEINBLENDER_OT_domain_splitter_remove(_RowEdit, Operator):
    """Remove this domain, giving its residues to a neighbour"""
    bl_idname = "proteinblender.domain_splitter_remove"
    bl_label = "Remove Domain"

    def edit(self, instance):
        instance.remove_row(self.index)


CLASSES = [
    PROTEINBLENDER_DomainLayoutRow,
    PROTEINBLENDER_OT_edit_chain_domains,
    PROTEINBLENDER_OT_domain_splitter_add,
    PROTEINBLENDER_OT_domain_splitter_split,
    PROTEINBLENDER_OT_domain_splitter_merge,
    PROTEINBLENDER_OT_domain_splitter_remove,
]
