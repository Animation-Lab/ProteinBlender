"""Operators for the Membrane Builder.

The membrane is represented by ONE Mesh object (the "membrane root"). All
related objects — Lattice deformer, hole controllers — are children of the
root, and the root carries the GN modifier that turns the flat plane into a
bilayer of lipid instances.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from typing import Optional

from . import lipid_assets
from . import force_fields
from .membrane_geometry import (
    NM_PER_BU,
    MAX_HOLES,
    SHAPE_FLAT,
    SHAPE_MODE_INT,
    get_or_build_membrane_gn_tree,
    set_membrane_colors,
    build_membrane_lattice,
    build_membrane_base_mesh,
    update_base_mesh,
    update_lattice_for_shape,
)


GN_MOD_NAME = "PB_Membrane_GN"
LATTICE_MOD_NAME = "PB_Membrane_Lattice"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_membrane_name(prefix: str) -> str:
    """Return the next free Membrane_NNN-style name."""
    counter = 1
    while True:
        name = f"{prefix}_{counter:03d}"
        if name not in bpy.data.objects:
            return name
        counter += 1


def _next_hole_name(membrane_name: str) -> str:
    counter = 1
    while True:
        name = f"{membrane_name}.hole.{counter:03d}"
        if name not in bpy.data.objects:
            return name
        counter += 1


def _ensure_membrane_collection(scene: bpy.types.Scene,
                                  membrane_name: str) -> bpy.types.Collection:
    """Create-or-find a per-membrane collection so the root + children + lattice
    + holes are all grouped together in the outliner."""
    coll_name = f"{membrane_name}_Group"
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        scene.collection.children.link(coll)
    return coll


def _link_to_coll(coll: bpy.types.Collection, obj: bpy.types.Object) -> None:
    """Link obj to coll if not already linked, and remove from scene root if so."""
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    # Best-effort remove from the scene root if it was added there by an op.
    scene_root = bpy.context.scene.collection
    if obj.name in scene_root.objects and coll is not scene_root:
        try:
            scene_root.objects.unlink(obj)
        except Exception:
            pass


def _get_membrane_root(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    """Resolve any related object (membrane root, lattice, hole) to the
    membrane root."""
    if obj is None:
        return None
    if obj.get("pb_is_membrane", False):
        return obj
    owner = obj.get("pb_membrane_owner")
    if owner:
        candidate = bpy.data.objects.get(owner)
        if candidate is not None and candidate.get("pb_is_membrane", False):
            return candidate
    return None


def _get_gn_modifier(obj: bpy.types.Object) -> Optional[bpy.types.Modifier]:
    """Return the membrane GN modifier on obj, or None."""
    for mod in obj.modifiers:
        if mod.type == "NODES" and mod.name == GN_MOD_NAME:
            return mod
    return None


def _set_mod_input(mod: bpy.types.Modifier, socket_name: str, value) -> None:
    """Set a value on a GN modifier input socket.

    Modifier inputs are addressed by the *interface socket's identifier*
    (``Socket_N`` strings), not the socket name. We look up the identifier
    via the modifier's node_group.interface.
    """
    ng = mod.node_group
    if ng is None:
        return
    for item in ng.interface.items_tree:
        if hasattr(item, "in_out") and item.in_out == "INPUT" and item.name == socket_name:
            try:
                mod[item.identifier] = value
                return
            except Exception as e:
                print(f"[membrane] Failed to set '{socket_name}': {e}")
                return
    # If not found, no-op.


def _refresh_modifier(mod: bpy.types.Modifier) -> None:
    """Force the modifier to recompute (Blender doesn't always re-eval on prop set).

    Toggling show_render flips the visibility flag for a re-eval kick. We
    also tag the owning object so the depsgraph treats it as dirty — for
    Collection-typed inputs (Lipid Collection), writing ``mod[id] = coll``
    alone does NOT invalidate the cached Collection Info contents, so the
    viewport keeps showing the previous style until something else dirties
    the object. ``update_tag()`` forces a re-evaluation.
    """
    try:
        mod.show_render = not mod.show_render
        mod.show_render = not mod.show_render
        obj = mod.id_data
        if obj is not None:
            obj.update_tag()
    except Exception:
        pass


def apply_props_to_membrane(root_obj: bpy.types.Object, props,
                              defer_refresh: bool = False) -> None:
    """Push every scene-level property value to the membrane's GN modifier
    inputs AND to the persistent custom-property store on the root.

    The custom-property store is what ``sync_props_from_object`` reads back
    when the user re-selects this membrane later.

    ``defer_refresh=True`` skips the trailing modifier refresh — used by
    Build Membrane so the three back-to-back input-write phases (props,
    holes, FFs) only trigger one GN evaluation instead of three.
    """
    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return

    # Shape change is destructive — rebuild the base mesh + lattice in
    # place before pushing the other settings. The mesh and lattice
    # datablocks themselves are kept so all the modifier references
    # remain valid.
    new_shape = str(props.shape)
    old_shape = str(root_obj.get("pb_mem_shape", SHAPE_FLAT))
    needs_shape_rebuild = (new_shape != old_shape)
    if needs_shape_rebuild:
        _rebuild_membrane_for_shape(root_obj, props)

    _set_mod_input(mod, "Shape Mode", int(SHAPE_MODE_INT[new_shape]))
    _set_mod_input(mod, "Sphere Radius (nm)", float(props.radius))
    _set_mod_input(mod, "Density (per nm²)", float(props.density))
    _set_mod_input(mod, "Bilayer Thickness (nm)", float(props.bilayer_thickness))
    _set_mod_input(mod, "Random Rotation", bool(props.random_rotation))
    _set_mod_input(mod, "Animate Bob", bool(props.animate_bob))
    _set_mod_input(mod, "Bob Amplitude (nm)", float(props.bob_amplitude))
    _set_mod_input(mod, "Bob Speed", float(props.bob_speed))

    # Render style — swap which collection feeds the GN modifier and push
    # the matching variant count so the per-point random Instance Index
    # stays inside the collection's range. Also push the per-style outer
    # extent so the Bilayer Thickness slider stays calibrated against the
    # visible bilayer thickness regardless of style.
    style = str(props.render_style)
    _set_mod_input(mod, "Lipid Collection",
                   lipid_assets.get_or_build_lipid_collection(style))
    _set_mod_input(mod, "Lipid Variant Count",
                   lipid_assets.variant_count_for_style(style))
    _set_mod_input(mod, "Lipid Outer Extent (nm)",
                   lipid_assets.outer_extent_for_style(style))

    # Mirror onto the root as custom properties (so size-edit operator can
    # detect what's needed, and so we can re-sync to panel when reselected).
    root_obj["pb_mem_shape"] = new_shape
    root_obj["pb_mem_density"] = float(props.density)
    root_obj["pb_mem_bilayer_thickness"] = float(props.bilayer_thickness)
    root_obj["pb_mem_random_rotation"] = bool(props.random_rotation)
    root_obj["pb_mem_animate_bob"] = bool(props.animate_bob)
    root_obj["pb_mem_bob_amplitude"] = float(props.bob_amplitude)
    root_obj["pb_mem_bob_speed"] = float(props.bob_speed)
    root_obj["pb_mem_render_style"] = style
    root_obj["pb_mem_width"] = float(props.width)
    root_obj["pb_mem_height"] = float(props.height)
    root_obj["pb_mem_radius"] = float(props.radius)

    # Update shared materials in case any colour prop was changed.
    set_membrane_colors(
        root_obj,
        tuple(props.color_head),
        tuple(props.color_tail),
        tuple(props.color_surface),
    )
    root_obj["pb_mem_color_head"] = list(props.color_head)
    root_obj["pb_mem_color_tail"] = list(props.color_tail)
    root_obj["pb_mem_color_surface"] = list(props.color_surface)

    if not defer_refresh:
        _refresh_modifier(mod)


def _rebuild_membrane_for_shape(root_obj: bpy.types.Object, props) -> None:
    """Destructively rebuild the base mesh and lattice for a new shape.

    Keeps the mesh / lattice datablocks (modifier references stay valid)
    but discards any prior lattice deformation. Called from
    ``apply_props_to_membrane`` when the shape prop changes.
    """
    shape = str(props.shape)
    update_base_mesh(root_obj.data, shape,
                     float(props.width), float(props.height),
                     float(props.radius))
    for child in root_obj.children:
        if child.type == "LATTICE":
            update_lattice_for_shape(child, shape,
                                     float(props.width),
                                     float(props.height),
                                     float(props.radius))
            break


def reapply_membrane_settings(root_obj: bpy.types.Object) -> None:
    """Re-push a membrane's stored (pb_mem_*) settings onto its GN modifier.

    Called after a GN-tree version upgrade re-links the modifier to a fresh
    tree — the new tree has fresh socket identifiers, so the modifier's input
    values must be written again. Reads from the root's own custom properties
    (not the scene props) so it works on any membrane, selected or not.
    """
    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return

    style = str(root_obj.get("pb_mem_render_style", lipid_assets.DEFAULT_STYLE))
    _set_mod_input(mod, "Lipid Collection",
                   lipid_assets.get_or_build_lipid_collection(style))
    _set_mod_input(mod, "Lipid Variant Count",
                   lipid_assets.variant_count_for_style(style))
    _set_mod_input(mod, "Lipid Outer Extent (nm)",
                   lipid_assets.outer_extent_for_style(style))
    shape = str(root_obj.get("pb_mem_shape", SHAPE_FLAT))
    _set_mod_input(mod, "Shape Mode", int(SHAPE_MODE_INT.get(shape, 0)))
    _set_mod_input(mod, "Sphere Radius (nm)",
                   float(root_obj.get("pb_mem_radius", 15.0)))
    _set_mod_input(mod, "Density (per nm²)",
                   float(root_obj.get("pb_mem_density", 1.5)))
    _set_mod_input(mod, "Bilayer Thickness (nm)",
                   float(root_obj.get("pb_mem_bilayer_thickness", 5.0)))
    _set_mod_input(mod, "Random Rotation",
                   bool(root_obj.get("pb_mem_random_rotation", True)))
    _set_mod_input(mod, "Animate Bob",
                   bool(root_obj.get("pb_mem_animate_bob", False)))
    _set_mod_input(mod, "Bob Amplitude (nm)",
                   float(root_obj.get("pb_mem_bob_amplitude", 0.3)))
    _set_mod_input(mod, "Bob Speed",
                   float(root_obj.get("pb_mem_bob_speed", 0.6)))
    # FF Smoothness (α). Blender preserves modifier input values across
    # node_group reassignment by socket name, so a v25-built membrane
    # rebuilding to v26 would keep α=5.0. Push the stored value (or the
    # current v26 default of 2.0 if absent) so old membranes pick up the
    # tighter cluster bridging without needing a manual edit.
    _set_mod_input(mod, "FF Smoothness",
                   float(root_obj.get("pb_mem_ff_smoothness", 2.0)))
    # Re-push protein force fields too — a GN tree upgrade clears the new
    # slots' identifiers along with everything else.
    try:
        force_fields.apply_force_fields_to_membrane(root_obj,
                                                    defer_refresh=True)
    except Exception:
        pass
    _refresh_modifier(mod)


def _rebuild_hole_assignments(root_obj: bpy.types.Object,
                                defer_refresh: bool = False) -> None:
    """Walk the root's tracked hole list and assign them to the GN modifier slots
    in order. Slots without a hole get cleared and disabled.

    Ensures the shared GN tree has enough hole slots first — if this
    membrane just gained a hole past current capacity, the tree is rebuilt
    larger and every membrane's modifier is re-linked to it (see
    ``get_or_build_membrane_gn_tree``). Slots are cleared only up to the
    tree's current ``pb_active_holes`` count.
    """
    scene = bpy.context.scene if bpy.context else None
    tree = get_or_build_membrane_gn_tree(scene)
    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return
    if mod.node_group is not tree:
        mod.node_group = tree
    hole_names = list(_iter_hole_names(root_obj))
    tree_holes = int(tree.get("pb_active_holes", MAX_HOLES))
    for slot_i in range(1, tree_holes + 1):
        if slot_i <= len(hole_names):
            hole = bpy.data.objects.get(hole_names[slot_i - 1])
            _set_mod_input(mod, f"Hole {slot_i}", hole)
            _set_mod_input(mod, f"Hole {slot_i} Enabled", hole is not None)
        else:
            _set_mod_input(mod, f"Hole {slot_i}", None)
            _set_mod_input(mod, f"Hole {slot_i} Enabled", False)
    if not defer_refresh:
        _refresh_modifier(mod)


def _iter_holes(root_obj: bpy.types.Object):
    """Yield the hole Empty objects parented to *root_obj*, ordered.

    Children are filtered by ``pb_is_membrane_hole`` and sorted by their
    ``pb_hole_order`` integer custom property (assigned at create time).
    This is the authoritative source — walking children means the list
    survives hole renames done in the Outliner or by the user editing
    the name field in the dialog (the cached ``pb_mem_holes`` string
    would go stale).

    Old membranes built before ``pb_hole_order`` existed have it
    backfilled from their ``pb_mem_holes`` position on first read.
    """
    children = [c for c in root_obj.children
                if c.get("pb_is_membrane_hole", False)]
    if not children:
        return

    if any(c.get("pb_hole_order") is None for c in children):
        raw = root_obj.get("pb_mem_holes", "")
        legacy_order = [n for n in (raw.split("|") if raw else []) if n]
        legacy_index = {n: i for i, n in enumerate(legacy_order)}
        max_seen = max((c.get("pb_hole_order") or -1) for c in children) + 1
        for c in children:
            if c.get("pb_hole_order") is None:
                c["pb_hole_order"] = legacy_index.get(c.name, max_seen)
                max_seen += 1

    children.sort(key=lambda c: int(c.get("pb_hole_order", 0)))
    for c in children:
        yield c


def _iter_hole_names(root_obj: bpy.types.Object):
    """Yield the current hole object names, in order. See _iter_holes."""
    for h in _iter_holes(root_obj):
        yield h.name


def _resync_hole_cache(root_obj: bpy.types.Object) -> None:
    """Refresh the ``pb_mem_holes`` pipe-delimited cache from the current
    child list. ``_iter_holes`` walks children directly, but the GN-tree
    sizer in ``membrane_geometry._required_slot_counts`` reads the
    cache — call this after add/remove so the cache stays in sync."""
    names = [h.name for h in _iter_holes(root_obj)]
    root_obj["pb_mem_holes"] = "|".join(names)


def _next_hole_order(root_obj: bpy.types.Object) -> int:
    """Next free ``pb_hole_order`` integer for a new hole on *root_obj*."""
    max_order = -1
    for c in root_obj.children:
        if c.get("pb_is_membrane_hole", False):
            order = c.get("pb_hole_order")
            if order is not None and int(order) > max_order:
                max_order = int(order)
    return max_order + 1


# ---------------------------------------------------------------------------
# Build Membrane
# ---------------------------------------------------------------------------

def _build_new_membrane(context, props):
    """Create a brand-new membrane root + lattice + GN modifier, push props."""
    prefix = props.name_prefix or "Membrane"
    name = _next_membrane_name(prefix)

    shape = str(props.shape)

    mesh = build_membrane_base_mesh(shape, props.width, props.height,
                                     props.radius)
    mesh.name = f"{name}_mesh"
    root = bpy.data.objects.new(name, mesh)
    root["pb_is_membrane"] = True
    # Seed the shape custom prop so apply_props_to_membrane below sees
    # a matching old_shape and doesn't trigger a redundant rebuild.
    root["pb_mem_shape"] = shape

    coll = _ensure_membrane_collection(context.scene, name)
    _link_to_coll(coll, root)

    lattice = build_membrane_lattice(
        shape, props.width, props.height, props.radius,
        resolution=int(props.lattice_resolution),
    )
    lattice.name = f"{name}.lattice"
    lattice["pb_membrane_owner"] = name
    _link_to_coll(coll, lattice)
    lattice.parent = root

    latt_mod = root.modifiers.new(LATTICE_MOD_NAME, "LATTICE")
    latt_mod.object = lattice

    tree = get_or_build_membrane_gn_tree(context.scene)
    gn_mod = root.modifiers.new(GN_MOD_NAME, "NODES")
    gn_mod.node_group = tree

    # Three back-to-back input writes (props, holes, FFs) only trigger
    # one GN evaluation instead of three.
    apply_props_to_membrane(root, props, defer_refresh=True)
    force_fields.apply_force_fields_to_membrane(
        root, context.scene, defer_refresh=True)
    _refresh_modifier(gn_mod)

    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    context.view_layer.objects.active = root

    try:
        from ..utils.scene_manager import build_outliner_hierarchy
        build_outliner_hierarchy(context)
    except Exception:
        pass

    return root


def _update_existing_membrane(context, root, props):
    """Apply scene props to an existing membrane root, rebuilding size if
    width/height/radius changed. Used by build_membrane's update path."""
    new_shape = str(props.shape)
    old_w = float(root.get("pb_mem_width", props.width))
    old_h = float(root.get("pb_mem_height", props.height))
    old_r = float(root.get("pb_mem_radius", props.radius))
    needs_resize = (
        abs(old_w - float(props.width)) > 1e-6
        or abs(old_h - float(props.height)) > 1e-6
        or abs(old_r - float(props.radius)) > 1e-6
    )

    apply_props_to_membrane(root, props)

    if needs_resize:
        update_base_mesh(root.data, new_shape,
                         float(props.width), float(props.height),
                         float(props.radius))
        for child in root.children:
            if child.type == "LATTICE":
                update_lattice_for_shape(child, new_shape,
                                         float(props.width),
                                         float(props.height),
                                         float(props.radius))
                break
        root["pb_mem_width"] = float(props.width)
        root["pb_mem_height"] = float(props.height)
        root["pb_mem_radius"] = float(props.radius)
        mod = _get_gn_modifier(root)
        if mod is not None:
            _refresh_modifier(mod)


