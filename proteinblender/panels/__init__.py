# protein_workspace/panels/__init__.py
from .panel_import_protein import PROTEIN_PB_PT_import_protein
from .molecule_list_panel import MOLECULE_PB_PT_list, MOLECULE_PB_OT_select, MOLECULE_PB_OT_edit, MOLECULE_PB_OT_delete
from .molecule_edit_panel import MOLECULE_PB_PT_edit

CLASSES = [
    PROTEIN_PB_PT_import_protein,
    MOLECULE_PB_PT_list,
    MOLECULE_PB_OT_select,
    MOLECULE_PB_OT_edit,
    MOLECULE_PB_OT_delete,
    MOLECULE_PB_PT_edit,
]