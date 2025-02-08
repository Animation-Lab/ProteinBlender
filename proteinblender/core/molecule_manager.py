from typing import Optional, Dict, List
import bpy
from pathlib import Path

from ..utils.molecularnodes.entities import fetch, load_local
from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..utils.molecularnodes.blender import nodes
from ..utils.molecularnodes.props import MolecularNodesSceneProperties
from ..utils.molecularnodes.session import MNSession
from ..utils.molecularnodes.addon import _test_register
from .domain import Domain

class MoleculeWrapper:
    """
    Wraps a MolecularNodes molecule and provides additional functionality
    and metadata specific to ProteinBlender
    """
    def __init__(self, molecule: Molecule, identifier: str):
        self.molecule = molecule
        self.identifier = identifier  # PDB ID or filename
        self.style = "spheres"  # Default style
        self.select_protein_chain = "NONE"
        self.domains = bpy.data.collections.new(f"{identifier}_domains")
        
    @property
    def object(self) -> bpy.types.Object:
        """Get the Blender object"""
        return self.molecule.object
        
    def change_style(self, new_style: str) -> None:
        """Change the visualization style of the molecule"""
        try:
            nodes.change_style_node(self.object, new_style)
            self.style = new_style
        except Exception as e:
            print(f"Error changing style for {self.identifier}: {str(e)}")
            raise

    def select_chains(self, chain_ids):
        """Select specific chains in the molecule"""
        if self.object and "chain_id" in self.object.data.attributes:
            # Get the geometry nodes modifier
            gn_mod = self.object.modifiers.get("MolecularNodes")
            if gn_mod is None:
                return
            
            node_group = gn_mod.node_group
            if node_group is None:
                return
            
            # Find existing chain selection node or create a new one
            chain_node = None
            for node in node_group.nodes:
                if node.bl_idname == "GeometryNodeGroup" and node.node_tree and "Select Chain" in node.node_tree.name:
                    chain_node = node
                    break
                
            if chain_node is None:
                # Import needed functions
                from ..utils.molecularnodes.blender.nodes import add_selection
                
                # Get all available chains from attributes
                chain_attr = self.object.data.attributes["chain_id"]
                all_chains = sorted({value.value for value in chain_attr.data})
                
                # Create chain selection node using MolecularNodes' add_selection
                chain_node = add_selection(
                    node_group,
                    f"Select Chain {self.object.name}",
                    all_chains,
                    field="chain_id"
                )
            
            # Update chain selections based on button states
            for chain_id in chain_node.inputs.keys():
                if chain_id.isdigit():  # Check if input is a number
                    chain_node.inputs[chain_id].default_value = chain_id in chain_ids

    def add_domain(self, chain_id: str, start: int, end: int, name: Optional[str] = None) -> None:
        """Add a new domain to the molecule"""
        print(f"Adding domain: {chain_id}, {start}, {end}, {name}")
        
        # Create new domain
        new_domain = self.domains.objects.new(name="Domain" if not name else name)
        new_domain.chain_id = chain_id
        new_domain.start = start
        new_domain.end = end
        new_domain.name = name if name else ""
        
        # Get the node group from the MolecularNodes modifier
        gn_mod = self.object.modifiers.get("MolecularNodes")
        if gn_mod and gn_mod.node_group:
            node_group = gn_mod.node_group
            
            # Get existing nodes
            group_input = nodes.get_input(node_group)
            group_output = nodes.get_output(node_group)
            style_node = nodes.style_node(node_group)
            
            # Find existing Join Geometry node
            join_node = None
            original_select_node = None
            for node in node_group.nodes:
                if node.bl_idname == "GeometryNodeJoinGeometry":
                    join_node = node
                elif (node.bl_idname == "GeometryNodeGroup" and 
                      node.node_tree and "Select Res ID Range" in node.node_tree.name):
                    original_select_node = node
            
            # If this is the first domain (no Join Geometry node exists)
            if join_node is None:
                # Create original Select Res ID Range node
                original_select_node = nodes.add_custom(node_group, "Select Res ID Range")
                original_select_node.inputs["Min"].default_value = 0
                original_select_node.inputs["Max"].default_value = 9999
                
                # Create Join Geometry node
                join_node = node_group.nodes.new("GeometryNodeJoinGeometry")
                
                # Position nodes
                style_pos = style_node.location
                join_node.location = (style_pos[0] + 200, style_pos[1])
                original_select_node.location = (style_pos[0] - 200, style_pos[1] - 200)
                
                # Connect original nodes
                node_group.links.new(original_select_node.outputs["Selection"], style_node.inputs["Selection"])
                node_group.links.new(style_node.outputs[0], join_node.inputs[0])
                node_group.links.new(join_node.outputs[0], group_output.inputs[0])
            
            # Create new domain nodes
            color_common = nodes.add_custom(node_group, "Color Common")
            set_color = nodes.add_custom(node_group, "Set Color")
            select_node = nodes.add_custom(node_group, "Select Res ID Range")
            style_surface = nodes.add_custom(node_group, "Style Surface")
            
            # Set Select Res ID Range values
            select_node.inputs["Min"].default_value = start
            select_node.inputs["Max"].default_value = end
            
            # Position nodes (offset each set of nodes vertically)
            base_y_offset = -300 * (len(self.domains) + 1)
            style_pos = style_node.location
            color_common.location = (style_pos[0] - 600, style_pos[1] + base_y_offset)
            set_color.location = (style_pos[0] - 400, style_pos[1] + base_y_offset)
            select_node.location = (style_pos[0] - 200, style_pos[1] + base_y_offset)
            style_surface.location = (style_pos[0], style_pos[1] + base_y_offset)
            
            # Connect nodes
            node_group.links.new(color_common.outputs["Color"], set_color.inputs["Color"])
            node_group.links.new(group_input.outputs["Atoms"], set_color.inputs["Atoms"])
            node_group.links.new(set_color.outputs["Atoms"], style_surface.inputs["Atoms"])
            node_group.links.new(select_node.outputs["Selection"], style_surface.inputs["Selection"])
            node_group.links.new(style_surface.outputs[0], join_node.inputs[0])
            
            # Connect Select Res ID Range Inverted output to original Select Res ID Range And input
            if original_select_node:
                node_group.links.new(select_node.outputs["Inverted"], original_select_node.inputs["And"])

