# protein_workspace/operators/__init__.py
from .operator_import_pdb import register_operator_import_pdb, unregister_operator_import_pdb

def register():
    register_operator_import_pdb()

def unregister():
    unregister_operator_import_pdb()
