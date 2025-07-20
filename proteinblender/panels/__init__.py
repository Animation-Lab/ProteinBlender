# protein_workspace/panels/__init__.py
from .panel_import_protein import PROTEIN_PB_PT_import_protein
from .outliner_panel import PROTEIN_PB_PT_outliner
from .outliner_panel_v2 import VIEW3D_PT_pb_protein_outliner, PROTEIN_PB_OT_toggle_outliner_expand
from .visual_setup_panel import VIEW3D_PT_pb_visual_setup, PROTEIN_PB_OT_sync_visual_selection
from .domain_maker_panel import VIEW3D_PT_pb_domain_maker, PB_OT_split_chain, PB_OT_auto_split_chains
from .group_maker_panel import VIEW3D_PT_pb_group_maker, PB_OT_create_edit_group, PB_OT_toggle_group_member, PB_OT_delete_group
from .pose_library_panel import VIEW3D_PT_pb_protein_pose_library, PB_OT_create_edit_pose, PB_OT_apply_pose, PB_OT_update_pose, PB_OT_delete_pose
from .animate_scene_panel import VIEW3D_PT_pb_animate_scene, PB_OT_move_pivot, PB_OT_snap_to_center, PB_OT_add_keyframe
from .ui_panels import VIEW3D_PT_pb_importer

CLASSES = [
    # Original panels (keep for compatibility)
    PROTEIN_PB_PT_import_protein,
    PROTEIN_PB_PT_outliner,
    # New workspace panels in order
    VIEW3D_PT_pb_importer,  # Panel 1
    VIEW3D_PT_pb_protein_outliner,  # Panel 2
    PROTEIN_PB_OT_toggle_outliner_expand,
    VIEW3D_PT_pb_visual_setup,  # Panel 3
    PROTEIN_PB_OT_sync_visual_selection,
    VIEW3D_PT_pb_domain_maker,  # Panel 4
    PB_OT_split_chain,
    PB_OT_auto_split_chains,
    VIEW3D_PT_pb_group_maker,  # Panel 5
    PB_OT_create_edit_group,
    PB_OT_toggle_group_member,
    PB_OT_delete_group,
    VIEW3D_PT_pb_protein_pose_library,  # Panel 6
    PB_OT_create_edit_pose,
    PB_OT_apply_pose,
    PB_OT_update_pose,
    PB_OT_delete_pose,
    VIEW3D_PT_pb_animate_scene,  # Panel 7
    PB_OT_move_pivot,
    PB_OT_snap_to_center,
    PB_OT_add_keyframe,
] 