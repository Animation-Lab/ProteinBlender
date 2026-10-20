"""Keyframing a helical filament: where it is, how it bends, and its numbers.

A built filament is three things a user would animate. Where it stands is
its molecule object's transform, and how it bends is the transforms of its
bend control nodes - both ordinary keyframes Blender plays back on its own.
The third is its numbers: how many subunits, the rise and twist between
them, and how its strands sit. Those are not properties of any datablock
Blender evaluates; they are a recipe the copies were placed from.

So the numbers are kept as animatable properties on the molecule object
(``Object.pb_filament``), keyed like any other, and :func:`follow_animation`
re-places the copies from their value at each frame. It writes into the
point clouds the build already has (``assembly.update_operator_points``) and
creates nothing, which is what makes it safe from a frame-change handler,
during playback and during an animation render alike.

What a filament is built from stays the record on its assembly node
(``assembly.built_build_params``): the dialog reopens on it and Cancel puts
it back. Playing the animation keeps that record on the frame's values, so
Edit Assembly at any frame opens on what is on screen.
"""

from __future__ import annotations

import logging
import math

import bpy
from bpy.app.handlers import persistent
from bpy.props import FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup

from . import assembly as assembly_core
from . import bend_rig, symmetry_bend, symmetry_builder

logger = logging.getLogger(__name__)

#: Where the numbers live on the molecule object.
DATA_PATH = "pb_filament"

#: The build settings that can be keyed, in the order they are listed.
PARAMETERS = ("count", "rise", "twist", "strands", "stagger", "strand_twist")
_WHOLE = {"count", "strands"}

#: The action group the keys are filed under in the Graph Editor.
GROUP = "Filament"


class PBFilamentParameters(PropertyGroup):
    """A filament's numbers, as keyframes see them. See the module docstring."""

    count: IntProperty(name="Subunits", min=1, max=symmetry_builder.MAX_COUNT,
                       default=10)
    rise: FloatProperty(name="Rise", default=0.0)
    twist: FloatProperty(name="Twist", default=0.0)
    strands: IntProperty(name="Strands", min=1, max=64, default=1)
    stagger: FloatProperty(name="Stagger", default=0.0)
    #: 0 for "evenly round the axis", as on the dialog's control.
    strand_twist: FloatProperty(name="Strand Twist", default=0.0)


def is_filament(molecule) -> bool:
    """Whether a molecule has a generated helical assembly built."""
    try:
        return assembly_core.built_assembly_id(molecule) == "generated:H"
    except ReferenceError:
        return False


def _owner(molecule):
    return symmetry_bend.owner_object(molecule)


def write_parameters(molecule) -> bool:
    """Put the filament's built numbers on its object, ready to be keyed."""
    obj = _owner(molecule)
    built = assembly_core.built_build_params(molecule)
    if obj is None or not built:
        return False
    lattice = symmetry_builder.lattice_settings(built)
    values = {
        "count": int(built.get("count", 10)),
        "rise": float(built.get("rise", 0.0)),
        "twist": float(built.get("twist", 0.0)),
        "strands": lattice["strands"],
        "stagger": lattice["stagger"],
        "strand_twist": lattice["strand_twist"] or 0.0,
    }
    target = getattr(obj, DATA_PATH)
    for name, value in values.items():
        setattr(target, name, value)
    return True


def keyframe_parameters(molecule, frame: int) -> int:
    """Key every number the filament is built from at ``frame``. Returns how many."""
    obj = _owner(molecule)
    if obj is None or not write_parameters(molecule):
        return 0
    keyed = 0
    for name in PARAMETERS:
        if obj.keyframe_insert(data_path=f"{DATA_PATH}.{name}", frame=frame,
                               group=GROUP):
            keyed += 1
    return keyed


def delete_parameter_keyframes(obj, frame: int) -> None:
    """Take the numbers' keys at ``frame`` off a filament's object."""
    if obj is None or obj.animation_data is None or obj.animation_data.action is None:
        return
    for name in PARAMETERS:
        try:
            obj.keyframe_delete(data_path=f"{DATA_PATH}.{name}", frame=frame)
        except (RuntimeError, TypeError):
            pass  # not keyed at that frame


def parameter_fcurves(obj) -> dict:
    """``{name: fcurve}`` for each of the filament's numbers that is keyed."""
    if obj is None or obj.animation_data is None or obj.animation_data.action is None:
        return {}
    from ..utils.animation import get_fcurves_from_action

    prefix = f"{DATA_PATH}."
    found = {}
    for fcurve in get_fcurves_from_action(obj.animation_data.action,
                                          obj.animation_data):
        if fcurve.data_path.startswith(prefix) and len(fcurve.keyframe_points):
            name = fcurve.data_path[len(prefix):]
            if name in PARAMETERS:
                found[name] = fcurve
    return found


