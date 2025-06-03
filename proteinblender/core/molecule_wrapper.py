from typing import Optional, Dict, List, Tuple, Union, Set
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
        self.residue_sets: Dict[str, Set[int]] = {} # For custom residue selections
        
        # Ensure the molecule has the necessary integer chain ID attribute
        if not self.molecule.array.has_annotation("chain_id_int"):
            self.molecule.array.add_annotation("chain_id_int", dtype=int)
            unique_chain_ids, int_indices = np.unique(self.molecule.array.chain_id, return_inverse=True)
            self.molecule.array.set_annotation("chain_id_int", int_indices)
            print(f"DEBUG MoleWrap.__init__: Added 'chain_id_int' annotation. Unique chains processed: {len(unique_chain_ids)}")

        # 1. Author-provided chain ID map (often from mmCIF _atom_site.auth_asym_id)
        # Biotite's chain_mapping_str() typically provides a map from an integer index (related to unique auth_asym_ids) to the auth_asym_id string.
        # Let's verify its structure and content.
        raw_auth_map = molecule.array.chain_mapping_str() if hasattr(molecule.array, 'chain_mapping_str') else {}
        self.auth_chain_id_map: Dict[int, str] = {}
        if isinstance(raw_auth_map, dict):
            self.auth_chain_id_map = {k: v for k, v in raw_auth_map.items() if isinstance(k, int) and isinstance(v, str)}
        print(f"DEBUG MoleWrap.__init__: self.auth_chain_id_map (processed from chain_mapping_str): {self.auth_chain_id_map}")

        # 2. Map from internal integer chain index (0,1,2...) to _atom_site.label_asym_id ('A','B','C'...)
        # This uses molecule.array.chain_id which Biotite populates with label_asym_id for mmCIF.
        self.idx_to_label_asym_id_map: Dict[int, str] = {}
        if hasattr(molecule.array, 'chain_id'): # This is label_asym_id from Biotite for mmCIF
            unique_label_asym_ids = sorted(list(np.unique(molecule.array.chain_id)))
            print(f"DEBUG MoleWrap.__init__: Unique label_asym_ids from molecule.array.chain_id: {unique_label_asym_ids}")
            for i, label_id_str in enumerate(unique_label_asym_ids):
                self.idx_to_label_asym_id_map[i] = str(label_id_str) # Ensure it's a string
        else:
            print("Warning MoleWrap.__init__: molecule.array.chain_id not found. Cannot create idx_to_label_asym_id_map.")
        print(f"DEBUG MoleWrap.__init__: self.idx_to_label_asym_id_map: {self.idx_to_label_asym_id_map}")
        
        self.chain_residue_ranges: Dict[str, Tuple[int, int]] = self._get_chain_residue_ranges()
        print(f"DEBUG MoleWrap.__init__: self.chain_residue_ranges: {self.chain_residue_ranges}")
        
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
        mapped_chain = self.auth_chain_id_map.get(chain_id_int, str(chain_id))
        
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
        if end == 9999:  # Only check if end is the default value
            end = max_res
            print(f"Using chain max range: {end}")
        
        # Make sure start/end are within valid range for this chain
        original_start, original_end = start, end
        start = max(min_res, start)
        
        # Only limit end to max_res if it exceeds max_res
        if end > max_res:
            end = max_res
            
        if original_start != start or original_end != end:
            print(f"Adjusting range from {original_start}-{original_end} to valid range {start}-{end}")
        
        return start, end
    '''
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
    '''
    
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
        mapped_chain = self.auth_chain_id_map.get(chain_id_int, str(chain_id))
        
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
        """Parse chain mapping string (likely numeric_id_from_source_file -> auth_asym_id) into a dictionary"""
        mapping = {}
        if mapping_str:
            for pair in mapping_str.split(\",\"):
                if \":\" in pair:
                    try:
                        k_str, v = pair.split(\":\")
                        mapping[int(k_str)] = v
                    except ValueError:
                        print(f"Warning: Could not parse pair '{pair}' in chain_mapping_str '{mapping_str}'")
        return mapping
    
    def _get_chain_residue_ranges(self) -> Dict[str, Tuple[int, int]]:
        """Computes the min and max residue numbers for each chain, keyed by label_asym_id."""
        ranges: Dict[str, Tuple[int, int]] = {}
        if not hasattr(self.molecule.array, 'res_id') or not hasattr(self.molecule.array, 'chain_id_int'):
            print("Warning MoleWrap._get_chain_residue_ranges: Missing 'res_id' or 'chain_id_int' annotation. Cannot compute ranges.")
            return {}

        res_ids = self.molecule.array.res_id
        # Use 'chain_id_int' for grouping, as this is our reliable internal integer index (0, 1, 2...)
        int_chain_indices = self.molecule.array.chain_id_int 

        unique_int_chain_keys = np.unique(int_chain_indices)
        print(f"DEBUG MoleWrap._get_chain_residue_ranges: Unique integer chain keys found: {unique_int_chain_keys}")

        for int_chain_key in unique_int_chain_keys:
            # Convert integer chain key to label_asym_id for the ranges dictionary key
            label_asym_id_for_key = self.idx_to_label_asym_id_map.get(int(int_chain_key))
            
            if not label_asym_id_for_key:
                print(f"Warning MoleWrap._get_chain_residue_ranges: Integer chain_id {int_chain_key} not in idx_to_label_asym_id_map. Trying auth_chain_id_map or skipping.")
                # Fallback attempt using auth_chain_id_map if it has this integer key
                label_asym_id_for_key = self.auth_chain_id_map.get(int(int_chain_key))
                if not label_asym_id_for_key:
                    print(f"Warning MoleWrap._get_chain_residue_ranges: Still no mapping for int_chain_key {int_chain_key}. Using str({int_chain_key}) as fallback key.")
                    label_asym_id_for_key = str(int_chain_key) # Last resort, use the int as string
            
            print(f"DEBUG MoleWrap._get_chain_residue_ranges: Processing int_chain_key: {int_chain_key}, resolved label_asym_id_for_key: {label_asym_id_for_key}")

            mask = (int_chain_indices == int_chain_key)
            if np.any(mask):
                chain_res_ids = res_ids[mask]
                if chain_res_ids.size > 0:
                    ranges[label_asym_id_for_key] = (int(np.min(chain_res_ids)), int(np.max(chain_res_ids)))
        else:
                    print(f"Warning MoleWrap._get_chain_residue_ranges: No residues found for int_chain_key {int_chain_key} (mapped to {label_asym_id_for_key}) despite mask being non-empty.")
            else:
                 print(f"Warning MoleWrap._get_chain_residue_ranges: No atoms found for int_chain_key {int_chain_key} (mask was empty).")
            
        if not ranges:
            print("Warning MoleWrap._get_chain_residue_ranges: No residue ranges could be determined for any chain.")
            # As a last resort, if idx_to_label_asym_id_map exists, create default (e.g., 1-100) ranges for all known label_asym_ids
            if self.idx_to_label_asym_id_map:
                print("Creating default (1-100) ranges for all chains known from idx_to_label_asym_id_map as a final fallback.")
                for label_asym_id_val in self.idx_to_label_asym_id_map.values():
                    ranges[label_asym_id_val] = (1, 100) # Default placeholder range

        print(f"DEBUG MoleWrap._get_chain_residue_ranges: Final 'ranges' to be returned: {ranges}")
        return ranges
    '''
    def _check_domain_overlap(self, chain_id: int, start: int, end: int, exclude_domain_id: Optional[str] = None) -> bool:
        """Check if a domain would overlap with existing domains"""
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.auth_chain_id_map.get(chain_id_int, str(chain_id))
        
        for domain_id, domain in self.domains.items():
            if exclude_domain_id and domain_id == exclude_domain_id:
                continue
                
            if domain.chain_id == mapped_chain:
                # Check for overlap
                if (start <= domain.end and end >= domain.start):
                    return True
                    
        return False
    '''
    
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
            mapped_chain = self.auth_chain_id_map.get(chain_id, str(chain_id))
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
    
    def _create_domain_mask_nodes(self, domain: DomainDefinition, chain_id_int_str: str, start: int, end: int):
        """Creates the Geometry Node setup on the domain object to mask the parent molecule."""
        if not domain.object:
            print(f"ERROR MoleWrap._create_domain_mask_nodes: Domain object for {domain.id} not found.")
            return
            
        print(f"DEBUG MoleWrap._create_domain_mask_nodes: Setting up GN for domain {domain.id}, chain_int_str '{chain_id_int_str}', range {start}-{end}")

        # Ensure there's a GN modifier
        if not domain.object.modifiers:
            gn_mod = domain.object.modifiers.new(name="ProteinBlender Domain Mask", type='NODES')
        else:
            gn_mod = domain.object.modifiers.get("ProteinBlender Domain Mask")
            if not gn_mod:
                gn_mod = domain.object.modifiers.new(name="ProteinBlender Domain Mask", type='NODES')
        
        if not gn_mod.node_group:
            gn_mod.node_group = bpy.data.node_groups.new(name=f"ng_{domain.id}_mask", type='GeometryNodeTree')
        
        ng = gn_mod.node_group
        nodes = ng.nodes
        links = ng.links
        nodes.clear()

        # Group Input and Output
        group_input = nodes.new(type='NodeGroupInput')
        group_input.location = (-400, 0)
        group_output = nodes.new(type='NodeGroupOutput')
        group_output.location = (400, 0)

        # Object Info node for the parent molecule
        obj_info_node = nodes.new(type='GeometryNodeObjectInfo')
        obj_info_node.location = (-200, 200)
        obj_info_node.transform_space = 'RELATIVE' # Important for instanced molecules too
        if self.molecule.object:
            obj_info_node.inputs[0].default_value = self.molecule.object # Link to parent molecule

        # Named Attribute for chain_id_int
        chain_attr_node = nodes.new(type='GeometryNodeInputNamedAttribute')
        chain_attr_node.location = (-200, 100)
        chain_attr_node.data_type = 'INT'
        chain_attr_node.inputs["Name"].default_value = "chain_id_int"

        # Compare node for chain_id_int
        compare_chain_node = nodes.new(type='FunctionNodeCompare')
        compare_chain_node.location = (0, 100)
        compare_chain_node.data_type = 'INT'
        compare_chain_node.operation = 'EQUAL'
        compare_chain_node.inputs[2].default_value = int(chain_id_int_str) # B input

        # Named Attribute for res_id
        res_attr_node = nodes.new(type='GeometryNodeInputNamedAttribute')
        res_attr_node.location = (-200, 0)
        res_attr_node.data_type = 'INT'
        res_attr_node.inputs["Name"].default_value = "res_id"

        # Compare node for start residue (res_id >= start)
        compare_start_node = nodes.new(type='FunctionNodeCompare')
        compare_start_node.location = (0, 0)
        compare_start_node.data_type = 'INT'
        compare_start_node.operation = 'GREATER_THAN_OR_EQUAL'
        compare_start_node.inputs[2].default_value = start # B input

        # Compare node for end residue (res_id <= end)
        compare_end_node = nodes.new(type='FunctionNodeCompare')
        compare_end_node.location = (0, -100)
        compare_end_node.data_type = 'INT'
        compare_end_node.operation = 'LESS_THAN_OR_EQUAL'
        compare_end_node.inputs[2].default_value = end # B input

        # Boolean Math AND node (Chain AND Start)
        and1_node = nodes.new(type='FunctionNodeBooleanMath')
        and1_node.location = (200, 50)
        and1_node.operation = 'AND'

        # Boolean Math AND node ((Chain AND Start) AND End)
        and2_node = nodes.new(type='FunctionNodeBooleanMath')
        and2_node.location = (200, -50)
        and2_node.operation = 'AND'

        # Link nodes
        links.new(obj_info_node.outputs['Geometry'], chain_attr_node.inputs['Geometry'])
        links.new(obj_info_node.outputs['Geometry'], res_attr_node.inputs['Geometry'])
        
        links.new(chain_attr_node.outputs['Attribute'], compare_chain_node.inputs[1]) # A input
        links.new(res_attr_node.outputs['Attribute'], compare_start_node.inputs[1])   # A input
        links.new(res_attr_node.outputs['Attribute'], compare_end_node.inputs[1])     # A input

        links.new(compare_chain_node.outputs['Result'], and1_node.inputs[0])
        links.new(compare_start_node.outputs['Result'], and1_node.inputs[1])
        
        links.new(and1_node.outputs['Boolean'], and2_node.inputs[0])
        links.new(compare_end_node.outputs['Result'], and2_node.inputs[1])

        # Output the original geometry and the selection
        if not ng.outputs:
            ng.outputs.new('NodeSocketGeometry', 'Geometry')
            ng.outputs.new('NodeSocketBool', 'Selection')
        elif len(ng.outputs) < 2:
            if 'Geometry' not in ng.outputs: ng.outputs.new('NodeSocketGeometry', 'Geometry')
            if 'Selection' not in ng.outputs: ng.outputs.new('NodeSocketBool', 'Selection')
        else: # Ensure correct names if they exist
            if ng.outputs[0].name != 'Geometry': ng.outputs[0].name = 'Geometry'
            if ng.outputs[1].name != 'Selection': ng.outputs[1].name = 'Selection'

        links.new(obj_info_node.outputs['Geometry'], group_output.inputs['Geometry'])
        links.new(and2_node.outputs['Boolean'], group_output.inputs['Selection'])

        print(f"DEBUG MoleWrap._create_domain_mask_nodes: GN setup complete for domain {domain.id}")

    def _create_domain_with_params(self, chain_id_int_str: str, start: int, end: int, name: Optional[str] = None, 
                                   auto_fill_chain: bool = True, 
                                   parent_domain_id: Optional[str] = None,
                                   fill_boundaries_start: Optional[int] = None,
                                   fill_boundaries_end: Optional[int] = None,
                                   parent_domain_id_for_fillers: Optional[str] = None
                                   ) -> Optional[str]:
        """Internal method to create a domain with specific parameters.
        Args:
            chain_id_int_str: The STRINGIFIED INTEGER chain ID (e.g., '0', '1', '2') used for attribute lookups in Blender.
            start: Start residue
            end: End residue
            name: Optional name for the domain
            auto_fill_chain: Whether to automatically create additional domains to fill the chain.
            parent_domain_id: ID of an existing domain this new one might be a sub-part of.
            fill_boundaries_start: Optional start of the context to fill (used by auto_fill_chain)
            fill_boundaries_end: Optional end of the context to fill (used by auto_fill_chain)
            parent_domain_id_for_fillers: Explicit parent for fillers if different from 'parent_domain_id'
        """
        try:
            chain_id_int = int(chain_id_int_str)
        except ValueError:
            print(f"ERROR MoleWrap._create_domain_with_params: chain_id_int_str '{chain_id_int_str}' could not be converted to int. Skipping domain.")
            return None

        label_asym_id_for_domain = self.idx_to_label_asym_id_map.get(chain_id_int)
        if not label_asym_id_for_domain:
            print(f"Warning MoleWrap._create_domain_with_params: Integer chain ID {chain_id_int} not found in idx_to_label_asym_id_map. Attempting fallback to auth_chain_id_map or using stringified int.")
            label_asym_id_for_domain = self.auth_chain_id_map.get(chain_id_int, chain_id_int_str) # Fallback
            print(f"Fallback: Using '{label_asym_id_for_domain}' for domain naming/definition based on fallback for int chain id {chain_id_int}.")

        domain_name = name if name else f"Chain {label_asym_id_for_domain}"
        # Use label_asym_id for domain_id generation if possible, otherwise the int string
        base_chain_id_for_domain_obj = label_asym_id_for_domain 

        domain_id = f"{self.identifier}_{base_chain_id_for_domain_obj}_{start}_{end}_{name if name else 'domain'}".replace(" ", "_")
        if domain_id in self.domains:
            print(f"Warning: Domain ID '{domain_id}' already exists. Skipping.")
            return domain_id # Or None, depending on desired behavior for duplicates

        current_start, current_end = start, end
        # Clamp start/end to actual chain residue ranges using label_asym_id_for_domain as key
        if label_asym_id_for_domain in self.chain_residue_ranges:
            min_res_chain, max_res_chain = self.chain_residue_ranges[label_asym_id_for_domain]
            current_start = max(current_start, min_res_chain)
            current_end = min(current_end, max_res_chain)
            if current_start > current_end:
                print(f"Warning MoleWrap._create_domain_with_params: Domain for {label_asym_id_for_domain} (Int ID: {chain_id_int_str}) has start ({start}>{end}) or ({current_start}>{current_end}) after clamping. Range: ({min_res_chain}-{max_res_chain}). Skipping.")
                return None
        else:
            print(f"Warning MoleWrap._create_domain_with_params: Chain key '{label_asym_id_for_domain}' (derived from int_id {chain_id_int_str}) not in self.chain_residue_ranges. Cannot accurately clamp. Ranges: {self.chain_residue_ranges}. Skipping.")
            return None

        domain = DomainDefinition(
            id=domain_id, 
            name=domain_name, 
            molecule_wrapper=self, 
            chain_id=label_asym_id_for_domain, # Store the label_asym_id here
            start=current_start, 
            end=current_end,
            parent_domain_id=parent_domain_id
        )

        # _setup_domain_network MUST receive the stringified INTEGER chain ID (chain_id_int_str) for attribute comparison in Blender
        if not self._setup_domain_network(domain, chain_id_int_str, current_start, current_end):
            print(f"Warning MoleWrap._create_domain_with_params: Domain '{domain.name}' (Labelled Chain: {label_asym_id_for_domain}, Int Attr: {chain_id_int_str}, Range: {current_start}-{current_end}) could not be fully initialized via _setup_domain_network. Skipping.")
            if domain.object and domain.object.name in bpy.data.objects: # Cleanup if object was created
                try: bpy.data.objects.remove(domain.object, do_unlink=True)
                except: pass
            return None

        if not domain.object:
             print(f"Critical Error MoleWrap._create_domain_with_params: domain.object is not set after successful _setup_domain_network for {domain_id}. This should not happen. Skipping further setup.")
             return None # Cannot proceed without the Blender object

        domain.object["domain_expanded"] = False
        domain.object["domain_color_field_name"] = f"domain_color_{domain_id}"
        domain.object["parent_protein_obj_name"] = self.molecule.object.name
        if parent_domain_id:
            domain.object["parent_domain_id"] = parent_domain_id

        self.domains[domain_id] = domain
        print(f"DEBUG MoleWrap._create_domain_with_params: Domain '{domain_id}' added to self.domains. Current count: {len(self.domains)}")

        # Handle auto-fill logic. This should not change the return of *this* primary domain_id.
        if auto_fill_chain and parent_domain_id_for_fillers:
            print(f"DEBUG MoleWrap._create_domain_with_params: auto_fill_chain is True for {domain_id}. Parent for fillers: {parent_domain_id_for_fillers}")
            context_min_res_for_fill = fill_boundaries_start if fill_boundaries_start is not None else self.chain_residue_ranges[label_asym_id_for_domain][0]
            context_max_res_for_fill = fill_boundaries_end if fill_boundaries_end is not None else self.chain_residue_ranges[label_asym_id_for_domain][1]
            
            self._create_additional_domains_to_span_context(
                chain_id_int_str=chain_id_int_str, 
                current_domain_start=current_start,
                current_domain_end=current_end,
                mapped_chain_label_asym_id=label_asym_id_for_domain, 
                context_min_res=context_min_res_for_fill,
                context_max_res=context_max_res_for_fill,
                parent_domain_id_for_fillers=parent_domain_id_for_fillers
            )
        
        return domain_id # Return the primary domain ID string

    def _setup_domain_network(self, domain: DomainDefinition, chain_id_int_str: str, start: int, end: int) -> bool:
        """
        Sets up the Blender object and Geometry Nodes for the domain.
        Args:
            domain: The DomainDefinition object.
            chain_id_int_str: The STRINGIFIED INTEGER chain ID (e.g., '0', '1', '2') to use for attribute comparison.
            start: The start residue for this domain.
            end: The end residue for this domain.
        Returns:
            True if setup was successful, False otherwise.
        """
        if not self.molecule.object:
            print("ERROR MoleWrap._setup_domain_network: Parent molecule object does not exist.")
            return False

        # Create new Blender object for the domain, parented to the main molecule object
        domain_obj = bpy.data.objects.new(name=domain.id, object_data=None)
        domain_obj.empty_display_type = 'ARROWS' # or 'PLAIN_AXES', 'SPHERE', etc.
        domain_obj.empty_display_size = 0.1
        bpy.context.scene.collection.objects.link(domain_obj)
        domain_obj.parent = self.molecule.object
        domain.object = domain_obj # Assign to the domain definition
        print(f"DEBUG MoleWrap._setup_domain_network: Created Blender object for domain: {domain.id}")

        # Store domain metadata on the Blender object
        domain_obj["is_protein_blender_domain"] = True
        domain_obj["pb_domain_id"] = domain.id
        domain_obj["pb_chain_id"] = domain.chain_id # This is label_asym_id
        domain_obj["pb_start_residue"] = start
        domain_obj["pb_end_residue"] = end
        domain_obj["pb_molecule_id"] = self.identifier

        attrs = self.molecule.object.data.attributes
        residue_attr_name = "res_id" # Standard residue ID attribute
        chain_attr_name = "chain_id_int" # Our integer chain ID attribute
        position_attr_name = "position"
        atom_name_attr = "atom_name"
        is_alpha_carbon_attr = "is_alpha_carbon"

        has_atom_name_attr = atom_name_attr in attrs
        has_is_alpha_carbon_attr = is_alpha_carbon_attr in attrs

        if not (residue_attr_name in attrs and chain_attr_name in attrs and position_attr_name in attrs):
            print(f"ERROR MoleWrap._setup_domain_network: Missing required attributes ('{residue_attr_name}', '{chain_attr_name}', or '{position_attr_name}') on parent molecule mesh. Cannot find Cα. Domain: {domain.id}")
            return False

        ca_pos_start = None
        print(f"DEBUG MoleWrap._setup_domain_network: Searching for Cα for START of domain {domain.name}, target chain_id_int_str: '{chain_id_int_str}', target res_id: {start}")
        for i in range(len(attrs[residue_attr_name].data)):
            atom_chain_id_val = str(attrs[chain_attr_name].data[i].value) # Compare string vs string
            atom_res_num = attrs[residue_attr_name].data[i].value
            
            is_ca = False
            if has_is_alpha_carbon_attr:
                is_ca = attrs[is_alpha_carbon_attr].data[i].value
            elif has_atom_name_attr:
                is_ca = (attrs[atom_name_attr].data[i].value == 2) # 2 is the integer for 'CA' from atom_names.json

            if atom_chain_id_val == chain_id_int_str and atom_res_num == start and is_ca:
                ca_pos_start = attrs[position_attr_name].data[i].vector.copy()
                print(f"DEBUG MoleWrap._setup_domain_network: Found Cα for START of domain {domain.name} at atom index {i}. Position: {ca_pos_start}")
                break
        
        if ca_pos_start is None:
            print(f"ERROR MoleWrap._setup_domain_network: No Alpha Carbon (CA) atom found for the start residue {start} of chain (int_id_str) {chain_id_int_str} for domain '{domain.name}'. Searched {len(attrs[residue_attr_name].data)} atoms.")
            # Try to print some atoms from the target chain and residue to debug
            count = 0
            for i in range(len(attrs[residue_attr_name].data)):
                if str(attrs[chain_attr_name].data[i].value) == chain_id_int_str and attrs[residue_attr_name].data[i].value == start and count < 5:
                    atom_name_val = attrs[atom_name_attr].data[i].value if has_atom_name_attr else 'N/A'
                    is_ca_val = attrs[is_alpha_carbon_attr].data[i].value if has_is_alpha_carbon_attr else 'N/A'
                    print(f"  Nearby atom: chain={str(attrs[chain_attr_name].data[i].value)}, res={attrs[residue_attr_name].data[i].value}, name_code={atom_name_val}, is_CA_attr={is_ca_val}")
                    count += 1
            return False # Cannot proceed without Cα for start

        # Set the domain object's location to the Cα of the start residue (in world space)
        domain_obj.location = self.molecule.object.matrix_world @ ca_pos_start
        print(f"DEBUG MoleWrap._setup_domain_network: Set domain object '{domain.id}' location to {domain_obj.location}")
        
        # Call the method to create geometry nodes for masking this domain
        self._create_domain_mask_nodes(domain, chain_id_int_str, start, end)
        return True
    
    def _create_additional_domains_to_span_context(
        self,
        chain_id_int_str: str, 
        current_domain_start: int, 
        current_domain_end: int,
        mapped_chain_label_asym_id: str, # The label_asym_id for the chain context
        context_min_res: int, 
        context_max_res: int,
        parent_domain_id_for_fillers: str
    ) -> List[str]:
        """Creates domains to fill gaps before and after a given domain within a chain's full context."""
        created_filler_domain_ids: List[str] = []
        print(f"DEBUG MoleWrap._create_additional_domains: Called for chain {mapped_chain_label_asym_id} (int_str: {chain_id_int_str}), domain {current_domain_start}-{current_domain_end}, context {context_min_res}-{context_max_res}, parent_for_fillers: {parent_domain_id_for_fillers}")

        # Fill before the current domain if needed
        if current_domain_start > context_min_res:
            filler_start = context_min_res
            filler_end = current_domain_start - 1
            filler_name = f"{mapped_chain_label_asym_id}_{filler_start}-{filler_end}_filler_pre"
            print(f"Attempting to create PRE-filler: {filler_name} for chain {mapped_chain_label_asym_id} (int_str: {chain_id_int_str})")
            filler_id = self._create_domain_with_params(
                chain_id_int_str=chain_id_int_str,
                start=filler_start, 
                end=filler_end, 
                name=filler_name, 
                auto_fill_chain=False, # Fillers should not auto-fill themselves
                parent_domain_id=parent_domain_id_for_fillers, # Parented to the original domain that triggered auto-fill
                parent_domain_id_for_fillers=None # Fillers don't have their own fillers
            )
            if filler_id:
                created_filler_domain_ids.append(filler_id)
                print(f"Successfully created PRE-filler domain: {filler_id}")
            else:
                print(f"Failed to create PRE-filler domain for {mapped_chain_label_asym_id} range {filler_start}-{filler_end}")

        # Fill after the current domain if needed
        if current_domain_end < context_max_res:
            filler_start = current_domain_end + 1
            filler_end = context_max_res
            filler_name = f"{mapped_chain_label_asym_id}_{filler_start}-{filler_end}_filler_post"
            print(f"Attempting to create POST-filler: {filler_name} for chain {mapped_chain_label_asym_id} (int_str: {chain_id_int_str})")
            filler_id = self._create_domain_with_params(
                chain_id_int_str=chain_id_int_str,
                start=filler_start, 
                end=filler_end, 
                name=filler_name, 
                auto_fill_chain=False, 
                parent_domain_id=parent_domain_id_for_fillers,
                parent_domain_id_for_fillers=None
            )
            if filler_id:
                created_filler_domain_ids.append(filler_id)
                print(f"Successfully created POST-filler domain: {filler_id}")
            else:
                print(f"Failed to create POST-filler domain for {mapped_chain_label_asym_id} range {filler_start}-{filler_end}")
        
        return created_filler_domain_ids

    def _create_domain_mask_nodes(self, domain: DomainDefinition, chain_id_int_str: str, start: int, end: int):
        """Creates the Geometry Node setup on the domain object to mask the parent molecule."""
        if not domain.object:
            print(f"ERROR MoleWrap._create_domain_mask_nodes: Domain object for {domain.id} not found.")
            return

        print(f"DEBUG MoleWrap._create_domain_mask_nodes: Setting up GN for domain {domain.id}, chain_int_str '{chain_id_int_str}', range {start}-{end}")

        # Ensure there's a GN modifier
        if not domain.object.modifiers:
            gn_mod = domain.object.modifiers.new(name="ProteinBlender Domain Mask", type='NODES')
            else:
            gn_mod = domain.object.modifiers.get("ProteinBlender Domain Mask")
            if not gn_mod:
                gn_mod = domain.object.modifiers.new(name="ProteinBlender Domain Mask", type='NODES')
        
        if not gn_mod.node_group:
            gn_mod.node_group = bpy.data.node_groups.new(name=f"ng_{domain.id}_mask", type='GeometryNodeTree')
        
        ng = gn_mod.node_group
        nodes = ng.nodes
        links = ng.links
        nodes.clear()

        # Group Input and Output
        group_input = nodes.new(type='NodeGroupInput')
        group_input.location = (-400, 0)
        group_output = nodes.new(type='NodeGroupOutput')
        group_output.location = (400, 0)

        # Object Info node for the parent molecule
        obj_info_node = nodes.new(type='GeometryNodeObjectInfo')
        obj_info_node.location = (-200, 200)
        obj_info_node.transform_space = 'RELATIVE' # Important for instanced molecules too
        if self.molecule.object:
            obj_info_node.inputs[0].default_value = self.molecule.object # Link to parent molecule

        # Named Attribute for chain_id_int
        chain_attr_node = nodes.new(type='GeometryNodeInputNamedAttribute')
        chain_attr_node.location = (-200, 100)
        chain_attr_node.data_type = 'INT'
        chain_attr_node.inputs["Name"].default_value = "chain_id_int"

        # Compare node for chain_id_int
        compare_chain_node = nodes.new(type='FunctionNodeCompare')
        compare_chain_node.location = (0, 100)
        compare_chain_node.data_type = 'INT'
        compare_chain_node.operation = 'EQUAL'
        compare_chain_node.inputs[2].default_value = int(chain_id_int_str) # B input

        # Named Attribute for res_id
        res_attr_node = nodes.new(type='GeometryNodeInputNamedAttribute')
        res_attr_node.location = (-200, 0)
        res_attr_node.data_type = 'INT'
        res_attr_node.inputs["Name"].default_value = "res_id"

        # Compare node for start residue (res_id >= start)
        compare_start_node = nodes.new(type='FunctionNodeCompare')
        compare_start_node.location = (0, 0)
        compare_start_node.data_type = 'INT'
        compare_start_node.operation = 'GREATER_THAN_OR_EQUAL'
        compare_start_node.inputs[2].default_value = start # B input

        # Compare node for end residue (res_id <= end)
        compare_end_node = nodes.new(type='FunctionNodeCompare')
        compare_end_node.location = (0, -100)
        compare_end_node.data_type = 'INT'
        compare_end_node.operation = 'LESS_THAN_OR_EQUAL'
        compare_end_node.inputs[2].default_value = end # B input

        # Boolean Math AND node (Chain AND Start)
        and1_node = nodes.new(type='FunctionNodeBooleanMath')
        and1_node.location = (200, 50)
        and1_node.operation = 'AND'

        # Boolean Math AND node ((Chain AND Start) AND End)
        and2_node = nodes.new(type='FunctionNodeBooleanMath')
        and2_node.location = (200, -50)
        and2_node.operation = 'AND'

        # Link nodes
        links.new(obj_info_node.outputs['Geometry'], chain_attr_node.inputs['Geometry'])
        links.new(obj_info_node.outputs['Geometry'], res_attr_node.inputs['Geometry'])
        
        links.new(chain_attr_node.outputs['Attribute'], compare_chain_node.inputs[1]) # A input
        links.new(res_attr_node.outputs['Attribute'], compare_start_node.inputs[1])   # A input
        links.new(res_attr_node.outputs['Attribute'], compare_end_node.inputs[1])     # A input

        links.new(compare_chain_node.outputs['Result'], and1_node.inputs[0])
        links.new(compare_start_node.outputs['Result'], and1_node.inputs[1])
        
        links.new(and1_node.outputs['Boolean'], and2_node.inputs[0])
        links.new(compare_end_node.outputs['Result'], and2_node.inputs[1])

        # Output the original geometry and the selection
        if not ng.outputs:
            ng.outputs.new('NodeSocketGeometry', 'Geometry')
            ng.outputs.new('NodeSocketBool', 'Selection')
        elif len(ng.outputs) < 2:
            if 'Geometry' not in ng.outputs: ng.outputs.new('NodeSocketGeometry', 'Geometry')
            if 'Selection' not in ng.outputs: ng.outputs.new('NodeSocketBool', 'Selection')
        else: # Ensure correct names if they exist
            if ng.outputs[0].name != 'Geometry': ng.outputs[0].name = 'Geometry'
            if ng.outputs[1].name != 'Selection': ng.outputs[1].name = 'Selection'

        links.new(obj_info_node.outputs['Geometry'], group_output.inputs['Geometry'])
        links.new(and2_node.outputs['Boolean'], group_output.inputs['Selection'])

        print(f"DEBUG MoleWrap._create_domain_mask_nodes: GN setup complete for domain {domain.id}")

    def get_domain_by_id(self, domain_id: str) -> Optional[DomainDefinition]:
        return self.domains.get(domain_id)

    def delete_domain(self, domain_id: str):
        domain_def = self.domains.pop(domain_id, None)
        if domain_def and domain_def.object:
            if domain_def.object.name in bpy.data.objects:
                bpy.data.objects.remove(domain_def.object, do_unlink=True)
            # Also remove associated residue sets if any were created for this domain
            self.residue_sets.pop(domain_id, None)
            print(f"Domain {domain_id} and its Blender object deleted.")
            return True
        print(f"Domain {domain_id} not found for deletion.")
        return False

    def update_domain_color(self, domain_id: str, color: Tuple[float, float, float, float]):
        domain = self.get_domain_by_id(domain_id)
        if domain and domain.object:
            # Ensure the color field attribute exists on the parent molecule
            mol_obj = self.molecule.object
            color_field_name = domain.object.get("domain_color_field_name", f"domain_color_{domain_id}")
            
            if mol_obj:
                if color_field_name not in mol_obj.data.attributes:
                    # Create the attribute (Color type, Point domain)
                    attr = mol_obj.data.attributes.new(name=color_field_name, type="FLOAT_COLOR", domain="POINT")
                    # Initialize with a default color (e.g., transparent black or white)
                    # Ensure this is done efficiently for all points.
                    # For now, it will be black by default.
                    print(f"Created color attribute '{color_field_name}' on {mol_obj.name}")
            else:
                    attr = mol_obj.data.attributes[color_field_name]
                
                # Update the domain object's stored color
                domain.object["domain_color_rgba"] = color 
                domain.color = color # Update in the definition too

                # Trigger an update of the geometry nodes that use this (if any)
                # This might involve setting a property that the GN tree is listening to,
                # or directly modifying a node input if the color is passed to the domain's GN tree.
                # For now, we assume the main molecule's material/shader will read this attribute.
                print(f"Stored color {color} for domain {domain_id} on its object and in attr '{color_field_name}'. Shader needs to use it.")
                else:
                print(f"Error: Molecule object not found for {self.identifier}")
            else:
            print(f"Error: Domain or domain object not found for {domain_id}")

    def get_all_domains(self) -> List[DomainDefinition]:
        return list(self.domains.values())

    def clear_all_domains(self):
        domain_ids_to_delete = list(self.domains.keys())
        for domain_id in domain_ids_to_delete:
            self.delete_domain(domain_id)
        print("All domains cleared.")

    def get_unique_label_asym_ids(self) -> List[str]:
        """Returns a sorted list of unique label_asym_id strings present in the molecule."""
        if hasattr(self.molecule.array, 'chain_id'): # This is label_asym_id
            return sorted(list(np.unique(self.molecule.array.chain_id).astype(str)))
        return []

    def get_chain_atoms_count(self) -> Dict[str, int]:
        """Returns a dictionary mapping label_asym_id to atom count for that chain."""
        counts = {}
        if hasattr(self.molecule.array, 'chain_id'): # This is label_asym_id
            chain_ids, atom_counts = np.unique(self.molecule.array.chain_id, return_counts=True)
            for chain_id_val, count in zip(chain_ids, atom_counts):
                counts[str(chain_id_val)] = int(count)
        return counts

    def get_int_chain_index(self, label_asym_id: str) -> Optional[int]:
        """Return the internal integer chain index for a given label_asym_id, or None if not found."""
        # Direct mapping from idx_to_label_asym_id_map
        for idx, lab in self.idx_to_label_asym_id_map.items():
            if lab == label_asym_id:
                return idx
        # Fallback mapping from auth_chain_id_map (auth asym ID to index)
        for idx, auth_lab in self.auth_chain_id_map.items():
            if auth_lab == label_asym_id:
                return idx
        return None