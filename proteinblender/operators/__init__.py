# proteinblender/operators/__init__.py

from .molecule_operators import MOLECULE_OT_select, MOLECULE_OT_edit, MOLECULE_OT_delete
from .operator_import_protein import PROTEIN_OT_import_protein

CLASSES = (
    MOLECULE_OT_select,
    MOLECULE_OT_edit,
    MOLECULE_OT_delete,
    PROTEIN_OT_import_protein,
)
