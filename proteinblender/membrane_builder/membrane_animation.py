"""Keyframe-animation operators for the Membrane Builder.

The Membrane Builder's animatable parts — pores, lipid-motion strength, the
membrane transform — are keyframed from the Membrane Builder panel rather
than the puppet-only "Create Keyframe" tool. This module provides:

* Key Membrane     — snapshot every enabled channel at the current frame.
* Key Pore         — key one pore's size + position.
* Pore Lifecycle   — guided: open/close a pore over a frame range in one go.
* Clear Animation  — strip all membrane keyframes.
* Jump Keyframe    — step the playhead to the membrane's keyframes.

Plus helpers the panel uses to show per-pore keyframe state.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty
from typing import Iterator, List

from .membrane_operators import (
    NM_PER_BU,
    GN_MOD_NAME,
    _get_membrane_root,
    _get_gn_modifier,
    _iter_hole_names,
)

# Pre-formation pore radius — small enough to carve nothing, not exactly zero
# (a zero-scale empty is awkward to grab again afterwards).
_CLOSED_RADIUS = 0.02


def _membrane_lattice(root: bpy.types.Object):
    """Return the membrane's Lattice deformer child, or None."""
    if root is None:
        return None
    for child in root.children:
        if child.type == "LATTICE":
            return child
    return None


# ===========================================================================
# F-Curve / keyframe helpers (Blender legacy + slotted-action aware)
# ===========================================================================

def iter_fcurves(obj: bpy.types.Object) -> Iterator[bpy.types.FCurve]:
    """Yield every F-Curve driving *obj*, across Blender's legacy actions and
    the slotted actions introduced in Blender 4.4 / 5.x."""
    ad = getattr(obj, "animation_data", None)
    if ad is None or ad.action is None:
        return
    action = ad.action

    legacy = getattr(action, "fcurves", None)
    if legacy is not None:                       # Blender <= 4.3
        for fc in legacy:
            yield fc
        return

    slot = getattr(ad, "action_slot", None)      # Blender 4.4+ slotted action
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            cbag = None
            if slot is not None and hasattr(strip, "channelbag"):
                try:
                    cbag = strip.channelbag(slot)
                except Exception:
                    cbag = None
            if cbag is not None:
                for fc in getattr(cbag, "fcurves", []):
                    yield fc
            else:
                for cb2 in getattr(strip, "channelbags", []):
                    for fc in getattr(cb2, "fcurves", []):
                        yield fc


def smooth_object_fcurves(obj: bpy.types.Object) -> None:
    """Give every keyframe on *obj* smooth Bezier ease — used after the
    guided tools so generated motion isn't robotic."""
    for fc in iter_fcurves(obj):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
        try:
            fc.update()
        except Exception:
            pass


def pore_anim_state(hole: bpy.types.Object, frame: float) -> str:
    """Return 'KEYED' (a key sits on *frame*), 'ANIMATED' (keyed elsewhere)
    or 'NONE' — used to pick the per-pore keyframe icon in the panel."""
    found_any = False
    for fc in iter_fcurves(hole):
        for kp in fc.keyframe_points:
            found_any = True
            if abs(kp.co[0] - frame) < 0.5:
                return "KEYED"
    return "ANIMATED" if found_any else "NONE"


def _gn_input_path(mod: bpy.types.Modifier, socket_name: str):
    """RNA data path for keyframing a Geometry Nodes modifier input."""
    ng = mod.node_group
    if ng is None:
        return None
    for item in ng.interface.items_tree:
        if (getattr(item, "in_out", None) == "INPUT"
                and item.name == socket_name):
            return f'modifiers["{mod.name}"]["{item.identifier}"]'
    return None


def _membrane_anim_ids(root: bpy.types.Object) -> List:
    """Every datablock that can carry a membrane keyframe: the root, the
    pores, and the Lattice deformer (its deform keys live on the Lattice
    *data*, so both the object and its data are included)."""
    ids = [root] + [c for c in root.children
                    if c.get("pb_is_membrane_hole", False)]
    lattice = _membrane_lattice(root)
    if lattice is not None:
        ids.append(lattice)
        if lattice.data is not None:
            ids.append(lattice.data)
    return ids


