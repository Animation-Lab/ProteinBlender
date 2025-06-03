import bpy
import os
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from ..utils.scene_manager import ProteinBlenderScene

class PROTEIN_OT_import_local(Operator, ImportHelper):
    bl_idname = "protein.import_local"
    bl_label = "Import Local PDB File"
    bl_description = "Import a PDB file from your local filesystem"
    
    # File browser properties
    filename_ext = ".pdb"
    filter_glob: StringProperty(default="*.pdb;*.ent;*.cif;*.mmcif;*.bcif;*.pdbx;*.gz", options={'HIDDEN'})
    
    def execute(self, context):
        filepath = self.filepath
        
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}
        
        filename = os.path.basename(filepath)
        identifier = os.path.splitext(filename)[0]
        
        scene_manager = ProteinBlenderScene.get_instance()
        success = scene_manager.import_molecule_from_file(filepath, identifier)
        
        if not success:
            self.report({'ERROR'}, f"Failed to import {filepath}")
            return {'CANCELLED'}
            
        self.report({'INFO'}, f"Successfully imported {identifier}")
        return {'FINISHED'}

# List of operators in this module
CLASSES = [
    PROTEIN_OT_import_local,
]

def register_operator_import_local():
    """Register operator"""
    bpy.utils.register_class(PROTEIN_OT_import_local)

def unregister_operator_import_local():
    """Unregister operator"""
    bpy.utils.unregister_class(PROTEIN_OT_import_local) 