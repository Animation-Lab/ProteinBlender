# protein_workspace/props/__init__.py
from .protein_properties import register_protein_properties, unregister_protein_properties
def register():
    print('registering props')
    register_protein_properties()

def unregister():
    print('unregistering props')
    unregister_protein_properties()
