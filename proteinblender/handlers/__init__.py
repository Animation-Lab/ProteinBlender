# proteinblender/handlers/__init__.py

from . import frame_change_handler

CLASSES = ()


def register():
    """Register all handlers"""
    frame_change_handler.register()


def unregister():
    """Unregister all handlers"""
    frame_change_handler.unregister()