def bend_objects(molecule) -> list:
    """The bend curve and its control nodes: what shapes the filament's path."""
    owner = _owner(molecule)
    curve = bend_rig.get_curve(symmetry_bend.SPEC, owner)
    objects = [curve] if curve is not None else []
    objects.extend(bend_rig.get_nodes(symmetry_bend.SPEC, owner))
    return objects


def _bend_is_animated(molecule) -> bool:
    from ..utils.animation import get_fcurves_from_action

    for obj in bend_objects(molecule):
        animation = obj.animation_data
        if animation is None or animation.action is None:
            continue
        if any(len(fcurve.keyframe_points)
               for fcurve in get_fcurves_from_action(animation.action, animation)):
            return True
    return False


def settings_at(molecule, frame: float):
    """What the filament is built from at ``frame``, or None if not keyed.

    The record, with every keyed number replaced by its value at that frame.
    Read off the F-curves rather than the evaluated property, because an
    animation render evaluates into a depsgraph of its own and leaves the
    object's own value where the viewport last put it.
    """
    obj = _owner(molecule)
    curves = parameter_fcurves(obj)
    built = assembly_core.built_build_params(molecule)
    if not curves or not built:
        return None
    settings = dict(built)
    for name, fcurve in curves.items():
        value = float(fcurve.evaluate(frame))
        if name in _WHOLE:
            value = max(int(math.floor(value + 0.5)), 1)
        settings[name] = value
    # 0 between strands is "evenly", as on the dialog's control.
    settings.update(symmetry_builder.lattice_settings(settings))
    settings["count"] = min(int(settings.get("count", 10)), symmetry_builder.MAX_COUNT)
    return settings


def _differs(first: dict, second: dict) -> bool:
    for name in PARAMETERS:
        a, b = first.get(name), second.get(name)
        if a is None or b is None:
            if a != b:
                return True
        elif abs(float(a) - float(b)) > 1e-6:
            return True
    return False


def follow_animation(molecule, frame: float, depsgraph=None) -> bool:
    """Re-place a filament's copies for ``frame``. Returns True if it did.

    Does nothing to a filament with no keyed numbers and no keyed bend. A
    keyed bend is followed here as well as by the drag handler, because a
    frame change is not a drag: the nodes move without anyone touching them.
    """
    if not is_filament(molecule):
        return False
    built = assembly_core.built_build_params(molecule)
    if not built:
        return False
    wanted = settings_at(molecule, frame)
    bent = _bend_is_animated(molecule)
    changed = wanted is not None and _differs(wanted, built)
    if not changed and not bent:
        return False

    settings = wanted if wanted is not None else built
    lattice = symmetry_builder.lattice_settings(settings)
    operators = symmetry_bend.build_operators(
        molecule, "H", count=int(settings.get("count", 10)),
        rise=float(settings.get("rise", 0.0)),
        twist=float(settings.get("twist", 0.0)),
        axis=tuple(settings.get("axis", (0.0, 0.0, 1.0))),
        depsgraph=depsgraph, **lattice)
    if not operators or not assembly_core.update_operator_points(molecule, operators):
        return False
    if changed:
        assembly_core.record_build_params(molecule, dict(settings))
    return True


#: Re-entrancy guard: writing the point clouds tags the depsgraph again.
_following = False


@persistent
def filament_frame_change(scene, depsgraph=None):
    """Bring every keyframed filament to the frame now showing."""
    global _following
    if _following:
        return
    try:
        from ..utils.scene_manager import ProteinBlenderScene
        molecules = list(ProteinBlenderScene.get_instance().molecules.values())
    except Exception:
        return
    _following = True
    try:
        frame = scene.frame_current + scene.frame_subframe
        for molecule in molecules:
            try:
                follow_animation(molecule, frame, depsgraph)
            except ReferenceError:
                continue
    except Exception:
        # A handler that raises is one Blender disables for the session.
        logger.exception("could not follow the filament animation")
    finally:
        _following = False


def register():
    bpy.utils.register_class(PBFilamentParameters)
    bpy.types.Object.pb_filament = PointerProperty(type=PBFilamentParameters)
    if filament_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(filament_frame_change)


def unregister():
    if filament_frame_change in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(filament_frame_change)
    if hasattr(bpy.types.Object, "pb_filament"):
        del bpy.types.Object.pb_filament
    try:
        bpy.utils.unregister_class(PBFilamentParameters)
    except RuntimeError:
        pass
