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

class MOLECULE_PB_OT_edit_domain(Operator):
    """Unified domain editing operator that handles multiple domain properties"""
    bl_idname = "molecule.edit_domain"
    bl_label = "Edit Domain"
    bl_description = "Edit domain properties"
    
    domain_id: StringProperty(
        name="Domain ID",
        description="ID of the domain to edit"
    )
    
    edit_type: EnumProperty(
        name="Edit Type",
        description="Type of edit to perform",
        items=[
            ('CHAIN', "Chain", "Edit domain chain"),
            ('START', "Start", "Edit domain start residue"),
            ('END', "End", "Edit domain end residue"),
            ('COLOR', "Color", "Edit domain color"),
            ('TRANSFORM', "Transform", "Edit domain transformation")
        ],
        default='CHAIN'
    )
    
    def invoke(self, context, event):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the molecule and domain
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        domain = molecule.domains.get(self.domain_id) if molecule else None
        
        if not molecule or not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
        
        # Store the domain_id in a scene property for access in draw functions
        scene.temp_domain_id = self.domain_id
        
        # Different behavior based on edit type
        if self.edit_type == 'CHAIN':
            return self._invoke_chain_editor(context, molecule, domain)
        elif self.edit_type == 'START':
            return self._invoke_start_editor(context, molecule, domain)
        elif self.edit_type == 'END':
            return self._invoke_end_editor(context, molecule, domain)
        elif self.edit_type == 'COLOR':
            return self._invoke_color_editor(context, molecule, domain)
        else:
            self.report({'ERROR'}, f"Edit type {self.edit_type} not implemented")
            return {'CANCELLED'}
    
    def _invoke_chain_editor(self, context, molecule, domain):
        # Show popup menu for chain selection
        context.window_manager.popup_menu(self._draw_chain_menu, title="Select Chain")
        return {'FINISHED'}
        
    def _draw_chain_menu(self, popup, context):
        layout = popup.layout
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        domain_id = scene.temp_domain_id
        domain = molecule.domains.get(domain_id) if molecule else None
        
        if not domain:
            layout.label(text="Domain not found")
            return
            
        # Get available chains
        available_chains = []
        if molecule and molecule.object and "chain_id" in molecule.object.data.attributes:
            chain_attr = molecule.object.data.attributes["chain_id"]
            available_chains = sorted(set(value.value for value in chain_attr.data))
        
        # Add menu items for each chain
        for chain_id in available_chains:
            chain_str = str(chain_id)
            row = layout.row()
            # Add indicator for current chain
            if chain_str == domain.chain_id:
                row.label(text="✓", icon='CHECKMARK')
            else:
                row.label(text="")
            # Create operator to set chain
            op = row.operator(
                "molecule.update_domain",
                text=f"Chain {chain_str}"
            )
            op.domain_id = domain_id
            op.action = 'SET_CHAIN'
            op.chain_id = chain_str
    
    def _invoke_start_editor(self, context, molecule, domain):
        # Configure temp property for start value
        if not hasattr(context.scene, "temp_domain_start"):
            context.scene.temp_domain_start = domain.start
        else:
            context.scene.temp_domain_start = domain.start
            
        # Show popup for start editing
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def _invoke_end_editor(self, context, molecule, domain):
        # Configure temp property for end value
        if not hasattr(context.scene, "temp_domain_end"):
            context.scene.temp_domain_end = domain.end
        else:
            context.scene.temp_domain_end = domain.end
            
        # Show popup for end editing
        return context.window_manager.invoke_props_dialog(self, width=300)
        
    def _invoke_color_editor(self, context, molecule, domain):
        # Configure temp property for color
        if not hasattr(context.scene, "temp_domain_color"):
            # Try to get current color from domain
            context.scene.temp_domain_color = (0.8, 0.1, 0.8, 1.0)  # Default
            # Attempt to find actual color from nodes
            if domain.node_group:
                for node in domain.node_group.nodes:
                    if node.name.startswith("Color Common"):
                        if "Color" in node.outputs:
                            context.scene.temp_domain_color = node.outputs["Color"].default_value
        
        # Show popup for color editing
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        domain_id = scene.temp_domain_id
        
        # Get the molecule and domain
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        domain = molecule.domains.get(domain_id) if molecule else None
        
        if not domain:
            layout.label(text="Domain not found")
            return
            
        # Draw different UI based on edit type
        if self.edit_type == 'START':
            layout.label(text=f"Current start: {domain.start}")
            layout.prop(scene, "temp_domain_start", text="New Start")
        
        elif self.edit_type == 'END':
            layout.label(text=f"Current end: {domain.end}")
            layout.prop(scene, "temp_domain_end", text="New End")
            
        elif self.edit_type == 'COLOR':
            layout.label(text="Domain Color")
            layout.prop(scene, "temp_domain_color", text="")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Get the molecule and domain
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        domain = molecule.domains.get(scene.temp_domain_id) if molecule else None
        
        if not molecule or not domain:
            self.report({'ERROR'}, "Domain not found")
            return {'CANCELLED'}
            
        # Handle different edit types
        if self.edit_type == 'START':
            # Update start with validation
            new_start = scene.temp_domain_start
            if new_start > domain.end:
                new_start = domain.end  # Don't allow start > end
                
            # Check for overlaps
            if molecule._check_domain_overlap(
                domain.chain_id, 
                new_start, 
                domain.end,
                exclude_domain_id=scene.temp_domain_id
            ):
                self.report({'ERROR'}, f"Domain would overlap with existing domain")
                return {'CANCELLED'}
                
            # Update domain
            domain.start = new_start
            return {'FINISHED'}
            
        elif self.edit_type == 'END':
            # Update end with validation
            new_end = scene.temp_domain_end
            if new_end < domain.start:
                new_end = domain.start  # Don't allow end < start
                
            # Check for overlaps
            if molecule._check_domain_overlap(
                domain.chain_id, 
                domain.start, 
                new_end,
                exclude_domain_id=scene.temp_domain_id
            ):
                self.report({'ERROR'}, f"Domain would overlap with existing domain")
                return {'CANCELLED'}
                
            # Update domain
            domain.end = new_end
            return {'FINISHED'}
            
        elif self.edit_type == 'COLOR':
            # Update color
            # Call existing color update operator to reuse its functionality
            bpy.ops.molecule.update_domain_color(
                domain_id=scene.temp_domain_id, 
                color=scene.temp_domain_color
            )
            return {'FINISHED'}
            
        return {'CANCELLED'}
        
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
    bpy.utils.register_class(MOLECULE_PB_OT_edit_domain)  # New consolidated operator

def unregister():
    bpy.utils.unregister_class(MOLECULE_PB_OT_edit_domain)  # New consolidated operator
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_color)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain_ui_values)
    bpy.utils.unregister_class(MOLECULE_PB_OT_toggle_domain_expanded)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_rotation)
    bpy.utils.unregister_class(MOLECULE_PB_OT_keyframe_domain_location)
    bpy.utils.unregister_class(MOLECULE_PB_OT_delete_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_update_domain)
    bpy.utils.unregister_class(MOLECULE_PB_OT_create_domain)