class PROTEINBLENDER_OT_build_membrane(Operator):
    """Open the Membrane Builder dialog.

    Two modes, controlled by ``membrane_root_to_update``:

    * **Create (empty)** — opens the dialog seeded from
      ``scene.membrane_builder_props``. Clicking OK creates a new
      membrane and adds it to the PB Outliner.
    * **Update (set to a membrane root name)** — the PB Outliner's
      edit pencil invokes us with this set. ``invoke`` syncs the
      scene props from the target root's ``pb_mem_*`` custom props
      so the dialog opens pre-populated; ``execute`` pushes the
      props back, rebuilding mesh + lattice only if size changed.

    The dialog body (see ``_draw_membrane_form``) is identical for
    create and edit — only the Holes / Deformation sections are
    hidden in create mode since they don't exist yet.
    """

    bl_idname = "proteinblender.build_membrane"
    bl_label = "Build Membrane"
    bl_options = {"REGISTER", "UNDO"}

    membrane_root_to_update: StringProperty(
        name="Membrane to update",
        description=(
            "If set, edit this membrane's root object name instead of "
            "creating a new one. Settings are applied in-place; size "
            "changes rebuild the mesh + lattice"
        ),
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        if self.membrane_root_to_update:
            from .membrane_props import sync_props_from_object
            root = bpy.data.objects.get(self.membrane_root_to_update)
            if root is not None and root.get("pb_is_membrane", False):
                sync_props_from_object(
                    context.scene.membrane_builder_props, root,
                )
                # Set the membrane as active so in-dialog hole/deform
                # operators resolve to the right membrane.
                try:
                    if context.mode != "OBJECT":
                        bpy.ops.object.mode_set(mode="OBJECT")
                    bpy.ops.object.select_all(action="DESELECT")
                    root.select_set(True)
                    context.view_layer.objects.active = root
                except Exception:
                    pass
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        _draw_membrane_form(
            self.layout,
            context.scene.membrane_builder_props,
            root=self._target_root(),
        )

    def _target_root(self):
        if not self.membrane_root_to_update:
            return None
        root = bpy.data.objects.get(self.membrane_root_to_update)
        if root is None or not root.get("pb_is_membrane", False):
            # The user may have just renamed the membrane in the dialog's
            # Name field. The stored name is stale — fall back to the
            # currently active object's membrane root (invoke() made the
            # target the active obj, and it stays active through rename).
            root = _get_membrane_root(bpy.context.active_object)
            if root is not None and root.get("pb_is_membrane", False):
                # Cache the new name so future lookups hit the fast path.
                self.membrane_root_to_update = root.name
            else:
                return None
        return root

    def execute(self, context):
        props = context.scene.membrane_builder_props

        if self.membrane_root_to_update:
            root = self._target_root()
            if root is None:
                self.report({"ERROR"},
                            f"Membrane '{self.membrane_root_to_update}' not found.")
                return {"CANCELLED"}
            _update_existing_membrane(context, root, props)
            shape = str(props.shape)
            if shape == SHAPE_FLAT:
                msg = f"Updated {root.name}: {props.width:.1f} × {props.height:.1f} nm"
            else:
                msg = f"Updated {root.name}: {shape.lower()} r={props.radius:.1f} nm"
            self.report({"INFO"}, msg)
            return {"FINISHED"}

        root = _build_new_membrane(context, props)
        shape = str(props.shape)
        if shape == SHAPE_FLAT:
            msg = f"Created {root.name}: {props.width:.1f} × {props.height:.1f} nm"
        else:
            msg = f"Created {root.name}: {shape.lower()} r={props.radius:.1f} nm"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _draw_membrane_form(layout, props, *, root=None):
    """Shared dialog body for Create-Membrane / Edit-Membrane.

    The Deformation and Holes sections only appear when ``root`` is
    set (edit mode) — they don't exist on a not-yet-built membrane.
    """
    from . import lipid_assets as _la

    # ---- Shape + size -------------------------------------------------
    layout.prop(props, "shape", text="Shape")
    if props.shape == "FLAT":
        size_row = layout.row(align=True)
        size_row.prop(props, "width", text="Width (nm)")
        size_row.prop(props, "height", text="Height (nm)")
    else:
        layout.prop(props, "radius", text="Radius (nm)")

    # ---- Name ---------------------------------------------------------
    # Edit mode: bind the name field to the root object's name so the
    # user can rename the membrane in-place. Create mode: bind to the
    # scene's name_prefix.
    if root is not None:
        layout.prop(root, "name", text="Name")
    else:
        layout.prop(props, "name_prefix", text="Name")
        layout.prop(props, "lattice_resolution", text="Deform Res")

    # ---- Lipids -------------------------------------------------------
    lip_box = layout.box()
    lip_header = lip_box.row()
    lip_header.prop(
        props, "show_lipid_section",
        text="Lipids",
        icon="TRIA_DOWN" if props.show_lipid_section else "TRIA_RIGHT",
        emboss=False,
    )
    if props.show_lipid_section:
        lip_box.prop(props, "render_style", text="Style")
        col = lip_box.column(align=True)
        col.prop(props, "density")
        col.prop(props, "bilayer_thickness")
        lip_box.prop(props, "random_rotation")

    # ---- Animation ----------------------------------------------------
    anim_box = layout.box()
    anim_header = anim_box.row()
    anim_header.prop(
        props, "show_animation_section",
        text="Bobbing Animation",
        icon="TRIA_DOWN" if props.show_animation_section else "TRIA_RIGHT",
        emboss=False,
    )
    if props.show_animation_section:
        anim_box.prop(props, "animate_bob")
        col = anim_box.column(align=True)
        col.enabled = props.animate_bob
        col.prop(props, "bob_amplitude")
        col.prop(props, "bob_speed")

    # ---- Colors -------------------------------------------------------
    col_box = layout.box()
    col_header = col_box.row()
    col_header.prop(
        props, "show_colors_section",
        text="Colors",
        icon="TRIA_DOWN" if props.show_colors_section else "TRIA_RIGHT",
        emboss=False,
    )
    if props.show_colors_section:
        c = col_box.column(align=True)
        if props.render_style == _la.STYLE_SURFACE:
            c.prop(props, "color_surface")
        else:
            c.prop(props, "color_head")
            c.prop(props, "color_tail")
        col_box.label(
            text="Colors are shared across all membranes.",
            icon="INFO",
        )

    # ---- Deformation (edit mode only) ---------------------------------
    if root is not None:
        deform_box = layout.box()
        deform_header = deform_box.row()
        deform_header.prop(
            props, "show_deform_section",
            text="Deformation",
            icon="TRIA_DOWN" if props.show_deform_section else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_deform_section:
            row = deform_box.row(align=True)
            row.scale_y = 1.2
            row.operator(
                "proteinblender.membrane_edit_deform",
                text="Edit Deformation",
                icon="MOD_LATTICE",
            )
            row.operator(
                "proteinblender.membrane_reset_deform",
                text="",
                icon="LOOP_BACK",
            )
            deform_box.label(
                text="Close dialog to grab lattice points; right-click → Insert Keyframe.",
                icon="INFO",
            )

    # ---- Holes (edit mode only) ---------------------------------------
    if root is not None:
        hole_box = layout.box()
        hole_header = hole_box.row()
        hole_header.prop(
            props, "show_holes_section",
            text="Holes",
            icon="TRIA_DOWN" if props.show_holes_section else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_holes_section:
            holes = list(_iter_holes(root))
            count_row = hole_box.row()
            count_row.label(text=f"Holes: {len(holes)} / {MAX_HOLES}")
            add_row = hole_box.row()
            add_row.scale_y = 1.2
            add_row.enabled = len(holes) < MAX_HOLES
            add_row.operator(
                "proteinblender.membrane_add_hole",
                text="➕ Add Hole",
                icon="MESH_TORUS",
            )

            if holes:
                hole_box.separator(factor=0.3)
                # One row per hole: editable name field + radius slider + delete.
                # The name field binds directly to the Empty's own name —
                # renaming here renames the object, which is exactly what
                # makes keyframes legible in the F-curve editor.
                for hole in holes:
                    row = hole_box.row(align=True)
                    row.prop(hole, "name", text="")
                    row.prop(hole, "scale", index=0, text="r")
                    rem = row.operator(
                        "proteinblender.membrane_remove_hole",
                        text="", icon="X",
                    )
                    rem.hole_name = hole.name
                hole_box.separator(factor=0.3)
                hole_box.label(
                    text="Rename to taste — keyframes follow the new name.",
                    icon="INFO",
                )
                hole_box.label(
                    text="Close dialog to grab a hole in the viewport, then keyframe r or location.",
                    icon="BLANK1",
                )


# ---------------------------------------------------------------------------
# Update Membrane Size (rebuild grid + resize lattice)
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_resize_membrane(Operator):
    """Apply current Width/Height to the selected membrane (rebuilds grid)"""

    bl_idname = "proteinblender.resize_membrane"
    bl_label = "Resize Membrane"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}
        props = context.scene.membrane_builder_props

        shape = str(props.shape)

        # Rebuild the base mesh in place for the current shape + size.
        update_base_mesh(root.data, shape,
                         float(props.width), float(props.height),
                         float(props.radius))

        # Resize the lattice to match.
        for child in root.children:
            if child.type == "LATTICE":
                update_lattice_for_shape(child, shape,
                                         float(props.width),
                                         float(props.height),
                                         float(props.radius))
                break

        root["pb_mem_shape"] = shape
        root["pb_mem_width"] = float(props.width)
        root["pb_mem_height"] = float(props.height)
        root["pb_mem_radius"] = float(props.radius)

        mod = _get_gn_modifier(root)
        if mod is not None:
            _set_mod_input(mod, "Sphere Radius (nm)", float(props.radius))
            _refresh_modifier(mod)

        if shape == SHAPE_FLAT:
            msg = f"Resized to {props.width:.1f} × {props.height:.1f} nm"
        else:
            msg = f"Resized to {shape.lower()} r={props.radius:.1f} nm"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Hole operators
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_add_hole(Operator):
    """Add a hole controller to the active membrane"""

    bl_idname = "proteinblender.membrane_add_hole"
    bl_label = "Add Hole"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}

        existing = list(_iter_hole_names(root))
        if len(existing) >= MAX_HOLES:
            self.report({"WARNING"},
                        f"Maximum {MAX_HOLES} holes per membrane reached.")
            return {"CANCELLED"}

        hole_name = _next_hole_name(root.name)
        hole = bpy.data.objects.new(hole_name, None)
        hole.empty_display_type = "SPHERE"
        hole.empty_display_size = 1.0
        # The hole empty is a real sphere: the hole it carves is the sphere's
        # cross-section with the membrane, so the default radius must reach
        # past both leaflets or it wouldn't carve anything. Half the bilayer
        # thickness (in BU) + a margin guarantees it spans the membrane.
        half_thick_bu = float(root.get("pb_mem_bilayer_thickness", 5.0)) / (
            2.0 * NM_PER_BU)
        hole_radius = half_thick_bu + 0.15
        hole.scale = (hole_radius, hole_radius, hole_radius)
        # Position slightly offset from origin so user can grab it easily,
        # and centred in Z (the bilayer midplane) so it carves both leaflets.
        offset = 0.1 * len(existing)
        hole.location = (offset, offset, 0.0)
        hole["pb_membrane_owner"] = root.name
        hole["pb_is_membrane_hole"] = True
        hole["pb_hole_order"] = _next_hole_order(root)

        coll_name = f"{root.name}_Group"
        coll = bpy.data.collections.get(coll_name)
        if coll is None:
            coll = _ensure_membrane_collection(context.scene, root.name)
        _link_to_coll(coll, hole)
        hole.parent = root

        _resync_hole_cache(root)
        _rebuild_hole_assignments(root)

        # Select the new hole so the user can immediately position it
        bpy.ops.object.select_all(action="DESELECT")
        hole.select_set(True)
        context.view_layer.objects.active = hole

        self.report({"INFO"}, f"Added hole {hole_name}")
        return {"FINISHED"}


class PROTEINBLENDER_OT_remove_hole(Operator):
    """Remove a hole controller from the active membrane"""

    bl_idname = "proteinblender.membrane_remove_hole"
    bl_label = "Remove Hole"
    bl_options = {"REGISTER", "UNDO"}

    hole_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}

        target = self.hole_name
        if not target:
            # If invoked without an explicit name, pop the last hole.
            existing = list(_iter_hole_names(root))
            if not existing:
                self.report({"WARNING"}, "No holes to remove.")
                return {"CANCELLED"}
            target = existing[-1]

        # Remove the actual object first.
        hole_obj = bpy.data.objects.get(target)
        if hole_obj is not None:
            try:
                bpy.data.objects.remove(hole_obj, do_unlink=True)
            except Exception:
                pass

        # Refresh the cache from current children (target is gone).
        _resync_hole_cache(root)
        _rebuild_hole_assignments(root)

        # Re-select the membrane root.
        try:
            bpy.ops.object.select_all(action="DESELECT")
            root.select_set(True)
            context.view_layer.objects.active = root
        except Exception:
            pass

        return {"FINISHED"}


