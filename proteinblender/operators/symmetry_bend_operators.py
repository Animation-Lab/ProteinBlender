"""Operators for the helical filament's bend rig.

Thin Blender-facing wrappers; the geometry is in ``core.symmetry_bend`` and the
rig itself in ``core.bend_rig``.

The handler at the bottom is what makes the bend feel like the DNA one: when a
control node moves, the built filament follows it in the same viewport update.
It re-places the existing copies in place rather than rebuilding the assembly,
because building tears down and recreates objects and node groups - which is
exactly what must not happen inside a depsgraph callback.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..core import bend_rig, symmetry_bend
from ..utils.scene_manager import ProteinBlenderScene, resolve_active_molecule_id


def _molecule(molecule_id):
    return ProteinBlenderScene.get_instance().molecules.get(molecule_id)


def _active(context, molecule_id=""):
    return _molecule(molecule_id or resolve_active_molecule_id(context) or "")


def _settings(context):
    scene = context.scene
    return dict(
        count=getattr(scene, "pb_symmetry_count", 10),
        rise=getattr(scene, "pb_symmetry_rise", 0.0),
        twist=getattr(scene, "pb_symmetry_twist", 0.0),
        axis=tuple(getattr(scene, "pb_symmetry_axis", (0.0, 0.0, 1.0))),
    )


def _refresh_ui(context):
    for area in getattr(context.screen, "areas", []):
        area.tag_redraw()


def _rebuild_filament(context, molecule) -> bool:
    """Re-place a built helical filament against the current bend.

    Only touches a filament that is actually built - adding or removing a bend
    with nothing on screen just leaves the rig ready for the next Build.
    """
    tag = assembly_core.built_assembly_id(molecule)
    if tag is None or not str(tag).startswith("generated:H"):
        return False

    operators = symmetry_bend.build_operators(molecule, "H", **_settings(context))
    if not operators:
        return False
    if assembly_core.update_operator_points(molecule, operators):
        return True
    return assembly_core.apply_operators(molecule, operators, str(tag))


def _select_nodes(context, nodes):
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    for node in nodes:
        try:
            node.select_set(True)
        except Exception:
            pass
    if nodes:
        context.view_layer.objects.active = nodes[0]


class MOLECULE_PB_OT_add_filament_bend(Operator):
    """Give the filament a path to follow"""

    bl_idname = "molecule.add_filament_bend"
    bl_label = "Add Bend"
    bl_description = (
        "Add a curve along the filament with draggable control nodes. The "
        "subunits are re-placed along it and stay rigid - a real filament "
        "bends by reorienting its subunits, not by distorting them")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule = _active(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}
        if symmetry_bend.has_bend(molecule):
            self.report({"INFO"}, "This filament already has a bend")
            return {"CANCELLED"}

        settings = _settings(context)
        curve = symmetry_bend.add_bend(
            molecule,
            count=settings["count"], rise=settings["rise"],
            axis=settings["axis"],
            n_points=getattr(context.scene, "pb_bend_nodes", bend_rig.RES_DEFAULT))
        if curve is None:
            self.report({"WARNING"},
                        "This filament has no length to bend along")
            return {"CANCELLED"}

        _rebuild_filament(context, molecule)
        _select_nodes(context, symmetry_bend.get_bend_nodes(molecule))
        self.report({"INFO"},
                    "Bend added - drag the control nodes to curve the filament")
        _refresh_ui(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_edit_filament_bend(Operator):
    """Select the bend's control nodes so they can be dragged"""

    bl_idname = "molecule.edit_filament_bend"
    bl_label = "Edit Bend"
    bl_description = (
        "Select the filament's control nodes. Drag them with the usual "
        "transform gizmo; the copies follow as you go")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule = _active(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}

        nodes = symmetry_bend.get_bend_nodes(molecule)
        if not nodes:
            self.report({"WARNING"}, "This filament has no bend to edit")
            return {"CANCELLED"}

        _select_nodes(context, nodes)
        _refresh_ui(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_set_filament_bend_nodes(Operator):
    """Change how many control nodes shape the bend"""

    bl_idname = "molecule.set_filament_bend_nodes"
    bl_label = "Bend Nodes"
    bl_description = (
        "Change how many handles shape the path. The bend you have already "
        "made is resampled onto the new handles rather than reset")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    n_points: IntProperty(default=bend_rig.RES_DEFAULT,
                          min=bend_rig.RES_MIN, max=bend_rig.RES_MAX)

    def execute(self, context):
        molecule = _active(context, self.molecule_id)
        if molecule is None or not symmetry_bend.has_bend(molecule):
            self.report({"WARNING"}, "This filament has no bend")
            return {"CANCELLED"}

        if bend_rig.has_keyframes(symmetry_bend.SPEC,
                                  symmetry_bend.owner_object(molecule)):
            # Rebuilding recreates the Empties, orphaning every F-curve keyed
            # against the old ones. Refusing is kinder than silently losing an
            # animation the user cannot see has gone.
            self.report({"WARNING"},
                        "This bend is keyframed - remove the keys before "
                        "changing the node count")
            return {"CANCELLED"}

        if not symmetry_bend.set_node_count(molecule, self.n_points):
            self.report({"ERROR"}, "Could not change the node count")
            return {"CANCELLED"}

        _rebuild_filament(context, molecule)
        _select_nodes(context, symmetry_bend.get_bend_nodes(molecule))
        _refresh_ui(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_filament_bend_preset(Operator):
    """Start the bend from one of a few shapes"""

    bl_idname = "molecule.filament_bend_preset"
    bl_label = "Bend Preset"
    bl_description = (
        "Replace the path with a starting shape. It is a starting point, not "
        "a constraint - the control nodes still move afterwards")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()
    preset: StringProperty(default="STRAIGHT")

    def execute(self, context):
        molecule = _active(context, self.molecule_id)
        if molecule is None or not symmetry_bend.has_bend(molecule):
            self.report({"WARNING"}, "This filament has no bend")
            return {"CANCELLED"}

        settings = _settings(context)
        if not symmetry_bend.apply_preset(
                molecule, self.preset,
                count=settings["count"], rise=settings["rise"],
                axis=settings["axis"]):
            self.report({"ERROR"}, "Could not apply that shape")
            return {"CANCELLED"}

        _rebuild_filament(context, molecule)
        _select_nodes(context, symmetry_bend.get_bend_nodes(molecule))
        self.report({"INFO"}, f"Bend set to {self.preset.title()}")
        _refresh_ui(context)
        return {"FINISHED"}


class MOLECULE_PB_OT_remove_filament_bend(Operator):
    """Take the bend away, straightening the filament"""

    bl_idname = "molecule.remove_filament_bend"
    bl_label = "Remove Bend"
    bl_description = (
        "Delete the bend curve and its control nodes. The filament goes back "
        "to running straight along its axis")
    bl_options = {"REGISTER", "UNDO"}

    molecule_id: StringProperty()

    def execute(self, context):
        molecule = _active(context, self.molecule_id)
        if molecule is None:
            self.report({"ERROR"}, "No protein selected")
            return {"CANCELLED"}
        if not symmetry_bend.remove_bend(molecule):
            self.report({"INFO"}, "This filament has no bend")
            return {"CANCELLED"}

        _rebuild_filament(context, molecule)
        self.report({"INFO"}, "Bend removed - the filament is straight again")
        _refresh_ui(context)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Following the control nodes live
# ---------------------------------------------------------------------------

#: Re-entrancy guard. Writing the point cloud's attributes queues another
#: depsgraph update, and without this the handler would answer its own work
#: forever.
_following = False


@persistent
def filament_bend_follow_handler(scene, depsgraph):
    """Re-place a built filament when one of its control nodes is dragged.

    Deliberately narrow: it does nothing at all unless a *transform* update
    landed on an object that some molecule claims as a bend control node. The
    common case - any other depsgraph tick in the session - costs one pass over
    the update list and returns.
    """
    global _following
    if _following:
        return

    moved = {update.id.name for update in depsgraph.updates
             if update.is_updated_transform
             and isinstance(update.id, bpy.types.Object)}
    if not moved:
        return

    try:
        molecules = ProteinBlenderScene.get_instance().molecules
    except Exception:
        return

    _following = True
    try:
        for molecule in list(molecules.values()):
            nodes = symmetry_bend.get_bend_nodes(molecule)
            if not nodes or not any(node.name in moved for node in nodes):
                continue

            tag = assembly_core.built_assembly_id(molecule)
            if tag is None or not str(tag).startswith("generated:H"):
                continue

            operators = symmetry_bend.build_operators(
                molecule, "H",
                count=getattr(scene, "pb_symmetry_count", 10),
                rise=getattr(scene, "pb_symmetry_rise", 0.0),
                twist=getattr(scene, "pb_symmetry_twist", 0.0),
                axis=tuple(getattr(scene, "pb_symmetry_axis", (0.0, 0.0, 1.0))),
            )
            if operators:
                # In place only. A full rebuild from here would create and
                # remove objects inside the depsgraph's own callback.
                assembly_core.update_operator_points(molecule, operators)
    except Exception:
        # A handler that raises is a handler Blender disables, taking the live
        # bend with it for the rest of the session.
        import logging
        logging.getLogger(__name__).exception(
            "could not follow the filament bend")
    finally:
        _following = False


@persistent
def filament_bend_load_post(_dummy):
    bend_rig.cleanup_orphans(symmetry_bend.SPEC)


def register_handlers():
    if filament_bend_follow_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(filament_bend_follow_handler)
    if filament_bend_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(filament_bend_load_post)


def unregister_handlers():
    if filament_bend_follow_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(filament_bend_follow_handler)
    if filament_bend_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(filament_bend_load_post)


CLASSES = (
    MOLECULE_PB_OT_add_filament_bend,
    MOLECULE_PB_OT_edit_filament_bend,
    MOLECULE_PB_OT_set_filament_bend_nodes,
    MOLECULE_PB_OT_filament_bend_preset,
    MOLECULE_PB_OT_remove_filament_bend,
)
