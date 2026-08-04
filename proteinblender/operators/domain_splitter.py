"""The Domain Splitter dialog - edit a chain's name and its domain layout.

Opened from the pencil button on a chain row in the Protein Outliner. The
dialog edits a *desired layout* (a list of named residue ranges) and hands it
to :mod:`core.domain_layout`, which reconciles it against the chain's current
domains rather than rebuilding them - see that module for why that matters.

Nothing here mutates the model. `draw()` only reads, the row-editing buttons
only touch the dialog's own rows, and the model is changed once, in `execute`.

The row buttons ("Build Domains", split, merge, remove) reach the live modal
operator through ``_active_instance``. A modal dialog is not in
``wm.operators``, so a button inside it cannot address the instance any other
way; this is the same workaround ``keyframe_operators`` uses.
"""

from __future__ import annotations

import json

import bpy
from bpy.props import (BoolProperty, CollectionProperty, IntProperty,
                       StringProperty)
from bpy.types import Operator, PropertyGroup

from ..core import domain_layout
from ..utils.chain_utils import chain_token_from_item
from ..utils.scene_manager import ProteinBlenderScene

# Blender caps how tall a dialog can usefully get; past this the row list stops
# being readable and the user is better served splitting in stages.
MAX_DOMAINS = 32


def _active():
    return PROTEINBLENDER_OT_edit_chain_domains._active_instance


def _clamp_row(row, context):
    """Keep a row's start/end inside the chain and correctly ordered.

    Runs as the update callback on both fields so the numbers a user types are
    corrected as they type, instead of failing validation at OK time.
    """
    instance = _active()
    if instance is None:
        return
    low, high = instance.chain_min, instance.chain_max
    start = max(low, min(high, row.start))
    end = max(low, min(high, row.end))
    if end < start:
        end = start
    if row.start != start:
        row.start = start
    if row.end != end:
        row.end = end


