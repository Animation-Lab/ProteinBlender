# proteinblender/handlers/__init__.py
from .outliner_handler import register as register_outliner_handler, unregister as unregister_outliner_handler

def register():
    """Register all handlers for the addon."""
    register_outliner_handler()

def unregister():
    """Unregister all handlers for the addon."""
    unregister_outliner_handler()


# No bpy classes in this module, so CLASSES is empty
CLASSES = [] 