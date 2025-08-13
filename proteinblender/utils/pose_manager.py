"""Pose Manager module for handling pose operations in ProteinBlender"""

import bpy
import numpy as np
from mathutils import Vector, Matrix
from datetime import datetime
import os
import uuid


class PoseManager:
    """Manages pose operations for molecules"""
    
    @staticmethod
    def calculate_alpha_carbon_center(molecule_object):
        """
        Calculate the center of mass of alpha carbons (CA atoms) in the molecule.
        
        Args:
            molecule_object: Blender object containing the molecule mesh
            
        Returns:
            Vector: 3D position of the alpha carbon center of mass
        """
        if not molecule_object or not molecule_object.data:
            return Vector((0, 0, 0))
        
        mesh = molecule_object.data
        
        # Check if required attributes exist
        if "atom_name" not in mesh.attributes:
            print(f"Warning: No atom_name attribute found in {molecule_object.name}")
            # Fallback to object center
            return molecule_object.location.copy()
        
        # Get atom names and positions
        atom_name_attr = mesh.attributes["atom_name"]
        vertices = mesh.vertices
        
        # Find alpha carbons (CA atoms)
        ca_positions = []
        for i, atom_data in enumerate(atom_name_attr.data):
            # The atom_name attribute stores integer values that map to atom names
            # CA atoms typically have a specific integer value (need to check the mapping)
            # For now, we'll use a simple heuristic or check the actual mapping
            
            # Try to get the actual atom name if there's a mapping
            # This depends on how MolecularNodes stores atom names
            if i < len(vertices):
                vertex = vertices[i]
                # Check if this is a CA atom (this logic may need adjustment based on actual data structure)
                # For now, collect all vertices as a fallback
                ca_positions.append(molecule_object.matrix_world @ vertex.co)
        
        # If no CA atoms found, use all vertices as fallback
        if not ca_positions:
            ca_positions = [molecule_object.matrix_world @ v.co for v in vertices]
        
        if not ca_positions:
            return molecule_object.location.copy()
        
        # Calculate center of mass
        center = Vector((0, 0, 0))
        for pos in ca_positions:
            center += pos
        center /= len(ca_positions)
        
        return center
    
    @staticmethod
    def get_all_groups(context):
        """
        Get all groups in the scene.
        
        Args:
            context: Blender context
            
        Returns:
            dict: Dictionary of group_id -> list of member_ids for all groups
        """
        groups = {}
        
        # Find all groups in the scene
        for item in context.scene.outliner_items:
            if item.item_type == 'PUPPET' and item.item_id != "puppets_separator":
                # Get member IDs for this group
                member_ids = item.puppet_memberships.split(',') if item.puppet_memberships else []
                # Include the group even if it has no members (empty groups are still valid)
                groups[item.item_id] = member_ids
        
        return groups
    
    @staticmethod
    def get_groups_for_molecule(context, molecule_id):
        """
        Get all groups that contain chains or domains from this molecule.
        
        Args:
            context: Blender context
            molecule_id: ID of the molecule
            
        Returns:
            dict: Dictionary of group_id -> list of member_ids for this molecule
        """
        # For now, return all groups since poses should work with any groups
        return PoseManager.get_all_groups(context)
    
    @staticmethod
    def get_group_objects(context, group_id):
        """
        Get all Blender objects associated with a group.
        
        Args:
            context: Blender context
            group_id: ID of the group
            
        Returns:
            list: List of Blender objects in the group
        """
        from ..utils.scene_manager import ProteinBlenderScene
        
        objects = []
        scene_manager = ProteinBlenderScene.get_instance()
        
        # Find the group
        group_item = None
        for item in context.scene.outliner_items:
            if item.item_id == group_id and item.item_type == 'PUPPET':
                group_item = item
                break
        
        if not group_item or not group_item.puppet_memberships:
            return objects
        
        member_ids = group_item.puppet_memberships.split(',')
        
        for member_id in member_ids:
            # Parse member ID to get molecule and component
            if '_' in member_id:
                parts = member_id.split('_')
                mol_id = parts[0]
                
                molecule = scene_manager.molecules.get(mol_id)
                if not molecule:
                    continue
                
                # Check if it's a domain
                if len(parts) >= 2:
                    domain_id = '_'.join(parts[1:])
                    if domain_id in molecule.domains:
                        domain = molecule.domains[domain_id]
                        if domain.object:
                            objects.append(domain.object)
                # Check if it's a chain (format: mol_id_chain_X)
                elif member_id.startswith(f"{mol_id}_chain_"):
                    # For chains, we need to get the chain's visual representation
                    # This might be part of the main molecule object or a separate object
                    if molecule.object:
                        objects.append(molecule.object)
        
        return objects
    
    @staticmethod
    def capture_group_transforms(context, pose, group_ids, alpha_carbon_center):
        """
        Capture the current transforms of groups relative to alpha carbon center.
        
        Args:
            context: Blender context
            pose: MoleculePose object to store transforms in
            group_ids: List of group IDs to capture
            alpha_carbon_center: Vector representing the alpha carbon center
        """
        # Clear existing transforms
        pose.group_transforms.clear()
        
        # Store alpha carbon center
        pose.alpha_carbon_center = alpha_carbon_center
        
        for group_id in group_ids:
            objects = PoseManager.get_group_objects(context, group_id)
            
            for obj in objects:
                transform = pose.group_transforms.add()
                transform.group_id = f"{group_id}_{obj.name}"
                
                # Calculate relative position to alpha carbon center
                relative_location = obj.location - alpha_carbon_center
                transform.relative_location = relative_location
                transform.relative_rotation = obj.rotation_euler.copy()
                transform.relative_scale = obj.scale.copy()
    
    @staticmethod
    def apply_group_transforms(context, pose, molecule_object):
        """
        Apply stored transforms to groups, adjusting for current alpha carbon center.
        
        Args:
            context: Blender context
            pose: MoleculePose object containing transforms
            molecule_object: Current molecule object to calculate new alpha carbon center
        """
        # Calculate current alpha carbon center
        current_center = PoseManager.calculate_alpha_carbon_center(molecule_object)
        
        # Apply transforms
        for transform in pose.group_transforms:
            # Parse the group_id_objectname format
            parts = transform.group_id.rsplit('_', 1)
            if len(parts) < 2:
                continue
                
            group_id = parts[0]
            obj_name = parts[1]
            
            # Find the object
            obj = bpy.data.objects.get(obj_name)
            if not obj:
                continue
            
            # Apply relative transform
            obj.location = current_center + Vector(transform.relative_location)
            obj.rotation_euler = transform.relative_rotation
            obj.scale = transform.relative_scale
    
    @staticmethod
    def create_pose_screenshot(context, pose, groups, output_dir=None):
        """
        Create a screenshot of the pose showing only the groups.
        
        Args:
            context: Blender context
            pose: MoleculePose object
            groups: List of group IDs in the pose
            output_dir: Directory to save screenshot (defaults to temp)
            
        Returns:
            str: Path to the saved screenshot
        """
        import tempfile
        
        if not output_dir:
            output_dir = tempfile.gettempdir()
        
        # Generate unique filename
        screenshot_name = f"pose_{uuid.uuid4().hex[:8]}.png"
        screenshot_path = os.path.join(output_dir, screenshot_name)
        
        # Store current visibility states
        visibility_states = {}
        for obj in bpy.data.objects:
            visibility_states[obj] = obj.hide_viewport
        
        try:
            # Hide all objects first
            for obj in bpy.data.objects:
                obj.hide_viewport = True
            
            # Show only objects in the pose groups
            for group_id in groups:
                objects = PoseManager.get_group_objects(context, group_id)
                for obj in objects:
                    obj.hide_viewport = False
            
            # Set up render settings for thumbnail
            scene = context.scene
            original_x = scene.render.resolution_x
            original_y = scene.render.resolution_y
            original_percentage = scene.render.resolution_percentage
            
            # Set thumbnail size
            scene.render.resolution_x = 256
            scene.render.resolution_y = 256
            scene.render.resolution_percentage = 100
            
            # Frame the visible objects in the viewport
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = {'area': area, 'region': region}
                            bpy.ops.view3d.view_all(override)
                            break
            
            # Render to file
            scene.render.filepath = screenshot_path
            bpy.ops.render.render(write_still=True)
            
            # Restore render settings
            scene.render.resolution_x = original_x
            scene.render.resolution_y = original_y
            scene.render.resolution_percentage = original_percentage
            
        finally:
            # Restore visibility states
            for obj, hidden in visibility_states.items():
                obj.hide_viewport = hidden
        
        return screenshot_path
    
    @staticmethod
    def create_default_pose(context, molecule_item, molecule):
        """
        Create a default pose for a newly imported molecule.
        
        Args:
            context: Blender context
            molecule_item: MoleculeListItem
            molecule: MoleculeWrapper object
            
        Returns:
            MoleculePose: The created default pose
        """
        # Create the default pose
        pose = molecule_item.poses.add()
        pose.name = "Default"
        pose.is_default = True
        pose.created_at = datetime.now().isoformat()
        pose.modified_at = pose.created_at
        
        # Get all groups for this molecule
        groups = PoseManager.get_groups_for_molecule(context, molecule.identifier)
        
        if groups:
            # Store group IDs
            all_group_ids = list(groups.keys())
            pose.group_ids = ','.join(all_group_ids)
            
            # Calculate alpha carbon center
            alpha_center = PoseManager.calculate_alpha_carbon_center(molecule.object)
            
            # Capture current transforms
            PoseManager.capture_group_transforms(context, pose, all_group_ids, alpha_center)
            
            # Create screenshot
            screenshot_path = PoseManager.create_pose_screenshot(context, pose, all_group_ids)
            pose.screenshot_path = screenshot_path
        
        return pose
    
    @staticmethod
    def update_pose_timestamp(pose):
        """Update the modified timestamp of a pose"""
        pose.modified_at = datetime.now().isoformat()