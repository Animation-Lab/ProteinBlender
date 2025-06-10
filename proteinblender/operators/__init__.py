# proteinblender/operators/__init__.py

import bpy

from .molecule_operators import (
    MOLECULE_OT_select,
    MOLECULE_OT_delete,
    MOLECULE_OT_add_domain,
    MOLECULE_OT_delete_domain,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_select_protein_chain,
    MOLECULE_PB_OT_move_protein_pivot,
    MOLECULE_PB_OT_snap_protein_pivot_center,
    MOLECULE_PB_OT_toggle_protein_pivot_edit,
    MOLECULE_PB_OT_toggle_visibility,
)
from .operator_import_protein import PROTEIN_OT_import_protein
from .operator_import_local import PROTEIN_OT_import_local
from .selection_operators import MOLECULE_PB_OT_select_object
from .domain_operators import (
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
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
)

# This list holds all operator classes that need to be registered.
CLASSES = [
    PROTEIN_OT_import_protein,
    PROTEIN_OT_import_local,
    MOLECULE_OT_select,
    MOLECULE_OT_delete,
    MOLECULE_OT_add_domain,
    MOLECULE_OT_delete_domain,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_select_protein_chain,
    MOLECULE_PB_OT_move_protein_pivot,
    MOLECULE_PB_OT_snap_protein_pivot_center,
    MOLECULE_PB_OT_toggle_protein_pivot_edit,
    MOLECULE_PB_OT_toggle_visibility,
    MOLECULE_PB_OT_select_object,
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
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
]

def register():
    """Register all operators."""
    print(f"OPERATORS __INIT__ DEBUG: Registering {len(CLASSES)} operators: {[cls.__name__ for cls in CLASSES]}")
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
            print(f"  Successfully registered: {cls.__name__}")
        except Exception as e:
            print(f"  Failed to register {cls.__name__}: {e}")

def unregister():
    """Unregister all operators."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)