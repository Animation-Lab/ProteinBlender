"""The Symmetry panel.

Two halves, gated differently on purpose.

The **deposited assembly** half only appears when the active protein's file
describes symmetry that would put something new on screen - the meeting's
"only show if symmetry is present in the PDB". See
``core.assembly.has_buildable_symmetry`` for why "the file mentions an
assembly" is not that test.

The **symmetry builder** half is always available. It is a construction tool,
not a reader: its whole purpose is giving symmetry to a structure whose file
has none, so gating it on the file having symmetry would hide it precisely
when it is wanted.
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

        box.separator()
        self._draw_builder(box, scene, molecule)

        if built_id is not None:
            box.separator()
            self._draw_animation(box, scene, molecule, built_id)

        box.separator(factor=0.5)

    # -- deposited ---------------------------------------------------------

    def _draw_deposited(self, box, scene, molecule):
        box.label(text="Deposited Assembly")

        col = box.column(align=True)
        col.prop(scene, "pb_assembly_id", text="")

        info = assembly_core.get_assembly_info(
            molecule, getattr(scene, "pb_assembly_id", "") or "")
        if info is not None:
            row = col.row()
            row.enabled = False
            row.label(text=f"{info.transform_count} copies of "
                           f"{len(info.chain_ids)} chain"
                           f"{'' if len(info.chain_ids) == 1 else 's'}")

        build = box.row(align=True)
        build.scale_y = 1.2
        op = build.operator("molecule.build_assembly", text="Build Assembly")
        op.molecule_id = molecule.identifier
        op.assembly_id = getattr(scene, "pb_assembly_id", "") or ""

    # -- generated ---------------------------------------------------------

    def _draw_builder(self, box, scene, molecule):
        box.label(text="Symmetry Builder")

        col = box.column(align=True)
        col.prop(scene, "pb_symmetry_kind", text="")

        kind = getattr(scene, "pb_symmetry_kind", "C")
        if kind in {"C", "D"}:
            col.prop(scene, "pb_symmetry_order")
        else:
            col.prop(scene, "pb_symmetry_count")
            col.prop(scene, "pb_symmetry_rise")
            col.prop(scene, "pb_symmetry_twist")
        col.prop(scene, "pb_symmetry_axis")

        summary = box.row()
        summary.enabled = False
        summary.label(text=symmetry_builder.describe(
            kind,
            order=getattr(scene, "pb_symmetry_order", 3),
            count=getattr(scene, "pb_symmetry_count", 10),
            rise=getattr(scene, "pb_symmetry_rise", 0.0),
            twist=getattr(scene, "pb_symmetry_twist", 0.0)))

        row = box.row(align=True)
        row.scale_y = 1.2
        op = row.operator("molecule.build_symmetry", text="Build Symmetry")
        op.molecule_id = molecule.identifier

    # -- animation ---------------------------------------------------------

    def _draw_animation(self, box, scene, molecule, built_id):
        kind = symmetry_builder.built_symmetry_kind(molecule)
        label = f"Generated {kind}" if kind else f"Assembly {built_id}"
        box.label(text=f"{label} built", icon='CHECKMARK')

        anim = box.column(align=True)
        anim.prop(scene, "pb_assembly_factor", slider=True)
        anim.prop(scene, "pb_assembly_stagger", slider=True)

        row = box.row(align=True)
        row.scale_y = 1.1
        key = row.operator("molecule.keyframe_assembly",
                           text="Keyframe", icon='KEY_HLT')
        key.molecule_id = molecule.identifier
        clear = row.operator("molecule.clear_assembly", text="Clear")
        clear.molecule_id = molecule.identifier

        note = box.row()
        note.enabled = False
        note.label(text="Copies are instances - one set of atoms", icon='INFO')


CLASSES = (
    PROTEINBLENDER_PT_symmetry,
)
