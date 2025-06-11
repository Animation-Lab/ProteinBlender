# proteinblender/handlers/__init__.py
from . import sync

# This list remains for class-based handlers, but we'll use
# the register/unregister functions for our new module-based handler.
CLASSES = ()

def register():
    sync.register()

def unregister():
    sync.unregister()
