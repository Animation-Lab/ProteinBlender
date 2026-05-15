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

from .membrane_geometry import (
    NM_PER_BU,
    MAX_HOLES,
    GN_TREE_NAME,
    LIPID_ASSET_NAME,
    HEAD_MATERIAL_NAME,
    TAIL_MATERIAL_NAME,
    get_or_build_lipid_asset,
    get_or_build_membrane_gn_tree,
    set_membrane_colors,
    build_membrane_lattice,
    _build_grid_mesh,
    update_grid_mesh,
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

    Toggling show_render then back works as a "kick" without visible side
    effects.
    """
    try:
        mod.show_render = not mod.show_render
        mod.show_render = not mod.show_render
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

    _set_mod_input(mod, "Density (per nm²)", float(props.density))
    _set_mod_input(mod, "Bilayer Thickness (nm)", float(props.bilayer_thickness))
    _set_mod_input(mod, "Lipid Scale", float(props.lipid_scale))
    _set_mod_input(mod, "Random Rotation", bool(props.random_rotation))
    _set_mod_input(mod, "Animate Bob", bool(props.animate_bob))
    _set_mod_input(mod, "Bob Amplitude (nm)", float(props.bob_amplitude))
    _set_mod_input(mod, "Bob Speed", float(props.bob_speed))

    # Mirror onto the root as custom properties (so size-edit operator can
    # detect what's needed, and so we can re-sync to panel when reselected).
    root_obj["pb_mem_density"] = float(props.density)
    root_obj["pb_mem_bilayer_thickness"] = float(props.bilayer_thickness)
    root_obj["pb_mem_lipid_scale"] = float(props.lipid_scale)
    root_obj["pb_mem_random_rotation"] = bool(props.random_rotation)
    root_obj["pb_mem_animate_bob"] = bool(props.animate_bob)
    root_obj["pb_mem_bob_amplitude"] = float(props.bob_amplitude)
    root_obj["pb_mem_bob_speed"] = float(props.bob_speed)
    root_obj["pb_mem_width"] = float(props.width)
    root_obj["pb_mem_height"] = float(props.height)

    # Update shared materials in case head/tail colour props were changed.
    set_membrane_colors(root_obj, tuple(props.color_head), tuple(props.color_tail))
    root_obj["pb_mem_color_head"] = list(props.color_head)
    root_obj["pb_mem_color_tail"] = list(props.color_tail)

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

        # 1. Build the base grid mesh and root object.
        mesh = _build_grid_mesh(props.width, props.height)
        mesh.name = f"{name}_mesh"
        root = bpy.data.objects.new(name, mesh)
        root["pb_is_membrane"] = True

        coll = _ensure_membrane_collection(context.scene, name)
        _link_to_coll(coll, root)

        # 2. Build the Lattice deformer and parent it to the root.
        lattice = build_membrane_lattice(props.width, props.height,
                                         resolution=int(props.lattice_resolution))
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

        # 4. Wire the lipid asset and props into the modifier.
        lipid = get_or_build_lipid_asset()
        _set_mod_input(gn_mod, "Lipid Asset", lipid)
        apply_props_to_membrane(root, props)
        _rebuild_hole_assignments(root)

        # 5. Make root the active object so the panel switches to edit mode.
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        context.view_layer.objects.active = root

        self.report({"INFO"},
                    f"Created {name}: {props.width:.1f} × {props.height:.1f} nm")
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

        # Rebuild the grid mesh in place.
        update_grid_mesh(root.data, props.width, props.height)

        # Resize the lattice.
        for child in root.children:
            if child.type == "LATTICE":
                child.scale = (props.width / NM_PER_BU,
                               props.height / NM_PER_BU,
                               1.0)
                break

        root["pb_mem_width"] = float(props.width)
        root["pb_mem_height"] = float(props.height)

        mod = _get_gn_modifier(root)
        if mod is not None:
            _refresh_modifier(mod)

        self.report({"INFO"},
                    f"Resized to {props.width:.1f} × {props.height:.1f} nm")
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
        # Hole radius in BU. Default to 1 nm radius = 0.1 BU.
        hole.scale = (0.1, 0.1, 0.1)
        # Position slightly offset from origin so user can grab it easily,
        # but stay within the membrane.
        # Use root's bounding box center.
        from mathutils import Vector
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
    """Delete the active membrane and all of its children (lattice, holes)"""

    bl_idname = "proteinblender.delete_membrane"
    bl_label = "Delete Membrane"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
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
