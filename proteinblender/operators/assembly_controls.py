"""Assembly controls opened explicitly from an assembly's PB Outliner row."""

from bpy.props import FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..core import assembly as assembly_core
from ..core import bend_rig, symmetry_builder, symmetry_bend
from ..utils.scene_manager import ProteinBlenderScene


class MOLECULE_PB_OT_assembly_controls(Operator):
    bl_idname = "molecule.assembly_controls"
    bl_label = "Assembly Controls"
    bl_description = (
        "Assembly Controls: adjust assembly progress and copy delay, keyframe "
        "the assembly, show axes, cut away copies, or bend a filament")
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    molecule_id: StringProperty(options={'HIDDEN'})
    progress: FloatProperty(
        name="Assembly progress", min=0.0, max=1.0, default=1.0,
        subtype='FACTOR',
        description="0 overlaps the copies; 1 places them in the full assembly")
    copy_delay: FloatProperty(
        name="Copy delay", min=0.0, max=1.0, default=0.0,
        subtype='FACTOR',
        description="Delay successive copies during assembly progress; has no effect at 0 or 1")
    cut_direction: FloatVectorProperty(
        name="Cut Direction", default=(0.0, -1.0, 0.0), size=3, subtype='XYZ',
        description="The side of the assembly to take away")
    cut_depth: FloatProperty(
        name="Cut Depth", default=0.0, min=-1000.0, max=1000.0,
        description="Angstrom to move the cut plane; larger values take less away")
    bend_nodes: IntProperty(
        name="Nodes", default=bend_rig.RES_DEFAULT,
        min=bend_rig.RES_MIN, max=bend_rig.RES_MAX,
        description="How many control handles shape the filament's bend path")

    def _molecule(self):
        molecule = ProteinBlenderScene.get_instance().molecules.get(self.molecule_id)
        if molecule is not None and assembly_core.built_assembly_id(molecule) is not None:
            return molecule
        return None

    def invoke(self, context, event):
        molecule = self._molecule()
        if molecule is None:
            self.report({'WARNING'}, "This assembly is no longer available")
            return {'CANCELLED'}
        self.progress = assembly_core.get_assembly_factor(molecule)
        self.copy_delay = assembly_core.get_assembly_stagger(molecule)
        self.bend_nodes = len(symmetry_bend.get_bend_nodes(molecule)) or bend_rig.RES_DEFAULT
        # Auto-execution gives edits immediate viewport feedback and Blender
        # undo, just like the outliner's color popup. Dismissing keeps edits.
        return context.window_manager.invoke_props_popup(self, event)

    def check(self, context):
        return True

    def execute(self, context):
        molecule = self._molecule()
        if molecule is None:
            return {'CANCELLED'}
        assembly_core.set_assembly_factor(molecule, self.progress, stagger=self.copy_delay)
        for area in getattr(context.screen, 'areas', []):
            area.tag_redraw()
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        molecule = self._molecule()
        if molecule is None:
            layout.label(text="This assembly is no longer available", icon='INFO')
            return
        layout.label(text=molecule.identifier, icon='MOD_ARRAY')
        self._draw_animation(layout, molecule,
                             assembly_core.built_assembly_id(molecule))
        if symmetry_builder.built_symmetry_kind(molecule) == 'H':
            layout.separator()
            self._draw_bend(layout, context.scene, molecule)

    # -- bending a filament -------------------------------------------------

    def _draw_bend(self, box, scene, molecule):
        """Only for helical: a ring or a double ring has no path to follow."""
        box.separator(factor=0.5)
        box.label(text="Bend")

        if not symmetry_bend.has_bend(molecule):
            note = box.row()
            note.enabled = False
            note.label(text="Subunits stay rigid as the path bends",
                       icon='INFO')
            add = box.row(align=True)
            add_op = add.operator("molecule.add_filament_bend",
                                  text="Add Bend", icon='CURVE_BEZCURVE')
            add_op.molecule_id = molecule.identifier
            add_op.n_points = self.bend_nodes
            return

        nodes = symmetry_bend.get_bend_nodes(molecule)

        count = box.row(align=True)
        count.prop(self, "bend_nodes")
        apply_count = count.operator("molecule.set_filament_bend_nodes",
                                     text="", icon='CHECKMARK')
        apply_count.molecule_id = molecule.identifier
        apply_count.n_points = self.bend_nodes

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

        box.label(text="Close popup to drag the selected nodes", icon='INFO')

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

    def _draw_animation(self, box, molecule, built_id):
        kind = symmetry_builder.built_symmetry_kind(molecule)
        label = f"Generated {kind}" if kind else f"Assembly {built_id}"
        box.label(text=f"{label} built", icon='CHECKMARK')

        anim = box.column(align=True)
        anim.prop(self, "progress", slider=True)
        anim.prop(self, "copy_delay", slider=True)
        anim.label(text='0 = overlapping; 1 = assembled')
        anim.label(text='Copy delay affects progress between 0 and 1')
        edit = box.operator('molecule.symmetry_dialog', text='Change Assembly…', icon='GREASEPENCIL')
        edit.molecule_id_to_update = molecule.identifier

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
        cut_row.prop(self, "cut_direction", text="")
        cut.prop(self, "cut_depth")
        cut_row = box.row(align=True)
        cut_op = cut_row.operator("molecule.cutaway", text="Cut Away",
                                  icon='MOD_BOOLEAN')
        cut_op.molecule_id = molecule.identifier
        cut_op.normal = self.cut_direction
        cut_op.offset = self.cut_depth

        box.separator(factor=0.5)
        real = box.row(align=True)
        real_op = real.operator("molecule.realize_copies",
                                text="Realize Copies", icon='OUTLINER_OB_MESH')
        real_op.molecule_id = molecule.identifier

        note = box.row()
        note.enabled = False
        note.label(text="Copies are instances - one set of atoms", icon='INFO')


CLASSES = (MOLECULE_PB_OT_assembly_controls,)
