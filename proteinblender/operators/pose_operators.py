import bpy
from bpy.types import Operator
from bpy.props import StringProperty, FloatVectorProperty
from ..utils.scene_manager import get_protein_blender_scene

class MOLECULE_PB_OT_create_pose(Operator):
    bl_idname = "molecule.create_pose"
    bl_label = "Create Pose"
    bl_description = "Save current domain positions as a new pose"
    
    pose_name: StringProperty(
        name="Pose Name",
        description="Name for the new pose",
        default="New Pose"
    )
    
    def invoke(self, context, event):
        # Set a better default name based on molecule and pose count
        scene = context.scene
        scene_manager = get_protein_blender_scene(context)
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if molecule:
            # Find molecule item
            molecule_item = None
            for item in scene.molecule_list_items:
                if item.identifier == molecule.identifier:
                    molecule_item = item
                    break
            
            if molecule_item:
                pose_count = len(molecule_item.poses)
                if pose_count == 0:
                    self.pose_name = f"{molecule.identifier} State 1"
                else:
                    self.pose_name = f"{molecule.identifier} State {pose_count + 1}"
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pose_name")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = get_protein_blender_scene(context)
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item from scene property
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Create a new pose
        pose = molecule_item.poses.add()
        pose.name = self.pose_name
        
        # Don't store the main protein object transform
        pose.has_protein_transform = False
        
        # For each domain, store its current transforms
        for domain_id, domain in molecule.domains.items():
            if not domain.object:
                continue
                
            transform = pose.domain_transforms.add()
            transform.domain_id = domain_id
            transform.location = domain.object.location.copy()
            transform.rotation = domain.object.rotation_euler.copy()
            transform.scale = domain.object.scale.copy()
        
        # Set the new pose as active
        molecule_item.active_pose_index = len(molecule_item.poses) - 1
        
        self.report({'INFO'}, f"Created pose '{self.pose_name}' with {len(pose.domain_transforms)} domains")
        return {'FINISHED'}

