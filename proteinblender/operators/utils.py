"""Utility functions for ProteinBlender operators.

This module provides common functionality shared across operators
to reduce code duplication and improve maintainability.
"""

import bpy
import logging
from typing import Optional, Tuple

from ..utils.scene_manager import ProteinBlenderScene
from ..core.molecule import MoleculeWrapper
from ..core.domain import Domain

logger = logging.getLogger(__name__)


def get_scene_manager() -> ProteinBlenderScene:
    """Get the ProteinBlenderScene instance.
    
    Returns:
        The singleton ProteinBlenderScene instance.
    """
    return ProteinBlenderScene.get_instance()


def get_selected_molecule(context) -> Optional[MoleculeWrapper]:
    """Get the currently selected molecule.
    
    Args:
        context: The Blender context.
        
    Returns:
        The selected MoleculeWrapper or None if not found.
    """
    scene_manager = get_scene_manager()
    molecule_id = context.scene.selected_molecule_id
    
    if not molecule_id:
        return None
        
    return scene_manager.molecules.get(molecule_id)


def validate_molecule_selection(operator, context) -> Tuple[Optional[MoleculeWrapper], bool]:
    """Validate that a molecule is selected and exists.
    
    Args:
        operator: The operator instance for reporting.
        context: The Blender context.
        
    Returns:
        Tuple of (molecule, success) where success is True if validation passed.
    """
    molecule = get_selected_molecule(context)
    
    if not molecule:
        operator.report({'ERROR'}, "No molecule selected")
        return None, False
        
    if not molecule.object:
        operator.report({'ERROR'}, "Selected molecule has no associated object")
        return None, False
        
    return molecule, True


def get_domain_from_molecule(
    operator,
    molecule: MoleculeWrapper,
    domain_id: str
) -> Optional[Domain]:
    """Get a domain from a molecule with validation.
    
    Args:
        operator: The operator instance for reporting.
        molecule: The molecule containing the domain.
        domain_id: The ID of the domain to retrieve.
        
    Returns:
        The Domain object or None if not found.
    """
    if domain_id not in molecule.domains:
        operator.report({'ERROR'}, f"Domain '{domain_id}' not found")
        return None
        
    domain = molecule.domains[domain_id]
    
    if not domain.object:
        operator.report({'ERROR'}, f"Domain '{domain_id}' has no associated object")
        return None
        
    return domain


def refresh_timeline() -> None:
    """Refresh the timeline to ensure keyframes are displayed correctly."""
    try:
        for area in bpy.context.screen.areas:
            if area.type == 'DOPESHEET_EDITOR':
                area.tag_redraw()
    except Exception as e:
        logger.warning(f"Failed to refresh timeline: {e}")


def set_active_object(obj: bpy.types.Object) -> None:
    """Set an object as the active object and select it.
    
    Args:
        obj: The object to make active.
    """
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def frame_selected_in_viewport() -> None:
    """Frame the selected objects in the 3D viewport."""
    try:
        # Find 3D viewport and frame selected
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'area': area,
                            'region': region,
                            'edit_object': bpy.context.edit_object
                        }
                        bpy.ops.view3d.view_selected(override)
                        break
    except Exception as e:
        logger.warning(f"Failed to frame selected objects: {e}")


def ensure_animation_data(obj: bpy.types.Object) -> bpy.types.AnimData:
    """Ensure an object has animation data.
    
    Args:
        obj: The object to check.
        
    Returns:
        The animation data for the object.
    """
    if not obj.animation_data:
        obj.animation_data_create()
    
    if not obj.animation_data.action:
        obj.animation_data.action = bpy.data.actions.new(name=f"{obj.name}_Action")
        
    return obj.animation_data