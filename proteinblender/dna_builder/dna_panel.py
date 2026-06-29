"""Builder panel for DNA/RNA creation.

The panel is intentionally minimal: just a "Create New DNA / RNA" button
that opens the build dialog (``proteinblender.build_dna``). Editing an
existing strand is driven from the PB Outliner's edit pencil, which
fires the same operator with ``molecule_id_to_update`` set — so the
create and edit flows are pixel-identical.

The Shape / bend-rig controls live inside that dialog too (edit mode
only). Nothing about DNA editing lives in this panel anymore.
"""

import bpy
from bpy.types import Panel


class PROTEINBLENDER_PT_builders(Panel):
    """Builders panel — entry point for the DNA / RNA build dialog."""

    bl_label = "Builders"
    bl_idname = "PROTEINBLENDER_PT_builders"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_order = 8  # After Flexible Linkers (7)
    bl_options = {'HIDE_HEADER', 'HEADER_LAYOUT_EXPAND'}

    def draw(self, context):
        layout = self.layout

        main_box = layout.box()
        main_box.label(text="Builders", icon="CURVE_DATA")
        main_box.separator()

        create_row = main_box.row()
        create_row.scale_y = 1.4
        create_row.operator(
            "proteinblender.build_dna",
            text="Create New DNA / RNA",
            icon="ADD",
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
