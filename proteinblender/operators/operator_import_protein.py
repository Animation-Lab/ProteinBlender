"""Import protein operator for ProteinBlender.

This module provides operators for importing proteins from various sources
including PDB and AlphaFold databases.
"""

import bpy
from bpy.types import Operator
import logging
from typing import Set

logger = logging.getLogger(__name__)

class MOLECULE_OT_import_protein(Operator):
    """Import a protein from PDB, AlphaFold, or mmCIF."""
    bl_idname = "molecule.import_protein"
    bl_label = "Import Protein"
    bl_description = "Import a protein from PDB, AlphaFold, or mmCIF database"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context) -> Set[str]:
        """Execute the protein import operation.
        
        Args:
            context: The Blender context.
            
        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' on failure.
        """
        scene = context.scene
        props = scene.protein_props
        
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Determine identifier, method, and format for import
        import_config = self._get_import_config(props)
        if not import_config:
            self.report({'ERROR'}, f"Unknown import method: {props.import_method}")
            return {'CANCELLED'}
        
        identifier, method, fmt = import_config
        
        try:
            success = scene_manager.create_molecule_from_id(
                identifier,
                import_method=method,
                remote_format=fmt
            )
            
            if not success:
                self.report({'ERROR'}, f"Failed to import {identifier}")
                return {'CANCELLED'}
                
            self.report({'INFO'}, f"Successfully imported {identifier}")
            return {'FINISHED'}
            
        except Exception as e:
            logger.error(f"Error importing protein {identifier}: {e}")
            self.report({'ERROR'}, f"Error importing protein: {str(e)}")
            return {'CANCELLED'}
    
    def _get_import_config(self, props) -> tuple:
        """Get import configuration based on import method.
        
        Args:
            props: The protein properties.
            
        Returns:
            Tuple of (identifier, method, format) or None if invalid method.
        """
        import_configs = {
            'PDB': (props.pdb_id, 'PDB', props.remote_format),
            'ALPHAFOLD': (props.uniprot_id, 'ALPHAFOLD', props.remote_format),
            'MMCIF': (props.pdb_id, 'PDB', 'cif')
        }
        
        return import_configs.get(props.import_method)

# Classes to register
CLASSES = [
    MOLECULE_OT_import_protein,
]


def register_operator_import_protein() -> None:
    """Register the import protein operator."""
    bpy.utils.register_class(MOLECULE_OT_import_protein)


def unregister_operator_import_protein() -> None:
    """Unregister the import protein operator."""
    bpy.utils.unregister_class(MOLECULE_OT_import_protein)