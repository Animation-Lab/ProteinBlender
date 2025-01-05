# protein_workspace/operators/__init__.py
from .operator_import_protein import register_operator_import_protein, unregister_operator_import_protein

def register():
    register_operator_import_protein()

def unregister():
    unregister_operator_import_protein()