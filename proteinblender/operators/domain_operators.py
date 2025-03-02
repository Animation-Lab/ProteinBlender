import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty
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
            
        # Update UI inputs to reflect actual domain values using our new operator
        if domain_id in molecule.domains:
            domain = molecule.domains[domain_id]
            
            # Call our UI update operator
            bpy.ops.molecule.update_domain_ui_values(domain_id=domain_id)
            
            # Automatically expand the new domain
            if domain.object:
                try:
                    # Try to set the property directly
                    domain.object["domain_expanded"] = True
                except:
                    # If that fails, ensure the property exists first
                    if not hasattr(domain.object, "domain_expanded"):
                        # Register the property if needed
                        bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
                    # Then set it
                    domain.object.domain_expanded = True
            
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
        success = molecule.update_domain(
            domain_id=self.domain_id,
            chain_id=scene.selected_chain_for_domain,
            start=scene.domain_start,
            end=scene.domain_end
        )
        
        if not success:
            self.report({'ERROR'}, "Failed to update domain")
            return {'CANCELLED'}
            
        # Get the updated domain ID (it might have changed if chain/range changed)
        updated_domain_id = None
        for d_id, domain in molecule.domains.items():
            if d_id.endswith(f"{scene.selected_chain_for_domain}_{scene.domain_start}_{scene.domain_end}"):
                updated_domain_id = d_id
                break
                
        # If we found the updated domain, ensure UI values match using our new operator
        if updated_domain_id and updated_domain_id in molecule.domains:
            # Call our UI update operator
            bpy.ops.molecule.update_domain_ui_values(domain_id=updated_domain_id)
        
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

class MOLECULE_PB_OT_toggle_domain_expanded(Operator):
    bl_idname = "molecule.toggle_domain_expanded"
    bl_label = "Toggle Domain Expanded"
    bl_description = "Toggle domain expanded state and load its values"
    
    domain_id: StringProperty()
    is_expanded: BoolProperty()
    
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
        if not domain or not domain.object:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Toggle expanded state
        try:
            # Try to set the property directly
            domain.object["domain_expanded"] = self.is_expanded
        except:
            # If that fails, ensure the property exists first
            if not hasattr(domain.object, "domain_expanded"):
                # Register the property if needed
                bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
            # Then set it
            domain.object.domain_expanded = self.is_expanded
        
        # If expanding, update UI values using our new operator
        if self.is_expanded:
            bpy.ops.molecule.update_domain_ui_values(domain_id=self.domain_id)
        
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_ui_values(Operator):
    bl_idname = "molecule.update_domain_ui_values"
    bl_label = "Update Domain UI"
    bl_description = "Update UI values to match domain values"
    bl_options = {'INTERNAL'}
    
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
            
        # Find the numeric chain ID that corresponds to the domain's chain_id
        numeric_chain_id = None
        # First, check if the domain's chain_id is already numeric
        if domain.chain_id.isdigit():
            numeric_chain_id = domain.chain_id
        else:
            # If not, we need to find the numeric ID by looking at the chain mapping
            for num_id, mapped_id in molecule.chain_mapping.items():
                if mapped_id == domain.chain_id:
                    numeric_chain_id = str(num_id)
                    break
                    
            # If we couldn't find it in the mapping, try the first available chain
            if numeric_chain_id is None and molecule.object and "chain_id" in molecule.object.data.attributes:
                chain_attr = molecule.object.data.attributes["chain_id"]
                chain_ids = sorted({value.value for value in chain_attr.data})
                if chain_ids:
                    numeric_chain_id = str(chain_ids[0])
        
        # If we found a valid numeric chain ID, update the UI
        if numeric_chain_id is not None:
            try:
                # Update the UI properties to match the actual domain values
                scene.selected_chain_for_domain = numeric_chain_id
                scene.domain_start = domain.start
                scene.domain_end = domain.end
            except (TypeError, ValueError) as e:
                self.report({'WARNING'}, f"Could not update UI: {str(e)}")
                
        return {'FINISHED'}

# Register
def register():
    bpy.utils.register_class(MOLECULE_PB_OT_create_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.register_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.register_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_ui_values)

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_ui_values)
