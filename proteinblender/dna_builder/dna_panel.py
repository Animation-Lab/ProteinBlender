"""Builders panel — entry points for the DNA/RNA and Membrane build dialogs.

Both builders share this one panel. Each is a single button that opens
its build dialog; editing an existing item is driven from the PB
Outliner's edit pencil, which fires the same operator with the
appropriate ``*_to_update`` argument (so create and edit show pixel-
identical dialogs).

The bend-rig controls for DNA live inside the DNA dialog (edit mode);
the hole / deformation controls for membranes live inside the membrane
dialog (edit mode). Nothing about a selected item shows in this panel.
"""

import bpy
from bpy.types import Panel


class PROTEINBLENDER_PT_builders(Panel):
    """Builders panel — entry point for the DNA/RNA and Membrane dialogs."""

    bl_label = "Builders"
    bl_idname = "PROTEINBLENDER_PT_builders"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    # Sits above Domain Maker (3, conditional) and Puppet Maker (4) — the
    # builders create the molecules everything downstream depends on, so
    # they belong near the top of the panel stack.
    bl_order = 3
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    def draw(self, context):
        layout = self.layout

        main_box = layout.box()
        main_box.label(text="Builders", icon="MOD_BUILD")
        main_box.separator()

        dna_row = main_box.row()
        dna_row.scale_y = 1.4
        dna_row.operator(
            "proteinblender.build_dna",
            text="Create New DNA / RNA",
            icon="RNA",
        )

        mem_row = main_box.row()
        mem_row.scale_y = 1.4
        mem_row.operator(
            "proteinblender.build_membrane",
            text="Create New Membrane",
            icon="MOD_FLUIDSIM",
        )

        # A built symmetry is an object like the other two, not a setting on
        # the protein it repeats, so its entry point belongs here rather than
        # in the Symmetry panel. Always shown, for the same reason the others
        # are: the button is how you find out the feature exists.
        sym_row = main_box.row()
        sym_row.scale_y = 1.4
        sym_row.operator(
            "molecule.symmetry_dialog",
            text="Create New Symmetry",
            icon="MOD_ARRAY",
        )


CLASSES = (PROTEINBLENDER_PT_builders,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
