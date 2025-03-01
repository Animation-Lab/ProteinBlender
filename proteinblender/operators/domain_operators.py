import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty
from ..utils.scene_manager import ProteinBlenderScene

class MOLECULE_PB_OT_create_domain(Operator):
    bl_idname = "molecule.create_domain"
    bl_label = "Create Domain"
    bl_description = "Create a new domain from the selected residue range"
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Create the domain with default values
        domain_id = molecule.create_domain(
            # Create with default values that will need to be configured 
            chain_id=None,  # Will be automatically selected first available chain
            start=1,  # Default start value
            end=9999  # Default end value that will be adjusted based on chain
        )
        
        if domain_id is None:
            self.report({'ERROR'}, "Failed to create domain")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain(Operator):
    bl_idname = "molecule.update_domain"
    bl_label = "Update Domain"
    bl_description = "Update the selected domain's parameters"
    
    domain_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Check if the new chain ID is different
        chain_changed = domain.chain_id != scene.selected_chain_for_domain
        
        # Check if the residue range is valid
        if scene.domain_start > scene.domain_end:
            self.report({'ERROR'}, f"Invalid residue range: {scene.domain_start} > {scene.domain_end}")
            return {'CANCELLED'}
            
        # Check for overlaps with other domains (exclude this domain)
        if molecule._check_domain_overlap(
            scene.selected_chain_for_domain, 
            scene.domain_start, 
            scene.domain_end,
            exclude_domain_id=self.domain_id
        ):
            self.report({'ERROR'}, f"Domain overlaps with existing domain in chain {scene.selected_chain_for_domain}")
            return {'CANCELLED'}
            
        # Update the domain
        molecule.update_domain(
            domain_id=self.domain_id,
            chain_id=scene.selected_chain_for_domain,
            start=scene.domain_start,
            end=scene.domain_end
        )
        
        return {'FINISHED'}

class MOLECULE_PB_OT_delete_domain(Operator):
    bl_idname = "molecule.delete_domain"
    bl_label = "Delete Domain"
    bl_description = "Delete the selected domain"
    
    domain_id: StringProperty()
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the selected molecule
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Delete the domain
        molecule.delete_domain(self.domain_id)
        return {'FINISHED'}

class MOLECULE_PB_OT_keyframe_domain_location(Operator):
    bl_idname = "molecule.keyframe_domain_location"
    bl_label = "Keyframe Location"
    bl_description = "Add keyframe for domain location"
    
    def execute(self, context):
        obj = context.active_object
        if obj:
            obj.keyframe_insert(data_path="location")
        return {'FINISHED'}

class MOLECULE_PB_OT_keyframe_domain_rotation(Operator):
    bl_idname = "molecule.keyframe_domain_rotation"
    bl_label = "Keyframe Rotation"
    bl_description = "Add keyframe for domain rotation"
    
    def execute(self, context):
        obj = context.active_object
        if obj:
            obj.keyframe_insert(data_path="rotation_euler")
        return {'FINISHED'}

# Register
def register():
    bpy.utils.register_class(MOLECULE_PB_OT_create_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_rotation)

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
