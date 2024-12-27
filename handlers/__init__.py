# protein_workspace/handlers/__init__.py
from .load_handlers import register_load_handlers, unregister_load_handlers

def register():
    register_load_handlers()

def unregister():
    unregister_load_handlers()