def membrane_keyframe_times(root: bpy.types.Object) -> List[float]:
    """Sorted, de-duplicated list of every frame the membrane (its transform,
    its GN inputs, its deformation, and all its pores) has a keyframe on."""
    times = set()
    for obj in _membrane_anim_ids(root):
        for fc in iter_fcurves(obj):
            for kp in fc.keyframe_points:
                times.add(round(kp.co[0]))
    return sorted(times)


# ===========================================================================
# Keying operators
# ===========================================================================

def _key_pore(hole: bpy.types.Object, frame: int) -> None:
    """Keyframe a single pore's position + size at *frame*."""
    hole.keyframe_insert(data_path="location", frame=frame)
    hole.keyframe_insert(data_path="scale", frame=frame)


def _key_lipid_motion(root: bpy.types.Object, frame: int) -> bool:
    """Keyframe the membrane's lipid-motion GN inputs at *frame*."""
    mod = _get_gn_modifier(root)
    if mod is None:
        return False
    keyed = False
    for socket in ("Bob Amplitude (nm)", "Bob Speed"):
        path = _gn_input_path(mod, socket)
        if path:
            try:
                root.keyframe_insert(data_path=path, frame=frame)
                keyed = True
            except Exception:
                pass
    return keyed


def _key_deform(root: bpy.types.Object, frame: int) -> bool:
    """Keyframe the membrane's lattice-deformer shape at *frame*.

    Every lattice point's deformed position is keyed, so the whole bilayer
    surface holds its shape on this frame regardless of which points the
    user has since dragged. v6 of the GN tree distributes lipids on a static
    grid and projects them onto the deformed surface, so an animated
    deformation slides the lipids without re-sampling the distribution.
    """
    lattice = _membrane_lattice(root)
    if lattice is None or lattice.data is None:
        return False
    data = lattice.data
    keyed = False
    for i in range(len(data.points)):
        try:
            data.keyframe_insert(
                data_path=f"points[{i}].co_deform", frame=frame)
            keyed = True
        except Exception:
            pass
    return keyed


class PROTEINBLENDER_OT_membrane_key(Operator):
    """Keyframe every enabled channel of the membrane at the current frame"""

    bl_idname = "proteinblender.membrane_key"
    bl_label = "Key Membrane"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        if root is None:
            return {"CANCELLED"}
        props = context.scene.membrane_builder_props
        frame = context.scene.frame_current
        parts = []

        if props.key_pores:
            holes = [c for c in root.children
                     if c.get("pb_is_membrane_hole", False)]
            for hole in holes:
                _key_pore(hole, frame)
            if holes:
                parts.append(f"{len(holes)} pore(s)")

        if props.key_lipid_motion and _key_lipid_motion(root, frame):
            parts.append("lipid motion")

        if props.key_deform and _key_deform(root, frame):
            parts.append("deformation")

        if props.key_transform:
            root.keyframe_insert(data_path="location", frame=frame)
            root.keyframe_insert(data_path="rotation_euler", frame=frame)
            parts.append("transform")

        if not parts:
            self.report({"WARNING"}, "No channels enabled to key.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Keyed {', '.join(parts)} at frame {frame}")
        return {"FINISHED"}


class PROTEINBLENDER_OT_membrane_key_pore(Operator):
    """Keyframe this pore's size and position at the current frame"""

    bl_idname = "proteinblender.membrane_key_pore"
    bl_label = "Key Pore"
    bl_options = {"REGISTER", "UNDO"}

    hole_name: StringProperty()

    def execute(self, context):
        hole = bpy.data.objects.get(self.hole_name)
        if hole is None:
            self.report({"ERROR"}, "Pore not found.")
            return {"CANCELLED"}
        frame = context.scene.frame_current
        _key_pore(hole, frame)
        smooth_object_fcurves(hole)
        self.report({"INFO"}, f"Keyed {self.hole_name} at frame {frame}")
        return {"FINISHED"}


