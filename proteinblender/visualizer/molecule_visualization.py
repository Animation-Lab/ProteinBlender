import bpy
import numpy as np
from typing import Optional, Dict, List
from enum import Enum
from pathlib import Path

from ..utils.molecular_nodes.mn_nodes import styles_mapping
from ..utils.molecular_nodes import mn_nodes as nodes
from ..utils.molecular_nodes.mn_material import add_all_materials, append, default
from ..utils.molecular_nodes.mn_utils import MN_DATA_FILE

class VisualizationStyle(Enum):
    SURFACE = "surface"
    CARTOON = "cartoon" 
    SPHERES = "spheres"
    RIBBON = "ribbon"
    BALL_AND_STICK = "ball_and_stick"
    STICKS = "sticks"

class MoleculeVisualization:
    """Handles the visualization of molecules using Geometry Nodes"""
    
    def __init__(self, molecule):
        self.molecule = molecule
        self.style = VisualizationStyle.SURFACE
        self.object: Optional[bpy.types.Object] = None
        self.groups: Dict[str, Dict] = {}  # Store visibility groups
        self._node_tree = None
        
    @property
    def node_tree(self):
        """Get the geometry nodes tree for this visualization"""
        if self.object:
            return self.object.modifiers["MolecularNodes"].node_group
        return None

    def create_visualization(self, style: str = "surface") -> None:
        """Create the initial visualization of the molecule"""
        try:
            # Create the base object directly without pre-processing vertices
            self.object = self._create_base_object(None)
            
            # Set up geometry nodes modifier
            self._setup_geometry_nodes(style)
            
            # Store reference back in molecule
            self.molecule.object = self.object


            
        except Exception as e:
            print(f"Error creating visualization: {str(e)}")
            raise

    def _create_base_object(self, vertices=None) -> bpy.types.Object:
        """Create the base Blender object with vertex data"""
        from ..utils.molecular_nodes.mn_mesh import create_data_object
        
        # Let create_data_object handle the array directly
        obj = create_data_object(
            array=self.molecule.array,
            name=self.molecule.identifier,
            world_scale=0.01,
        )
        
        return obj

    def _setup_geometry_nodes(self, style: str) -> None:
        """Set up the geometry nodes system for visualization"""
        if not self.object:
            raise ValueError("No object created yet")
            
        from ..utils.molecular_nodes.mn_nodes import (
            create_starting_node_tree,
            styles_mapping
        )
        from ..utils.molecular_nodes.mn_material import add_all_materials, append, default
        import bpy
        
        # First ensure all MolecularNodes materials are available
        add_all_materials()
        
        # Create the node tree with proper settings
        # we use BP_ to avoid conflicts with MolecularNodes
        self._node_tree = create_starting_node_tree(
            object=self.object,
            style=style,
            name=f"BP_{self.object.name}",
            color="common",
            is_modifier=False
        )
        
        # Ensure material is properly set up
        if self.object:
            # Remove any existing materials
            self.object.data.materials.clear()
            
            '''
            # Get or create the MN Default material
            mat = bpy.data.materials.get("MN Default")
            if not mat:
                mat = default()  # This will append the default material from the data file
            
            # Add the material to the object
            self.object.data.materials.append(mat)
            
            # Ensure material uses nodes
            mat.use_nodes = True
            
            # Set material properties for better visualization
            mat.blend_method = 'OPAQUE'  # or 'BLEND' if you want transparency
            mat.shadow_method = 'OPAQUE'  # or 'NONE' if you don't want shadows
            
            print(f"Material setup complete. Active material: {mat.name}")
            print(f"Material nodes enabled: {mat.use_nodes}")
            print(f"Material blend method: {mat.blend_method}")
            '''
    def _setup_basic_nodes(self, style: str) -> None:
        """
        This method is now handled by create_starting_node_tree
        We keep it for compatibility but it's essentially a no-op
        """
        pass

    def change_style(self, style: str) -> None:
        """Change the visualization style"""
        if not self.object:
            return
            
        try:
            nodes.change_style_node(self.object, style)
            self.style = VisualizationStyle(style)
        except Exception as e:
            print(f"Error changing style: {str(e)}")
            raise

    def create_group(self, name: str, residues: List[int]) -> None:
        """Create a new visibility group"""
        if name in self.groups:
            raise ValueError(f"Group {name} already exists")
            
        self.groups[name] = {
            'residues': residues,
            'visible': True
        }
        
        # Update nodes to support new group
        self._update_group_nodes()

    def update_visibility(self, group_name: str, visible: bool) -> None:
        """Update visibility of a group"""
        if group_name not in self.groups:
            raise ValueError(f"Group {group_name} does not exist")
            
        self.groups[group_name]['visible'] = visible
        self._update_group_nodes()

    def _update_group_nodes(self) -> None:
        """Update the node tree to reflect current group settings"""
        if not self._node_tree:
            return
            
        # Implementation will depend on how we want to handle
        # group visibility in the geometry nodes
        pass

    def remove(self) -> None:
        """Remove the visualization"""
        if self.object:
            bpy.data.objects.remove(self.object, do_unlink=True)
            self.object = None
            self._node_tree = None

    def get_groups(self) -> Dict:
        """Get current group settings for serialization"""
        return self.groups