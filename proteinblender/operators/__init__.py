# proteinblender/operators/__init__.py

from .molecule_operators import (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_create_domain,
)
from .operator_import_protein import PROTEIN_OT_import_protein
from .domain_operators import (
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_domain_location,
    MOLECULE_PB_OT_keyframe_domain_rotation,
)

CLASSES = (
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_OT_update_identifier,
    PROTEIN_OT_import_protein,
    MOLECULE_PB_OT_change_style,
    MOLECULE_PB_OT_create_domain,
    MOLECULE_PB_OT_delete_domain,
    MOLECULE_PB_OT_keyframe_domain_location,
    MOLECULE_PB_OT_keyframe_domain_rotation,
)