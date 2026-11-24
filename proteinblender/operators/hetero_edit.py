"""The pencil on a Ligands / Ions / Water row: representation, color, size.

A smaller cousin of the Visual Set-up block (operators/visual_edit.py). A group
of ligands is not a protein part: it has no backbone to draw as a cartoon, no
B-factor motion worth animating and no pivot of its own (it moves with its
protein), so it gets its own dialog with only the choices that make sense:

* Representation, limited per kind (core.hetero_groups.STYLES_FOR_KIND);
* Color, by element (carbon takes the color, N/O/P/S keep theirs) or solid;
* Size, scaling the spheres and bonds of whichever style is drawn.

Edits apply live, as in the other pencil dialogs. Every value lives on the
group's node tree, so all of it can be keyed from Create Keyframe.

The same two Blender quirks as visual_edit.py apply: an ``update=`` callback's
``self`` cannot reach the operator's methods, so callbacks go through the live
dialog recorded in ``_ACTIVE``, and seeding the fields from the object must not
fire those callbacks.
"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty

from ..core import hetero_groups, visual_style
from .pivot_operators import find_row

_ACTIVE = {"dialog": None, "suspended": False}


def _group_object(row):
    if row is None or row.item_type != 'HETERO' or not row.object_name:
        return None
    return bpy.data.objects.get(row.object_name)


def styles_for(row):
    """The style identifiers offered for this row, in menu order."""
    kind = hetero_groups.kind_of(_group_object(row))
    return list(hetero_groups.STYLES_FOR_KIND.get(kind, ()))


_LABELS = {identifier: (name, description)
           for identifier, name, description in visual_style.REAL_STYLE_ITEMS}
# Every identifier keeps one fixed number, so the dynamic enum's stored value
# never points at a different style when the list is filtered.
_NUMBERS = {identifier: number for number, (identifier, *_rest)
            in enumerate(visual_style.REAL_STYLE_ITEMS)}

_ITEMS_CACHE = []   # Blender requires dynamic enum strings to stay referenced


def _style_items(self, context):
    row = find_row(context.scene, self.item_id) if context else None
    offered = styles_for(row) or list(_NUMBERS)
    items = [(s, *_LABELS[s], _NUMBERS[s]) for s in offered]
    _ITEMS_CACHE[:] = items
    return items


def _live():
    return None if _ACTIVE["suspended"] else _ACTIVE["dialog"]


def _on_style(_self, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_style(context)


def _on_color(_self, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_color(context)


def _on_size(_self, context):
    dialog = _live()
    if dialog is not None:
        dialog.apply_size(context)


class PROTEINBLENDER_OT_edit_hetero_group(Operator):
    """Change how this protein's ligands, ions or water are drawn"""
    bl_idname = "proteinblender.edit_hetero_group"
    bl_label = "Edit Ligands / Ions / Water"
    bl_options = {'REGISTER', 'UNDO'}

    item_id: StringProperty(name="Row", description="item_id of the Ligands / Ions / Water row")

    vs_style: EnumProperty(name="Representation", description="How these atoms are drawn",
                           items=_style_items, update=_on_style)
    vs_color: FloatVectorProperty(
        name="Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.2, 0.78, 0.35, 1.0), update=_on_color,
        description="Carbon color when coloring by element, otherwise the color of every atom")
    vs_by_element: BoolProperty(
        name="Color by Element", default=True, update=_on_color,
        description="Keep nitrogen blue, oxygen red and so on; only carbons take the color")
    vs_size: FloatProperty(
        name="Size", default=1.0, min=0.0, soft_min=0.1, soft_max=3.0, max=10.0,
        precision=2, update=_on_size,
        description="Scale the atoms and bonds: 1 is the representation's own size")

    # ------------------------------------------------------------------

    def _row(self, context):
        return find_row(context.scene, self.item_id)

    def _object(self, context):
        return _group_object(self._row(context))

    def apply_style(self, context):
        obj = self._object(context)
        if obj is not None:
            # The Size node is not part of the style, so the new style is
            # drawn at the size the group already had.
            hetero_groups.set_style(obj, self.vs_style)
        _redraw(context)

    def apply_color(self, context):
        obj = self._object(context)
        if obj is not None:
            hetero_groups.set_color(obj, self.vs_color, element=self.vs_by_element)
        _redraw(context)

    def apply_size(self, context):
        obj = self._object(context)
        if obj is not None:
            hetero_groups.set_size(obj, self.vs_size)
        _redraw(context)

    def _seed(self, obj):
        _ACTIVE["suspended"] = True
        try:
            style = hetero_groups.get_style(obj)
            if style in hetero_groups.STYLES_FOR_KIND.get(hetero_groups.kind_of(obj), ()):
                self.vs_style = style
            color = hetero_groups.get_color(obj)
            if color is not None:
                self.vs_color = color
            self.vs_by_element = hetero_groups.by_element(obj)
            self.vs_size = hetero_groups.get_size(obj)
        finally:
            _ACTIVE["suspended"] = False

    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = self._object(context)
        if obj is None:
            self.report({'ERROR'}, "Could not find the ligands, ions or water to edit")
            return {'CANCELLED'}
        self._seed(obj)
        _ACTIVE["dialog"] = self
        return context.window_manager.invoke_props_dialog(self, width=360)

    def check(self, context):
        return True

    def draw(self, context):
        _ACTIVE["dialog"] = self
        layout = self.layout
        row = self._row(context)
        if row is not None:
            layout.label(text=row.name, icon=row.icon or 'PHYSICS')
        box = layout.box()
        box.label(text="Visual Set-up", icon='SHADING_RENDERED')

        styles = box.column(align=True)
        styles.label(text="Representation", icon='MESH_UVSPHERE')
        styles.prop(self, "vs_style", text="")
        # A single entry is still shown, greyed, so it is clear what draws them.
        styles.enabled = len(styles_for(row)) > 1

        box.separator()
        colors = box.column(align=True)
        colors.label(text="Carbon Color" if self.vs_by_element else "Color", icon='COLOR')
        colors.prop(self, "vs_color", text="")
        colors.prop(self, "vs_by_element")

        box.separator()
        box.prop(self, "vs_size", slider=True)
        box.label(text="Visibility, color and size can be keyed in Create Keyframe.",
                  icon='KEYFRAME')

    def execute(self, context):
        """Headless and scripted calls land here without invoke: apply what
        the caller set. From the dialog, everything is already applied."""
        obj = self._object(context)
        try:
            if obj is None:
                self.report({'ERROR'}, "Could not find the ligands, ions or water to edit")
                return {'CANCELLED'}
            if _ACTIVE["dialog"] is None:
                props = self.properties
                if props.is_property_set("vs_style"):
                    self.apply_style(context)
                if props.is_property_set("vs_color") or props.is_property_set("vs_by_element"):
                    color = (self.vs_color if props.is_property_set("vs_color")
                             else hetero_groups.get_color(obj))
                    element = (self.vs_by_element if props.is_property_set("vs_by_element")
                               else None)
                    hetero_groups.set_color(obj, color, element=element)
                if props.is_property_set("vs_size"):
                    self.apply_size(context)
                _redraw(context)
            return {'FINISHED'}
        finally:
            _ACTIVE["dialog"] = None

    def cancel(self, context):
        _ACTIVE["dialog"] = None


def _redraw(context):
    # The row's swatch shows the group's color, so it follows the dialog.
    from ..core.outliner_colors import sync_outliner_colors
    sync_outliner_colors(context)
    for window in getattr(context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type in ('VIEW_3D', 'PROPERTIES'):
                area.tag_redraw()


CLASSES = [PROTEINBLENDER_OT_edit_hetero_group]
