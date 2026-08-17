# protein_workspace/panels/__init__.py

# Import all panel modules
from .panel_import_protein import PROTEIN_PB_PT_import_protein
from .protein_outliner_panel import (
    PROTEINBLENDER_UL_outliner,
    PROTEINBLENDER_OT_toggle_expand,
    PROTEINBLENDER_OT_outliner_select,
    PROTEINBLENDER_OT_toggle_visibility,
    PROTEINBLENDER_OT_outliner_item_info,
    PROTEINBLENDER_PT_outliner
)
from .group_maker_panel import (
    PROTEINBLENDER_OT_create_puppet,
    PROTEINBLENDER_OT_edit_puppet,
    PROTEINBLENDER_OT_delete_puppet,
    PROTEINBLENDER_PT_puppet_maker
)
from .pose_library_panel import (
    PROTEINBLENDER_PT_pose_library,
    PROTEINBLENDER_OT_toggle_puppet_selection,
    PROTEINBLENDER_OT_create_pose,
    PROTEINBLENDER_OT_apply_pose,
    PROTEINBLENDER_OT_capture_pose,
    PROTEINBLENDER_OT_delete_pose,
)
from .symmetry_panel import (
    PROTEINBLENDER_PT_symmetry,
    CLASSES as SYMMETRY_CLASSES,
)
from .animation_panel import (
    PROTEINBLENDER_KeyframeListItem,
    PROTEINBLENDER_UL_keyframes,
    PROTEINBLENDER_PT_animation,
    PROTEINBLENDER_OT_delete_keyframe as PROTEINBLENDER_OT_anim_delete_keyframe,
    PROTEINBLENDER_OT_jump_to_keyframe,
    PROTEINBLENDER_OT_edit_keyframe,
    register_props as animation_register_props,
    unregister_props as animation_unregister_props,
)
# Export all for clarity
__all__ = [
    'PROTEIN_PB_PT_import_protein',
    'PROTEINBLENDER_UL_outliner',
    'PROTEINBLENDER_OT_toggle_expand',
    'PROTEINBLENDER_OT_outliner_select',
    'PROTEINBLENDER_OT_toggle_visibility',
    'PROTEINBLENDER_OT_outliner_item_info',
    'PROTEINBLENDER_PT_outliner',
    'PROTEINBLENDER_OT_create_puppet',
    'PROTEINBLENDER_OT_edit_puppet',
    'PROTEINBLENDER_OT_delete_puppet',
    'PROTEINBLENDER_PT_puppet_maker',
    'PROTEINBLENDER_PT_pose_library',
    'PROTEINBLENDER_OT_toggle_puppet_selection',
    'PROTEINBLENDER_OT_create_pose',
    'PROTEINBLENDER_OT_apply_pose',
    'PROTEINBLENDER_OT_capture_pose',
    'PROTEINBLENDER_OT_delete_pose',
    'PROTEINBLENDER_PT_animation',
    'PROTEINBLENDER_PT_symmetry',
    'CLASSES',
    'register',
    'unregister'
]

# All classes in correct registration order
CLASSES = [
    # Operators first
    PROTEINBLENDER_UL_outliner,
    PROTEINBLENDER_OT_toggle_expand,
    PROTEINBLENDER_OT_outliner_select,
    PROTEINBLENDER_OT_toggle_visibility,
    PROTEINBLENDER_OT_outliner_item_info,
    PROTEINBLENDER_OT_create_puppet,
    PROTEINBLENDER_OT_edit_puppet,
    PROTEINBLENDER_OT_delete_puppet,
    PROTEINBLENDER_OT_toggle_puppet_selection,
    PROTEINBLENDER_OT_create_pose,
    PROTEINBLENDER_OT_apply_pose,
    PROTEINBLENDER_OT_capture_pose,
    PROTEINBLENDER_OT_delete_pose,
    PROTEINBLENDER_OT_anim_delete_keyframe,
    PROTEINBLENDER_OT_jump_to_keyframe,
    PROTEINBLENDER_OT_edit_keyframe,

    # Data types used by the animation panel's template_list. Both must
    # be registered before PROTEINBLENDER_PT_animation references them.
    PROTEINBLENDER_KeyframeListItem,
    PROTEINBLENDER_UL_keyframes,

    # Panels in order (top to bottom)
    PROTEIN_PB_PT_import_protein,      # 0: Importer
    PROTEINBLENDER_PT_outliner,        # 1: Protein Outliner
    *SYMMETRY_CLASSES,                 # 2: Symmetry (polls itself away)
    PROTEINBLENDER_PT_puppet_maker,    # 3: Puppet Maker
    PROTEINBLENDER_PT_pose_library,    # 4: Pose Library
    PROTEINBLENDER_PT_animation,       # 5: Animation
]

def register():
    """Register all panel properties"""
    animation_register_props()

def unregister():
    """Unregister all panel properties"""
    animation_unregister_props()