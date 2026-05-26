"""Operators for the Membrane Builder.

The membrane is represented by ONE Mesh object (the "membrane root"). All
related objects — Lattice deformer, hole controllers — are children of the
root, and the root carries the GN modifier that turns the flat plane into a
bilayer of lipid instances.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty
from typing import Optional

from . import lipid_assets
from . import force_fields
from .membrane_geometry import (
    NM_PER_BU,
    MAX_HOLES,
    GN_TREE_NAME,
    HEAD_MATERIAL_NAME,
    TAIL_MATERIAL_NAME,
    SHAPE_FLAT,
    SHAPE_SPHERE,
    SHAPE_HEMISPHERE,
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


def apply_props_to_membrane(root_obj: bpy.types.Object, props) -> None:
    """Push every scene-level property value to the membrane's GN modifier
    inputs AND to the persistent custom-property store on the root.

    The custom-property store is what ``sync_props_from_object`` reads back
    when the user re-selects this membrane later.
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
    _set_mod_input(mod, "Lipid Scale", float(props.lipid_scale))
    _set_mod_input(mod, "Random Rotation", bool(props.random_rotation))
    _set_mod_input(mod, "Animate Bob", bool(props.animate_bob))
    _set_mod_input(mod, "Bob Amplitude (nm)", float(props.bob_amplitude))
    _set_mod_input(mod, "Bob Speed", float(props.bob_speed))

    # Render style — swap which collection feeds the GN modifier and push
    # the matching variant count so the per-point random Instance Index
    # stays inside the collection's range.
    style = str(props.render_style)
    _set_mod_input(mod, "Lipid Collection",
                   lipid_assets.get_or_build_lipid_collection(style))
    _set_mod_input(mod, "Lipid Variant Count",
                   lipid_assets.variant_count_for_style(style))

    # Mirror onto the root as custom properties (so size-edit operator can
    # detect what's needed, and so we can re-sync to panel when reselected).
    root_obj["pb_mem_shape"] = new_shape
    root_obj["pb_mem_density"] = float(props.density)
    root_obj["pb_mem_bilayer_thickness"] = float(props.bilayer_thickness)
    root_obj["pb_mem_lipid_scale"] = float(props.lipid_scale)
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
    shape = str(root_obj.get("pb_mem_shape", SHAPE_FLAT))
    _set_mod_input(mod, "Shape Mode", int(SHAPE_MODE_INT.get(shape, 0)))
    _set_mod_input(mod, "Sphere Radius (nm)",
                   float(root_obj.get("pb_mem_radius", 15.0)))
    _set_mod_input(mod, "Density (per nm²)",
                   float(root_obj.get("pb_mem_density", 1.5)))
    _set_mod_input(mod, "Bilayer Thickness (nm)",
                   float(root_obj.get("pb_mem_bilayer_thickness", 3.2)))
    _set_mod_input(mod, "Lipid Scale",
                   float(root_obj.get("pb_mem_lipid_scale", 1.0)))
    _set_mod_input(mod, "Random Rotation",
                   bool(root_obj.get("pb_mem_random_rotation", True)))
    _set_mod_input(mod, "Animate Bob",
                   bool(root_obj.get("pb_mem_animate_bob", False)))
    _set_mod_input(mod, "Bob Amplitude (nm)",
                   float(root_obj.get("pb_mem_bob_amplitude", 0.3)))
    _set_mod_input(mod, "Bob Speed",
                   float(root_obj.get("pb_mem_bob_speed", 0.6)))

    _rebuild_hole_assignments(root_obj)
    # Re-push protein force fields too — a GN tree upgrade clears the new
    # slots' identifiers along with everything else.
    try:
        force_fields.apply_force_fields_to_membrane(root_obj)
    except Exception:
        pass
    _refresh_modifier(mod)


