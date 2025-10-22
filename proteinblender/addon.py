"""ProteinBlender addon registration module.

This module handles the registration and unregistration of all addon components
including operators, panels, properties, and handlers.
"""

import bpy
from bpy.props import PointerProperty, BoolProperty
import logging
from typing import List, Type

from .core import CLASSES as core_classes
from .handlers import CLASSES as handler_classes
from .operators import CLASSES as operator_classes, register as register_operators, unregister as unregister_operators
from .panels import CLASSES as panel_classes, register as register_panels, unregister as unregister_panels
from .properties.protein_props import register as register_protein_props, unregister as unregister_protein_props
from .properties.molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .properties.pose_props import register as register_pose_props, unregister as unregister_pose_props
from .layout.workspace_setup import ProteinWorkspaceManager
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

def create_workspace_callback() -> None:
    """Create custom workspace for ProteinBlender.
    
    This is called via a timer to ensure Blender is fully initialized.
    
    Returns:
        None to remove the timer.
    """
    try:
        workspace_manager = ProteinWorkspaceManager()
        workspace_manager.create_custom_workspace()
        workspace_manager.add_panels_to_workspace()
        workspace_manager.set_properties_context()
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
    return None  # Remove the timer

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
    register_protein_props()
    register_molecule_props()
    register_pose_props()  # Register pose properties
    register_panels()  # Register panel properties
    register_operators()  # Register operator properties (includes keyframe_dialog_items)
    
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
    
    # Schedule workspace creation after a short delay
    bpy.app.timers.register(create_workspace_callback, first_interval=WORKSPACE_TIMER_INTERVAL)

    # Register persistent workspace handler (survives Ctrl+N)
    from .handlers import load_handlers
    load_handlers.register_load_handlers()

    # Register undo/redo handlers to sync and restore molecules
    from .utils.scene_manager import sync_molecule_list_after_undo
    if sync_molecule_list_after_undo not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(sync_molecule_list_after_undo)
    if sync_molecule_list_after_undo not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(sync_molecule_list_after_undo)

    # Register selection sync handlers
    from .handlers import selection_sync
    selection_sync.register()

    # Register frame change handler for color animation
    from .handlers import frame_change_handler
    frame_change_handler.register()

def unregister() -> None:
    """Unregister the ProteinBlender addon.
    
    This function unregisters all classes, properties, and handlers,
    cleaning up the addon state.
    """
    # Clear any pending timers
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(create_workspace_callback):
        bpy.app.timers.unregister(create_workspace_callback)

    # Unregister persistent workspace handler
    try:
        from .handlers import load_handlers
        load_handlers.unregister_load_handlers()
    except Exception as e:
        logger.debug(f"Failed to unregister load handlers: {e}")

    # Unregister undo/redo handlers
    try:
        from .utils.scene_manager import sync_molecule_list_after_undo
        if sync_molecule_list_after_undo in bpy.app.handlers.undo_post:
            bpy.app.handlers.undo_post.remove(sync_molecule_list_after_undo)
        if sync_molecule_list_after_undo in bpy.app.handlers.redo_post:
            bpy.app.handlers.redo_post.remove(sync_molecule_list_after_undo)
    except Exception as e:
        logger.debug(f"Failed to unregister undo/redo handler: {e}")

    # Unregister selection sync handlers
    try:
        from .handlers import selection_sync
        selection_sync.unregister()
    except Exception as e:
        logger.debug(f"Failed to unregister selection sync handler: {e}")

    # Unregister frame change handler
    try:
        from .handlers import frame_change_handler
        frame_change_handler.unregister()
    except Exception as e:
        logger.debug(f"Failed to unregister frame change handler: {e}")

    # Unregister properties
    try:
        unregister_protein_props()
    except Exception as e:
        logger.debug(f"Failed to unregister protein props: {e}")
    
    try:
        unregister_molecule_props()
    except Exception as e:
        logger.debug(f"Failed to unregister molecule props: {e}")
    
    try:
        unregister_pose_props()
    except Exception as e:
        logger.debug(f"Failed to unregister pose props: {e}")
    
    try:
        unregister_panels()
    except Exception as e:
        logger.debug(f"Failed to unregister panel props: {e}")
    
    try:
        unregister_operators()
    except Exception as e:
        logger.debug(f"Failed to unregister operator props: {e}")
    
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