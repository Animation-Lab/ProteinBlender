"""The Symmetry panel - build the deposited biological assembly.

Appears only when the active protein's file describes symmetry that would
actually put something new on screen. See ``core.assembly.has_buildable_symmetry``
for why "the file mentions an assembly" is not that test.
"""

from bpy.types import Panel

from ..core import assembly as assembly_core
from ..utils.scene_manager import ProteinBlenderScene


def _active_molecule(context):
    molecule_id = getattr(context.scene, "selected_molecule_id", "")
    if not molecule_id:
        return None
    return ProteinBlenderScene.get_instance().molecules.get(molecule_id)


class PROTEINBLENDER_PT_symmetry(Panel):
    """Deposited biological assembly for the active protein."""

    bl_label = "Symmetry"
    bl_idname = "PROTEINBLENDER_PT_symmetry"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}
    bl_order = 2  # after the outliner

    @classmethod
    def poll(cls, context):
        """Hide the panel unless the active protein actually has symmetry.

        A structure with no deposited operators - or whose only operator is the
        identity, which is most monomers - gets no panel at all rather than a
        panel whose button does nothing.
        """
        try:
            molecule = _active_molecule(context)
        except Exception:
            return False
        return molecule is not None and assembly_core.has_buildable_symmetry(molecule)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        molecule = _active_molecule(context)
        if molecule is None:
            return

        box = layout.box()
        box.label(text="Symmetry", icon='MOD_ARRAY')

        built_id = assembly_core.built_assembly_id(molecule)

        col = box.column(align=True)
        col.prop(scene, "pb_assembly_id", text="")

        info = assembly_core.get_assembly_info(
            molecule, getattr(scene, "pb_assembly_id", "") or "")
        if info is not None:
            col.label(
                text=f"{info.transform_count} copies of "
                     f"{len(info.chain_ids)} chain"
                     f"{'' if len(info.chain_ids) == 1 else 's'}",
                icon='INFO')

        box.separator(factor=0.5)

        row = box.row(align=True)
        row.scale_y = 1.2
        build = row.operator("molecule.build_assembly", text="Build Assembly")
        build.molecule_id = molecule.identifier
        build.assembly_id = getattr(scene, "pb_assembly_id", "") or ""

        clear = row.row(align=True)
        clear.enabled = built_id is not None
        clear_op = clear.operator("molecule.clear_assembly", text="Clear")
        clear_op.molecule_id = molecule.identifier

        if built_id is not None:
            box.label(text=f"Assembly {built_id} built", icon='CHECKMARK')
            box.label(
                text="Copies are instances - one set of atoms",
                icon='INFO')

        box.separator(factor=0.5)


CLASSES = (
    PROTEINBLENDER_PT_symmetry,
)
