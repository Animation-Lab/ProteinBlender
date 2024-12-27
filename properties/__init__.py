from .protein_props import register_properties, unregister_properties

def register():
    print('registering properties')
    register_properties()

def unregister():
    print('unregistering properties')
    unregister_properties() 