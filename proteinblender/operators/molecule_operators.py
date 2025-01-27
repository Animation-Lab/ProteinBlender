import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_OT_select(Operator):
    bl_idname = "molecule.select"
    bl_label = "Select Molecule"
    bl_description = "Select this molecule"
    bl_order = 0
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.selected_molecule_id = self.molecule_id
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(self.molecule_id)
        
        if molecule:
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Select the molecule's object
            molecule.object.select_set(True)
            context.view_layer.objects.active = molecule.object
            
        return {'FINISHED'}

class MOLECULE_OT_edit(Operator):
    bl_idname = "molecule.edit"
    bl_label = "Edit Molecule"
    bl_description = "Edit this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        context.scene.show_molecule_edit_panel = True
        context.scene.selected_molecule_id = self.molecule_id
        return {'FINISHED'}

class MOLECULE_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete this molecule"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        scene_manager.delete_molecule(self.molecule_id)
        return {'FINISHED'}

