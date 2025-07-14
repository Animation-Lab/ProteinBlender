"""Selection operators for ProteinBlender.

This module provides operators for selecting molecules and domains
in the 3D viewport.
"""

import bpy
import logging
from typing import Set
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty

from ..utils.scene_manager import ProteinBlenderScene

logger = logging.getLogger(__name__)

class MOLECULE_PB_OT_select_object(Operator):
    """Select a molecule or domain object in the 3D viewport."""
    bl_idname = "molecule.select_object"
    bl_label = "Select Object"
    bl_description = "Select this object in the 3D viewport"
    bl_options = {'REGISTER', 'UNDO'}
    
    object_id: StringProperty(
        name="Object ID",
        description="ID of the object to select"
    )
    is_domain: BoolProperty(
        name="Is Domain",
        description="Whether the object is a domain or a protein",
        default=False
    )
    
    def execute(self, context) -> Set[str]:
        """Execute the object selection operation.
        
        Args:
            context: The Blender context.
            
        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' on failure.
        """
        try:
            scene_manager = ProteinBlenderScene.get_instance()
            
            # First deselect all objects
            bpy.ops.object.select_all(action='DESELECT')
            
            if self.is_domain:
                success = self._select_domain(context, scene_manager)
            else:
                success = self._select_molecule(scene_manager)
            
            if not success:
                return {'CANCELLED'}
                
            return {'FINISHED'}
            
        except Exception as e:
            logger.error(f"Error selecting object: {e}")
            self.report({'ERROR'}, f"Error selecting object: {str(e)}")
            return {'CANCELLED'}
    
    def _select_domain(self, context, scene_manager) -> bool:
        """Select a domain object.
        
        Args:
            context: The Blender context.
            scene_manager: The ProteinBlenderScene instance.
            
        Returns:
            True if successful, False otherwise.
        """
        # Get the selected molecule
        molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return False
            
        # Get the domain
        domain = molecule.domains.get(self.object_id)
        if not domain or not domain.object:
            self.report({'ERROR'}, f"Domain '{self.object_id}' not found")
            return False
            
        # Select the domain object
        domain.object.select_set(True)
        context.view_layer.objects.active = domain.object
        return True
    
    def _select_molecule(self, scene_manager) -> bool:
        """Select a molecule object.
        
        Args:
            scene_manager: The ProteinBlenderScene instance.
            
        Returns:
            True if successful, False otherwise.
        """
        # Get the molecule
        molecule = scene_manager.molecules.get(self.object_id)
        if not molecule or not molecule.object:
            self.report({'ERROR'}, f"Molecule '{self.object_id}' not found")
            return False
            
        # Select the molecule object
        molecule.object.select_set(True)
        bpy.context.view_layer.objects.active = molecule.object
        return True 