class MOLECULE_PB_OT_apply_pose(Operator):
    bl_idname = "molecule.apply_pose"
    bl_label = "Apply Pose"
    bl_description = "Apply the selected pose to the molecule"
    
    pose_index: StringProperty(
        name="Pose Index",
        description="Index of the pose to apply",
        default=""
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = get_protein_blender_scene(context)
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item from scene property
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Get pose index - either from parameter or active index
        pose_idx = -1
        if self.pose_index and self.pose_index.isdigit():
            pose_idx = int(self.pose_index)
            # Update active pose index when applying via index
            molecule_item.active_pose_index = pose_idx
        else:
            pose_idx = molecule_item.active_pose_index
        
        # Check if pose exists
        if pose_idx < 0 or pose_idx >= len(molecule_item.poses):
            self.report({'ERROR'}, f"Invalid pose index: {pose_idx}")
            return {'CANCELLED'}
        
        pose = molecule_item.poses[pose_idx]
        
        # Get list of domains that exist in the pose
        domains_in_pose = {transform.domain_id for transform in pose.domain_transforms}
        
        # Apply transforms from pose to domains
        applied_count = 0
        for transform in pose.domain_transforms:
            domain_id = transform.domain_id
            
            # Skip if domain doesn't exist
            if domain_id not in molecule.domains:
                continue
                
            domain = molecule.domains[domain_id]
            
            # Skip if domain doesn't have an object
            if not domain.object:
                continue
                
            # Apply transforms
            domain.object.location = transform.location
            domain.object.rotation_euler = transform.rotation
            domain.object.scale = transform.scale
            
            applied_count += 1
        
        # Reset domains that don't have stored transforms in this pose to their initial state
        reset_count = 0
        for domain_id, domain in molecule.domains.items():
            # Skip domains that were handled above
            if domain_id in domains_in_pose:
                continue
            # Skip domains without objects
            if not domain.object:
                continue
            # Reset to default transforms (identity)
            domain.object.location = (0, 0, 0)
            domain.object.rotation_euler = (0, 0, 0)
            domain.object.scale = (1, 1, 1)
            # Attempt to restore from initial_matrix_local if available
            try:
                if "initial_matrix_local" in domain.object:
                    from mathutils import Matrix
                    stored_matrix_list = domain.object["initial_matrix_local"]
                    initial_matrix = Matrix(stored_matrix_list)
                    domain.object.matrix_local = initial_matrix
            except Exception as e:
                print(f"Warning: Could not restore initial matrix for {domain.name}: {e}")
            reset_count += 1
        
        report_message = f"Applied pose '{pose.name}' to {applied_count} domains"
        if reset_count > 0:
            report_message += f" and reset {reset_count} domains to their default state"
        self.report({'INFO'}, report_message)
        return {'FINISHED'}

class MOLECULE_PB_OT_delete_pose(Operator):
    bl_idname = "molecule.delete_pose"
    bl_label = "Delete Pose"
    bl_description = "Delete the selected pose"
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item from scene property
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Get pose index
        pose_idx = molecule_item.active_pose_index
        
        # Check if pose exists
        if pose_idx < 0 or pose_idx >= len(molecule_item.poses):
            self.report({'ERROR'}, f"Invalid pose index: {pose_idx}")
            return {'CANCELLED'}
        
        pose_name = molecule_item.poses[pose_idx].name
        
        # Remove pose
        molecule_item.poses.remove(pose_idx)
        
        # Update active index
        if molecule_item.active_pose_index >= len(molecule_item.poses):
            molecule_item.active_pose_index = max(0, len(molecule_item.poses) - 1)
        
        self.report({'INFO'}, f"Deleted pose '{pose_name}'")
        return {'FINISHED'}

class MOLECULE_PB_OT_rename_pose(Operator):
    bl_idname = "molecule.rename_pose"
    bl_label = "Rename Pose"
    bl_description = "Rename the selected pose"
    
    new_name: StringProperty(
        name="New Name",
        description="New name for the pose",
        default=""
    )
    
    def invoke(self, context, event):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Get pose index
        pose_idx = molecule_item.active_pose_index
        
        # Check if pose exists
        if pose_idx < 0 or pose_idx >= len(molecule_item.poses):
            self.report({'ERROR'}, f"Invalid pose index: {pose_idx}")
            return {'CANCELLED'}
        
        # Set default name to current pose name
        self.new_name = molecule_item.poses[pose_idx].name
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Get pose index
        pose_idx = molecule_item.active_pose_index
        
        # Check if pose exists
        if pose_idx < 0 or pose_idx >= len(molecule_item.poses):
            self.report({'ERROR'}, f"Invalid pose index: {pose_idx}")
            return {'CANCELLED'}
        
        old_name = molecule_item.poses[pose_idx].name
        molecule_item.poses[pose_idx].name = self.new_name
        
        self.report({'INFO'}, f"Renamed pose from '{old_name}' to '{self.new_name}'")
        return {'FINISHED'}

class MOLECULE_PB_OT_update_pose(Operator):
    bl_idname = "molecule.update_pose"
    bl_label = "Update Pose"
    bl_description = "Update the pose with current domain positions, overwriting the existing pose"
    
    pose_index: StringProperty(
        name="Pose Index",
        description="Index of the pose to update",
        default=""
    )
    
    def execute(self, context):
        scene = context.scene
        scene_manager = ProteinBlenderScene.get_instance()
        molecule = scene_manager.molecules.get(scene.selected_molecule_id)
        
        if not molecule:
            self.report({'ERROR'}, "No molecule selected")
            return {'CANCELLED'}
            
        # Get molecule item from scene property
        molecule_item = None
        for item in scene.molecule_list_items:
            if item.identifier == molecule.identifier:
                molecule_item = item
                break
        
        if not molecule_item:
            self.report({'ERROR'}, "Could not find molecule in scene list")
            return {'CANCELLED'}
        
        # Get pose index
        if not self.pose_index or not self.pose_index.isdigit():
            self.report({'ERROR'}, "Invalid pose index")
            return {'CANCELLED'}
            
        pose_idx = int(self.pose_index)
        
        # Check if pose exists
        if pose_idx < 0 or pose_idx >= len(molecule_item.poses):
            self.report({'ERROR'}, f"Invalid pose index: {pose_idx}")
            return {'CANCELLED'}
        
        # Get the existing pose
        pose = molecule_item.poses[pose_idx]
        pose_name = pose.name
        
        # Don't update the main protein object transform
        pose.has_protein_transform = False
        
        # Clear existing domain transformations
        pose.domain_transforms.clear()
        
        # For each domain, store its current transforms
        for domain_id, domain in molecule.domains.items():
            if not domain.object:
                continue
                
            transform = pose.domain_transforms.add()
            transform.domain_id = domain_id
            transform.location = domain.object.location.copy()
            transform.rotation = domain.object.rotation_euler.copy()
            transform.scale = domain.object.scale.copy()
        
        # Set as active
        molecule_item.active_pose_index = pose_idx
        
        self.report({'INFO'}, f"Updated pose '{pose_name}' with {len(pose.domain_transforms)} domains")
        return {'FINISHED'}

# List of operator classes to be registered
CLASSES = [
    MOLECULE_PB_OT_create_pose,
    MOLECULE_PB_OT_apply_pose,
    MOLECULE_PB_OT_update_pose,
    MOLECULE_PB_OT_delete_pose,
    MOLECULE_PB_OT_rename_pose,
] 