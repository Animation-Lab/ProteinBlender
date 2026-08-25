"""The Symmetry panel - what belongs to the *protein*, not to a Symmetry.

Generating a symmetry is not done here. A built symmetry is an object in its
own right, so it is created from the Builders panel alongside a membrane or a
DNA strand, and edited from its own row in the PB Outliner. What is left here
is everything that is a property of the protein rather than of that object:

* the **deposited assembly** its file describes, shown only when the file
  describes symmetry that would put something new on screen - the meeting's
  "only show if symmetry is present in the PDB". See
  ``core.assembly.has_buildable_symmetry`` for why "the file mentions an
  assembly" is not that test;
* the **bend** rig for a built filament, and the **animation** controls for
  whatever is built, both of which are live and continuous and so want a panel
  that stays on screen rather than a dialog that closes over them.
"""

from bpy.types import Panel

from ..core import assembly as assembly_core
from ..core import symmetry_builder
from ..utils.scene_manager import resolve_active_molecule


def _active_molecule(context):
    return resolve_active_molecule(context)


class PROTEINBLENDER_PT_symmetry(Panel):
    """Deposited assemblies and generated symmetry for the active protein."""

    bl_label = "Symmetry"
    bl_idname = "PROTEINBLENDER_PT_symmetry"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 2  # after the outliner

    @classmethod
    def poll(cls, context):
        """Shown whenever a protein is active - the builder always applies."""
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
        box.label(text="Symmetry", icon='MOD_ARRAY')

        built_id = assembly_core.built_assembly_id(molecule)

        if assembly_core.has_buildable_symmetry(molecule):
            self._draw_deposited(box, scene, molecule)
        else:
            note = box.row()
            note.enabled = False
            note.label(text="No assembly deposited with this structure",
                       icon='INFO')

        # No builder section here: a symmetry is an object, so it is created
        # from the Builders panel like a membrane or a strand, and edited from
        # its own row in the PB Outliner. This panel is left with what belongs
        # to the *protein* - the assembly its file describes - and with the
        # controls that act on a build already on screen.

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

    # -- deposited ---------------------------------------------------------

    def _draw_deposited(self, box, scene, molecule):
        box.label(text="Deposited Assembly")

        col = box.column(align=True)
        col.prop(scene, "pb_assembly_id", text="")

        chosen = (getattr(scene, "pb_assembly_id", "")
                  or assembly_core.ASYMMETRIC_UNIT_ID)
        showing_unit = chosen == assembly_core.ASYMMETRIC_UNIT_ID

        build = box.row(align=True)
        build.scale_y = 1.2
        # One button, named for whichever of the picker's states it applies -
        # so "Build Assembly" never sits above a picker set to the asymmetric
        # unit, where pressing it would take copies away rather than add them.
        op = build.operator(
            "molecule.build_assembly",
            text="Show Asymmetric Unit" if showing_unit else "Build Assembly",
            icon='LOOP_BACK' if showing_unit else 'MOD_ARRAY')
        op.molecule_id = molecule.identifier
        op.assembly_id = chosen

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
