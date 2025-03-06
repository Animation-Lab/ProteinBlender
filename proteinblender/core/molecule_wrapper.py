from typing import Optional, Dict, List, Tuple
import bpy
import numpy as np
import colorsys
import random

from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..utils.molecularnodes.blender import nodes
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
        
    @property
    def object(self) -> bpy.types.Object:
        """Get the Blender object for this molecule"""
        return self.molecule.object
        
    def to_json(self):
        """
        Serialize the molecule wrapper to a JSON-compatible dictionary
        This is used for saving state or transferring data
        """
        # Create base dictionary with essential properties
        data = {
            "identifier": self.identifier,
            "style": self.style,
            # Add other serializable properties 
            "domains": {}
        }
        
        # Add domain information
        for domain_id, domain in self.domains.items():
            data["domains"][domain_id] = {
                "chain_id": domain.chain_id,
                "start": domain.start,
                "end": domain.end,
                "name": domain.name
            }
            
        return data 

    def _setup_protein_domain_infrastructure(self):
        """
        Set up the infrastructure for protein domains in the parent molecule's node group
        This creates the necessary nodes for domain selection and masking
        """
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            print("Parent molecule does not have a valid MolecularNodes modifier")
            return
            
        parent_node_group = parent_modifier.node_group
        
        # Check if we already have a domain join node
        join_node_name = f"Domain_Join_{self.identifier}"
        for node in parent_node_group.nodes:
            if node.name == join_node_name:
                self.domain_join_node = node
                return
                
        # Create a join node for all domain selections
        self.domain_join_node = parent_node_group.nodes.new('GeometryNodeJoinGeometry')
        self.domain_join_node.name = join_node_name
        
        # Position it to the right of the style node
        style_node = self.get_main_style_node()
        if style_node:
            self.domain_join_node.location = (style_node.location.x + 300, style_node.location.y)
            
            # Connect the style node to the join node
            parent_node_group.links.new(style_node.outputs[0], self.domain_join_node.inputs[0])
            
            # Connect the join node to the group output
            for node in parent_node_group.nodes:
                if node.bl_idname == 'NodeGroupOutput':
                    parent_node_group.links.new(self.domain_join_node.outputs[0], node.inputs[0])
                    break 

    def change_style(self, new_style: str) -> None:
        """Change the visualization style of the molecule"""
        if not self.molecule.object:
            return
            
        # Get the style node
        style_node = self.get_main_style_node()
        if not style_node:
            return
            
        # Update style
        if "Style" in style_node.inputs:
            style_node.inputs["Style"].default_value = new_style
            self.style = new_style
    
    def select_chains(self, chain_ids):
        """Select specific chains in the molecule"""
        if not self.molecule.object:
            return
            
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            return
            
        parent_node_group = parent_modifier.node_group
        
        # Find chain selection node
        chain_select = None
        for node in parent_node_group.nodes:
            if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Chain" in node.node_tree.name:
                chain_select = node
                break
                
        if not chain_select:
            return
            
        # Update chain selection
        for input_socket in chain_select.inputs:
            if input_socket.type != 'BOOLEAN':
                continue
                
            # Check if this chain should be selected
            chain_id = input_socket.name
            input_socket.default_value = chain_id in chain_ids
    
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

    def create_domain(self, chain_id: Optional[str] = None, start: int = 1, end: int = 9999, name: Optional[str] = None) -> Optional[str]:
        """Create a new domain with specified parameters or defaults
        
        Args:
            chain_id: Chain identifier (will use first available if None)
            start: Starting residue number
            end: Ending residue number
            name: Optional domain name (will generate one if None)
            
        Returns:
            Domain ID string if successful, None if failed
        """
        # Basic validation of molecule and chains
        if not self._validate_domain_prerequisites():
            return None
            
        # Determine and validate chain ID
        chain_id, mapped_chain = self._resolve_domain_chain(chain_id)
        if not mapped_chain:
            return None
            
        # Adjust range to valid values for this chain
        start, end = self._normalize_domain_range(mapped_chain, start, end)
        
        # Check for conflicts with existing domains
        if not self._handle_domain_overlaps(chain_id, start, end):
            return None
        
        # Create the domain object
        domain_id = self._create_domain_object(chain_id, mapped_chain, start, end, name)
        if not domain_id:
            return None
            
        return domain_id
    
    def _validate_domain_prerequisites(self) -> bool:
        """Validate basic requirements for domain creation"""
        # Check if we have a valid object
        if not self.molecule.object:
            self._show_message("No valid molecule object found", "Cannot Create Domain", 'ERROR')
            return False
            
        # Check if there are any chains available
        if not self._get_available_chains():
            self._show_message("No chains found in molecule", "Cannot Create Domain", 'ERROR')
            return False
            
        # Check if we have residue ranges
        if not self.chain_residue_ranges:
            self._show_message("No residue data found for chains", "Cannot Create Domain", 'ERROR')
            return False
            
        return True
    
    def _resolve_domain_chain(self, chain_id: Optional[str]) -> Tuple[str, Optional[str]]:
        """Resolve chain ID to a valid mapped chain
        
        Args:
            chain_id: Original chain ID or None to use first available
            
        Returns:
            Tuple of (original_chain_id, mapped_chain_id)
        """
        available_chains = self._get_available_chains()
        
        # If no chain_id specified, use the first available chain
        if chain_id is None:
            chain_id = available_chains[0]
            print(f"No chain specified, using first available chain: {chain_id}")
        
        # Determine the mapped chain
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        
        # Check if the mapped chain has residue ranges
        if mapped_chain not in self.chain_residue_ranges:
            # Try using the original chain ID
            if str(chain_id) in self.chain_residue_ranges:
                mapped_chain = str(chain_id)
            else:
                # Try to find a chain that exists in the residue ranges
                print(f"Chain {mapped_chain} not found in residue ranges. Available: {list(self.chain_residue_ranges.keys())}")
                for c in self.chain_residue_ranges.keys():
                    mapped_chain = c
                    print(f"Using alternative chain: {mapped_chain}")
                    break
        
        # Ensure we have a valid residue range
        if mapped_chain not in self.chain_residue_ranges:
            self._show_message(f"No residue range found for chain {mapped_chain}", "Cannot Create Domain", 'ERROR')
            return chain_id, None
            
        return chain_id, mapped_chain
    
    def _normalize_domain_range(self, mapped_chain: str, start: int, end: int) -> Tuple[int, int]:
        """Normalize start and end values to valid range for the chain
        
        Args:
            mapped_chain: The mapped chain ID
            start: Initial start value
            end: Initial end value
            
        Returns:
            Tuple of (normalized_start, normalized_end)
        """
        # Get the valid residue range for this chain
        min_res, max_res = self.chain_residue_ranges[mapped_chain]
        
        # If default values were provided, use the full chain range
        if start == 1 and end == 9999:
            start = min_res
            end = max_res
            print(f"Using full chain range: {start}-{end}")
        else:
            # Make sure start/end are within valid range for this chain
            original_start, original_end = start, end
            start = max(min_res, start)
            end = min(max_res, end)
            
            if original_start != start or original_end != end:
                print(f"Adjusting range from {original_start}-{original_end} to valid range {start}-{end}")
        
        return start, end
    
    def _handle_domain_overlaps(self, chain_id: str, start: int, end: int) -> bool:
        """Handle potential overlaps with existing domains
        
        Args:
            chain_id: The chain ID
            start: Start residue
            end: End residue
            
        Returns:
            True if domain can be created, False if cannot handle overlaps
        """
        # If no domains or no overlap, we're good to go (this should be the most common case)
        if not self.domains or not self._check_domain_overlap(chain_id, start, end):
            print(f"No domain overlap, using range {start}-{end}")
            return True
            
        print(f"Domain overlaps with existing domain. Attempting to find available space.")
        
        # Store original values before adjustment
        original_start, original_end = start, end
        available_chains = self._get_available_chains()
        min_res, max_res = self.chain_residue_ranges[self.get_author_chain_id(int(chain_id) if chain_id.isdigit() else chain_id)]
        
        # Only handle overlaps if there are actual domains
        if len(self.domains) > 0:
            # For second domain, use area not covered by first domain
            existing_domain = next(iter(self.domains.values()))
            if existing_domain.end < max_res:
                start = existing_domain.end + 1
                print(f"Second domain: Adjusting range to {start}-{end}")
                return True
            else:
                # If existing domain covers the end, use the beginning
                end = existing_domain.start - 1
                print(f"Second domain: Adjusting range to {start}-{end}")
                return True
        
        # Case 2: For third+ domain, find any available gap
        available_section = self._find_next_available_section(chain_id)
        if available_section:
            start, end = available_section
            print(f"Found available section: {start}-{end}")
            return True
            
        # Case 3: Try other chains if this one is full
        for next_chain in available_chains:
            if next_chain != chain_id:
                available_section = self._find_next_available_section(next_chain)
                if available_section:
                    # Change to use the new chain
                    chain_id = next_chain
                    start, end = available_section
                    print(f"Found available section on chain {chain_id}: {start}-{end}")
                    return True
        
        # No suitable space found
        message = f"Cannot create domain with range {original_start}-{original_end} due to overlaps."
        self._show_message(message, "Cannot Create Domain", 'ERROR')
        return False
    
    def _create_domain_object(self, chain_id: str, mapped_chain: str, start: int, end: int, 
                             name: Optional[str] = None) -> Optional[str]:
        """Create the domain object with the specified parameters
        
        Args:
            chain_id: Original chain ID
            mapped_chain: Mapped chain ID
            start: Start residue
            end: End residue
            name: Optional name
            
        Returns:
            Domain ID if successful, None if failed
        """
        # Create domain ID
        domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
        
        # Create domain definition
        domain = DomainDefinition(mapped_chain, start, end, name)
        domain.parent_molecule_id = self.identifier
        domain.domain_id = domain_id
        
        # Create domain object (copy of parent molecule)
        if not domain.create_object_from_parent(self.molecule.object):
            print(f"Failed to create domain object for {domain_id}")
            return None
        
        # Add domain expanded property to object
        domain.object["domain_expanded"] = False
        
        # Ensure the property exists
        if not hasattr(bpy.types.Object, "domain_expanded"):
            bpy.types.Object.domain_expanded = bpy.props.BoolProperty()
            
        # Set domain color property for UI
        domain.color = (0.8, 0.1, 0.8, 1.0)  # Default purple
        
        # Ensure the domain's node network uses the same structure as the preview domain
        self._setup_domain_network(domain, chain_id, start, end)
        
        # Update residue assignments
        self._update_residue_assignments(domain)
        
        # Create mask nodes in the parent molecule to hide this domain region
        self._create_domain_mask_nodes(domain_id, chain_id, start, end)
        
        # Store the domain
        self.domains[domain_id] = domain
        
        # Store domain properties for internal usage - this can be used to transition to the new system
        # We'll add this when we're ready to migrate to the new property system
        
        return domain_id
    
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
    
    def _show_message(self, message: str, title: str = "Message", icon: str = 'INFO'):
        """Show a message to the user via Blender's interface"""
        def draw(self, context):
            self.layout.label(text=message)
            
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    
    def _get_available_chains(self) -> List[str]:
        """Get a list of available chains in the molecule"""
        if not self.molecule.object:
            return []
            
        # Check if we have chain_id attribute
        if "chain_id" not in self.molecule.object.data.attributes:
            return []
            
        # Get unique chain IDs
        chain_attr = self.molecule.object.data.attributes["chain_id"]
        chain_ids = sorted(set(value.value for value in chain_attr.data))
        
        return [str(chain_id) for chain_id in chain_ids]
    
    def _find_next_available_section(self, chain_id: str) -> Optional[tuple]:
        """Find the next available non-overlapping section on a chain"""
        # Get the residue range for this chain
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        
        print(f"Finding available section for chain_id={chain_id}, mapped_chain={mapped_chain}")
        print(f"Available residue ranges: {self.chain_residue_ranges}")
        
        if mapped_chain not in self.chain_residue_ranges:
            # Try using the chain_id directly if mapping failed
            if str(chain_id) in self.chain_residue_ranges:
                mapped_chain = str(chain_id)
                print(f"Using unmapped chain_id {chain_id} found in residue ranges")
            else:
                print(f"Chain {mapped_chain} not found in residue ranges")
                return None
            
        min_res, max_res = self.chain_residue_ranges[mapped_chain]
        print(f"Residue range for chain {mapped_chain}: {min_res}-{max_res}")
        
        # If no domains yet, return the full range
        if not self.domains:
            print(f"No domains exist yet, returning full range: {min_res}-{max_res}")
            return (min_res, max_res)
            
        # Get all domains on this chain
        chain_domains = []
        for domain_id, domain in self.domains.items():
            if domain.chain_id == mapped_chain:
                chain_domains.append((domain.start, domain.end))
                
        print(f"Existing domains on chain {mapped_chain}: {chain_domains}")
                
        if not chain_domains:
            # No domains on this chain yet
            print(f"No domains on chain {mapped_chain} yet, returning full range: {min_res}-{max_res}")
            return (min_res, max_res)
            
        # Sort domains by start position
        chain_domains.sort()
        
        # Check for a gap at the beginning
        if chain_domains[0][0] > min_res:
            section = (min_res, chain_domains[0][0] - 1)
            print(f"Found gap at beginning: {section}")
            return section
            
        # Check for gaps between domains
        for i in range(len(chain_domains) - 1):
            if chain_domains[i+1][0] > chain_domains[i][1] + 1:
                section = (chain_domains[i][1] + 1, chain_domains[i+1][0] - 1)
                print(f"Found gap between domains: {section}")
                return section
                
        # Check for a gap at the end
        if chain_domains[-1][1] < max_res:
            section = (chain_domains[-1][1] + 1, max_res)
            print(f"Found gap at end: {section}")
            return section
            
        # No gaps found
        print(f"No gaps found on chain {mapped_chain}")
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
    
    def _get_chain_residue_ranges(self) -> Dict[str, tuple]:
        """Get the residue ranges for each chain in the molecule"""
        ranges = {}
        
        if not self.molecule.object:
            print("No molecule object found")
            return ranges
            
        # Check if we have chain_id attribute at least
        if "chain_id" in self.molecule.object.data.attributes:
            # Get chain attribute
            chain_attr = self.molecule.object.data.attributes["chain_id"]
            
            # If we have residue_number attribute, use it to determine ranges
            if "residue_number" in self.molecule.object.data.attributes:
                res_attr = self.molecule.object.data.attributes["residue_number"]
                
                # Ensure both attributes have data
                if len(res_attr.data) > 0 and len(chain_attr.data) > 0:
                    # Group residues by chain
                    chain_residues = {}
                    for i in range(len(res_attr.data)):
                        chain_id = str(chain_attr.data[i].value)
                        res_num = res_attr.data[i].value
                        
                        if chain_id not in chain_residues:
                            chain_residues[chain_id] = []
                            
                        chain_residues[chain_id].append(res_num)
                        
                    # Calculate min/max for each chain
                    for chain_id, residues in chain_residues.items():
                        if residues:
                            ranges[chain_id] = (min(residues), max(residues))
            
            # If we still have no ranges but we have chains, create default ranges
            if not ranges:
                print("No residue ranges found, creating default ranges")
                
                # Get unique chain IDs
                unique_chains = sorted(set(str(value.value) for value in chain_attr.data))
                
                # Create default ranges (1-100 for each chain)
                for chain_id in unique_chains:
                    ranges[chain_id] = (1, 100)
                    
                print(f"Created default residue ranges for {len(ranges)} chains")
        else:
            print("No chain_id attribute found in molecule data")
            
        # Add debug information
        print(f"Found chain residue ranges: {ranges}")
        if not ranges:
            print("Warning: No residue ranges found for any chain")
            
        return ranges
    
    def _check_domain_overlap(self, chain_id: str, start: int, end: int, exclude_domain_id: Optional[str] = None) -> bool:
        """Check if a domain would overlap with existing domains"""
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        
        for domain_id, domain in self.domains.items():
            if exclude_domain_id and domain_id == exclude_domain_id:
                continue
                
            if domain.chain_id == mapped_chain:
                # Check for overlap
                if (start <= domain.end and end >= domain.start):
                    return True
                    
        return False
    
    def _update_residue_assignments(self, domain: DomainDefinition):
        """Update the residue assignments dictionary to track which residues are in domains"""
        # This is used to track which residues are assigned to domains
        # for potential future use in preventing overlaps or showing UI feedback
        chain_id = domain.chain_id
        
        if chain_id not in self.residue_assignments:
            self.residue_assignments[chain_id] = set()
            
        # Add all residues in this domain to the set
        for res in range(domain.start, domain.end + 1):
            self.residue_assignments[chain_id].add(res)
    
    def _setup_preview_domain(self):
        """Set up a preview domain for showing selection before creating a domain"""
        if not self.molecule.object:
            return
            
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            return
            
        parent_node_group = parent_modifier.node_group
        
        # Check if we already have preview nodes
        if self.preview_nodes:
            return
            
        # Create preview nodes
        self.preview_nodes = {
            "chain_select": None,
            "res_select": None,
            "style": None,
            "visible": None
        }
        
        # Create nodes for preview domain
        # This will be similar to domain mask nodes but with different styling
        # Implementation details would go here
    
    def set_preview_visibility(self, visible: bool):
        """Set the visibility of the preview domain"""
        if not self.preview_nodes or not self.preview_nodes.get("visible"):
            return
            
        # Set visibility
        self.preview_nodes["visible"].inputs[0].default_value = visible
    
    def update_preview_range(self, chain_id: int, start: int, end: int):
        """Update the preview domain to show a specific residue range"""
        if not self.preview_nodes:
            return
            
        # Update chain selection
        chain_select = self.preview_nodes.get("chain_select")
        if chain_select:
            # Clear existing selections
            for input_socket in chain_select.inputs:
                if input_socket.type == 'BOOLEAN':
                    input_socket.default_value = False
                    
            # Set the selected chain
            mapped_chain = self.chain_mapping.get(chain_id, str(chain_id))
            for input_socket in chain_select.inputs:
                if input_socket.name == mapped_chain:
                    input_socket.default_value = True
                    break
        
        # Update residue range
        res_select = self.preview_nodes.get("res_select")
        if res_select:
            if "Min" in res_select.inputs:
                res_select.inputs["Min"].default_value = start
            if "Max" in res_select.inputs:
                res_select.inputs["Max"].default_value = end
    
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
    
    def _create_domain_mask_nodes(self, domain_id: str, chain_id: str, start: int, end: int):
        """Create nodes to mask out a domain in the parent molecule"""
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            return
            
        parent_node_group = parent_modifier.node_group
        
        # Step 1: Create chain selection node
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
            res_select_group = nodes.custom_range(
                name="selection", 
                field="residue_number", 
                dtype="INT"
            )
            
            res_select = nodes.add_custom(
                parent_node_group,
                res_select_group.name
            )
            
            # Position to the right of chain selection
            res_select.location = (chain_select.location.x + 300, chain_select.location.y)
            res_select.name = res_select_name
        
        # Step 4: Configure residue range
        if "Min" in res_select.inputs:
            res_select.inputs["Min"].default_value = start
        if "Max" in res_select.inputs:
            res_select.inputs["Max"].default_value = end
        
        # Step 5: Connect chain and residue selection
        if chain_select and res_select:
            print("Connecting chain selection to residue range")
            # Find the output socket from chain selection
            chain_out = None
            for output in chain_select.outputs:
                if output.type == 'GEOMETRY':
                    chain_out = output
                    print(f"Found chain selection output socket: {output.name}")
                    break
                    
            # Find the geometry input socket for residue selection
            res_in = None
            for input_socket in res_select.inputs:
                if input_socket.type == 'GEOMETRY':
                    res_in = input_socket
                    print(f"Found residue range input socket: {input_socket.name}")
                    break
                    
            if chain_out and res_in:
                try:
                    node_group.links.new(chain_out, res_in)
                    print(f"Connected chain selection output to residue range input")
                except Exception as e:
                    print(f"Error connecting chain selection to residue range: {e}")
            else:
                print(f"Could not connect chain to residue selection: chain_out={chain_out is not None}, res_in={res_in is not None}")
        
        # Step 6: Connect to the style node
        style_node = None
        for node in node_group.nodes:
            if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Style" in node.node_tree.name:
                style_node = node
                print(f"Found style node: {node.name}")
                break
                
        if style_node and res_select:
            print("Connecting residue range to style node")
            res_out = None
            for output in res_select.outputs:
                if output.type == 'GEOMETRY':
                    res_out = output
                    print(f"Found residue range output socket: {output.name}")
                    break
                    
            if res_out:
                # Find the geometry input socket for style node
                style_in = None
                for input_socket in style_node.inputs:
                    if input_socket.type == 'GEOMETRY':
                        style_in = input_socket
                        print(f"Found style node input socket: {input_socket.name}")
                        break
                        
                if style_in:
                    try:
                        node_group.links.new(res_out, style_in)
                        print(f"Connected residue range output to style node input")
                    except Exception as e:
                        print(f"Error connecting residue range to style node: {e}")
                else:
                    print("Could not find geometry input socket for style node")
            else:
                print("Could not find geometry output socket for residue range")
        else:
            print(f"Could not connect residue range to style: style_node={style_node is not None}, res_select={res_select is not None}")
        
        # Step 7: Clean up any unused nodes
        print("Cleaning up unused nodes")
        self._clean_unused_nodes(node_group)
        
        print("Domain network setup complete")
    
    def _clean_unused_nodes(self, node_group):
        """Clean up unused nodes in a node group"""
        # Find all connected nodes starting from the group output
        connected_nodes = set()
        output_node = None
        
        # Find the group output node
        for node in node_group.nodes:
            if node.bl_idname == 'NodeGroupOutput':
                output_node = node
                break
                
        if not output_node:
            return
            
        # Recursive function to find all connected nodes
        def find_connected_nodes(node):
            if node in connected_nodes:
                return
                
            connected_nodes.add(node)
            
            # Check all input links
            for input_socket in node.inputs:
                for link in input_socket.links:
                    find_connected_nodes(link.from_node)
        
        # Start from the output node
        find_connected_nodes(output_node)
        
        # Remove all nodes that are not connected to the output
        for node in list(node_group.nodes):
            if node not in connected_nodes:
                node_group.nodes.remove(node)
    
    def update_domain(self, domain_id: str, chain_id: str, start: int, end: int) -> bool:
        """Update an existing domain with new parameters"""
        if domain_id not in self.domains:
            return False
            
        try:
            domain = self.domains[domain_id]
            
            # Check for overlaps with other domains
            if self._check_domain_overlap(chain_id, start, end, exclude_domain_id=domain_id):
                print(f"Domain overlap detected for chain {chain_id} ({start}-{end})")
                return False
                
            # Update domain definition
            domain.chain_id = chain_id
            domain.start = start
            domain.end = end
            
            # Update domain object name
            new_domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
            domain.object.name = f"{domain.name}_{chain_id}_{start}_{end}"
            
            # Update domain node network
            self._setup_domain_network(domain, chain_id, start, end)
            
            # Update domain mask nodes
            self._delete_domain_mask_nodes(domain_id)
            self._create_domain_mask_nodes(new_domain_id, chain_id, start, end)
            
            # Update residue assignments
            self._update_residue_assignments(domain)
            
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
    
    def update_domain_color(self, domain_id: str, color: tuple) -> bool:
        """Update the color of a domain"""
        if domain_id not in self.domains:
            return False
            
        try:
            domain = self.domains[domain_id]
            
            # Get the domain's node group
            if not domain.node_group:
                return False
                
            # Find the color node
            color_node = None
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and 
                    node.node_tree and 
                    "Color" in node.node_tree.name):
                    color_node = node
                    break
                    
            if not color_node:
                return False
                
            # Find the color common node
            color_emit = None
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'ShaderNodeEmission' or
                    (node.bl_idname == 'GeometryNodeGroup' and 
                     node.node_tree and 
                     "Color Common" in node.node_tree.name)):
                    color_emit = node
                    break
                    
            if not color_emit:
                return False
                
            # If it's a group node, we need to create a custom node tree for this domain
            if color_emit.bl_idname == 'GeometryNodeGroup':
                # If not, create a duplicate of the node tree specific to this domain
                original_node_tree = color_emit.node_tree
                new_node_tree_name = f"Color Common_{domain_id}"
                
                # Check if a custom tree already exists for this domain
                if new_node_tree_name in bpy.data.node_groups:
                    # Use existing custom node tree
                    color_emit.node_tree = bpy.data.node_groups[new_node_tree_name]
                else:
                    # Create a copy of the node tree with a unique name
                    new_node_tree = original_node_tree.copy()
                    new_node_tree.name = new_node_tree_name
                    color_emit.node_tree = new_node_tree
                
            # Now update the Carbon color input 
            if "Carbon" in color_emit.inputs:
                color_emit.inputs["Carbon"].default_value = color
                return True
            elif len(color_emit.inputs) > 0 and hasattr(color_emit.inputs[0], "default_value"):
                # Fallback - update the first input if named Carbon input not found
                color_emit.inputs[0].default_value = color
                return True
            else:
                print(f"Domain {domain_id}'s Color Common node has no Carbon input")
                return False
            
        except Exception as e:
            print(f"Error updating domain color: {str(e)}")
            return False

    def get_author_chain_id(self, chain_id):
        """
        Convert internal chain ID to author chain ID.
        
        Parameters
        ----------
        chain_id : str or int
            The internal chain ID to convert.
            
        Returns
        -------
        str
            The author chain ID corresponding to the internal chain ID.
            If no mapping exists, returns the string representation of the chain ID.
        """
        # Convert numeric chain_id to int for lookup
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        
        # Check if we have a mapping for this chain
        if chain_id_int in self.chain_mapping:
            return self.chain_mapping[chain_id_int]
            
        # If no mapping found, try to match chain_id as a string against chain_residue_ranges
        if str(chain_id) in self.chain_residue_ranges:
            return str(chain_id)
            
        # No mapping found, just return chain_id as string with a warning
        print(f"Warning: No chain mapping found for chain {chain_id}. Using numeric ID.")
        return str(chain_id)

    def _setup_domain_network(self, domain: DomainDefinition, chain_id: str, start: int, end: int):
        """Set up the node network for a domain"""
        if not domain.object or not domain.node_group:
            print("Domain object or node group is missing")
            return
            
        print(f"Setting up domain network for chain {chain_id}, range {start}-{end}")
            
        # Get the domain's node group
        node_group = domain.node_group
        
        # Step 1: Create chain selection node
        chain_select = None
        for node in node_group.nodes:
            if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Chain" in node.node_tree.name:
                chain_select = node
                print(f"Found existing chain selection node: {node.name}")
                break
                
        if not chain_select:
            print("Creating new chain selection node")
            # Create chain selection node
            try:
                chain_select_group = nodes.custom_iswitch(
                    name="selection", 
                    iter_list=self.chain_mapping.values() or [str(chain_id)], 
                    field="chain_id", 
                    dtype="BOOLEAN"
                )
                
                chain_select = nodes.add_custom(
                    node_group,
                    chain_select_group.name
                )
                print(f"Created chain selection node: {chain_select.name}")
            except Exception as e:
                print(f"Error creating chain selection node: {e}")
            
            # Position appropriately
            style_node = None
            for node in node_group.nodes:
                if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Style" in node.node_tree.name:
                    style_node = node
                    break
                    
            if style_node:
                chain_select.location = (style_node.location.x - 600, style_node.location.y)
                print(f"Positioned chain selection node relative to style node")
        
        # Step 2: Configure chain selection
        mapped_chain = self.chain_mapping.get(int(chain_id) if chain_id.isdigit() else chain_id, str(chain_id))
        print(f"Configuring chain selection for mapped chain: {mapped_chain}")
        for input_socket in chain_select.inputs:
            # Skip non-boolean inputs (like group inputs)
            if input_socket.type != 'BOOLEAN':
                continue
            if input_socket.name == mapped_chain:
                input_socket.default_value = True
                print(f"Set input socket {input_socket.name} to True")
            else:
                input_socket.default_value = False
        
        # Step 3: Create residue range selection node
        res_select = None
        for node in node_group.nodes:
            if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Range" in node.node_tree.name:
                res_select = node
                print(f"Found existing residue range node: {node.name}")
                break
                
        if not res_select:
            print("Creating new residue range selection node")
            # Create residue range selection node
            try:
                # Check if custom_range function exists
                if not hasattr(nodes, 'custom_range'):
                    print("ERROR: nodes module does not have custom_range function")
                    # Create a simple node group for range selection
                    # This is a fallback in case the custom_range function is not available
                    tree_name = "Range Selection"
                    tree = bpy.data.node_groups.get(tree_name)
                    if not tree:
                        tree = bpy.data.node_groups.new(tree_name, 'GeometryNodeTree')
                        
                        # Create input/output nodes
                        input_node = tree.nodes.new('NodeGroupInput')
                        output_node = tree.nodes.new('NodeGroupOutput')
                        input_node.location = (-600, 0)
                        output_node.location = (600, 0)
                        
                        # Create attribute input node
                        attr_node = tree.nodes.new("GeometryNodeInputNamedAttribute")
                        attr_node.data_type = "INT"
                        attr_node.location = (-400, 0)
                        attr_node.inputs["Name"].default_value = "residue_number"
                        
                        # Create comparison nodes
                        compare_min = tree.nodes.new("FunctionNodeCompare")
                        compare_min.data_type = "INT"
                        compare_min.operation = "GREATER_EQUAL"
                        compare_min.location = (-200, 50)
                        
                        compare_max = tree.nodes.new("FunctionNodeCompare")
                        compare_max.data_type = "INT"
                        compare_max.operation = "LESS_EQUAL"
                        compare_max.location = (-200, -50)
                        
                        # Create AND node
                        and_node = tree.nodes.new("FunctionNodeBooleanMath")
                        and_node.operation = "AND"
                        and_node.location = (0, 0)
                        
                        # Create filter node
                        filter_node = tree.nodes.new("GeometryNodeDeleteGeometry")
                        filter_node.domain = "POINT"
                        filter_node.mode = "ALL"
                        filter_node.location = (200, 0)
                        
                        # Create interface sockets
                        geom_in = tree.interface.new_socket("Geometry", "INPUT", "NodeSocketGeometry")
                        min_in = tree.interface.new_socket("Min", "INPUT", "NodeSocketInt")
                        max_in = tree.interface.new_socket("Max", "INPUT", "NodeSocketInt")
                        selection_out = tree.interface.new_socket("Selection", "OUTPUT", "NodeSocketGeometry")
                        inverted_out = tree.interface.new_socket("Inverted", "OUTPUT", "NodeSocketGeometry")
                        
                        # Set default values
                        min_in.default_value = 1
                        max_in.default_value = 100
                        
                        # Connect nodes
                        links = tree.links
                        # Connect inputs
                        links.new(input_node.outputs[geom_in.identifier], filter_node.inputs["Geometry"])
                        links.new(input_node.outputs[min_in.identifier], compare_min.inputs[1])
                        links.new(input_node.outputs[max_in.identifier], compare_max.inputs[1])
                        
                        # Connect attribute to comparisons
                        links.new(attr_node.outputs["Attribute"], compare_min.inputs[0])
                        links.new(attr_node.outputs["Attribute"], compare_max.inputs[0])
                        
                        # Connect comparisons to AND
                        links.new(compare_min.outputs[0], and_node.inputs[0])
                        links.new(compare_max.outputs[0], and_node.inputs[1])
                        
                        # Connect AND to filter
                        links.new(and_node.outputs[0], filter_node.inputs["Selection"])
                        
                        # Connect filter to outputs
                        links.new(filter_node.outputs["Geometry"], output_node.inputs[selection_out.identifier])
                        links.new(filter_node.outputs["Inverted"], output_node.inputs[inverted_out.identifier])
                    
                    res_select_group = tree
                else:
                    res_select_group = nodes.custom_range(
                        name="selection", 
                        field="residue_number", 
                        dtype="INT"
                    )
                    print(f"Created residue range group: {res_select_group.name}")
                
                res_select = nodes.add_custom(
                    node_group,
                    res_select_group.name
                )
                print(f"Added residue range node to node group: {res_select.name}")
            except Exception as e:
                print(f"Error creating residue range node: {e}")
                import traceback
                traceback.print_exc()
            
            # Position to the right of chain selection
            if chain_select:
                res_select.location = (chain_select.location.x + 300, chain_select.location.y)
                print(f"Positioned residue range node relative to chain selection node")
        
        # Step 4: Configure residue range
        if res_select:
            print(f"Configuring residue range: {start}-{end}")
            if "Min" in res_select.inputs:
                res_select.inputs["Min"].default_value = start
                print(f"Set Min input to {start}")
            else:
                print(f"WARNING: Min input not found in residue range node")
                
            if "Max" in res_select.inputs:
                res_select.inputs["Max"].default_value = end
                print(f"Set Max input to {end}")
            else:
                print(f"WARNING: Max input not found in residue range node")
        else:
            print("ERROR: Failed to create or find residue range node")
            
        # Step 5: Connect chain and residue selection
        if chain_select and res_select:
            print("Connecting chain selection to residue range")
            # Find the output socket from chain selection
            chain_out = None
            for output in chain_select.outputs:
                if output.type == 'GEOMETRY':
                    chain_out = output
                    print(f"Found chain selection output socket: {output.name}")
                    break
                    
            # Find the geometry input socket for residue selection
            res_in = None
            for input_socket in res_select.inputs:
                if input_socket.type == 'GEOMETRY':
                    res_in = input_socket
                    print(f"Found residue range input socket: {input_socket.name}")
                    break
                    
            if chain_out and res_in:
                try:
                    node_group.links.new(chain_out, res_in)
                    print(f"Connected chain selection output to residue range input")
                except Exception as e:
                    print(f"Error connecting chain selection to residue range: {e}")
            else:
                print(f"Could not connect chain to residue selection: chain_out={chain_out is not None}, res_in={res_in is not None}")
        
        # Step 6: Connect to the style node
        style_node = None
        for node in node_group.nodes:
            if node.bl_idname == 'GeometryNodeGroup' and node.node_tree and "Style" in node.node_tree.name:
                style_node = node
                print(f"Found style node: {node.name}")
                break
                
        if style_node and res_select:
            print("Connecting residue range to style node")
            res_out = None
            for output in res_select.outputs:
                if output.type == 'GEOMETRY':
                    res_out = output
                    print(f"Found residue range output socket: {output.name}")
                    break
                    
            if res_out:
                # Find the geometry input socket for style node
                style_in = None
                for input_socket in style_node.inputs:
                    if input_socket.type == 'GEOMETRY':
                        style_in = input_socket
                        print(f"Found style node input socket: {input_socket.name}")
                        break
                        
                if style_in:
                    try:
                        node_group.links.new(res_out, style_in)
                        print(f"Connected residue range output to style node input")
                    except Exception as e:
                        print(f"Error connecting residue range to style node: {e}")
                else:
                    print("Could not find geometry input socket for style node")
            else:
                print("Could not find geometry output socket for residue range")
        else:
            print(f"Could not connect residue range to style: style_node={style_node is not None}, res_select={res_select is not None}")
        
        # Step 7: Clean up any unused nodes
        print("Cleaning up unused nodes")
        self._clean_unused_nodes(node_group)
        
        print("Domain network setup complete")