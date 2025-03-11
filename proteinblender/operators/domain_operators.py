import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, FloatVectorProperty
from ..utils.scene_manager import ProteinBlenderScene

# Ensure domain properties are registered
from ..core.domain import ensure_domain_properties_registered
ensure_domain_properties_registered()

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
        
        # Log the domain creation
        print(f"Creating primary domain for chain {scene.new_domain_chain} ({scene.new_domain_start}-{scene.new_domain_end})")
        
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
                    
                    # Also sync the domain_color property with the actual color used
                    if hasattr(domain, "color"):
                        # Set the domain_color property to match the actual color used in the node tree
                        domain.object.domain_color = domain.color
                except:
                    # If that fails, ensure the property exists first
                    if not hasattr(domain.object, "domain_expanded"):
                        # Register the property if needed
                        bpy.types.Object.domain_expanded = bpy.props.BoolProperty(default=False)
                    # Then set it
                    domain.object.domain_expanded = True
                    
                    # And try setting the color again
                    if hasattr(domain, "color") and hasattr(domain.object, "domain_color"):
                        domain.object.domain_color = domain.color
            
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
            
        # Get the domain to be deleted
        if self.domain_id not in molecule.domains:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Delete the domain and get the ID of the domain that replaced it (if any)
        new_domain_id = molecule.delete_domain(self.domain_id)
        
        # If there's a replacement domain, select it to maintain UI continuity
        if new_domain_id and new_domain_id in molecule.domains:
            domain = molecule.domains.get(new_domain_id)
            if domain and domain.object:
                # Make the domain object the active object to help with UI continuity
                context.view_layer.objects.active = domain.object
        
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

class MOLECULE_PB_OT_update_domain_style(Operator):
    bl_idname = "molecule.update_domain_style"
    bl_label = "Update Domain Style"
    bl_description = "Change the visualization style of the domain"
    
    domain_id: StringProperty()
    style: StringProperty(default="ribbon")
    
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
        
        # Update the domain's style
        try:
            print(f"Operator: Changing domain style for {self.domain_id} to {self.style}")
            
            # Update the style in the node network
            if domain.node_group:
                # Find style node
                style_node = None
                for node in domain.node_group.nodes:
                    if (node.bl_idname == 'GeometryNodeGroup' and 
                        node.node_tree and 
                        "Style" in node.node_tree.name):
                        style_node = node
                        break
                
                if style_node:
                    # Get the style node name from the style value
                    from ..utils.molecularnodes.blender.nodes import styles_mapping, append, swap
                    if self.style in styles_mapping:
                        style_node_name = styles_mapping[self.style]
                        # Swap the style node
                        swap(style_node, append(style_node_name))
                        
                        # Update the domain's style property
                        domain.style = self.style
                        
                        # Try to set the domain_style property, handling possible errors
                        try:
                            domain.object.domain_style = self.style
                        except (AttributeError, TypeError):
                            # Fall back to custom property if needed
                            domain.object["domain_style"] = self.style
                        
                        return {'FINISHED'}
                    else:
                        self.report({'ERROR'}, f"Invalid style: {self.style}")
                        return {'CANCELLED'}
                else:
                    self.report({'ERROR'}, "Style node not found in domain node group")
                    return {'CANCELLED'}
            else:
                self.report({'ERROR'}, "Domain node group not found")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Error updating domain style: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

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
    bpy.utils.register_class(MOLECULE_PB_OT_update_domain_style)

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_style)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_color)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_ui_values)
    bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
