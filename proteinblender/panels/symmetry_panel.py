"""Live controls for the assembly child selected in the PB Outliner.

Creation and editing share the Assembly dialog. Animation and bend controls
stay beside the viewport while working with an existing assembly child.
"""

from bpy.types import Panel

from ..core import assembly as assembly_core
from ..core import symmetry_builder
from ..utils.scene_manager import resolve_active_assembly_molecule


def _active_molecule(context):
    return resolve_active_assembly_molecule(context)


class PROTEINBLENDER_PT_symmetry(Panel):
    """Animation and bend controls for either kind of assembly child."""

    bl_label = "Assembly Controls"
    bl_idname = "PROTEINBLENDER_PT_symmetry"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 2  # after the outliner

    @classmethod
    def poll(cls, context):
        """Open through an assembly child, for both deposited and generated builds."""
        try:
            return _active_molecule(context) is not None
        except Exception:
            return False

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        molecule = _active_molecule(context)
        if molecule is None:
            return

        box = layout.box()
        box.label(text=f"Assembly Controls - {molecule.identifier}", icon='MOD_ARRAY')

        built_id = assembly_core.built_assembly_id(molecule)

        # Bend follows what is *built*, not what the dialog's picker says: a
        # path to bend exists once there is a filament on screen. It stays on
        # the panel rather than moving into the dialog because dragging the
        # control nodes is a mode, and a dialog that closes over it would end
        # the drag at the moment it began.
        if symmetry_builder.built_symmetry_kind(molecule) == "H":
            box.separator()
            self._draw_bend(box, scene, molecule)

        if built_id is not None:
            box.separator()
            self._draw_animation(box, scene, molecule, built_id)

        box.separator(factor=0.5)

    # -- bending a filament -------------------------------------------------

    def _draw_bend(self, box, scene, molecule):
        """Only for helical: a ring or a double ring has no path to follow."""
        from ..core import bend_rig, symmetry_bend

        box.separator(factor=0.5)
        box.label(text="Bend")

        if not symmetry_bend.has_bend(molecule):
            note = box.row()
            note.enabled = False
            note.label(text="Subunits stay rigid - the path bends, not them",
                       icon='INFO')
            add = box.row(align=True)
            add_op = add.operator("molecule.add_filament_bend",
                                  text="Add Bend", icon='CURVE_BEZCURVE')
            add_op.molecule_id = molecule.identifier
            return

        nodes = symmetry_bend.get_bend_nodes(molecule)

        count = box.row(align=True)
        count.prop(scene, "pb_bend_nodes")
        apply_count = count.operator("molecule.set_filament_bend_nodes",
                                     text="", icon='CHECKMARK')
        apply_count.molecule_id = molecule.identifier
        apply_count.n_points = getattr(scene, "pb_bend_nodes",
                                       bend_rig.RES_DEFAULT)

        presets = box.row(align=True)
        for identifier, label, _description in bend_rig.PRESETS:
            preset_op = presets.operator("molecule.filament_bend_preset",
                                         text=label)
            preset_op.molecule_id = molecule.identifier
            preset_op.preset = identifier

        actions = box.row(align=True)
        edit_op = actions.operator("molecule.edit_filament_bend",
                                   text="Edit Bend", icon='EMPTY_DATA')
        edit_op.molecule_id = molecule.identifier
        remove_op = actions.operator("molecule.remove_filament_bend",
                                     text="Remove", icon='X')
        remove_op.molecule_id = molecule.identifier

        # Say whether the rig is doing anything, not merely that it exists -
        # a freshly added bend is straight until a node is dragged. Measured
        # against the settings the filament was *built* from, which the
        # scene sliders no longer have to agree with now that they are the
        # dialog's working copy.
        built = assembly_core.built_build_params(molecule) or {}
        departure = symmetry_bend.bend_departure(
            molecule,
            count=built.get("count", getattr(scene, "pb_symmetry_count", 10)),
            rise=built.get("rise", getattr(scene, "pb_symmetry_rise", 0.0)),
            twist=built.get("twist", getattr(scene, "pb_symmetry_twist", 0.0)),
            axis=tuple(built.get(
                "axis", getattr(scene, "pb_symmetry_axis", (0.0, 0.0, 1.0)))))

        status = box.row()
        status.enabled = False
        if departure < 1.0:
            status.label(text=f"{len(nodes)} nodes - drag one to bend",
                         icon='INFO')
        else:
            status.label(text=f"Tip is {departure:.0f} A off straight",
                         icon='CHECKMARK')

    # -- animation ---------------------------------------------------------

    def _draw_animation(self, box, scene, molecule, built_id):
        kind = symmetry_builder.built_symmetry_kind(molecule)
        label = f"Generated {kind}" if kind else f"Assembly {built_id}"
        box.label(text=f"{label} built", icon='CHECKMARK')

        anim = box.column(align=True)
        anim.prop(scene, "pb_assembly_factor", slider=True)
        anim.prop(scene, "pb_assembly_stagger", slider=True)

        from ..core import symmetry_axes
        axes_row = box.row(align=True)
        showing = bool(symmetry_axes.symmetry_axis_objects(molecule))
        axes_op = axes_row.operator(
            "molecule.toggle_symmetry_axes",
            text="Hide Symmetry Axes" if showing else "Show Symmetry Axes",
            icon='EMPTY_AXIS')
        axes_op.molecule_id = molecule.identifier

        row = box.row(align=True)
        row.scale_y = 1.1
        key = row.operator("molecule.keyframe_assembly",
                           text="Keyframe", icon='KEY_HLT')
        key.molecule_id = molecule.identifier
        clear = row.operator("molecule.clear_assembly", text="Clear")
        clear.molecule_id = molecule.identifier

        box.separator(factor=0.5)
        box.label(text="Cutaway")
        cut = box.column(align=True)
        cut_row = cut.row(align=True)
        cut_row.label(text="Direction")
        cut_row.prop(scene, "pb_cutaway_normal", text="")
        cut.prop(scene, "pb_cutaway_offset")
        cut_row = box.row(align=True)
        cut_op = cut_row.operator("molecule.cutaway", text="Cut Away",
                                  icon='MOD_BOOLEAN')
        cut_op.molecule_id = molecule.identifier

        box.separator(factor=0.5)
        real = box.row(align=True)
        real_op = real.operator("molecule.realize_copies",
                                text="Realize Copies", icon='OUTLINER_OB_MESH')
        real_op.molecule_id = molecule.identifier

        note = box.row()
        note.enabled = False
        note.label(text="Copies are instances - one set of atoms", icon='INFO')


CLASSES = (
    PROTEINBLENDER_PT_symmetry,
)