class PROTEINBLENDER_DomainLayoutRow(PropertyGroup):
    """One editable domain row inside the Domain Splitter dialog."""
    name: StringProperty(name="Name", description="Name for this domain")
    start: IntProperty(
        name="Start", description="First residue in this domain (inclusive)",
        update=_clamp_row)
    end: IntProperty(
        name="End", description="Last residue in this domain (inclusive)",
        update=_clamp_row)
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
    _active_instance = None

    item_id: StringProperty(
        name="Chain Row",
        description="item_id of the chain row in the Protein Outliner")
    chain_name: StringProperty(
        name="Chain Name",
        description="Display name for this chain in the Protein Outliner")
    domain_count: IntProperty(
        name="Number of Domains",
        description="How many domains to divide this chain into",
        default=2, min=1, max=MAX_DOMAINS)
    rows: CollectionProperty(type=PROTEINBLENDER_DomainLayoutRow)

    # Chain bounds, cached on the instance so draw() and the clamp callback do
    # not have to re-derive them on every redraw.
    chain_min: IntProperty(default=1)
    chain_max: IntProperty(default=1)

    built: BoolProperty(
        default=False,
        description="Whether the domain rows have been populated yet")

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

    # ------------------------------------------------------------------
    # Row editing, called by the in-dialog buttons
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
        self.domain_count = max(1, len(specs))

    def current_specs(self):
        return [domain_layout.DomainSpec(
                    name=row.name, start=row.start, end=row.end,
                    domain_id=row.domain_id or None)
                for row in self.rows]

    def rebuild_even(self):
        """Divide the chain evenly into ``domain_count`` rows.

        Existing domains are re-assigned to rows positionally, so reshaping a
        chain from 4 domains to 3 keeps three real domains (with their puppet
        membership, linkers and animation) and deletes only the fourth, rather
        than replacing all of them.
        """
        previous = [r.domain_id for r in self.rows if r.domain_id]
        ranges = domain_layout.even_split(self.chain_min, self.chain_max,
                                          self.domain_count)
        self.rows.clear()
        for i, (start, end) in enumerate(ranges):
            row = self.rows.add()
            row.start = start
            row.end = end
            # Names are reset because Build is a "start over with N even
            # pieces" action: carrying the old names over left the first row
            # labelled after the whole chain ("Chain A") while its siblings read
            # "Domain 2/3/4". The ids still carry over, which is what actually
            # preserves puppets, linkers and animation.
            row.name = f"Domain {i + 1}"
            if i < len(previous):
                row.domain_id = previous[i]
        self.built = True

    def split_row(self, index):
        """Cut one row in half, giving the new half a fresh (unassigned) row."""
        if not (0 <= index < len(self.rows)):
            return
        row = self.rows[index]
        if row.end - row.start < 1:
            return
        midpoint = row.start + (row.end - row.start) // 2
        tail_start, tail_end, tail_name = midpoint + 1, row.end, row.name
        row.end = midpoint

        new_row = self.rows.add()
        new_row.name = f"{tail_name} (2)" if tail_name else ""
        new_row.start = tail_start
        new_row.end = tail_end
        self.rows.move(len(self.rows) - 1, index + 1)
        self.domain_count = len(self.rows)

    def merge_row(self, index):
        """Absorb the following row into this one."""
        if not (0 <= index < len(self.rows) - 1):
            return
        row, nxt = self.rows[index], self.rows[index + 1]
        row.start = min(row.start, nxt.start)
        row.end = max(row.end, nxt.end)
        self.rows.remove(index + 1)
        self.domain_count = len(self.rows)

    def remove_row(self, index):
        if 0 <= index < len(self.rows) and len(self.rows) > 1:
            self.rows.remove(index)
            self.domain_count = len(self.rows)

    def add_row(self):
        """Append a row covering the first uncovered stretch of the chain."""
        if len(self.rows) >= MAX_DOMAINS:
            return
        gaps = domain_layout.coverage_gaps(self.current_specs(),
                                           self.chain_min, self.chain_max)
        row = self.rows.add()
        if gaps:
            row.start, row.end = gaps[0]
        else:
            row.start = row.end = self.chain_max
        row.name = f"Domain {len(self.rows)}"
        self.domain_count = len(self.rows)

    # ------------------------------------------------------------------
    # Invoke / draw / execute
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        chain_row = self._chain_row(context)
        molecule = self._molecule(context, chain_row)
        if chain_row is None or molecule is None:
            self.report({'ERROR'}, "Could not resolve the chain to edit")
            return {'CANCELLED'}

        token = chain_token_from_item(chain_row)
        self.chain_min, self.chain_max = domain_layout.chain_residue_range(
            molecule, token)
        self.chain_name = chain_row.name

        specs = domain_layout.current_layout(molecule, token)
        self.load_rows(specs)
        # A chain that is still one whole-chain domain has not been split yet,
        # so present the drawing's first step ("choose a count, then Build")
        # rather than a single row the user has to dismantle by hand.
        whole = (len(specs) == 1 and specs[0].start == self.chain_min
                 and specs[0].end == self.chain_max)
        self.built = bool(specs) and not whole
        if whole:
            self.domain_count = 2

        type(self)._active_instance = self
        return context.window_manager.invoke_props_dialog(self, width=520)

    def check(self, context):
        """Force the dialog to re-layout after every change.

        The row buttons (Build/split/merge/remove) add and remove rows rather
        than editing a property, and Blender only re-runs a dialog's draw() for
        property edits unless check() asks for it. Without this, pressing Build
        Domains updates the rows but the popup keeps showing the old layout.
        """
        return True

    def draw(self, context):
        layout = self.layout
        type(self)._active_instance = self

        header = layout.box()
        header.prop(self, "chain_name", text="Chain Name")

        header.prop(self, "domain_count")
        header.operator("proteinblender.domain_splitter_build",
                        text="Build Domains", icon='FILE_REFRESH')

        if not self.built:
            info = layout.box()
            info.label(text="Choose how many domains, then press Build Domains.",
                       icon='INFO')
            return

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
        specs = self.current_specs()
        errors = domain_layout.validate_layout(specs, self.chain_min,
                                               self.chain_max)
        if errors:
            box = layout.box()
            box.alert = True
            for message in errors:
                box.label(text=message, icon='ERROR')
            return

        gaps = domain_layout.coverage_gaps(specs, self.chain_min, self.chain_max)
        if gaps:
            box = layout.box()
            spans = ", ".join(f"{a}-{b}" for a, b in gaps)
            box.label(text=f"Not covered by any domain: {spans}", icon='INFO')

    def execute(self, context):
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
            self.chain_min, self.chain_max = domain_layout.chain_residue_range(
                molecule, token)
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
        type(self)._active_instance = None


def _tag_redraw(context):
    """Redraw the panels showing domains, headless-safe."""
    if getattr(context, "area", None) is not None:
        context.area.tag_redraw()
        return
    for window in getattr(context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'PROPERTIES'}:
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


class PROTEINBLENDER_OT_domain_splitter_build(_RowEdit, Operator):
    """Divide the chain evenly into the chosen number of domains"""
    bl_idname = "proteinblender.domain_splitter_build"
    bl_label = "Build Domains"

    def edit(self, instance):
        instance.rebuild_even()


class PROTEINBLENDER_OT_domain_splitter_add(_RowEdit, Operator):
    """Add another domain row"""
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
    """Remove this domain row"""
    bl_idname = "proteinblender.domain_splitter_remove"
    bl_label = "Remove Domain"

    def edit(self, instance):
        instance.remove_row(self.index)


CLASSES = [
    PROTEINBLENDER_DomainLayoutRow,
    PROTEINBLENDER_OT_edit_chain_domains,
    PROTEINBLENDER_OT_domain_splitter_build,
    PROTEINBLENDER_OT_domain_splitter_add,
    PROTEINBLENDER_OT_domain_splitter_split,
    PROTEINBLENDER_OT_domain_splitter_merge,
    PROTEINBLENDER_OT_domain_splitter_remove,
]
