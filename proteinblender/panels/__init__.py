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
from .visual_setup_panel import (
    PROTEINBLENDER_OT_apply_color,
    PROTEINBLENDER_OT_apply_representation,
    PROTEINBLENDER_PT_visual_setup,
    register_props as visual_setup_register_props,
    unregister_props as visual_setup_unregister_props
)
from .domain_maker_panel import (
    PROTEINBLENDER_PT_domain_maker,
    register_props as domain_maker_register_props,
    unregister_props as domain_maker_unregister_props
)
from .group_maker_panel import (
    PROTEINBLENDER_OT_create_puppet,
    PROTEINBLENDER_OT_edit_puppet,
    PROTEINBLENDER_PT_puppet_maker
)
from .pose_library_panel import (
    PROTEINBLENDER_PT_pose_library,
    PROTEINBLENDER_OT_toggle_puppet_selection,
    PROTEINBLENDER_OT_create_pose,
    PROTEINBLENDER_OT_apply_pose,
    PROTEINBLENDER_OT_capture_pose,
    PROTEINBLENDER_OT_delete_pose,
    PROTEINBLENDER_OT_placeholder
)
from .animation_panel import PROTEINBLENDER_PT_animation
# Direct panels - no container needed

# Legacy panels (to be phased out)
# from .molecule_edit_panel import MOLECULE_PB_PT_edit
# from .molecule_list_panel import MOLECULE_PB_PT_list, MOLECULE_PB_OT_toggle_chain_selection

# Export all for clarity
__all__ = [
    'PROTEIN_PB_PT_import_protein',
    'PROTEINBLENDER_UL_outliner',
    'PROTEINBLENDER_OT_toggle_expand',
    'PROTEINBLENDER_OT_outliner_select',
    'PROTEINBLENDER_OT_toggle_visibility',
    'PROTEINBLENDER_OT_outliner_item_info',
    'PROTEINBLENDER_PT_outliner',
    'PROTEINBLENDER_OT_apply_color',
    'PROTEINBLENDER_OT_apply_representation',
    'PROTEINBLENDER_PT_visual_setup',
    'PROTEINBLENDER_PT_domain_maker',
    'PROTEINBLENDER_OT_create_puppet',
    'PROTEINBLENDER_OT_edit_puppet',
    'PROTEINBLENDER_PT_puppet_maker',
    'PROTEINBLENDER_PT_pose_library',
    'PROTEINBLENDER_OT_toggle_puppet_selection',
    'PROTEINBLENDER_OT_create_pose',
    'PROTEINBLENDER_OT_apply_pose',
    'PROTEINBLENDER_OT_capture_pose',
    'PROTEINBLENDER_OT_delete_pose',
    'PROTEINBLENDER_OT_placeholder',
    'PROTEINBLENDER_PT_animation',
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
    PROTEINBLENDER_OT_apply_color,
    PROTEINBLENDER_OT_apply_representation,
    PROTEINBLENDER_OT_create_puppet,
    PROTEINBLENDER_OT_edit_puppet,
    PROTEINBLENDER_OT_toggle_puppet_selection,
    PROTEINBLENDER_OT_create_pose,
    PROTEINBLENDER_OT_apply_pose,
    PROTEINBLENDER_OT_capture_pose,
    PROTEINBLENDER_OT_delete_pose,
    PROTEINBLENDER_OT_placeholder,
    
    # Panels in order (top to bottom)
    PROTEIN_PB_PT_import_protein,      # 0: Importer
    PROTEINBLENDER_PT_outliner,        # 1: Protein Outliner
    PROTEINBLENDER_PT_visual_setup,    # 2: Visual Setup
    PROTEINBLENDER_PT_domain_maker,    # 3: Domain Maker
    PROTEINBLENDER_PT_puppet_maker,     # 4: Puppet Maker
    PROTEINBLENDER_PT_pose_library,    # 5: Pose Library
    PROTEINBLENDER_PT_animation,       # 6: Animation
]

def register():
    """Register all panel properties"""
    visual_setup_register_props()
    domain_maker_register_props()

def unregister():
    """Unregister all panel properties"""
    visual_setup_unregister_props()
    domain_maker_unregister_props()