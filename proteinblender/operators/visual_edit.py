"""The Visual Set-up block shared by the per-item edit dialogs.

Colour, representation, membrane force field and pivot used to live in one
selection-driven panel: pick rows in the Protein Outliner, then reach across to
a separate panel and hope it was talking about the rows you meant. They are now
edited *on the item*, from the pencil button on its own outliner row, and the
same block appears in all three dialogs:

    protein  ->  proteinblender.edit_protein_visuals
    chain    ->  proteinblender.edit_chain_domains   (the Domain Splitter)
    domain   ->  proteinblender.rename_domain

Two things this module has to work around, both of which fail silently rather
than raising (see ``operators/domain_splitter.py`` for the same two):

* the ``self`` Blender hands a property ``update=`` callback does not expose the
  operator's own methods, so every callback here routes through the live dialog
  recorded in ``_ACTIVE``;
* a plain class attribute is not reachable through that ``self`` either, so the
  re-entrancy guard is module state.

Only one dialog can be open at a time - they are all modal popups - so a single
module-level slot is exactly the right shape for "the dialog being edited".
"""

from bpy.types import Operator
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    StringProperty,
)

from ..core import visual_style
from ..utils.scene_manager import ProteinBlenderScene
# Imported by module path, not through the package: ``operators/__init__`` is
# still executing when this module is first loaded, so anything routed through
# it would resolve against a half-built package.
from .pivot_operators import find_row, row_objects


# The dialog currently on screen. Set from invoke() and again from draw(),
# because Blender rebuilds the operator instance behind a props dialog and the
# one that ran invoke() is not always the one whose properties get edited.
_ACTIVE = {"dialog": None}

_state = {
    # Guards the update callbacks while a dialog is loading its own initial
    # values off the objects it is about to edit. Without it, seeding the
    # colour field from the first target immediately writes that colour back
    # to every target, which quietly flattens a multi-coloured chain the
    # moment its dialog opens.
    "suspended": False,
    # The values the fields were seeded with, so execute() can tell an edit
    # from an untouched default. See commit_visual_edit for why that
    # distinction is the difference between "OK" and "flatten this chain".
    "seeded": None,
}


class _Suspend:
    def __enter__(self):
        _state["suspended"] = True

    def __exit__(self, *exc_info):
        _state["suspended"] = False
        return False


def active_dialog():
    return _ACTIVE["dialog"]


def _live():
    """The dialog an update callback should act on, or None."""
    if _state["suspended"]:
        return None
    return _ACTIVE["dialog"]


