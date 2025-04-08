# proteinblender/operators/__init__.py

from .molecule_operators import (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_PB_OT_change_style,
)
from .operator_import_protein import PROTEIN_OT_import_protein
from .operator_import_local import PROTEIN_OT_import_local
from .selection_operators import MOLECULE_PB_OT_select_object
from .domain_operators import (
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_protein,
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
)
from .pose_operators import (
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
)

CLASSES = (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    PROTEIN_OT_import_protein,
    PROTEIN_OT_import_local,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_protein,
    MOLECULE_PB_OT_update_domain,
    MOLECULE_PB_OT_toggle_domain_expanded,
    MOLECULE_PB_OT_update_domain_ui_values,
    MOLECULE_PB_OT_update_domain_color,
    MOLECULE_PB_OT_update_domain_name,
    MOLECULE_PB_OT_update_domain_name_dialog,
    MOLECULE_PB_OT_initialize_domain_temp_name,
    MOLECULE_PB_OT_update_domain_style,
    MOLECULE_PB_OT_toggle_pivot_edit,
    MOLECULE_PB_OT_set_parent_domain,
    MOLECULE_PB_OT_update_parent_domain,
    MOLECULE_PB_OT_select_object,
    MOLECULE_PB_OT_reset_domain_transform,
    MOLECULE_PB_OT_snap_pivot_to_residue,
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
)