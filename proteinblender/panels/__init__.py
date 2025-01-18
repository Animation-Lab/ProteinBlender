# protein_workspace/panels/__init__.py
from .panel_import_protein import register_panel_import_protein, unregister_panel_import_protein
from .protein_list_panel import register_protein_list_panel, unregister_protein_list_panel

def register():
    register_panel_import_protein()
    register_protein_list_panel()

def unregister():
    unregister_panel_import_protein()
    unregister_protein_list_panel()