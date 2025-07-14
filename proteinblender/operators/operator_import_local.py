"""Local file import operator for ProteinBlender.

This module provides operators for importing protein structure files
from the local filesystem.
"""

import bpy
import os
import logging
from typing import Set
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from ..utils.scene_manager import ProteinBlenderScene

logger = logging.getLogger(__name__)

class MOLECULE_OT_import_local(Operator, ImportHelper):
    """Import a protein structure file from the local filesystem."""
    bl_idname = "molecule.import_local"
    bl_label = "Import Local Structure File"
    bl_description = "Import a protein structure file (PDB, CIF, etc.) from your local filesystem"
    
    # File browser properties
    filename_ext = ".pdb"
    filter_glob: StringProperty(
        default="*.pdb;*.ent;*.cif;*.mmcif;*.bcif;*.pdbx;*.gz",
        options={'HIDDEN'},
        description="File types to filter in the file browser"
    )
    
    def execute(self, context) -> Set[str]:
        """Execute the local file import operation.
        
        Args:
            context: The Blender context.
            
        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' on failure.
        """
        filepath = self.filepath
        
        # Validate file exists
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}
        
        # Extract identifier from filename
        filename = os.path.basename(filepath)
        identifier = os.path.splitext(filename)[0]
        
        # Handle compressed files
        if identifier.endswith('.pdb') or identifier.endswith('.cif'):
            # Double extension like file.pdb.gz
            identifier = os.path.splitext(identifier)[0]
        
        try:
            scene_manager = ProteinBlenderScene.get_instance()
            success = scene_manager.import_molecule_from_file(filepath, identifier)
            
            if not success:
                self.report({'ERROR'}, f"Failed to import {filepath}")
                return {'CANCELLED'}
                
            self.report({'INFO'}, f"Successfully imported {identifier}")
            return {'FINISHED'}
            
        except Exception as e:
            logger.error(f"Error importing file {filepath}: {e}")
            self.report({'ERROR'}, f"Error importing file: {str(e)}")
            return {'CANCELLED'}

# Classes to register
CLASSES = [
    MOLECULE_OT_import_local,
]


def register_operator_import_local() -> None:
    """Register the local import operator."""
    bpy.utils.register_class(MOLECULE_OT_import_local)


def unregister_operator_import_local() -> None:
    """Unregister the local import operator."""
    bpy.utils.unregister_class(MOLECULE_OT_import_local) 