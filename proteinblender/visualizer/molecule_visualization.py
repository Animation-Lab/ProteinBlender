import bpy
import numpy as np
from typing import Optional, Dict, List
from enum import Enum
from pathlib import Path

from ..utils.molecular_nodes.mn_nodes import styles_mapping
from ..utils.molecular_nodes import mn_nodes as nodes

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
            
        # Get or create the geometry nodes modifier
        mod = nodes.get_mod(self.object)
        
        # Create node tree name
        tree_name = f"MN_{self.object.name}"
        
        # Create the node tree
        self._node_tree = nodes.new_tree(
            name=tree_name,
            geometry=True,
            input_name="Atoms",
            output_name="Geometry"
        )
        
        # Assign node tree to modifier
        mod.node_group = self._node_tree
        
        # Add basic nodes
        self._setup_basic_nodes(style)

    def _setup_basic_nodes(self, style: str) -> None:
        """Set up the basic node structure"""
        try:
            tree = self._node_tree
            
            # Get input and output nodes
            node_input = nodes.get_input(tree)
            node_output = nodes.get_output(tree)
            
            # Position nodes
            node_input.location = (0, 0)
            node_output.location = (700, 0)
            
            # Add style node
            style_name = styles_mapping.get(style, styles_mapping["surface"])
            print(f"\nSetting up style: {style} -> {style_name}")
            
            node_style = nodes.add_custom(
                tree,
                style_name,
                location=(450, 0),
                material="MN Default"
            )
            print(f"Created style node: {node_style.name}")
            print(f"Style node inputs: {[input.name for input in node_style.inputs]}")
            print(f"Style node outputs: {[output.name for output in node_style.outputs]}")
            
            # Set default values for surface style
            if style == "surface":
                # Print input types for debugging
                for input in node_style.inputs:
                    print(f"Input '{input.name}' type: {input.type}")
                
                # Set values based on input types
                node_style.inputs["Quality"].default_value = 2  # Medium quality (INT)
                node_style.inputs["Scale Radii"].default_value = 1.0  # Normal scale (VALUE/float)
                node_style.inputs["Probe Size"].default_value = 1.4  # Standard probe size (VALUE/float)
                node_style.inputs["Triangulate"].default_value = True  # Enable triangulation (BOOLEAN)
                node_style.inputs["Relaxation Steps"].default_value = 5  # Medium relaxation (INT)
                node_style.inputs["Color by CA"].default_value = False  # Color by all atoms (BOOLEAN)
                node_style.inputs["Color Blur"].default_value = 2  # Medium blur (INT)
                node_style.inputs["Shade Smooth"].default_value = True  # Enable smooth shading (BOOLEAN)
            
            # Link nodes
            tree.links.new(node_style.outputs[0], node_output.inputs[0])
            tree.links.new(node_input.outputs[0], node_style.inputs[0])
            print("Node connections established")
            
        except Exception as e:
            print(f"Error in _setup_basic_nodes: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

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