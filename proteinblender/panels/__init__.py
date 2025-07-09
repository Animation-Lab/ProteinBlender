# protein_workspace/panels/__init__.py
from .molecule_edit_panel import MOLECULE_PB_PT_edit
from .molecule_list_panel import MOLECULE_PB_PT_list
from .panel_import_protein import PROTEIN_PB_PT_import_protein
from .molecule_list_panel import MOLECULE_PB_OT_toggle_chain_selection
from .ui_mockup_panel import CLASSES as MOCKUP_CLASSES

CLASSES = [
    MOLECULE_PB_PT_edit,
    MOLECULE_PB_PT_list,
    PROTEIN_PB_PT_import_protein,
    MOLECULE_PB_OT_toggle_chain_selection
] + MOCKUP_CLASSES