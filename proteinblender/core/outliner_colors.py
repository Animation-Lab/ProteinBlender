"""The colour swatches on the Protein Outliner's rows.

Every protein, chain and domain row carries a ``row_color`` swatch
(`ProteinOutlinerItem.row_color`): click it, pick a colour, and the item is
recoloured on the spot - no dialog to open. This module owns both directions
of that binding:

* :func:`apply_row_color` - the property's update callback. Routes the pick
  through the same per-item apply helpers the Visual Set-up dialogs use, so a
  chain pick reaches every domain of the chain and a protein pick reaches the
  whole molecule.
* :func:`sync_outliner_colors` - reads what every row currently looks like
  back into its swatch. Called after an outliner rebuild and after anything
  else recolours objects (the Visual Set-up dialogs, the Domain Splitter), so
  the swatches track the viewport instead of going stale.

A row whose parts disagree (a protein with differently coloured chains) shows
:data:`operators.visual_edit.MIXED_COLOR` - the same neutral grey the dialogs
use - because a swatch has no way to render "mixed". Picking a colour on such
a row resolves the disagreement by applying it to everything the row covers.

Seeding a swatch is a property write like any other, so it would fire the
apply callback and repaint the item with its own colour - worse, a mixed row
would be flattened to grey. The module guard suspends the callback while
swatches are being seeded, the same pattern the dialogs use.
"""

import bpy

_state = {
    # True while sync_outliner_colors is writing swatches, so the writes do
    # not re-enter apply_row_color and repaint items with their own colours.
    "suspended": False,
}

# Row types that carry a colour swatch. DNA/RNA strands and membranes colour
# through their own builders; puppets have no colour of their own.
COLORABLE_TYPES = ('PROTEIN', 'CHAIN', 'DOMAIN')


class _Suspend:
    def __enter__(self):
        _state["suspended"] = True

    def __exit__(self, *exc_info):
        _state["suspended"] = False
        return False


def row_has_swatch(item):
    """Whether this outliner row gets a colour swatch.

    Reference rows (a chain shown again under a puppet) do not: their
    original row is the canonical place to recolour them.
    """
    return (item.item_type in COLORABLE_TYPES
            and "_ref_" not in item.item_id
            and item.item_id != "puppets_separator")


def apply_row_color(item, context):
    """Recolour everything ``item`` covers with its swatch's colour."""
    if _state["suspended"] or not row_has_swatch(item):
        return

    from ..utils.scene_manager import ProteinBlenderScene
    from .visual_style import (apply_chain_color_direct,
                               apply_domain_color_direct,
                               apply_protein_color_direct)

    scene_manager = ProteinBlenderScene.get_instance()
    color = tuple(item.row_color)
    if item.item_type == 'PROTEIN':
        apply_protein_color_direct(scene_manager, item, color)
    elif item.item_type == 'CHAIN':
        apply_chain_color_direct(scene_manager, item, color)
    elif item.item_type == 'DOMAIN':
        apply_domain_color_direct(scene_manager, item, color)

    # Recolouring one row moves what its relatives look like too: a domain
    # pick can turn its chain "mixed", a chain pick can un-mix its protein.
    sync_outliner_colors(context)

    for window in getattr(context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type in ('VIEW_3D', 'PROPERTIES'):
                area.tag_redraw()


def sync_outliner_colors(context=None):
    """Point every row's swatch at the colour its item currently shows."""
    if context is None:
        context = bpy.context
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "outliner_items"):
        return

    # Function-level import: operators.visual_edit reaches back into utils
    # and core at import time, and this module is imported during property
    # registration.
    from ..operators.visual_edit import (appearance_objects_for_row,
                                         seed_from_objects)

    with _Suspend():
        for item in scene.outliner_items:
            if not row_has_swatch(item):
                continue
            objects = appearance_objects_for_row(context, item)
            if not objects:
                continue
            color, _mixed, _style = seed_from_objects(objects)
            current = tuple(round(float(c), 4) for c in item.row_color)
            wanted = tuple(round(float(c), 4) for c in color)
            if current != wanted:
                item.row_color = color
