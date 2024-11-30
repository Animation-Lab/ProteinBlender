from . import panels
from . import operators

def register():
    panels.register()
    operators.register()

def unregister():
    panels.unregister()
    operators.unregister()