"""Operators module for ProteinBlender.

This module exports all operator classes used by the ProteinBlender addon.
"""

from .molecule_operators import (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_move_protein_pivot,
    MOLECULE_PB_OT_snap_protein_pivot_center,
    MOLECULE_PB_OT_toggle_protein_pivot_edit,
    MOLECULE_PB_OT_toggle_visibility,
)
from .operator_import_protein import MOLECULE_OT_import_protein
from .operator_import_local import MOLECULE_OT_import_local
from .selection_operators import MOLECULE_PB_OT_select_object
from .domain_operators import (
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_protein,
    MOLECULE_PB_OT_select_keyframe,
    MOLECULE_PB_OT_delete_keyframe,
    MOLECULE_PB_OT_edit_keyframe,
    MOLECULE_PB_OT_update_domain,
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_toggle_domain_expanded,
    MOLECULE_PB_OT_update_domain_ui_values,
    MOLECULE_PB_OT_update_domain_color,
    MOLECULE_PB_OT_update_domain_style,
    MOLECULE_PB_OT_update_domain_name,
    MOLECULE_PB_OT_update_domain_name_dialog,
    MOLECULE_PB_OT_initialize_domain_temp_name,
    MOLECULE_PB_OT_toggle_pivot_edit,
    MOLECULE_PB_OT_set_parent_domain,
    MOLECULE_PB_OT_update_parent_domain,
    MOLECULE_PB_OT_reset_domain_transform,
    MOLECULE_PB_OT_snap_pivot_to_residue,
    MOLECULE_PB_OT_split_domain,
)
from .pose_operators import (
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_apply_pose_and_keyframe,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
)
from .outliner_operators import (
    PROTEIN_PB_OT_rename_outliner_item,
    PROTEIN_PB_OT_manage_domains,
)

CLASSES = (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_OT_import_protein,
    MOLECULE_OT_import_local,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_move_protein_pivot,
    MOLECULE_PB_OT_snap_protein_pivot_center,
    MOLECULE_PB_OT_toggle_protein_pivot_edit,
    MOLECULE_PB_OT_toggle_visibility,
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_protein,
    MOLECULE_PB_OT_select_keyframe,
    MOLECULE_PB_OT_delete_keyframe,
    MOLECULE_PB_OT_edit_keyframe,
    MOLECULE_PB_OT_update_domain,
    MOLECULE_PB_OT_toggle_domain_expanded,
    MOLECULE_PB_OT_update_domain_ui_values,
    MOLECULE_PB_OT_update_domain_color,
    MOLECULE_PB_OT_update_domain_style,
    MOLECULE_PB_OT_update_domain_name,
    MOLECULE_PB_OT_update_domain_name_dialog,
    MOLECULE_PB_OT_initialize_domain_temp_name,
    MOLECULE_PB_OT_toggle_pivot_edit,
    MOLECULE_PB_OT_set_parent_domain,
    MOLECULE_PB_OT_update_parent_domain,
    MOLECULE_PB_OT_select_object,
    MOLECULE_PB_OT_reset_domain_transform,
    MOLECULE_PB_OT_snap_pivot_to_residue,
    MOLECULE_PB_OT_split_domain,
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_apply_pose_and_keyframe,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
    PROTEIN_PB_OT_rename_outliner_item,
    PROTEIN_PB_OT_manage_domains,
)