class PROTEINBLENDER_OT_membrane_pore_lifecycle(Operator):
    """Animate a pore opening or closing over a frame range, in one step"""

    bl_idname = "proteinblender.membrane_pore_lifecycle"
    bl_label = "Apply Pore Animation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        props = context.scene.membrane_builder_props

        hole = bpy.data.objects.get(props.anim_pore)
        if hole is None or props.anim_pore == "NONE":
            self.report({"ERROR"}, "Pick a pore to animate (add a hole first).")
            return {"CANCELLED"}
        f0, f1 = int(props.anim_from), int(props.anim_to)
        if f1 <= f0:
            self.report({"ERROR"}, "'To' frame must be after 'From' frame.")
            return {"CANCELLED"}

        # Open size = the pore's current radius; closed = a sliver.
        open_r = max(hole.scale.x, _CLOSED_RADIUS * 2)
        x, y = hole.location.x, hole.location.y

        # Z clearance so the pore sphere sits fully outside the bilayer.
        half_thick = float(root.get("pb_mem_bilayer_thickness", 5.0)) / (
            2.0 * NM_PER_BU)
        z_clear = half_thick + open_r + 0.25
        punch = bool(props.anim_punch_through)

        forming = props.anim_action == "FORM"
        # (radius, z) at the start frame and the end frame.
        if forming:
            start = (_CLOSED_RADIUS, z_clear if punch else 0.0)
            end = (open_r, 0.0)
        else:  # RESEAL
            start = (open_r, 0.0)
            end = (_CLOSED_RADIUS, z_clear if punch else 0.0)

        for frame, (radius, z) in ((f0, start), (f1, end)):
            hole.location = (x, y, z)
            hole.scale = (radius, radius, radius)
            hole.keyframe_insert(data_path="location", frame=frame)
            hole.keyframe_insert(data_path="scale", frame=frame)

        smooth_object_fcurves(hole)
        # Re-evaluate so the pore shows its state on the current frame.
        context.scene.frame_set(context.scene.frame_current)

        verb = "forms" if forming else "reseals"
        self.report({"INFO"},
                    f"{props.anim_pore} {verb} over frames {f0}-{f1}")
        return {"FINISHED"}


class PROTEINBLENDER_OT_membrane_clear_animation(Operator):
    """Remove every keyframe from the membrane and its pores"""

    bl_idname = "proteinblender.membrane_clear_animation"
    bl_label = "Clear Membrane Animation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        cleared = 0
        for obj in _membrane_anim_ids(root):
            if getattr(obj, "animation_data", None) is not None:
                obj.animation_data_clear()
                cleared += 1
        self.report({"INFO"},
                    f"Cleared animation from {cleared} membrane channel(s)")
        return {"FINISHED"}


class PROTEINBLENDER_OT_membrane_jump_keyframe(Operator):
    """Jump the playhead to the membrane's previous / next keyframe"""

    bl_idname = "proteinblender.membrane_jump_keyframe"
    bl_label = "Jump to Membrane Keyframe"
    bl_options = {"REGISTER"}

    direction: EnumProperty(
        items=[("PREV", "Previous", ""), ("NEXT", "Next", "")],
        default="NEXT",
    )

    @classmethod
    def poll(cls, context):
        return _get_membrane_root(context.active_object) is not None

    def execute(self, context):
        root = _get_membrane_root(context.active_object)
        times = membrane_keyframe_times(root)
        if not times:
            self.report({"INFO"}, "The membrane has no keyframes yet.")
            return {"CANCELLED"}
        cur = context.scene.frame_current
        if self.direction == "NEXT":
            later = [t for t in times if t > cur]
            target = later[0] if later else times[-1]
        else:
            earlier = [t for t in times if t < cur]
            target = earlier[-1] if earlier else times[0]
        context.scene.frame_set(int(target))
        return {"FINISHED"}


CLASSES = (
    PROTEINBLENDER_OT_membrane_key,
    PROTEINBLENDER_OT_membrane_key_pore,
    PROTEINBLENDER_OT_membrane_pore_lifecycle,
    PROTEINBLENDER_OT_membrane_clear_animation,
    PROTEINBLENDER_OT_membrane_jump_keyframe,
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
