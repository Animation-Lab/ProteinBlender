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
from .domain import Domain, DomainDefinition

class MoleculeWrapper:
    """
    Wraps a MolecularNodes molecule and provides additional functionality
    and metadata specific to ProteinBlender
    """
    def __init__(self, molecule: Molecule, identifier: str):
        self.molecule = molecule
        self.identifier = identifier
        self.style = "spheres"  # Default style
        self.domains: Dict[str, DomainDefinition] = {}  # Key: domain_id
        self.residue_assignments = {}  # Track which residues are assigned to domains
        
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

    def create_domain(self, chain_id: Optional[str] = None, start: int = 1, end: int = 9999, name: Optional[str] = None) -> Optional[str]:
        """Create a new domain with default or provided values"""
        # If chain_id is None, select the first available chain
        if chain_id is None:
            # Get chain IDs from the molecule's attributes
            if self.object and "chain_id" in self.object.data.attributes:
                chain_attr = self.object.data.attributes["chain_id"]
                chain_ids = sorted(set(value.value for value in chain_attr.data))
                if chain_ids:
                    chain_id = str(chain_ids[0])
                else:
                    print("No chains found in molecule")
                    return None
            else:
                print("No chain_id attribute found in molecule")
                return None
        
        # Adjust end value based on chain's residue range if needed
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        if mapped_chain in self.chain_residue_ranges:
            min_res, max_res = self.chain_residue_ranges[mapped_chain]
            start = max(min_res, start)
            if end > max_res:
                end = max_res
        
        # Check for overlaps - only if not first domain (initial domains can overlap until configured)
        if self.domains and self._check_domain_overlap(chain_id, start, end):
            print(f"Domain overlap detected for chain {chain_id} ({start}-{end})")
            return None
            
        # Create domain ID
        domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
        
        # Create domain definition
        domain = DomainDefinition(mapped_chain, start, end, name)
        domain.parent_molecule_id = self.identifier
        
        # Create domain object (copy of parent molecule)
        if not domain.create_object_from_parent(self.molecule.object):
            print(f"Failed to create domain object for {domain_id}")
            return None
        
        # Add domain expanded property to object
        domain.object["domain_expanded"] = False
        # Register domain expanded property to be accessible through UI
        bpy.types.Object.domain_expanded = bpy.props.BoolProperty()
        
        # Ensure the domain's node network uses the same structure as the preview domain
        self._setup_domain_network(domain, chain_id, start, end)
        
        # Update residue assignments
        self._update_residue_assignments(domain)
        
        self.domains[domain_id] = domain
        return domain_id
        
    def update_domain(self, domain_id: str, chain_id: str, start: int, end: int) -> bool:
        """Update an existing domain with new parameters"""
        # Check if domain exists
        if domain_id not in self.domains:
            print(f"Domain {domain_id} not found")
            return False
            
        domain = self.domains[domain_id]
        
        # Convert chain_id to the mapping used internally
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        
        # Check if anything changed
        if domain.chain_id == mapped_chain and domain.start == start and domain.end == end:
            print(f"No changes to domain {domain_id}")
            return True
            
        # Store important properties from the existing domain
        is_expanded = getattr(domain.object, "domain_expanded", False)
        loc = rot = scale = None
        if domain.object:
            loc = domain.object.location.copy()
            rot = domain.object.rotation_euler.copy()
            scale = domain.object.scale.copy()
        
        # Create new domain definition with updated parameters
        new_domain = DomainDefinition(mapped_chain, start, end, domain.name)
        new_domain.parent_molecule_id = self.identifier
        
        # Create new domain object
        if not new_domain.create_object_from_parent(self.molecule.object):
            print(f"Failed to create updated domain object for {domain_id}")
            return False
            
        # Restore transforms and properties
        if loc and rot and scale:
            new_domain.object.location = loc
            new_domain.object.rotation_euler = rot
            new_domain.object.scale = scale
        new_domain.object["domain_expanded"] = is_expanded
        
        # Set up domain network with updated parameters
        self._setup_domain_network(new_domain, chain_id, start, end)
        
        # Remove old domain object
        if domain.object:
            bpy.data.objects.remove(domain.object, do_unlink=True)
        
        # Update domain in domains dictionary
        self.domains[domain_id] = new_domain
        
        # Update UI properties to match new domain values for next UI refresh
        new_id = f"{self.identifier}_{chain_id}_{start}_{end}"
        if domain_id != new_id:
            # If the ID would change, update the dictionary key
            self.domains[new_id] = self.domains.pop(domain_id)
            
        return True
        
    def _check_domain_overlap(self, chain_id: str, start: int, end: int, exclude_domain_id: Optional[str] = None) -> bool:
        """Check if proposed domain overlaps with existing domains"""
        for domain_id, domain in self.domains.items():
            # Skip the domain we're updating
            if exclude_domain_id and domain_id == exclude_domain_id:
                continue
                
            if domain.chain_id == chain_id:
                if not (end < domain.start or start > domain.end):
                    return True
        return False
        
    def _update_residue_assignments(self, domain: DomainDefinition):
        """Track which residues are assigned to which domains"""
        for res in range(domain.start, domain.end + 1):
            key = (domain.chain_id, res)
            self.residue_assignments[key] = domain.name

    def delete_domain(self, domain_id: str):
        """Delete a domain and clean up its resources"""
        if domain_id in self.domains:
            domain = self.domains[domain_id]
            # Remove residue assignments
            for res in range(domain.start, domain.end + 1):
                key = (domain.chain_id, res)
                if key in self.residue_assignments:
                    del self.residue_assignments[key]
            # Clean up domain resources
            domain.cleanup()
            # Remove from domains dict
            del self.domains[domain_id]

    def cleanup(self):
        """Clean up all domains and resources"""
        for domain_id in list(self.domains.keys()):
            self.delete_domain(domain_id)

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
        """
        Create the preview domain node setup.
        This is now a stub for backwards compatibility.
        The actual domain node setup is handled by _setup_domain_network.
        """
        # This method is intentionally left as a stub for backwards compatibility
        self.preview_nodes = {
            "select": None,
            "style": None,
            "color": None,
            "set_color": None,
            "chain_select": None,
            "node_group": None
        }

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

    def _setup_domain_network(self, domain: DomainDefinition, chain_id: str, start: int, end: int):
        """Set up the domain's node network using the same structure as the preview domain"""
        if not domain.object or not domain.node_group:
            print("Domain object or node group is missing")
            return False
            
        try:
            # Get references to key nodes
            input_node = nodes.get_input(domain.node_group)
            output_node = nodes.get_output(domain.node_group)
            
            if not (input_node and output_node):
                print("Could not find input/output nodes in domain node group")
                return False
                
            # Create chain selection node
            chain_select = nodes.add_selection(
                group=domain.node_group,
                sel_name="Select Chain",
                input_list=self.chain_mapping.values() or [str(chain_id)],
                field="chain_id"
            )
            chain_select.location = (input_node.location.x + 200, input_node.location.y + 100)
            
            # Set the selected chain
            mapped_chain = self.chain_mapping.get(int(chain_id) if chain_id.isdigit() else chain_id, str(chain_id))
            for input_socket in chain_select.inputs:
                if input_socket.name == mapped_chain:
                    print(f"Setting chain selection for {input_socket.name} to True")
                    input_socket.default_value = True
                else:
                    input_socket.default_value = False
            
            # Create residue range selection node
            select_res_id_range = nodes.add_custom(domain.node_group, "Select Res ID Range")
            select_res_id_range.inputs["Min"].default_value = start
            select_res_id_range.inputs["Max"].default_value = end
            select_res_id_range.location = (chain_select.location.x + 200, chain_select.location.y)
            
            # Create color nodes
            color_emit = nodes.add_custom(domain.node_group, "Color Common")
            color_emit.outputs["Color"].default_value = (1.0, 1.0, 0.0, 1.0)  # Yellow
            color_emit.location = (select_res_id_range.location.x - 400, select_res_id_range.location.y)
            
            set_color = nodes.add_custom(domain.node_group, "Set Color")
            set_color.location = (color_emit.location.x + 200, color_emit.location.y)
            
            # Find or create style node
            style_node = None
            for node in domain.node_group.nodes:
                if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Style" in node.node_tree.name:
                    style_node = node
                    break
                    
            if not style_node:
                # Create style node if not found
                style_node = nodes.add_custom(domain.node_group, "Style Ribbon")
                style_node.location = (select_res_id_range.location.x + 200, select_res_id_range.location.y)
            
            # Find or create join geometry node
            join_node = None
            for node in domain.node_group.nodes:
                if node.bl_idname == "GeometryNodeJoinGeometry":
                    join_node = node
                    break
                    
            if not join_node:
                join_node = domain.node_group.nodes.new("GeometryNodeJoinGeometry")
                join_node.location = (style_node.location.x + 200, style_node.location.y)
            
            # Clear existing links and create new ones
            domain.node_group.links.clear()
            
            # Connect nodes
            domain.node_group.links.new(input_node.outputs["Atoms"], set_color.inputs["Atoms"])
            domain.node_group.links.new(color_emit.outputs["Color"], set_color.inputs["Color"])
            domain.node_group.links.new(set_color.outputs["Atoms"], style_node.inputs["Atoms"])
            domain.node_group.links.new(chain_select.outputs["Selection"], select_res_id_range.inputs["And"])
            domain.node_group.links.new(select_res_id_range.outputs["Selection"], style_node.inputs["Selection"])
            domain.node_group.links.new(style_node.outputs[0], join_node.inputs[0])
            domain.node_group.links.new(join_node.outputs[0], output_node.inputs["Geometry"])
            
            return True
            
        except Exception as e:
            print(f"Error setting up domain network: {str(e)}")
            return False

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