class PROTEINBLENDER_OT_select_hole(Operator):
    """Select a specific hole controller"""

    bl_idname = "proteinblender.membrane_select_hole"
    bl_label = "Select Hole"
    bl_options = {"REGISTER", "UNDO"}

    hole_name: StringProperty()

    def execute(self, context):
        hole = bpy.data.objects.get(self.hole_name)
        if hole is None:
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        hole.select_set(True)
        context.view_layer.objects.active = hole
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Deformation: enter/exit lattice edit mode, reset lattice
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_edit_deform(Operator):
    """Enter Lattice edit mode for the active membrane's deformer.

    The user can then grab lattice points, drag them, and keyframe them to
    animate the membrane's surface. Click the panel button again (or Tab)
    to return to Object mode.
    """

    bl_idname = "proteinblender.membrane_edit_deform"
    bl_label = "Edit Membrane Deformation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return False
        return any(c.type == "LATTICE" for c in root.children)

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}

        lattice = None
        for child in root.children:
            if child.type == "LATTICE":
                lattice = child
                break
        if lattice is None:
            self.report({"ERROR"}, "Membrane has no lattice deformer.")
            return {"CANCELLED"}

        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

        bpy.ops.object.select_all(action="DESELECT")
        lattice.select_set(True)
        context.view_layer.objects.active = lattice
        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except Exception as e:
            self.report({"ERROR"}, f"Could not enter edit mode: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}


class PROTEINBLENDER_OT_finish_deform(Operator):
    """Leave Lattice edit mode and re-select the membrane root"""

    bl_idname = "proteinblender.membrane_finish_deform"
    bl_label = "Finish Editing Deformation"

    def execute(self, context):
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        # If active is the lattice, jump to its parent membrane.
        obj = context.active_object
        if obj is not None and obj.type == "LATTICE" and obj.parent:
            bpy.ops.object.select_all(action="DESELECT")
            obj.parent.select_set(True)
            context.view_layer.objects.active = obj.parent
        return {"FINISHED"}


class PROTEINBLENDER_OT_reset_deform(Operator):
    """Reset the membrane's lattice points to their default flat positions"""

    bl_idname = "proteinblender.membrane_reset_deform"
    bl_label = "Reset Deformation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _get_membrane_root(context.active_object)
        return root is not None and any(c.type == "LATTICE" for c in root.children)

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}
        for child in root.children:
            if child.type == "LATTICE":
                # IMPORTANT: a lattice point's "no deformation" state is
                # ``co_deform == co`` (rest position), NOT (0,0,0). Setting
                # co_deform to (0,0,0) collapses every point to the lattice
                # centre, crushing the mesh into a tiny region.
                for p in child.data.points:
                    p.co_deform = tuple(p.co)
                break
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Delete Membrane
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_delete_membrane(Operator):
    """Delete a membrane and all of its children (lattice, holes).

    When invoked from the PB Outliner pass ``membrane_name``; when invoked
    from the Membrane Builder panel (no arg), it falls back to the active
    object's membrane root so the existing button still works.
    """

    bl_idname = "proteinblender.delete_membrane"
    bl_label = "Delete Membrane"
    bl_options = {"REGISTER", "UNDO"}

    membrane_name: StringProperty(
        name="Membrane Name",
        description="Name of the membrane root to delete (empty = active object)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        # Always pollable — if there's no explicit name we'll check the
        # active object inside execute.
        return True

    def execute(self, context):
        # Prefer the explicit name (outliner path); fall back to active.
        root = None
        if self.membrane_name:
            candidate = bpy.data.objects.get(self.membrane_name)
            if candidate is not None and candidate.get("pb_is_membrane", False):
                root = candidate
        if root is None:
            root = _get_membrane_root(context.active_object)
        if root is None:
            self.report({"WARNING"}, "No membrane to delete.")
            return {"CANCELLED"}

        coll_name = f"{root.name}_Group"
        coll = bpy.data.collections.get(coll_name)

        # Collect children to delete BEFORE removing root (children list is
        # invalidated otherwise).
        targets = [root] + list(root.children)
        for obj in targets:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

        # Remove the per-membrane collection if empty.
        if coll is not None and len(coll.objects) == 0:
            try:
                bpy.data.collections.remove(coll)
            except Exception:
                pass

        # Rebuild the outliner so the membrane row disappears.
        try:
            from ..utils.scene_manager import build_outliner_hierarchy
            build_outliner_hierarchy(context)
        except Exception:
            pass

        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_build_membrane,
    PROTEINBLENDER_OT_resize_membrane,
    PROTEINBLENDER_OT_add_hole,
    PROTEINBLENDER_OT_remove_hole,
    PROTEINBLENDER_OT_select_hole,
    PROTEINBLENDER_OT_edit_deform,
    PROTEINBLENDER_OT_finish_deform,
    PROTEINBLENDER_OT_reset_deform,
    PROTEINBLENDER_OT_delete_membrane,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