def _on_color_edited(_operator, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_visual_color(context)


def _on_style_edited(_operator, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_visual_style(context)


def _on_force_field_edited(_operator, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_visual_force_field(context)


class VisualEditMixin:
    """Colour / style / force-field properties plus the block that draws them.

    A dialog mixes this in, points ``visual_row()`` at the outliner row it is
    editing, and calls ``load_visual_state()`` from ``invoke()`` and
    ``draw_visual_setup()`` from ``draw()``. Everything else - resolving the
    row to objects, applying edits live, the pivot buttons - is handled here.

    Deliberately not an ``Operator`` subclass: it is never registered, and a
    bare unregistered Operator subclass trips the repository contract that
    every first-party operator appears in a CLASSES inventory. Blender collects
    property annotations across the whole MRO, so these still register on each
    concrete dialog.
    """

    vs_color: FloatVectorProperty(
        name="Color",
        description="Colour for every object this item covers",
        subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.8, 0.1, 0.8, 1.0),
        update=_on_color_edited,
    )
    vs_style: EnumProperty(
        name="Representation",
        description="How this item is drawn",
        items=visual_style.STYLE_ITEMS,
        default='surface',
        update=_on_style_edited,
    )
    vs_force_field: BoolProperty(
        name="Membrane Force Field",
        description="Part the lipids of any membrane around this item",
        default=False,
        update=_on_force_field_edited,
    )
    vs_force_field_spacing: FloatProperty(
        name="Spacing (nm)",
        description="How far the lipids stand off",
        default=1.5, min=0.0, soft_max=10.0,
        update=_on_force_field_edited,
    )

    # ------------------------------------------------------------------
    # What the dialog is editing. Subclasses supply the row.
    # ------------------------------------------------------------------

    def visual_row(self, context):
        """The outliner row this dialog edits, or None."""
        raise NotImplementedError

    def visual_objects(self, context):
        """Every Blender object the row draws through.

        ``row_objects``, not ``row_pivot_objects``: a colour or a style has to
        reach every domain of a protein, whereas its *pivot* may only be
        written to the molecule object. Using the pivot set here left a
        protein's domains wearing their old colour.
        """
        row = self.visual_row(context)
        if row is None:
            return []
        return row_objects(context, row)

    def force_field_objects(self, context):
        """The objects the membrane force field is set on - a narrower set.

        Colour, style and pivot are properties of *everything* a row draws,
        so they go to every object. A force field is not: it plants a hidden
        anchor Empty that the membrane parts around, and one protein wants one
        anchor at its centre, not one per domain. So a protein row owns its
        force field through the molecule object alone. A chain does keep one
        per domain - the domains of a split chain move independently, and a
        single anchor could not follow them.
        """
        row = self.visual_row(context)
        if row is not None and row.item_type in ('PROTEIN', 'DNA_RNA'):
            molecule = ProteinBlenderScene.get_instance().molecules.get(
                row.item_id)
            obj = getattr(molecule, 'object', None) if molecule else None
            return [obj] if obj is not None and obj.type == 'MESH' else []
        return [obj for obj in self.visual_objects(context)
                if obj.type == 'MESH']

    # ------------------------------------------------------------------
    # Seeding the fields from what is already on screen
    # ------------------------------------------------------------------

    def load_visual_state(self, context):
        """Fill the fields from the objects the dialog is about to edit.

        Colour and style are read from the *first* object, and the style falls
        back to the empty "Multiple" entry when the objects disagree - a chain
        whose domains are half cartoon and half surface has no single style to
        show, and displaying either one would be a lie the user then commits by
        pressing OK. Colour has no such sentinel (a colour field cannot show
        "mixed"), so it shows the first object's and only repaints the rest if
        the user actually picks something.

        Suspended throughout: these writes are property writes like any other,
        and unguarded they would fire the apply callbacks and flatten exactly
        the variety they are trying to report.
        """
        objects = self.visual_objects(context)
        if not objects:
            return

        with _Suspend():
            color = visual_style.get_object_color(objects[0])
            if len(color) == 3:
                color = (color[0], color[1], color[2], 1.0)
            for index in range(4):
                self.vs_color[index] = color[index]

            styles = {visual_style.get_object_style(obj) for obj in objects}
            styles.discard(None)
            self.vs_style = styles.pop() if len(styles) == 1 else ''

            owners = self.force_field_objects(context)
            first_owner = owners[0] if owners else objects[0]
            self.vs_force_field = bool(
                getattr(first_owner, "pb_force_field_enabled", False))
            self.vs_force_field_spacing = float(
                getattr(first_owner, "pb_force_field_spacing", 1.5))

        _state["seeded"] = self.visual_snapshot()

    def visual_snapshot(self):
        """The four fields as plain comparable values."""
        return {
            "color": tuple(round(channel, 6) for channel in self.vs_color),
            "style": self.vs_style,
            "force_field": bool(self.vs_force_field),
            "spacing": round(float(self.vs_force_field_spacing), 6),
        }

    # ------------------------------------------------------------------
    # Applying edits, live
    # ------------------------------------------------------------------

    def before_visual_edit(self, context):
        """Hook for a dialog that has to get out of its own way first.

        The Domain Splitter overrides it: it ghosts and re-colours the chain
        while a boundary is being dragged, and restores those colours when it
        closes. A colour set on top of a live preview would be restored right
        back off again, so the preview is dropped before the edit lands.
        """

    def apply_visual_color(self, context):
        self.before_visual_edit(context)
        for obj in self.visual_objects(context):
            visual_style.apply_color_to_object(obj, self.vs_color)
        self._after_visual_edit(context)

    def apply_visual_style(self, context):
        # The empty entry means "these objects disagree"; it is a thing the
        # list can display, not a style anything can be set to.
        if not self.vs_style:
            return
        self.before_visual_edit(context)
        row = self.visual_row(context)
        for obj in self.visual_objects(context):
            visual_style.apply_style_to_object(obj, self.vs_style)
        self._persist_style(context, row)
        self._after_visual_edit(context)

    def apply_visual_force_field(self, context):
        for obj in self.force_field_objects(context):
            # Assigning re-runs the property's own update, which is what
            # rebuilds the membranes; only write when it actually changes.
            if getattr(obj, "pb_force_field_enabled", False) != self.vs_force_field:
                obj.pb_force_field_enabled = self.vs_force_field
            if obj.pb_force_field_enabled:
                obj.pb_force_field_spacing = self.vs_force_field_spacing
        self._after_visual_edit(context)

    def _persist_style(self, context, row):
        """Mirror the new style onto the model, not just the node trees.

        ``Domain.style`` / ``MoleculeWrapper.style`` are what a save/load and
        a newly-created domain inherit from; writing only the geometry nodes
        leaves the next domain built on this chain wearing the old style.
        """
        scene_manager = ProteinBlenderScene.get_instance()
        if row is not None and row.item_type in ('PROTEIN', 'DNA_RNA'):
            molecule = scene_manager.molecules.get(row.item_id)
            if molecule is None:
                return
            molecule.style = self.vs_style
            for domain in molecule.domains.values():
                domain.style = self.vs_style
            return

        # Chains, domains, and the row-less case: match by object name, which
        # works whatever the dialog resolved its objects through.
        names = {obj.name for obj in self.visual_objects(context)}
        for molecule in scene_manager.molecules.values():
            for domain in getattr(molecule, 'domains', {}).values():
                obj = getattr(domain, 'object', None)
                if obj is not None and obj.name in names:
                    domain.style = self.vs_style

    def _after_visual_edit(self, context):
        for window in getattr(context.window_manager, "windows", []):
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'PROPERTIES'):
                    area.tag_redraw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw_visual_setup(self, layout, context):
        """The Visual Set-up block: colour, representation, pivot, force field."""
        _ACTIVE["dialog"] = self

        row = self.visual_row(context)
        objects = self.visual_objects(context)

        box = layout.box()
        box.label(text="Visual Set-up", icon='SHADING_RENDERED')

        if not objects:
            box.label(text="Nothing to style on this item", icon='INFO')
            return

        grid = box.row(align=True)
        left = grid.column(align=True)
        left.label(text="Color", icon='COLOR')
        left.prop(self, "vs_color", text="")
        right = grid.column(align=True)
        right.label(text="Representation", icon='MESH_UVSPHERE')
        right.prop(self, "vs_style", text="")

        box.separator()
        pivot = box.column(align=True)
        pivot.label(text="Pivot Point", icon='PIVOT_CURSOR')
        # First / Center / Last only. "Custom" is not a fourth choice here: it
        # is a placement *mode* that needs the viewport and the move gizmo, and
        # launching it from a dialog would tear it straight back down when the
        # dialog closed. It lives on the outliner row instead, where the button
        # stays on screen for the whole placement.
        buttons = pivot.row(align=True)
        buttons.scale_y = 1.2
        for operator_id, label in (("proteinblender.set_pivot_first", "Start"),
                                   ("proteinblender.set_pivot_center", "Center"),
                                   ("proteinblender.set_pivot_last", "End")):
            operator = buttons.operator(operator_id, text=label)
            operator.item_id = row.item_id if row is not None else ""

        owners = self.force_field_objects(context)
        if owners:
            box.separator()
            force_field = box.box()
            force_field.prop(self, "vs_force_field", icon='FORCE_FORCE')
            if self.vs_force_field:
                force_field.prop(self, "vs_force_field_spacing")
                force_field.label(
                    text=f"Lipids part around {len(owners)} object(s) "
                         f"in any membrane.",
                    icon='INFO')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin_visual_edit(self, context):
        """Call from ``invoke()``, after the row is resolvable."""
        _ACTIVE["dialog"] = self
        self.load_visual_state(context)

    def end_visual_edit(self):
        """Call from ``execute()`` and ``cancel()``.

        Every edit has already been applied live, so there is nothing to
        commit here - this only lets go of the dialog so a stale instance
        cannot be handed a later callback.

        Cleared unconditionally rather than only when the slot still holds
        *this* instance: Blender rebuilds the operator behind a props dialog,
        so "this instance" is not a question the slot can answer, and only one
        dialog is ever open at a time anyway.
        """
        _ACTIVE["dialog"] = None
        _state["seeded"] = None

    def commit_visual_edit(self, context):
        """Apply, from ``execute()``, the fields the *user* actually chose.

        Two things have to be told apart here, and getting either wrong is a
        silent data loss rather than an error.

        A field is only applied when the caller set it. Headless Blender
        routes INVOKE_DEFAULT straight to execute(), so a script never gets
        the seeding invoke() does, and applying unconditionally there would
        paint the default purple over an object whose colour the caller never
        mentioned.

        A field is also only applied when it *differs from what it was seeded
        with*. Opening a dialog writes every field, which marks them all set,
        so "set" alone cannot distinguish a choice from a default. A chain
        whose domains are different colours shows the first domain's colour -
        the field has nowhere to display "mixed" - and re-applying that on the
        way out would repaint the whole chain in it. Pressing OK without
        touching anything has to change nothing.
        """
        seeded = _state["seeded"]
        current = self.visual_snapshot()

        def chosen(prop, key):
            if not self.properties.is_property_set(prop):
                return False
            return seeded is None or seeded[key] != current[key]

        if chosen("vs_color", "color"):
            self.apply_visual_color(context)
        if chosen("vs_style", "style"):
            self.apply_visual_style(context)
        if (chosen("vs_force_field", "force_field")
                or chosen("vs_force_field_spacing", "spacing")):
            self.apply_visual_force_field(context)


class PROTEINBLENDER_OT_edit_protein_visuals(VisualEditMixin, Operator):
    """Edit this protein's colour, representation, force field and pivot"""
    bl_idname = "proteinblender.edit_protein_visuals"
    bl_label = "Edit Protein"
    bl_options = {'REGISTER', 'UNDO'}

    item_id: StringProperty(
        name="Protein Row",
        description="item_id of the protein row in the Protein Outliner")

    def visual_row(self, context):
        return find_row(context.scene, self.item_id)

    def invoke(self, context, event):
        if self.visual_row(context) is None:
            self.report({'ERROR'}, "Could not resolve the protein to edit")
            return {'CANCELLED'}
        self.begin_visual_edit(context)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def check(self, context):
        """Re-draw after any field changes.

        The force-field spacing slider only exists while the toggle is on, so
        the dialog has to be re-laid-out when it flips.
        """
        return True

    def draw(self, context):
        layout = self.layout
        row = self.visual_row(context)
        if row is not None:
            layout.label(text=row.name, icon=row.icon or 'MESH_DATA')
        self.draw_visual_setup(layout, context)

    def execute(self, context):
        row = self.visual_row(context)
        if row is None:
            self.end_visual_edit()
            self.report({'ERROR'}, "Could not resolve the protein to edit")
            return {'CANCELLED'}
        self.commit_visual_edit(context)
        self.end_visual_edit()
        return {'FINISHED'}

    def cancel(self, context):
        self.end_visual_edit()


CLASSES = [
    PROTEINBLENDER_OT_edit_protein_visuals,
]