class MoleculeManager:
    """Manages all molecules in the scene"""
    def __init__(self):
        self.molecules: Dict[str, MoleculeWrapper] = {}
        self._initialize_molecularnodes()
        
    def _initialize_molecularnodes(self):
        """Initialize MolecularNodes system"""
        # Register all MolecularNodes classes and systems
        
        # Register properties if needed
        '''
        if not hasattr(bpy.types.Scene, "mn"):
            from bpy.utils import register_class
            register_class(MolecularNodesSceneProperties)
            bpy.types.Scene.mn = bpy.props.PointerProperty(type=MolecularNodesSceneProperties)
        '''
        
    def import_from_pdb(self, pdb_id: str, molecule_id: str, style: str = "surface", **kwargs) -> MoleculeWrapper:
        """Import a molecule from PDB"""
        try:
            # Use MolecularNodes fetch functionality
            mol = fetch(
                pdb_code=pdb_id,
                style=style,
                del_solvent=True,  # Default settings, could be made configurable
                build_assembly=False,
                **kwargs
            )
            
            # Create our wrapper object
            wrapper = MoleculeWrapper(mol, molecule_id)
            self.molecules[molecule_id] = wrapper
            
            return wrapper
            
        except Exception as e:
            print(f"Failed to import PDB {pdb_id}: {str(e)}")
            raise
            
    def import_from_file(self, filepath: str, name: Optional[str] = None) -> MoleculeWrapper:
        """Import a molecule from a local file"""
        try:
            mol = load_local(
                file_path=filepath,
                name=name or Path(filepath).stem,
                style="spheres",
                del_solvent=True
            )
            
            identifier = name or Path(filepath).stem
            wrapper = MoleculeWrapper(mol, identifier)
            self.molecules[identifier] = wrapper
            
            return wrapper
            
        except Exception as e:
            print(f"Failed to import file {filepath}: {str(e)}")
            raise
    
    def get_molecule(self, identifier: str) -> Optional[MoleculeWrapper]:
        """Get a molecule by its identifier (PDB ID or name)"""
        return self.molecules.get(identifier) 