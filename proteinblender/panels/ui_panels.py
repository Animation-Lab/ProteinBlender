"""UI panels for the ProteinBlender workspace.

This module contains all the panels that appear in the right-side panel area
of the ProteinBlender workspace, in the specified order.
"""

import bpy
from bpy.types import Panel
from bpy.props import StringProperty, EnumProperty, FloatVectorProperty


# Panel 1: Importer (placeholder - using existing functionality)
class VIEW3D_PT_pb_importer(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"
    bl_label = "Importer"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Use existing import protein functionality
        if hasattr(scene, 'protein_props'):
            props = scene.protein_props
            
            # Method selector and identifier input
            row = layout.row(align=True)
            row.prop(props, "import_method", text="")
            if props.import_method in {'PDB', 'MMCIF'}:
                row.prop(props, "pdb_id", text="")
            elif props.import_method == 'ALPHAFOLD':
                row.prop(props, "uniprot_id", text="")
            
            # Import buttons
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("molecule.import_protein", text="Download")
            row.operator("molecule.import_local", text="Import Local")
        else:
            layout.label(text="Import functionality not available")


# Panel 2 is now handled by outliner_panel_v2.py
# This placeholder is kept for compatibility but won't be registered


# Panel 3 is now handled by visual_setup_panel.py
# This placeholder is kept for compatibility but won't be registered


# Panel 4 is now handled by domain_maker_panel.py
# This placeholder is kept for compatibility but won't be registered


# Panel 5 is now handled by group_maker_panel.py
# This placeholder is kept for compatibility but won't be registered


# Panel 6 is now handled by pose_library_panel.py
# This placeholder is kept for compatibility but won't be registered


# Panel 7 is now handled by animate_scene_panel.py
# This placeholder is kept for compatibility but won't be registered


# Placeholder operators for mock functionality
# PB_OT_split_chain is now in domain_maker_panel.py


# PB_OT_create_edit_group is now in group_maker_panel.py


class PB_OT_create_edit_pose(bpy.types.Operator):
    bl_idname = "pb.create_edit_pose"
    bl_label = "Create/Edit Pose"
    bl_description = "Create or edit a protein pose"
    
    def execute(self, context):
        self.report({'INFO'}, "Pose creation not yet implemented")
        return {'FINISHED'}


class PB_OT_apply_pose(bpy.types.Operator):
    bl_idname = "pb.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Apply the selected pose"
    
    def execute(self, context):
        self.report({'INFO'}, "Apply pose not yet implemented")
        return {'FINISHED'}


class PB_OT_update_pose(bpy.types.Operator):
    bl_idname = "pb.update_pose"
    bl_label = "Update Positions"
    bl_description = "Update pose positions"
    
    def execute(self, context):
        self.report({'INFO'}, "Update pose not yet implemented")
        return {'FINISHED'}


class PB_OT_move_pivot(bpy.types.Operator):
    bl_idname = "pb.move_pivot"
    bl_label = "Move Pivot"
    bl_description = "Move the pivot point"
    
    def execute(self, context):
        self.report({'INFO'}, "Move pivot not yet implemented")
        return {'FINISHED'}


class PB_OT_snap_to_center(bpy.types.Operator):
    bl_idname = "pb.snap_to_center"
    bl_label = "Snap to Center"
    bl_description = "Snap pivot to center"
    
    def execute(self, context):
        self.report({'INFO'}, "Snap to center not yet implemented")
        return {'FINISHED'}


# List of classes to register
CLASSES = [
    VIEW3D_PT_pb_importer,
    # VIEW3D_PT_pb_protein_outliner is now in outliner_panel_v2.py
    # VIEW3D_PT_pb_visual_setup is now in visual_setup_panel.py
    # VIEW3D_PT_pb_domain_maker is now in domain_maker_panel.py
    # VIEW3D_PT_pb_group_maker is now in group_maker_panel.py
    # VIEW3D_PT_pb_protein_pose_library is now in pose_library_panel.py
    # VIEW3D_PT_pb_animate_scene is now in animate_scene_panel.py
    # All operators have been moved to their respective panel files
]


def register():
    # Visual properties are now registered in visual_setup_panel.py
    # Only register brownian motion property here
    if not hasattr(bpy.types.Scene, "pb_brownian_motion"):
        bpy.types.Scene.pb_brownian_motion = bpy.props.BoolProperty(
            name="Brownian Motion",
            default=False,
        )
    
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            # Class already registered, skip
            pass


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    
    # Only remove brownian motion property
    if hasattr(bpy.types.Scene, "pb_brownian_motion"):
        del bpy.types.Scene.pb_brownian_motion