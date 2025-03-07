import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, FloatVectorProperty
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
        

        # get the chain_id as an int
        chain_id_char = molecule.chain_mapping.get(int(scene.new_domain_chain) if scene.new_domain_chain.isdigit() else scene.new_domain_chain, str(scene.new_domain_chain))
        print(f"Checking overlap for chain {chain_id_char} ({scene.new_domain_start}-{scene.new_domain_end})")
        check_overlap = molecule._check_domain_overlap(
            chain_id_char, 
            scene.new_domain_start, 
            scene.new_domain_end
        )

        if check_overlap:
            self.report({'ERROR'}, "Domain overlaps with existing domain")
            return {'CANCELLED'}
        
        # Create the domain with values from the UI
        domain_id = molecule.create_domain(
            chain_id=scene.new_domain_chain,  # Use the chain selected in UI
            start=scene.new_domain_start,  # Use the start value from UI
            end=scene.new_domain_end  # Use the end value from UI
        )
        
        if domain_id is None:
            self.report({'ERROR'}, "Failed to create domain")
            return {'CANCELLED'}
            
        # Automatically expand the new domain
        if domain_id in molecule.domains:
            domain = molecule.domains[domain_id]
            
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
    action: StringProperty(default='UPDATE')
    chain_id: StringProperty(default='')
    
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
        
        # Handle different actions
        if self.action == 'SET_CHAIN':
            # Get the mapped chain
            try:
                author_chain_id = molecule.get_author_chain_id(int(self.chain_id) if self.chain_id.isdigit() else self.chain_id)
                
                # If chain has changed, update residue range to valid values for this chain
                if author_chain_id in molecule.chain_residue_ranges:
                    min_res, max_res = molecule.chain_residue_ranges[author_chain_id]
                    
                    # Check for overlaps
                    if molecule._check_domain_overlap(
                        self.chain_id, min_res, max_res,
                        exclude_domain_id=self.domain_id
                    ):
                        self.report({'ERROR'}, f"Cannot change chain - would overlap with existing domain")
                        return {'CANCELLED'}
                    
                    # Proceed with update
                    domain.chain_id = author_chain_id
                    domain.start = min_res
                    domain.end = max_res
                    return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Error updating chain: {str(e)}")
                return {'CANCELLED'}
        else:
            # Use domain properties directly instead of scene properties
            chain_id = domain.chain_id
            start = domain.start
            end = domain.end
            
            # Check if the residue range is valid
            if start > end:
                self.report({'ERROR'}, f"Invalid residue range: {start} > {end}")
                return {'CANCELLED'}
            
            # Check for overlaps with other domains (exclude this domain)
            if molecule._check_domain_overlap(
                chain_id, 
                start, 
                end,
                exclude_domain_id=self.domain_id
            ):
                self.report({'ERROR'}, f"Domain overlaps with existing domain in chain {chain_id}")
                return {'CANCELLED'}
                
            # Update the domain
            success = molecule.update_domain(
                domain_id=self.domain_id,
                chain_id=chain_id,
                start=start,
                end=end
            )
            
            if not success:
                self.report({'ERROR'}, "Failed to update domain")
                return {'CANCELLED'}
        
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
        
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_ui_values(Operator):
    bl_idname = "molecule.update_domain_ui_values"
    bl_label = "Update Domain UI"
    bl_description = "Update UI values to match domain values"
    bl_options = {'INTERNAL'}
    
    domain_id: StringProperty()
    
    def execute(self, context):
        # This operator is largely obsolete now since we're using direct domain properties
        # It's kept for backward compatibility but doesn't need to do anything
        print(f"UI values updated for domain {self.domain_id}")
        return {'FINISHED'}

class MOLECULE_PB_OT_update_domain_color(Operator):
    bl_idname = "molecule.update_domain_color"
    bl_label = "Update Domain Color"
    bl_description = "Update the color of the selected domain"
    
    domain_id: StringProperty()
    color: FloatVectorProperty(
        size=4,
        min=0.0, max=1.0,
        default=(0.8, 0.1, 0.8, 1.0)
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the molecule and domain
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get the domain
        domain = molecule.domains.get(self.domain_id)
        if not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Get color
        color = scene.domain_color
        if hasattr(self, "color") and self.color[0] >= 0:  # Check if color parameter was provided
            color = self.color
            
        print(f"1 Updating color for domain {self.domain_id} to {color}")
        # Update domain color
        success = molecule.update_domain_color(self.domain_id, color)
        if not success:
            self.report({'ERROR'}, "Failed to update domain color")
            return {'CANCELLED'}
            
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
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_color)

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_color)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_ui_values)
    bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
