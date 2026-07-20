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
from .operators import (
    CLASSES as operator_classes,
    domain_maker_session_register_props,
    domain_maker_session_unregister_props,
)
from .panels import CLASSES as panel_classes, register as register_panels, unregister as unregister_panels
from .properties.protein_props import register as register_protein_props, unregister as unregister_protein_props
from .properties.molecule_props import register as register_molecule_props, unregister as unregister_molecule_props
from .properties.pose_props import register as register_pose_props, unregister as unregister_pose_props
from .linkers import register as register_linkers, unregister as unregister_linkers
from .dna_builder import register as register_dna_builder, unregister as unregister_dna_builder
from .membrane_builder import register as register_membrane_builder, unregister as unregister_membrane_builder
from .layout.workspace_setup import ProteinWorkspaceManager
from .utils.molecularnodes import session
from .utils.molecularnodes.props import MolecularNodesObjectProperties

# Set up logging
logger = logging.getLogger(__name__)

# Constants
WORKSPACE_TIMER_INTERVAL = 0.25  # seconds
_workspace_manager = None

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
    global _workspace_manager
    try:
        _workspace_manager = ProteinWorkspaceManager()
        _workspace_manager.create_custom_workspace()
        _workspace_manager.add_panels_to_workspace()
        _workspace_manager.set_properties_context()
        # Workspace assignment and its Window->Screen selection settle on the
        # next UI event-loop turn in Blender 5.2. Rebind then, otherwise the
        # context change can land on the old Layout screen and Protein Blender
        # later opens in Object properties with none of our Scene panels.
        if not bpy.app.timers.is_registered(_finalize_workspace_callback):
            bpy.app.timers.register(_finalize_workspace_callback,
                                    first_interval=0.05)
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
    return None  # Remove the timer


def _finalize_workspace_callback() -> None:
    global _workspace_manager
    try:
        if _workspace_manager is None:
            _workspace_manager = ProteinWorkspaceManager()
        _workspace_manager.create_custom_workspace()
        _workspace_manager.add_panels_to_workspace()
        _workspace_manager.set_properties_context()
        if not bpy.app.timers.is_registered(_apply_workspace_context_callback):
            bpy.app.timers.register(_apply_workspace_context_callback,
                                    first_interval=0.05)
    except Exception as e:
        logger.error(f"Failed to finalize workspace: {e}")
    return None


def _apply_workspace_context_callback() -> None:
    """Configure the screen selected after workspace activation has settled."""
    global _workspace_manager
    try:
        workspace = bpy.data.workspaces.get("Protein Blender")
        window = bpy.context.window or next(
            iter(bpy.context.window_manager.windows), None)
        if workspace is None or window is None:
            raise RuntimeError("Protein Blender workspace/window unavailable")
        if window.workspace != workspace:
            # Activation has not propagated yet; retry on another UI tick.
            window.workspace = workspace
            return 0.05
        _workspace_manager = ProteinWorkspaceManager()
        _workspace_manager.workspace = workspace
        _workspace_manager._bind_workspace_context()
        _workspace_manager.add_panels_to_workspace()
        _workspace_manager.set_properties_context()
    except Exception as e:
        logger.error(f"Failed to apply workspace Scene context: {e}")
    return None

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
    domain_maker_session_register_props()  # WindowManager.pb_domain_maker
    
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

    # Self-healing: purge orphaned molecule entries (objects deleted outside
    # ProteinBlender) on file load and immediately after any object deletion.
    from .utils.scene_manager import (
        purge_orphaned_molecules_on_load,
        detect_deleted_molecules,
    )
    if purge_orphaned_molecules_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(purge_orphaned_molecules_on_load)
    if detect_deleted_molecules not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(detect_deleted_molecules)

    # Finalises custom-pivot placement when the user clicks away from the gizmo.
    # Registered here, with every other handler, so unregister() can take it back
    # out: it used to be appended lazily from set_pivot_custom.execute(), which
    # left it installed across reloads holding a reference to the stale module.
    from .operators.pivot_operators import custom_pivot_deselection_handler
    if custom_pivot_deselection_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(custom_pivot_deselection_handler)

    # Register selection sync handlers
    from .handlers import selection_sync
    selection_sync.register()

    # Register frame change handler for color animation
    from .handlers import frame_change_handler
    frame_change_handler.register()

    # Register flexible linkers module
    register_linkers()

    # Register DNA/RNA builder module
    register_dna_builder()

    # Register Membrane builder module
    register_membrane_builder()

def unregister() -> None:
    """Unregister the ProteinBlender addon.
    
    This function unregisters all classes, properties, and handlers,
    cleaning up the addon state.
    """
    # Clear any pending timers
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(create_workspace_callback):
        bpy.app.timers.unregister(create_workspace_callback)
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(_finalize_workspace_callback):
        bpy.app.timers.unregister(_finalize_workspace_callback)
    if hasattr(bpy.app, "timers") and bpy.app.timers.is_registered(_apply_workspace_context_callback):
        bpy.app.timers.unregister(_apply_workspace_context_callback)

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

    # Unregister self-healing (orphaned molecule) handlers
    try:
        from .utils.scene_manager import (
            purge_orphaned_molecules_on_load,
            detect_deleted_molecules,
        )
        if purge_orphaned_molecules_on_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(purge_orphaned_molecules_on_load)
        if detect_deleted_molecules in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(detect_deleted_molecules)
    except Exception as e:
        logger.debug(f"Failed to unregister self-healing handlers: {e}")

    # Unregister the custom-pivot deselection handler
    try:
        from .operators.pivot_operators import custom_pivot_deselection_handler
        if custom_pivot_deselection_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(custom_pivot_deselection_handler)
    except Exception as e:
        logger.debug(f"Failed to unregister custom pivot handler: {e}")

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

    # Unregister Membrane builder module
    try:
        unregister_membrane_builder()
    except Exception as e:
        logger.debug(f"Failed to unregister membrane_builder: {e}")

    # Unregister DNA/RNA builder module
    try:
        unregister_dna_builder()
    except Exception as e:
        logger.debug(f"Failed to unregister dna_builder: {e}")

    # Unregister flexible linkers module
    try:
        unregister_linkers()
    except Exception as e:
        logger.debug(f"Failed to unregister linkers: {e}")

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
        domain_maker_session_unregister_props()
    except Exception as e:
        logger.debug(f"Failed to unregister domain maker session props: {e}")

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
