# protein_workspace/panels/__init__.py
from .panel_import_pdb import register_panel_import_pdb, unregister_panel_import_pdb

def register():
    print('registering panels')
    register_panel_import_pdb()

def unregister():
    print('unregistering panels')
    unregister_panel_import_pdb()
