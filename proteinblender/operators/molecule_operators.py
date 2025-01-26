import bpy
from bpy.types import Operator
from bpy.props import StringProperty

class MOLECULE_OT_edit(Operator):
    bl_idname = "molecule.edit"
    bl_label = "Edit Molecule"
    bl_description = "Edit molecule settings"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        # Show the edit panel and populate it with the selected molecule's data
        scene = context.scene
        scene.selected_molecule_id = self.molecule_id
        scene.show_molecule_edit_panel = True
        return {'FINISHED'}

class MOLECULE_OT_delete(Operator):
    bl_idname = "molecule.delete"
    bl_label = "Delete Molecule"
    bl_description = "Delete molecule from scene"
    
    molecule_id: StringProperty()
    
    def execute(self, context):
        from ..utils.scene_manager import ProteinBlenderScene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Delete the molecule
        if self.molecule_id in scene_manager.molecules:
            molecule = scene_manager.molecules[self.molecule_id]
            bpy.data.objects.remove(molecule.object, do_unlink=True)
            del scene_manager.molecules[self.molecule_id]
            
        return {'FINISHED'} 