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
        
        # Dictionary to track domain mask nodes in the parent molecule's node group
        self.domain_mask_nodes = {}  # Maps domain_id to tuple(chain_select_node, res_select_node)
        
        # Reference to the join node for domain selections
        self.domain_join_node = None
        
        # Setup the protein domain infrastructure
        self._setup_protein_domain_infrastructure()
        
    def _setup_protein_domain_infrastructure(self):
        """
        Set up the Multi_Boolean_OR and NOT node infrastructure for domains.
        This is called once during initialization of the MoleculeWrapper.
        """
        if not self.molecule.object:
            return
            
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            print("Parent molecule has no valid node group")
            return
            
        parent_node_group = parent_modifier.node_group
        
        try:
            # Find main style node
            main_style_node = self.get_main_style_node()
            if not main_style_node:
                print("Could not find main style node in parent molecule")
                return
                
            # Check and store the original selection connection to the style node
            original_selection_node = None
            original_selection_socket = None
            
            # First, check if there's any connection to the style node's Selection input
            for link in list(main_style_node.inputs["Selection"].links):
                original_selection_node = link.from_node
                original_selection_socket = link.from_socket
                # Don't remove this link yet - we'll do it after creating the infrastructure
                break
                
            # Create multi-input OR node group if it doesn't exist
            multi_or_group = nodes.create_multi_boolean_or()
            
            # Create the join node using our custom group
            self.domain_join_node = parent_node_group.nodes.new("GeometryNodeGroup")
            self.domain_join_node.node_tree = multi_or_group
            self.domain_join_node.location = (main_style_node.location.x - 400, main_style_node.location.y)
            self.domain_join_node.name = "Domain_Boolean_Join"
            
            # Create final NOT node after the join node
            final_not = parent_node_group.nodes.new("FunctionNodeBooleanMath")
            final_not.operation = 'NOT'
            final_not.location = (self.domain_join_node.location.x + 200, self.domain_join_node.location.y)
            final_not.name = "Domain_Final_Not"
            
            # Now that join node is created, handle the original connection
            if original_selection_node:
                # Connect original selection to join node input 1
                parent_node_group.links.new(original_selection_socket, 
                                         self.domain_join_node.inputs["Input_1"])
            
            # Remove ALL existing links to style node's Selection input
            for link in list(main_style_node.inputs["Selection"].links):
                parent_node_group.links.remove(link)
            
            # Connect OR output to NOT input
            parent_node_group.links.new(self.domain_join_node.outputs["Result"], final_not.inputs[0])
            
            # Connect NOT output to style Selection - this should be the ONLY connection to style's Selection
            parent_node_group.links.new(final_not.outputs["Boolean"], main_style_node.inputs["Selection"])
            
            # Ensure style node's Selection is only connected to the final NOT node
            '''
            for link in list(main_style_node.inputs["Selection"].links):
                if link.from_node != final_not:
                    parent_node_group.links.remove(link)
            '''
            
        except Exception as e:
            print(f"Error setting up protein domain infrastructure: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Add this at the end of _setup_protein_domain_infrastructure
        # Ensure style node's Selection is only connected to the final NOT node
        '''
        for link in list(main_style_node.inputs["Selection"].links):
            if link.from_node != final_not:
                parent_node_group.links.remove(link)
        '''
        
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
        # If explicit parameters are provided, use them directly
        if chain_id is not None and start != 1 and end != 9999:
            return self._create_domain_with_params(chain_id, start, end, name)
        
        # Otherwise, find the next available non-overlapping section
        # Get all available chains first
        available_chains = self._get_available_chains()
        if not available_chains:
            # No chains in the molecule
            print("No chains found in molecule")
            return None
        
        # If no chain_id specified, start with the first chain
        if chain_id is None:
            chain_id = available_chains[0]
        
        # Find a non-overlapping section on the current chain
        available_section = self._find_next_available_section(chain_id)
        
        # If no section is available on the current chain, try other chains
        if available_section is None:
            found_section = False
            # Start from the next chain after the current one
            try:
                current_idx = available_chains.index(chain_id)
                chains_to_check = available_chains[current_idx+1:] + available_chains[:current_idx]
            except ValueError:
                # If current chain_id not in available_chains for some reason
                chains_to_check = available_chains
                
            for next_chain in chains_to_check:
                available_section = self._find_next_available_section(next_chain)
                if available_section:
                    chain_id = next_chain
                    found_section = True
                    break
                    
            if not found_section:
                # No available sections on any chain
                # Show a message to the user via Blender's interface
                self._show_message("No available space to create new domains", "Cannot Create Domain", 'ERROR')
                return None
                
        # If we have an available section, use it
        if available_section:
            start, end = available_section
            return self._create_domain_with_params(chain_id, start, end, name)
        
        # This should not happen, but just in case
        print("Could not find suitable section for domain creation")
        return None
        
    def _create_domain_with_params(self, chain_id: str, start: int, end: int, name: Optional[str] = None) -> Optional[str]:
        """Internal method to create a domain with specific parameters"""
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
        
        # Create mask nodes in the parent molecule to hide this domain region
        self._create_domain_mask_nodes(domain_id, chain_id, start, end)
        
        self.domains[domain_id] = domain
        return domain_id
        
    def _find_next_available_section(self, chain_id: str) -> Optional[tuple]:
        """Find the next available non-overlapping section in a chain"""
        # Get chain mapping
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        
        # Get chain residue range
        if mapped_chain not in self.chain_residue_ranges:
            print(f"Chain {mapped_chain} not found in residue ranges")
            return None
            
        min_res, max_res = self.chain_residue_ranges[mapped_chain]
        
        # Get all domains on this chain
        chain_domains = []
        for domain_id, domain in self.domains.items():
            if domain.chain_id == mapped_chain:
                chain_domains.append((domain.start, domain.end))
                
        # Sort domains by start position
        chain_domains.sort()
        
        # If no domains on this chain, return the full chain range
        if not chain_domains:
            # Default domain size (30 residues or the full chain if smaller)
            domain_size = min(30, max_res - min_res + 1)
            return (min_res, min_res + domain_size - 1)
            
        # Find gaps between domains
        current_pos = min_res
        for start, end in chain_domains:
            if current_pos < start:
                # Found a gap
                gap_size = start - current_pos
                # If gap is large enough for a sensible domain (at least 5 residues)
                if gap_size >= 5:
                    # Default domain size (30 residues or the available gap if smaller)
                    domain_size = min(30, gap_size)
                    return (current_pos, current_pos + domain_size - 1)
            # Move current position to after this domain
            current_pos = max(current_pos, end + 1)
            
        # Check if there's space after the last domain
        if current_pos <= max_res:
            remaining = max_res - current_pos + 1
            # If remaining space is large enough for a sensible domain
            if remaining >= 5:
                # Default domain size (30 residues or the remaining space if smaller)
                domain_size = min(30, remaining)
                return (current_pos, current_pos + domain_size - 1)
                
        # No suitable gap found
        return None
        
    def _get_available_chains(self) -> List[str]:
        """Get list of all available chains in the molecule"""
        available_chains = []
        if not self.object or "chain_id" not in self.object.data.attributes:
            return available_chains
            
        # Get chain attribute
        chain_attr = self.object.data.attributes["chain_id"]
        numeric_chain_ids = sorted({value.value for value in chain_attr.data})
        
        # Convert to strings and apply mapping if available
        for chain_id in numeric_chain_ids:
            mapped_chain = self.get_author_chain_id(chain_id)
            # Use numeric ID as string if no mapping
            available_chains.append(str(chain_id))
            
        return available_chains
        
    def _show_message(self, message: str, title: str = "Message", icon: str = 'INFO'):
        """Show a message to the user via Blender's interface"""
        def draw(self, context):
            self.layout.label(text=message)
            
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

    def update_domain(self, domain_id: str, chain_id: str, start: int, end: int) -> bool:
        """Update an existing domain with new parameters"""
        # Check if domain exists
        if domain_id not in self.domains:
            print(f"Domain {domain_id} not found")
            return False
            
        # Get the domain
        domain = self.domains[domain_id]
        old_chain_id = domain.chain_id
        old_start = domain.start
        old_end = domain.end
        
        # Check if the new definition overlaps with other domains
        if self._check_domain_overlap(chain_id, start, end, exclude_domain_id=domain_id):
            print(f"Domain overlap detected for chain {chain_id} ({start}-{end})")
            return False
            
        try:
            # Map chain ID if needed
            chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
            mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
            
            # Check if we're actually changing anything
            if domain.chain_id == mapped_chain and domain.start == start and domain.end == end:
                # No changes needed
                return True
                
            # Create new domain ID based on new parameters
            new_domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
            
            # Delete the old mask nodes
            self._delete_domain_mask_nodes(domain_id)
            
            # Update domain fields
            domain.chain_id = mapped_chain
            domain.start = start
            domain.end = end
            
            # Update node network
            if domain.object and domain.node_group:
                # Find chain selection node and update it
                chain_select = None
                for node in domain.node_group.nodes:
                    if (node.bl_idname == 'GeometryNodeGroup' and 
                        node.node_tree and 
                        node.node_tree.name == "Select Chain"):
                        chain_select = node
                        break
                        
                if chain_select:
                    # Update chain selection
                    for input_socket in chain_select.inputs:
                        # Skip non-boolean inputs
                        if input_socket.type != 'BOOLEAN':
                            continue
                        if input_socket.name == mapped_chain:
                            input_socket.default_value = True
                        else:
                            input_socket.default_value = False
                            
                # Find residue range node and update it
                res_select = None
                for node in domain.node_group.nodes:
                    if (node.bl_idname == 'GeometryNodeGroup' and 
                        node.node_tree and 
                        node.node_tree.name == "Select Res ID Range"):
                        res_select = node
                        break
                        
                if res_select:
                    # Update residue range
                    res_select.inputs["Min"].default_value = start
                    res_select.inputs["Max"].default_value = end
                
            # Create new mask nodes in parent with updated parameters
            self._create_domain_mask_nodes(new_domain_id, chain_id, start, end)
            
            # If the domain ID has changed, update the dictionary
            if domain_id != new_domain_id:
                # Store domain under new ID
                self.domains[new_domain_id] = domain
                # Remove old ID entry
                del self.domains[domain_id]
                # Return the new domain ID
                return True
            
            return True
            
        except Exception as e:
            print(f"Error updating domain: {str(e)}")
            return False

    def _delete_domain_mask_nodes(self, domain_id: str):
        """Delete mask nodes for a domain in the parent molecule's node group"""
        if domain_id not in self.domain_mask_nodes:
            return
            
        nodes_to_remove = self.domain_mask_nodes[domain_id]
        
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            return
            
        parent_node_group = parent_modifier.node_group
        
        # Remove only the links connected to these specific nodes
        for link in list(parent_node_group.links):
            for node in nodes_to_remove:
                if link.from_node == node or link.to_node == node:
                    parent_node_group.links.remove(link)
                    break
        
        # Remove the nodes
        for node in nodes_to_remove:
            if node:
                parent_node_group.nodes.remove(node)
            
        # Remove from tracking dictionary
        del self.domain_mask_nodes[domain_id]
        
        # Note: We're no longer removing the domain infrastructure nodes (join node and NOT node)
        # when all domains are deleted. They will persist for future domain creations.

    def delete_domain(self, domain_id: str):
        """Delete a domain and its object"""
        if domain_id not in self.domains:
            return
            
        # Delete domain mask nodes in parent molecule
        self._delete_domain_mask_nodes(domain_id)
        
        # Clean up domain object and node group
        self.domains[domain_id].cleanup()
        
        # Remove from domains dictionary
        del self.domains[domain_id]

    def cleanup(self):
        """Remove all domains and clean up resources"""
        for domain_id in list(self.domains.keys()):
            self.delete_domain(domain_id)
            
    def get_main_style_node(self):
        """Get the main style node of the parent molecule"""
        if not self.molecule.object:
            return None
            
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            return None
            
        parent_node_group = parent_modifier.node_group
        
        # Find style node
        try:
            return nodes.style_node(parent_node_group)
        except:
            # Fallback to manual search
            for node in parent_node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    "Style" in node.node_tree.name):
                    return node
                    
        return None

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
                
            # Find or create nodes - reuse existing when possible
            # First check existing nodes before creating new ones
            
            # Look for chain selection node
            chain_select = None
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    node.node_tree.name == "Select Chain"):
                    chain_select = node
                    break
                    
            if not chain_select:
                # Create chain selection node if not found - but don't use nodes.add_selection
                # as it automatically connects to the style node
                chain_select_group = nodes.custom_iswitch(
                    name="selection", 
                    iter_list=self.chain_mapping.values() or [str(chain_id)], 
                    field="chain_id", 
                    dtype="BOOLEAN"
                )
                
                chain_select = nodes.add_custom(
                    domain.node_group,
                    chain_select_group.name
                )
                chain_select.name = "Select Chain"
                chain_select.location = (input_node.location.x + 200, input_node.location.y + 100)
            
            # Set the selected chain
            mapped_chain = self.chain_mapping.get(int(chain_id) if chain_id.isdigit() else chain_id, str(chain_id))
            for input_socket in chain_select.inputs:
                # Skip non-boolean inputs (like group inputs)
                if input_socket.type != 'BOOLEAN':
                    continue
                if input_socket.name == mapped_chain:
                    input_socket.default_value = True
                else:
                    input_socket.default_value = False
            
            # Look for residue range selection node
            select_res_id_range = None
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    node.node_tree.name == "Select Res ID Range"):
                    select_res_id_range = node
                    break
                    
            if not select_res_id_range:
                # Create residue range selection node if not found
                select_res_id_range = nodes.add_custom(domain.node_group, "Select Res ID Range")
                select_res_id_range.location = (chain_select.location.x + 200, chain_select.location.y)
            
            # Update the residue range
            select_res_id_range.inputs["Min"].default_value = start
            select_res_id_range.inputs["Max"].default_value = end
            
            # Look for color nodes
            color_emit = None
            set_color = None
            
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    node.node_tree.name == "Color Common"):
                    color_emit = node
                elif (node.bl_idname == 'GeometryNodeGroup' and 
                      node.node_tree and 
                      node.node_tree.name == "Set Color"):
                    set_color = node
            
            # Create color nodes if not found
            if not color_emit:
                color_emit = nodes.add_custom(domain.node_group, "Color Common")
                color_emit.outputs["Color"].default_value = (1.0, 1.0, 0.0, 1.0)  # Yellow
                color_emit.location = (select_res_id_range.location.x - 400, select_res_id_range.location.y)
            
            if not set_color:
                set_color = nodes.add_custom(domain.node_group, "Set Color")
                set_color.location = (color_emit.location.x + 200, color_emit.location.y)
            
            # Find or create style node
            style_node = None
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    "Style" in node.node_tree.name):
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
            
            # Connect the residue selection to the style node's Selection input
            domain.node_group.links.new(select_res_id_range.outputs["Selection"], style_node.inputs["Selection"])
            
            domain.node_group.links.new(style_node.outputs[0], join_node.inputs[0])
            domain.node_group.links.new(join_node.outputs[0], output_node.inputs["Geometry"])
            
            # Remove any orphaned or duplicate nodes
            self._clean_unused_nodes(domain.node_group)
            
            # Check for and remove any unwanted connections in the parent molecule's node group
            # Get the parent molecule's node group
            parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
            if parent_modifier and parent_modifier.node_group:
                parent_node_group = parent_modifier.node_group
                main_style_node = self.get_main_style_node()
                
                if main_style_node:
                    # Remove any direct connections between domain's chain selection and parent's style node
                    for link in list(parent_node_group.links):
                        if (link.from_node.name == chain_select.name and 
                            link.to_node == main_style_node and 
                            link.to_socket.name == "Selection"):
                            parent_node_group.links.remove(link)
            
            return True
            
        except Exception as e:
            print(f"Error setting up domain network: {str(e)}")
            return False
    
    def _clean_unused_nodes(self, node_group):
        """Remove any unused or orphaned nodes from the node group"""
        # Get all linked nodes starting from the output
        output_node = nodes.get_output(node_group)
        if not output_node:
            return
        
        linked_nodes = set()
        nodes_to_check = [output_node]
        
        # Traverse the node tree backwards to find all connected nodes
        while nodes_to_check:
            current = nodes_to_check.pop()
            linked_nodes.add(current)
            
            # Check all input sockets for connections
            for input_socket in current.inputs:
                for link in input_socket.links:
                    if link.from_node not in linked_nodes:
                        nodes_to_check.append(link.from_node)
        
        # Remove nodes that aren't linked to the output
        for node in list(node_group.nodes):
            if node not in linked_nodes:
                # Some nodes might be special system nodes we shouldn't remove
                if node.bl_idname != 'NodeGroupInput' and node.bl_idname != 'NodeGroupOutput':
                    node_group.nodes.remove(node)

    def _create_domain_mask_nodes(self, domain_id: str, chain_id: str, start: int, end: int):
        """Create nodes in the parent molecule to mask out the domain region"""
        if not self.molecule.object:
            return
        
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            print("Parent molecule has no valid node group")
            return
            
        parent_node_group = parent_modifier.node_group
        
        try:
            # Find main style node
            main_style_node = self.get_main_style_node()
            if not main_style_node:
                print("Could not find main style node in parent molecule")
                return
            
            # Check if domain infrastructure is set up
            if self.domain_join_node is None:
                print("Domain infrastructure not set up. Call _setup_protein_domain_infrastructure first.")
                return
                
            # Step 1: Create and configure chain selection node
            chain_select_name = f"Domain_Chain_Select_{domain_id}"
            chain_select = None
            for node in parent_node_group.nodes:
                if node.name == chain_select_name:
                    chain_select = node
                    break
                    
            if not chain_select:
                # Create chain selection node - but don't use nodes.add_selection directly
                # as it automatically connects to the style node
                chain_select_group = nodes.custom_iswitch(
                    name="selection", 
                    iter_list=self.chain_mapping.values() or [str(chain_id)], 
                    field="chain_id", 
                    dtype="BOOLEAN"
                )
                
                chain_select = nodes.add_custom(
                    parent_node_group,
                    chain_select_group.name
                )
                
                # Position to the left of the join node
                chain_select.location = (self.domain_join_node.location.x - 600, 
                                      self.domain_join_node.location.y - 100 - len(self.domain_mask_nodes) * 100)
                chain_select.name = chain_select_name
            
            # Step 2: Configure chain selection
            mapped_chain = self.chain_mapping.get(int(chain_id) if chain_id.isdigit() else chain_id, str(chain_id))
            for input_socket in chain_select.inputs:
                # Skip non-boolean inputs (like group inputs)
                if input_socket.type != 'BOOLEAN':
                    continue
                if input_socket.name == mapped_chain:
                    input_socket.default_value = True
                else:
                    input_socket.default_value = False
            
            # Step 3: Create residue range selection node
            res_select_name = f"Domain_Res_Select_{domain_id}"
            res_select = None
            for node in parent_node_group.nodes:
                if node.name == res_select_name:
                    res_select = node
                    break
                    
            if not res_select:
                # Create residue range selection node
                res_select = nodes.add_custom(parent_node_group, "Select Res ID Range")
                res_select.location = (chain_select.location.x + 200, chain_select.location.y)
                res_select.name = res_select_name
            
            # Update the residue range
            res_select.inputs["Min"].default_value = start
            res_select.inputs["Max"].default_value = end
            
            # Step 4: Connect chain select to res select
            # First remove any existing connections to res_select's "And" input
            for link in list(res_select.inputs["And"].links):
                parent_node_group.links.remove(link)
                
            # Connect chain select to res select
            parent_node_group.links.new(chain_select.outputs["Selection"], res_select.inputs["And"])
            
            # Step 5: Find next available input on join node
            available_input = None
            for i in range(1, 9):  # Check inputs 1-8
                input_name = f"Input_{i}"
                if input_name in self.domain_join_node.inputs and not self.domain_join_node.inputs[input_name].is_linked:
                    available_input = input_name
                    break
            
            if available_input is None:
                print(f"Warning: No available inputs in multi-input OR node for domain {domain_id}")
                return
            
            # Step 6: Connect residue selection to join node
            # First remove any existing connections to this input
            if self.domain_join_node.inputs[available_input].is_linked:
                for link in list(self.domain_join_node.inputs[available_input].links):
                    parent_node_group.links.remove(link)
                    
            # Connect residue selection output to join node input
            parent_node_group.links.new(res_select.outputs["Selection"], 
                                     self.domain_join_node.inputs[available_input])
            
            # Store the nodes for future reference
            self.domain_mask_nodes[domain_id] = (chain_select, res_select)
            
            # Remove any direct connections between chain selection and style node
            for link in list(parent_node_group.links):
                if (link.from_node == chain_select and 
                    link.to_node == main_style_node and 
                    link.to_socket.name == "Selection"):
                    parent_node_group.links.remove(link)
            
        except Exception as e:
            print(f"Error creating domain mask nodes: {str(e)}")
            import traceback
            traceback.print_exc()

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