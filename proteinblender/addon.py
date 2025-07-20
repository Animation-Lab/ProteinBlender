"""ProteinBlender addon registration module.

This module handles the registration and unregistration of all addon components
including operators, panels, properties, and handlers.
"""

import bpy
from bpy.props import PointerProperty, BoolProperty
import logging
from typing import List, Type

from .core import CLASSES as core_classes
from .handlers import CLASSES as handler_classes, register as register_handlers, unregister as unregister_handlers
from .operators import CLASSES as operator_classes
from .panels import CLASSES as panel_classes
from .properties import register as register_properties, unregister as unregister_properties
from .utils import scene_manager
from .utils.molecularnodes import session
from .utils.molecularnodes.props import MolecularNodesObjectProperties

# Set up logging
logger = logging.getLogger(__name__)

# Constants
WORKSPACE_TIMER_INTERVAL = 0.25  # seconds

# Track registered classes
registered_classes: List[Type] = []

# All ProteinBlender classes to register
ALL_PB_CLASSES = (
    core_classes,
    handler_classes,
    operator_classes,
    panel_classes,
    session.CLASSES,
)

def _test_register() -> None:
    """Test registration by unregistering and re-registering the addon.
    
    This is useful for development and debugging.
    """
    try:
        register()
    except Exception as e:
        logger.error(f"Error during test registration: {e}")
        unregister()
        register()

def register() -> None:
    """Register the ProteinBlender addon.
    
    This function registers all classes, properties, and handlers needed
    for the addon to function properly.
    """
    # Try unregistering first to clean up any previous state
    try:
        unregister()
    except Exception as e:
        logger.debug(f"Unregister during startup: {e}")
    
    # Register classes
    for class_group in ALL_PB_CLASSES:
        for cls in class_group:
            try:
                bpy.utils.register_class(cls)
                registered_classes.append(cls)
            except Exception as e:
                logger.error(f"Failed to register {cls.__name__}: {e}")
    
    # Register MolecularNodes session
    if not hasattr(bpy.types.Scene, "MNSession"):
        bpy.types.Scene.MNSession = session.MNSession()
    
    # Register properties
    register_properties()
    
    # Register brownian motion property directly here instead of through ui_panels
    if not hasattr(bpy.types.Scene, "pb_brownian_motion"):
        bpy.types.Scene.pb_brownian_motion = BoolProperty(
            name="Brownian Motion",
            default=False,
        )
    
    # Register handlers
    register_handlers()
    
    # Register domain expanded property if not already registered
    if not hasattr(bpy.types.Object, "domain_expanded"):
        bpy.types.Object.domain_expanded = BoolProperty(default=False)
    
    # Register MolecularNodes object properties
    try:
        bpy.utils.register_class(MolecularNodesObjectProperties)
        registered_classes.append(MolecularNodesObjectProperties)
    except Exception as e:
        logger.error(f"Failed to register MolecularNodesObjectProperties: {e}")
    
    # Register object properties if not already registered
    if not hasattr(bpy.types.Object, "mn"):
        bpy.types.Object.mn = PointerProperty(type=MolecularNodesObjectProperties)
    
    # Register undo/redo handlers to sync and restore molecules
    from .utils.scene_manager import sync_molecule_list_after_undo
    if sync_molecule_list_after_undo not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(sync_molecule_list_after_undo)
    if sync_molecule_list_after_undo not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(sync_molecule_list_after_undo)
    
    # Create and activate ProteinBlender workspace
    def create_workspace_deferred():
        """Create workspace after Blender is fully initialized"""
        try:
            # Check if we're in a valid context
            if bpy.context.window:
                bpy.ops.pb.create_workspace()
                logger.info("ProteinBlender workspace created")
        except Exception as e:
            logger.error(f"Failed to create workspace: {e}")
        return None  # Remove timer
    
    # Use a timer to defer workspace creation until Blender is ready
    bpy.app.timers.register(create_workspace_deferred, first_interval=0.1)

def unregister() -> None:
    """Unregister the ProteinBlender addon.
    
    This function unregisters all classes, properties, and handlers,
    cleaning up the addon state.
    """
    # Unregister undo/redo handlers
    try:
        from .utils.scene_manager import sync_molecule_list_after_undo
        if sync_molecule_list_after_undo in bpy.app.handlers.undo_post:
            bpy.app.handlers.undo_post.remove(sync_molecule_list_after_undo)
        if sync_molecule_list_after_undo in bpy.app.handlers.redo_post:
            bpy.app.handlers.redo_post.remove(sync_molecule_list_after_undo)
    except Exception as e:
        logger.debug(f"Failed to unregister undo/redo handler: {e}")

    # Unregister handlers
    try:
        unregister_handlers()
    except Exception as e:
        logger.debug(f"Failed to unregister handlers: {e}")

    # Unregister properties
    try:
        unregister_properties()
    except Exception as e:
        logger.debug(f"Failed to unregister properties: {e}")
    
    # Unregister brownian motion property
    if hasattr(bpy.types.Scene, "pb_brownian_motion"):
        del bpy.types.Scene.pb_brownian_motion
    
    # Unregister domain expanded property
    if hasattr(bpy.types.Object, "domain_expanded"):
        del bpy.types.Object.domain_expanded
    
    # Remove session
    if hasattr(bpy.types.Scene, "MNSession"):
        del bpy.types.Scene.MNSession
    
    # Remove object properties
    if hasattr(bpy.types.Object, "mn"):
        del bpy.types.Object.mn
    

    # Unregister classes
    for cls in reversed(registered_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            logger.debug(f"Failed to unregister {cls.__name__}: {e}")
    registered_classes.clear()