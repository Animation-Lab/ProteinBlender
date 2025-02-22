from typing import Optional, Dict, List
import bpy
from pathlib import Path
import numpy as np

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
        self.select_protein_chain= "NONE"
        # Store the chain mapping if available
        self.chain_mapping = {}
        if hasattr(molecule.array, 'chain_mapping_str'):
            self.chain_mapping = self._parse_chain_mapping(molecule.array.chain_mapping_str)
        
        # Initialize chain residue ranges
        self.chain_residue_ranges = self._get_chain_residue_ranges()
        
        # Add after existing initialization
        self.preview_nodes = None
        self._setup_preview_domain()
        
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
            
            # Get chain attribute data
            chain_attr = self.object.data.attributes["chain_id"]
            numeric_chain_ids = sorted({value.value for value in chain_attr.data})
            print(f"Numeric chain IDs: {numeric_chain_ids}")
            
            # Get chain mapping if available
            mapping_str = self.object.data.get("chain_mapping_str", "")
            print(f"Chain mapping string: {mapping_str}")
            chain_mapping = {}
            if mapping_str:
                for pair in mapping_str.split(","):
                    if ":" in pair:
                        k, v = pair.split(":")
                        chain_mapping[int(k)] = v
            print(f"Chain mapping dict: {chain_mapping}")
            
            # Map numeric IDs to author chain IDs
            mapped_chains = {}
            for chain_id in numeric_chain_ids:
                mapped_chain_id = chain_mapping.get(chain_id, str(chain_id))
                mapped_chains[str(mapped_chain_id)] = chain_id
            print(f"Mapped chains: {mapped_chains}")

    def add_domain(self, chain_id: str, start: int, end: int, name: Optional[str] = None) -> None:
        """Add a new domain to the molecule"""
        # Map the chain_id to author chain ID if mapping exists
        display_chain_id = self.chain_mapping.get(int(chain_id), chain_id) if self.chain_mapping else chain_id
        print(f"Adding domain: {display_chain_id}, {start}, {end}, {name}")
        
        # Create domain for node management
        scene = bpy.context.scene
        for item in scene.molecule_list_items:
            if item.identifier == self.identifier:
                # Create new domain through the collection property
                new_domain = item.domains.add()
                new_domain.chain_id = display_chain_id  # Use the mapped chain ID
                new_domain.start = start
                new_domain.end = end
                new_domain.name = name if name else ""
                break
        
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
            base_y_offset = -300 * (len(item.domains) + 1)
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

    def _parse_chain_mapping(self, mapping_str: str) -> dict:
        """Parse chain mapping string into a dictionary"""
        mapping = {}
        if mapping_str:
            for pair in mapping_str.split(","):
                if ":" in pair:
                    k, v = pair.split(":")
                    mapping[int(k)] = v
        return mapping

    def _get_chain_residue_ranges(self) -> Dict[str, Dict[str, tuple]]:
        """Get residue ranges for each chain
        Returns:
            Dict with structure:
            {
                'A': (1, 300),
                'B': (301, 511)
                ...
            }
        """
        ranges = {}
        if not self.object or "chain_id" not in self.object.data.attributes:
            return ranges
        
        # Get chain and residue attributes
        chain_attr = self.object.data.attributes["chain_id"]
        res_attr = self.object.data.attributes["res_id"]
        
        # Convert to numpy arrays for easier processing
        chain_ids = np.array([v.value for v in chain_attr.data])
        res_ids = np.array([v.value for v in res_attr.data])
        
        # Get unique chain IDs
        unique_chains = np.unique(chain_ids)
        
        
        for chain_id in unique_chains:
            # Get mask for current chain
            chain_mask = chain_ids == chain_id
            
            # Get residue IDs for this chain
            chain_res_ids = res_ids[chain_mask]
            # Get min and max residue IDs
            min_res = np.min(chain_res_ids)
            max_res = np.max(chain_res_ids)
            
            # Use chain mapping if available
            mapped_chain_id = str(chain_id)
            if self.chain_mapping:
                mapped_chain_id = self.chain_mapping.get(chain_id, str(chain_id))
            
            # Store chain ranges
            ranges[mapped_chain_id] = (min_res, max_res)
            
        return ranges

    def get_author_chain_id(self, numeric_chain_id: int) -> str:
        """Convert numeric chain ID to author chain ID
        
        Args:
            numeric_chain_id (int): The numeric chain ID to convert
            
        Returns:
            str: The author chain ID if found, otherwise the numeric chain ID as string
        """
        if self.chain_mapping:
            return self.chain_mapping.get(numeric_chain_id, str(numeric_chain_id))
        return str(numeric_chain_id)

    def _setup_preview_domain(self):
        """Create the preview domain node setup"""
        if not self.object or not self.object.modifiers.get("MolecularNodes"):
            return
            
        gn_mod = self.object.modifiers["MolecularNodes"]
        node_group = gn_mod.node_group
        
        # Get existing nodes
        group_input = nodes.get_input(node_group)
        group_output = nodes.get_output(node_group)
        molecule_style_node = nodes.style_node(node_group)
        
        # Find or create Join Geometry node
        join_node = None
        for node in node_group.nodes:
            if node.bl_idname == "GeometryNodeJoinGeometry":
                join_node = node
                break
        
        if join_node is None:
            # Create Join Geometry node
            join_node = node_group.nodes.new("GeometryNodeJoinGeometry")
            join_node.location = (molecule_style_node.location[0] + 200, molecule_style_node.location[1])
            
            # Connect style to join
            node_group.links.new(molecule_style_node.outputs[0], join_node.inputs[0])
            # Connect join to output
            node_group.links.new(join_node.outputs[0], group_output.inputs[0])
        
        # Create preview nodes
        color_emit = nodes.add_custom(node_group, "Color Common")
        color_emit.outputs["Color"].default_value = (1.0, 1.0, 0.0, 1.0)  # Yellow
        
        set_color = nodes.add_custom(node_group, "Set Color")
        select_res_id_range_node = nodes.add_custom(node_group, "Select Res ID Range")
        default_domain_style_node = nodes.add_custom(node_group, "Style Ribbon")
        # Add this near the start of _setup_preview_domain
        scene = bpy.context.scene
        for item in scene.molecule_list_items:
            if item.identifier == self.identifier:
                selected_chain = item.selected_chain_for_domain
                break
        else:
            selected_chain = "A"
        # Add a Select Chain node
        select_chain_node = nodes.add_selection(group=node_group,
                                       sel_name="Select Chain",
                                       input_list=self.chain_mapping.values(),
                                       field="chain_id")
        nodes.set_selection(node_group, molecule_style_node, select_chain_node)
        
        # Position nodes
        base_y_offset = -500
        style_pos = molecule_style_node.location
        color_emit.location = (style_pos[0] - 600, style_pos[1] + base_y_offset)
        set_color.location = (style_pos[0] - 400, style_pos[1] + base_y_offset)
        select_res_id_range_node.location = (style_pos[0] - 200, style_pos[1] + base_y_offset)
        default_domain_style_node.location = (style_pos[0], style_pos[1] + base_y_offset)
        
        # Connect preview nodes
        node_group.links.new(color_emit.outputs["Color"], set_color.inputs["Color"])
        node_group.links.new(group_input.outputs["Atoms"], set_color.inputs["Atoms"])
        node_group.links.new(set_color.outputs["Atoms"], default_domain_style_node.inputs["Atoms"])
        node_group.links.new(select_res_id_range_node.outputs["Selection"], default_domain_style_node.inputs["Selection"])
        node_group.links.new(default_domain_style_node.outputs[0], join_node.inputs[0])
        node_group.links.new(select_res_id_range_node.outputs["Selection"], select_chain_node.inputs[selected_chain])
        
        # Get the main style node and ensure proper connections
        #style_node = nodes.style_node(node_group)

        # Connect chain selection outputs
        node_group.links.new(select_chain_node.outputs["Selection"], default_domain_style_node.inputs["Selection"])
        node_group.links.new(select_chain_node.outputs["Inverted"], molecule_style_node.inputs["Selection"])

        # Store references to preview nodes
        self.preview_nodes = {
            "select": select_res_id_range_node,
            "style": default_domain_style_node,
            "color": color_emit,
            "set_color": set_color,
            "chain_select": select_chain_node,
            "node_group": node_group
        }
        
        # Initially disable preview
        #self.set_preview_visibility(False)
        selected_chain_id = 0
        for key, value in self.chain_mapping.items():
            if value == selected_chain:
                selected_chain_id = key
                break
        self.update_preview_range(selected_chain_id, self.chain_residue_ranges[selected_chain][0], self.chain_residue_ranges[selected_chain][1])
        
    def set_preview_visibility(self, visible: bool):
        """Toggle visibility of the preview domain"""
        if not self.preview_nodes:
            return
            
        self.preview_nodes["style"].mute = not visible
        self.preview_nodes["color"].mute = not visible
        self.preview_nodes["set_color"].mute = not visible
        self.preview_nodes["select"].mute = not visible
        
    def update_preview_range(self, chain_id: int, start: int, end: int):
        """Update the preview domain range and chain selection"""
        if not self.preview_nodes:
            return
        
        # Update residue range
        select_node = self.preview_nodes["select"]
        chain_select_node = self.preview_nodes["chain_select"]
        node_group = self.preview_nodes["node_group"]
        
        select_node.inputs["Min"].default_value = start
        select_node.inputs["Max"].default_value = end
        # Update chain selection
        chain_select_node = self.preview_nodes["chain_select"]
        if chain_select_node:
            # First, disconnect all chain inputs
            for input_socket in chain_select_node.inputs:
                if input_socket.is_linked:
                    for link in input_socket.links:
                        chain_select_node.id_data.links.remove(link)
            
            # Get the author chain ID if mapping exists
            display_chain_id = self.chain_mapping.get(int(chain_id), chain_id) if self.chain_mapping else chain_id

            # Connect the selected chain
            if display_chain_id in chain_select_node.inputs:
                for input_socket in chain_select_node.inputs:
                    input_socket.default_value = False
                chain_select_node.inputs[display_chain_id].default_value = True
                node_group.links.new(select_node.outputs["Selection"], chain_select_node.inputs[display_chain_id])

    def get_main_style_node(self):
        """Get the main style node for the molecule"""
        if not self.object:
            return None
        
        gn_mod = self.object.modifiers.get("MolecularNodes")
        if not gn_mod or not gn_mod.node_group:
            return None
        
        return nodes.style_node(gn_mod.node_group)

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