def _rebuild_hole_assignments(root_obj: bpy.types.Object) -> None:
    """Walk the root's tracked hole list and assign them to the GN modifier slots
    in order. Slots without a hole get cleared and disabled.
    """
    mod = _get_gn_modifier(root_obj)
    if mod is None:
        return
    hole_names = list(_iter_hole_names(root_obj))
    for slot_i in range(1, MAX_HOLES + 1):
        if slot_i <= len(hole_names):
            hole = bpy.data.objects.get(hole_names[slot_i - 1])
            _set_mod_input(mod, f"Hole {slot_i}", hole)
            _set_mod_input(mod, f"Hole {slot_i} Enabled", hole is not None)
        else:
            _set_mod_input(mod, f"Hole {slot_i}", None)
            _set_mod_input(mod, f"Hole {slot_i} Enabled", False)
    _refresh_modifier(mod)


def _iter_hole_names(root_obj: bpy.types.Object):
    """Yield the hole object names stored on the root, in order."""
    raw = root_obj.get("pb_mem_holes", "")
    if not raw:
        return
    for name in raw.split("|"):
        if name:
            yield name


def _set_hole_names(root_obj: bpy.types.Object, names) -> None:
    root_obj["pb_mem_holes"] = "|".join(names)


# ---------------------------------------------------------------------------
# Build Membrane
# ---------------------------------------------------------------------------

class PROTEINBLENDER_OT_build_membrane(Operator):
    """Build a new lipid bilayer membrane"""

    bl_idname = "proteinblender.build_membrane"
    bl_label = "Build Membrane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.membrane_builder_props
        prefix = props.name_prefix or "Membrane"
        name = _next_membrane_name(prefix)

        shape = str(props.shape)

        # 1. Build the base mesh for the requested shape and the root object.
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

        # 2. Build the Lattice deformer (sized for the shape) and parent
        # it to the root.
        lattice = build_membrane_lattice(
            shape, props.width, props.height, props.radius,
            resolution=int(props.lattice_resolution),
        )
        lattice.name = f"{name}.lattice"
        lattice["pb_membrane_owner"] = name
        _link_to_coll(coll, lattice)
        # Parent (keep transform false — the lattice should sit at root's origin).
        lattice.parent = root

        # Add Lattice modifier to root (before GN).
        latt_mod = root.modifiers.new(LATTICE_MOD_NAME, "LATTICE")
        latt_mod.object = lattice

        # 3. Add the GN modifier and assign the shared tree.
        tree = get_or_build_membrane_gn_tree()
        gn_mod = root.modifiers.new(GN_MOD_NAME, "NODES")
        gn_mod.node_group = tree

        # 4. Push props (which also picks the right Lipid Collection for the
        # selected render style) and wire the hole assignments.
        apply_props_to_membrane(root, props)
        _rebuild_hole_assignments(root)
        # New membrane inherits the scene's current FF-enabled proteins.
        force_fields.apply_force_fields_to_membrane(root, context.scene)

        # 5. Make root the active object so the panel switches to edit mode.
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        context.view_layer.objects.active = root

        if shape == SHAPE_FLAT:
            msg = f"Created {name}: {props.width:.1f} × {props.height:.1f} nm"
        else:
            msg = f"Created {name}: {shape.lower()} r={props.radius:.1f} nm"
        self.report({"INFO"}, msg)

        # Surface the new membrane in the PB Outliner.
        try:
            from ..utils.scene_manager import build_outliner_hierarchy
            build_outliner_hierarchy(context)
        except Exception:
            pass

        return {"FINISHED"}


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
        half_thick_bu = float(root.get("pb_mem_bilayer_thickness", 4.0)) / (
            2.0 * NM_PER_BU)
        hole_radius = half_thick_bu + 0.15
        hole.scale = (hole_radius, hole_radius, hole_radius)
        # Position slightly offset from origin so user can grab it easily,
        # and centred in Z (the bilayer midplane) so it carves both leaflets.
        offset = 0.1 * len(existing)
        hole.location = (offset, offset, 0.0)
        hole["pb_membrane_owner"] = root.name
        hole["pb_is_membrane_hole"] = True

        coll_name = f"{root.name}_Group"
        coll = bpy.data.collections.get(coll_name)
        if coll is None:
            coll = _ensure_membrane_collection(context.scene, root.name)
        _link_to_coll(coll, hole)
        hole.parent = root

        existing.append(hole_name)
        _set_hole_names(root, existing)
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

        # Update the tracked list.
        names = [n for n in _iter_hole_names(root) if n != target]
        _set_hole_names(root, names)
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
