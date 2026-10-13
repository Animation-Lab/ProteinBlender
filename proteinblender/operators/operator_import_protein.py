"""Import protein operator for ProteinBlender.

This module provides operators for importing proteins from various sources
including PDB and AlphaFold databases.
"""

from bpy.types import Operator
import logging
from typing import Set

logger = logging.getLogger(__name__)


def import_request(props):
    """What the import controls currently ask for.

    ``(identifier, method, format)`` as ``create_molecule_from_id`` takes
    them, or None for an import method nobody handles. Shared with the
    Create New Assembly dialog, which carries the same controls.
    """
    if props is None:
        return None
    requests = {
        'PDB': (props.pdb_id, 'PDB', props.remote_format),
        'ALPHAFOLD': (props.uniprot_id, 'ALPHAFOLD', props.remote_format),
        'MMCIF': (props.pdb_id, 'PDB', 'cif'),
    }
    return requests.get(props.import_method)


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
        return import_request(props)

