import bpy
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_PB_OT_select_object(Operator):
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
    
    def execute(self, context):
        scene_manager = ProteinBlenderScene.get_instance()
        
        # First deselect all objects
        bpy.ops.object.select_all(action='DESELECT')
        
        if self.is_domain:
            # Get the selected molecule
            molecule = scene_manager.molecules.get(context.scene.selected_molecule_id)
            if not molecule:
                self.report({'ERROR'}, "No molecule selected")
                return {'CANCELLED'}
                
            # Get the domain
            domain = molecule.domains.get(self.object_id)
            if not domain or not domain.object:
                self.report({'ERROR'}, "Domain not found")
                return {'CANCELLED'}
                
            # Select the domain object
            domain.object.select_set(True)
            context.view_layer.objects.active = domain.object
            
        else:
            # Select the protein object
            molecule = scene_manager.molecules.get(self.object_id)
            if not molecule or not molecule.object:
                self.report({'ERROR'}, "Molecule not found")
                return {'CANCELLED'}
                
            # Select the molecule object
            molecule.object.select_set(True)
            context.view_layer.objects.active = molecule.object
        
        return {'FINISHED'} 