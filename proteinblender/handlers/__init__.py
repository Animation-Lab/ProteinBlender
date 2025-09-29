# proteinblender/handlers/__init__.py

from . import frame_change_handler
from . import selection_sync

CLASSES = ()


def register():
    """Register all handlers"""
    frame_change_handler.register()
    selection_sync.register()


def unregister():
    """Unregister all handlers"""
    frame_change_handler.unregister()
    selection_sync.unregister()
