from typing import Optional, Dict, List
import bpy
from pathlib import Path
import numpy as np
import colorsys
import random
from mathutils import Vector

from ..utils.molecularnodes.entities import fetch, load_local
from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..utils.molecularnodes.blender import nodes
from ..utils.molecularnodes.props import MolecularNodesSceneProperties
from ..utils.molecularnodes.session import MNSession
from ..utils.molecularnodes.addon import _test_register
from .domain import Domain, DomainDefinition
from ..core.domain import ensure_domain_properties_registered

class MoleculeWrapper:
    """
    Wraps a MolecularNodes molecule and provides additional functionality
    and metadata specific to ProteinBlender
    """
    def __init__(self, molecule: Molecule, identifier: str):
        self.molecule = molecule
        self.identifier = identifier
        self.style = "surface"  # Default style
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

        #self._setup_preview_domain()
        
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
            
            # Track join nodes and final NOT node for dynamic expansion
            self.join_nodes = [self.domain_join_node]
            self.final_not = final_not
            
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

        if chain_id is not None:
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
        
    def _create_domain_with_params(self, chain_id: str, start: int, end: int, name: Optional[str] = None, auto_fill_chain: bool = True, parent_domain_id: Optional[str] = None) -> Optional[str]:
        """Internal method to create a domain with specific parameters
        
        Args:
            chain_id: The chain ID
            start: Start residue
            end: End residue
            name: Optional name for the domain
            auto_fill_chain: Whether to automatically create additional domains to fill the chain. 
                             When true, this will trigger the creation of additional domains to span
                             any areas of the chain not covered by this domain.
            parent_domain_id: Optional ID of the parent domain
        """
        # Adjust end value based on chain's residue range if needed
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        if mapped_chain in self.chain_residue_ranges:
            min_res, max_res = self.chain_residue_ranges[mapped_chain]
            start = max(min_res, start)
            if end > max_res:
                end = max_res
            
        # Create domain ID
        domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
        
        # Create domain definition
        domain = DomainDefinition(mapped_chain, start, end, name)
        domain.parent_molecule_id = self.identifier
        
        # If parent_domain_id was provided, use it
        if parent_domain_id and parent_domain_id in self.domains:
            domain.parent_domain_id = parent_domain_id
        # Otherwise, try to find a suitable parent domain based on containment
        else:
            # Find potential parent domains (domains that contain this one)
            potential_parents = []
            for existing_id, existing_domain in self.domains.items():
                if (existing_domain.chain_id == mapped_chain and
                    existing_domain.start <= start and
                    existing_domain.end >= end and
                    existing_id != domain_id):  # Avoid self-parenting
                    potential_parents.append((existing_id, existing_domain))
            
            # If potential parents found, choose the smallest one
            # (the one with the range closest to this domain)
            if potential_parents:
                # Sort by range size (ascending)
                potential_parents.sort(key=lambda x: x[1].end - x[1].start)
                domain.parent_domain_id = potential_parents[0][0]
                print(f"Auto-assigned parent domain {domain.parent_domain_id} to domain {domain_id}")
        
        # Set the domain's style to match the parent molecule
        domain.style = self.style
        
        # Create domain object (copy of parent molecule)
        if not domain.create_object_from_parent(self.molecule.object):
            print(f"Failed to create domain object for {domain_id}")
            return None
        
        # Add domain expanded property to object
        domain.object["domain_expanded"] = False
        domain.object["domain_id"] = domain_id
        domain.object["parent_molecule_id"] = self.identifier
        
        # Ensure all domain properties are registered before using them
        ensure_domain_properties_registered()
        
        # Set the domain_style property - safely handle the case if it's not registered yet
        try:
            # Try to set using the property directly
            domain.object.domain_style = domain.style
        except (AttributeError, TypeError):
            # Fallback to using custom property - this will be picked up when the property is registered
            domain.object["domain_style"] = domain.style
            print(f"Set domain style using custom property: {domain.style}")
        
        # Set the domain's parent using the centralized method
        self._set_domain_parent(domain, domain.parent_domain_id)
        
        # Ensure the domain's node network uses the same structure as the preview domain
        self._setup_domain_network(domain, chain_id, start, end)
        
        # --- Set the initial pivot using the new robust method --- 
        if domain.object: # Check again if object exists before setting pivot
            print(f"Setting initial pivot for new domain {domain.name} within create_domain")
            start_aa_pos = self._find_residue_alpha_carbon_pos(bpy.context, domain, residue_target='START') # Call internal method
            
            if start_aa_pos:
                if not self._set_domain_origin_and_update_matrix(bpy.context, domain, start_aa_pos): # Call internal method
                     # Optionally report a warning if setting pivot failed, though the helper logs errors
                     pass 
            else:
                 # Optionally report a warning if Cα not found, though the helper logs errors
                 pass
        # --- End initial pivot setting --- 

        # Update residue assignments
        self._update_residue_assignments(domain)
        
        # Create mask nodes in the parent molecule to hide this domain region
        self._create_domain_mask_nodes(domain_id, chain_id, start, end)
        
        # Add the domain to our domain collection
        self.domains[domain_id] = domain
        
        # Check if we need to create additional domains to span the rest of the chain
        # This is useful for visualizing the entire chain when users only select a portion
        if auto_fill_chain:
            self._create_additional_domains_to_span_chain(chain_id, start, end, mapped_chain, min_res, max_res, domain_id)
        
        return domain_id

    # --- Moved Helper: Find Alpha Carbon Position --- 
    def _find_residue_alpha_carbon_pos(self, context, domain: DomainDefinition, residue_target: str) -> Optional[Vector]:
        """
        Finds the 3D coordinates of the Alpha Carbon (CA) for a specific residue.
        For START, searches forward from domain.start until a CA is found.
        For END, searches backward from domain.end until a CA is found.

        Returns:
            mathutils.Vector: The coordinates if found, otherwise None.
        """
        try:
            mol_obj = self.molecule.object  # Use self.molecule.object
            if not mol_obj or not domain.object or not hasattr(mol_obj.data, "attributes"):
                print("Error: Molecule object, domain object, or attributes not found.")
                return None

            attrs = mol_obj.data.attributes
            # print(f"DEBUG: Available attributes on {mol_obj.name}.data: {list(attrs.keys())}") # Keep commented out for now

            # Determine residue number attribute
            residue_attr_name = None
            if "residue_number" in attrs:
                residue_attr_name = "residue_number"
            elif "res_id" in attrs:
                residue_attr_name = "res_id"
            else:
                print("Error: Residue number attribute ('residue_number' or 'res_id') not found.")
                return None

            # Check for required attributes (adjust if needed, e.g., is_alpha_carbon instead of atom_name)
            required_attrs = ["is_alpha_carbon", "chain_id", residue_attr_name, "position"]
            if not all(attr in attrs for attr in required_attrs):
                # Check for atom_name as fallback for older MN versions?
                if "atom_name" not in attrs: 
                   print(f"Error: Missing one or more required attributes: {required_attrs}")
                   return None
                else: # If atom_name exists but is_alpha_carbon doesn't, proceed with warning?
                   print("Warning: 'is_alpha_carbon' not found, will attempt using 'atom_name' but might be unreliable.")
                   # We'll handle checking atom_name later if is_alpha_carbon fails
                   pass

            # Get domain info
            domain_chain_id = domain.chain_id
            start_res = domain.start
            end_res = domain.end
            print(f"Searching for Cα for {residue_target} in chain '{domain_chain_id}', range {start_res}-{end_res}")

            # --- Helper function for chain IDs --- (Can remain nested or become internal method)
            def get_possible_chain_ids(chain_id):
                 # ... (implementation remains the same) ...
                 search_ids = [chain_id]
                 if isinstance(chain_id, str) and chain_id.isalpha():
                     try:
                         numeric_chain = ord(chain_id.upper()) - ord('A')
                         search_ids.append(numeric_chain)
                     except Exception: pass
                 elif isinstance(chain_id, (str, int)) and str(chain_id).isdigit():
                     try:
                         int_chain_id = int(chain_id)
                         alpha_chain = chr(int_chain_id + ord('A'))
                         search_ids.append(alpha_chain)
                         search_ids.append(int_chain_id)
                         search_ids.append(str(int_chain_id))
                     except Exception: pass
                 return list(set(filter(None.__ne__, search_ids)))
            # --- End helper --- 

            search_chain_ids = get_possible_chain_ids(domain_chain_id)
            print(f"Possible chain IDs to search: {search_chain_ids}")

            # Get attribute data arrays
            chain_ids_data = attrs["chain_id"].data
            res_nums_data = attrs[residue_attr_name].data
            positions_data = attrs["position"].data
            
            is_alpha_carbon_data = None
            is_alpha_carbon_attr = attrs.get("is_alpha_carbon")
            if is_alpha_carbon_attr:
                is_alpha_carbon_data = is_alpha_carbon_attr.data
            else:
                # Fallback: Try getting atom_name data if is_alpha_carbon isn't present
                atom_names_data = attrs.get("atom_name", None)
                if atom_names_data:
                   atom_names_data = atom_names_data.data
                else:
                    print("Error: Neither 'is_alpha_carbon' nor 'atom_name' attribute found.")
                    return None

            # Determine search range based on target
            residue_search_range = None
            if residue_target == 'START':
                residue_search_range = range(start_res, end_res + 1)
            elif residue_target == 'END':
                residue_search_range = range(end_res, start_res - 1, -1) # Iterate backwards
            else:
                print(f"Error: Invalid residue_target '{residue_target}'")
                return None

            print(f"Residue search order: {list(residue_search_range)}")

            # Map geometry node chain_id attribute to actual chain IDs via object custom property
            obj_chain_ids_list = None
            if hasattr(mol_obj, 'keys') and "chain_ids" in mol_obj.keys():
                obj_chain_ids_list = mol_obj["chain_ids"]

            # --- Search for the first CA encountered in the specified range order ---
            for target_res_num in residue_search_range:
                print(f"Checking residue {target_res_num}...")
                for atom_idx in range(len(positions_data)):
                    try:
                        atom_res_num = res_nums_data[atom_idx].value
                        if atom_res_num != target_res_num:
                            continue 
                        
                        # Determine actual chain ID for this atom using custom mapping
                        chain_id_val = chain_ids_data[atom_idx].value
                        if obj_chain_ids_list is not None:
                            try:
                                actual_chain_id = obj_chain_ids_list[chain_id_val]
                            except (IndexError, TypeError):
                                actual_chain_id = chain_id_val
                        else:
                            actual_chain_id = chain_id_val
                        # Skip atoms not in the target chain
                        if str(actual_chain_id) != str(domain_chain_id):
                            continue 
                        
                        # --- Check using the preferred method (is_alpha_carbon) --- 
                        is_ca = False
                        if is_alpha_carbon_data: 
                            is_ca = is_alpha_carbon_data[atom_idx].value
                        elif atom_names_data: # Fallback to checking name 'CA'
                            atom_name = str(atom_names_data[atom_idx].value).strip().upper()
                            if atom_name == "CA":
                                is_ca = True
                        
                        if is_ca:
                            # Get local position from attributes
                            local_pos = positions_data[atom_idx].vector
                            
                            # *** FIX: Transform local position to world space using protein's matrix_world ***
                            # We need to apply the parent protein's transformation to get the correct world position
                            world_pos = mol_obj.matrix_world @ local_pos
                            
                            print(f"Found Cα for target '{residue_target}' in residue {target_res_num} at index {atom_idx}")
                            print(f"  Local position: {local_pos}")
                            print(f"  World position: {world_pos}")
                            print(f"  Parent protein position: {mol_obj.location}")
                            
                            return world_pos  # Return the world position, not local position
                            
                    except (AttributeError, IndexError, ValueError, TypeError) as e_inner:
                        continue # Skip malformed atom data
                
                print(f"No Cα found in residue {target_res_num}.")

            # If we finish the loop without finding any CA in the entire range
            print(f"Error: No Alpha Carbon (CA) found within range {start_res}-{end_res} for chain {domain_chain_id}.")
            return None

        except Exception as e:
            print(f"Error in _find_residue_alpha_carbon_pos: {e}")
            import traceback
            traceback.print_exc()
            return None
    # --- End Moved Helper --- 

    # --- Moved Helper: Set Origin and Update Matrix --- 
    def _set_domain_origin_and_update_matrix(self, context, domain: DomainDefinition, target_pos: Vector):
        """
        Sets the domain object's origin to target_pos and updates initial_matrix_local.
        
        Args:
            context: The current Blender context
            domain: The DomainDefinition instance
            target_pos: The world space position to set as origin
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not domain or not domain.object or target_pos is None:
            print("Error: Invalid domain, object, or target position for setting origin.")
            return False

        print(f"Setting origin for domain {domain.name} to position {target_pos}")
        
        # Store the original cursor location
        orig_cursor_loc = context.scene.cursor.location.copy()
        
        try:
            # Set the 3D cursor to our target position (in world space)
            context.scene.cursor.location = target_pos
            
            # Deselect all objects
            bpy.ops.object.select_all(action='DESELECT')
            
            # Select only our domain object
            domain.object.select_set(True)
            context.view_layer.objects.active = domain.object
            
            # Set origin to cursor position
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')
            
            # Store the domain's local matrix for resetting later
            # This is critical for Reset Transform functionality
            domain.object["initial_matrix_local"] = [list(row) for row in domain.object.matrix_local]
            
            print(f"Successfully set origin for {domain.name} at {target_pos}")
            print(f"Stored initial_matrix_local: {domain.object.matrix_local}")
            
            return True
            
        except Exception as e:
            print(f"Error in _set_domain_origin_and_update_matrix: {e}")
            import traceback
            traceback.print_exc()
            
            # Restore cursor location on error
            context.scene.cursor.location = orig_cursor_loc
            return False
        
        finally:
            # Always restore cursor location
            context.scene.cursor.location = orig_cursor_loc
    # --- End Moved Helper --- 

    def _create_additional_domains_to_span_chain(self, chain_id: str, start: int, end: int, mapped_chain: str, min_res: int, max_res: int, domain_id: str):
        """Create additional domains to span the entire chain when a partial domain is created.
        
        This function is called after creating a domain that doesn't span the entire chain.
        It automatically creates up to two additional domains to ensure the entire chain is visualized:
        1. One domain from the chain's minimum residue to the start of the created domain (if needed)
        2. One domain from the end of the created domain to the chain's maximum residue (if needed)
        
        For example, if Chain A spans residues 1-150 and the user creates a domain for residues 50-75,
        this function will automatically create domains for residues 1-49 and 76-150.
        
        Args:
            chain_id: The original chain ID
            start: Start residue of the created domain
            end: End residue of the created domain
            mapped_chain: The mapped chain ID
            min_res: Minimum residue ID in the chain
            max_res: Maximum residue ID in the chain
            domain_id: The ID of the created domain
        """
        # Check if the domain spans the entire chain
        if start <= min_res and end >= max_res:
            # No additional domains needed
            return
        
        # Create gaps to fill
        # Gap 1: Before the domain (if needed)
        if start > min_res:
            # Check if a domain already exists in this range
            before_start = min_res
            before_end = start - 1
            
            if not self._check_domain_overlap(mapped_chain, before_start, before_end):
                # Create domain from min_res to start-1
                print(f"Creating additional domain to span the beginning of chain {chain_id}: {before_start}-{before_end}")
                before_domain_id = self._create_domain_with_params(
                    chain_id=chain_id,
                    start=before_start,
                    end=before_end,
                    name=f"Domain_{chain_id}_{before_start}_{before_end}",
                    auto_fill_chain=False,  # Prevent recursion
                    parent_domain_id=None   # Don't set parent - will default to original protein
                )
                
                # Ensure color is properly synchronized for the flanking domain
                if before_domain_id and before_domain_id in self.domains:
                    before_domain = self.domains[before_domain_id]
                    if before_domain.object and before_domain.node_group:
                        # Update the color in both the node tree and UI
                        self.update_domain_color(before_domain_id, before_domain.color)
                        before_domain.object.domain_color = before_domain.color
            else:
                print(f"Skipping creation of beginning domain ({before_start}-{before_end}) due to overlap with existing domain")
        
        # Gap 2: After the domain (if needed)
        if end < max_res:
            # Check if a domain already exists in this range
            after_start = end + 1
            after_end = max_res
            
            if not self._check_domain_overlap(mapped_chain, after_start, after_end):
                # Create domain from end+1 to max_res
                print(f"Creating additional domain to span the end of chain {chain_id}: {after_start}-{after_end}")
                after_domain_id = self._create_domain_with_params(
                    chain_id=chain_id,
                    start=after_start,
                    end=after_end,
                    name=f"Domain_{chain_id}_{after_start}_{after_end}",
                    auto_fill_chain=False,  # Prevent recursion
                    parent_domain_id=None   # Don't set parent - will default to original protein
                )
                
                # Ensure color is properly synchronized for the flanking domain
                if after_domain_id and after_domain_id in self.domains:
                    after_domain = self.domains[after_domain_id]
                    if after_domain.object and after_domain.node_group:
                        # Update the color in both the node tree and UI
                        self.update_domain_color(after_domain_id, after_domain.color)
                        after_domain.object.domain_color = after_domain.color
            else:
                print(f"Skipping creation of end domain ({after_start}-{after_end}) due to overlap with existing domain")
        
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
            # Use the full chain range instead of limiting to 30 residues
            return (min_res, max_res)
            
        # Find gaps between domains
        current_pos = min_res
        for start, end in chain_domains:
            if current_pos < start:
                # Found a gap
                gap_size = start - current_pos
                # If gap is large enough for a sensible domain (at least 5 residues)
                if gap_size >= 5:
                    # Use the entire gap size instead of limiting to 30
                    return (current_pos, start - 1)
            # Move current position to after this domain
            current_pos = max(current_pos, end + 1)
            
        # Check if there's space after the last domain
        if current_pos <= max_res:
            remaining = max_res - current_pos + 1
            # If remaining space is large enough for a sensible domain
            if remaining >= 5:
                # Use the entire remaining space instead of limiting to 30
                return (current_pos, max_res)
                
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

    def update_domain(self, domain_id: str, chain_id: str, start: int, end: int) -> str:
        """Update an existing domain with new parameters
        
        Args:
            domain_id: Current domain ID
            chain_id: New chain ID
            start: New start residue
            end: New end residue
            
        Returns:
            str: The new domain ID (which may be different if range changed)
        """
        print(f"DEBUG: update_domain called for ID: {domain_id}, New Range: {chain_id} ({start}-{end})") # DEBUG
        if domain_id not in self.domains:
            print(f"DEBUG: update_domain - Domain ID {domain_id} not found.") # DEBUG
            return domain_id
            
        try:
            domain = self.domains[domain_id]
            print(f"DEBUG: update_domain - Found domain object: {domain.name if domain else 'None'}") # DEBUG
            
            # Check for overlaps with other domains
            if self._check_domain_overlap(chain_id, start, end, exclude_domain_id=domain_id):
                print(f"Domain overlap detected for chain {chain_id} ({start}-{end})")
                return domain_id
                
            # Update domain definition
            print(f"DEBUG: update_domain - Updating domain definition {domain.name} properties.") # DEBUG
            domain.chain_id = chain_id
            domain.start = start
            domain.end = end
            
            # Generate new domain ID
            new_domain_id = f"{self.identifier}_{chain_id}_{start}_{end}"
            print(f"DEBUG: update_domain - New potential domain ID: {new_domain_id}") # DEBUG
            
            # Update domain object name
            if domain.object:
                domain.object.name = f"{domain.name}_{chain_id}_{start}_{end}"
                domain.object["domain_id"] = new_domain_id
            
            # Update domain node network
            print(f"DEBUG: update_domain - Calling _setup_domain_network for {new_domain_id}") # DEBUG
            self._setup_domain_network(domain, chain_id, start, end)
            
            # Update domain mask nodes
            print(f"DEBUG: update_domain - Calling _delete/_create_domain_mask_nodes for {domain_id} -> {new_domain_id}") # DEBUG
            self._delete_domain_mask_nodes(domain_id) # Delete old mask
            self._create_domain_mask_nodes(new_domain_id, chain_id, start, end) # Create new mask
            
            # Update residue assignments
            self._update_residue_assignments(domain)
            
            # If the domain ID has changed, update the dictionary
            if domain_id != new_domain_id:
                print(f"DEBUG: update_domain - Domain ID changed from {domain_id} to {new_domain_id}. Updating dictionary.") # DEBUG
                self.domains[new_domain_id] = domain
                del self.domains[domain_id]
                return new_domain_id
            
            return domain_id
            
        except Exception as e:
            print(f"Error updating domain: {str(e)}")
            import traceback
            traceback.print_exc()
            return domain_id

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

    def delete_domain(self, domain_id: str) -> Optional[str]:
        """Delete a domain and its object.

        If the domain is flanked by other domains on the same chain, the adjacent
        domain (preferring the preceding one) will expand to fill the gap.
        
        Returns:
            Optional[str]: The ID of the domain that filled the gap, if any.
        """
        if domain_id not in self.domains:
            return None
        
        # Get domain info before deletion
        domain_to_delete = self.domains[domain_id]
        chain_id = domain_to_delete.chain_id
        start = domain_to_delete.start
        end = domain_to_delete.end
        deleted_domain_name = domain_to_delete.name # For logging
        
        # Find child domains that need reparenting
        children_to_reparent = []
        for child_id, child_domain in self.domains.items():
            if hasattr(child_domain, 'parent_domain_id') and child_domain.parent_domain_id == domain_id:
                children_to_reparent.append(child_id)
                
        # Find the deleted domain's parent (will be inherited by children if no merge/expand occurs)
        deleted_domain_parent_id = getattr(domain_to_delete, 'parent_domain_id', None)
            
        # --- Find adjacent domains on the same chain --- 
        domain_before = None # Tuple: (id, domain_obj) ending right before 'start'
        domain_after = None  # Tuple: (id, domain_obj) starting right after 'end'

        for adj_domain_id, adj_domain in self.domains.items():
            if adj_domain_id != domain_id and adj_domain.chain_id == chain_id:
                if adj_domain.end == start - 1:
                    domain_before = (adj_domain_id, adj_domain)
                elif adj_domain.start == end + 1:
                    domain_after = (adj_domain_id, adj_domain)
        
        # --- Determine update target and range BEFORE deletion --- 
        update_target_id = None
        update_new_start = -1
        update_new_end = -1
        final_reparent_target_id = deleted_domain_parent_id # Default if no update happens

        if domain_before:
            # Plan to expand 'before' domain
            update_target_id = domain_before[0]
            update_new_start = domain_before[1].start
            update_new_end = end 
            final_reparent_target_id = update_target_id # Reparent children to this domain after update
            print(f"Planning to update domain {update_target_id} to expand range to {update_new_start}-{update_new_end}")

        elif domain_after:
            # Plan to expand 'after' domain 
            update_target_id = domain_after[0]
            update_new_start = start 
            update_new_end = domain_after[1].end
            final_reparent_target_id = update_target_id # Reparent children to this domain after update
            print(f"Planning to update domain {update_target_id} to expand range to {update_new_start}-{update_new_end}")

        # --- Perform Deletion FIRST --- 
        print(f"Deleting original domain {deleted_domain_name} ({domain_id}) now.")
        self._delete_domain_direct(domain_id)
        
        # --- Perform Update AFTER Deletion --- 
        updated_domain_id_result = None
        if update_target_id is not None:
            print(f"Executing update for domain {update_target_id} to range {update_new_start}-{update_new_end}")
            # Call update_domain. The returned ID might be new if the range change was significant
            # enough to alter the standard ID format (though less likely with simple expansion)
            updated_domain_id_result = self.update_domain(update_target_id, chain_id, update_new_start, update_new_end)
            final_reparent_target_id = updated_domain_id_result # Ensure reparenting uses the potentially new ID
        else:
             print("No adjacent domain found to update.")

        # --- Final Steps --- 
        
        # Reparent any children of the originally deleted domain
        print(f"Reparenting children to target: {final_reparent_target_id}")
        self._reparent_child_domains(children_to_reparent, final_reparent_target_id)
        
        # Return the ID of the domain that filled the gap (potentially the new ID after update)
        return updated_domain_id_result

    def _reparent_child_domains(self, child_domain_ids: List[str], new_parent_id: Optional[str]):
        """Reparent child domains to a new parent
        
        When a parent domain is deleted, its children inherit the parent's parent.
        If no parent exists in the hierarchy, children are parented to the original protein.
        
        Args:
            child_domain_ids: List of domain IDs to reparent
            new_parent_id: ID of the new parent domain (or None to use original protein as parent)
        """
        if not child_domain_ids:
            return
        
        print(f"Reparenting {len(child_domain_ids)} domains to new parent: {new_parent_id}")
        
        # Find all domains that are children of the domains we're reparenting
        # This is for two-level+ hierarchies
        grandchildren = {}
        for domain_id, domain in self.domains.items():
            if hasattr(domain, 'parent_domain_id') and domain.parent_domain_id in child_domain_ids:
                if domain.parent_domain_id not in grandchildren:
                    grandchildren[domain.parent_domain_id] = []
                grandchildren[domain.parent_domain_id].append(domain_id)
        
        # Reparent each child domain
        for child_id in child_domain_ids:
            if child_id not in self.domains:
                continue
            
            child_domain = self.domains[child_id]
            
            # Set new parent
            self._set_domain_parent(child_domain, new_parent_id)
            
            # Recursively update any grandchildren of this domain to preserve hierarchy
            if child_id in grandchildren:
                for grandchild_id in grandchildren[child_id]:
                    if grandchild_id in self.domains:
                        grandchild = self.domains[grandchild_id]
                        self._set_domain_parent(grandchild, child_id)
        
        print(f"Reparenting complete")

    def _set_domain_parent(self, domain: DomainDefinition, parent_domain_id: Optional[str]):
        """Set a domain's parent, handling both data structure and Blender object parenting.
        
        This is a helper method to centralize parenting logic in one place.
        
        Args:
            domain: The domain to set the parent for
            parent_domain_id: ID of the parent domain (or None to use original protein)
        """
        # Check if the parent domain exists
        parent_obj = None
        if parent_domain_id and parent_domain_id in self.domains:
            parent_domain = self.domains[parent_domain_id]
            if parent_domain.object:
                parent_obj = parent_domain.object
        
        # If no valid parent domain, use original protein as parent
        if parent_obj is None:
            parent_obj = self.molecule.object
            print(f"Using original protein as parent for domain {domain.name}")
        
        # Update parent domain ID in data structure
        domain.parent_domain_id = parent_domain_id
        
        # Update Blender parenting relationship
        if domain.object:
            try:
                # Set the parent in Blender
                domain.object.parent = parent_obj
                
                # Reset the matrix to maintain world position
                domain.object.matrix_parent_inverse = parent_obj.matrix_world.inverted()
            except Exception as e:
                print(f"Error updating parent for {domain.name}: {str(e)}")

    def cleanup(self):
        """Remove all domains and clean up resources"""
        # First clean up all domains
        for domain_id in list(self.domains.keys()):
            self.delete_domain(domain_id)
        
        # Clean up domain infrastructure nodes in parent molecule
        if self.molecule and self.molecule.object:
            parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
            if parent_modifier and parent_modifier.node_group:
                parent_node_group = parent_modifier.node_group
                
                # Clean up domain join node and its node tree
                if self.domain_join_node:
                    # Remove the node tree first
                    if self.domain_join_node.node_tree:
                        bpy.data.node_groups.remove(self.domain_join_node.node_tree, do_unlink=True)
                    # Then remove the node itself
                    parent_node_group.nodes.remove(self.domain_join_node)
                    self.domain_join_node = None
                
                # Clean up any remaining domain-related nodes
                nodes_to_remove = []
                for node in parent_node_group.nodes:
                    if (node.name.startswith("Domain_Chain_Select_") or 
                        node.name.startswith("Domain_Res_Select_") or
                        node.name == "Domain_Final_Not" or
                        node.name == "Domain_Boolean_Join"):
                        nodes_to_remove.append(node)
                
                # Remove all links connected to these nodes first
                for link in list(parent_node_group.links):
                    if (link.from_node in nodes_to_remove or 
                        link.to_node in nodes_to_remove):
                        parent_node_group.links.remove(link)
                
                # Then remove the nodes
                for node in nodes_to_remove:
                    parent_node_group.nodes.remove(node)
        
        # Clear all domain-related dictionaries
        self.domains.clear()
        self.domain_mask_nodes.clear()
        self.residue_assignments.clear()

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

    def _setup_domain_network(self, domain: DomainDefinition, chain_id: str, start: int, end: int):
        """Set up the domain's node network using the same structure as the preview domain"""
        print(f"DEBUG: _setup_domain_network called for domain {domain.name}, Range: {chain_id} ({start}-{end})") # DEBUG
        if not domain.object or not domain.node_group:
            print("DEBUG: _setup_domain_network - Domain object or node group is missing") # DEBUG
            return False
            
        try:
            # Get references to key nodes
            input_node = nodes.get_input(domain.node_group)
            output_node = nodes.get_output(domain.node_group)
            
            if not (input_node and output_node):
                print("DEBUG: _setup_domain_network - Could not find input/output nodes in domain node group") # DEBUG
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
            print(f"DEBUG: _setup_domain_network - Setting Res ID Range Min: {start}, Max: {end}") # DEBUG
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
                # Generate a unique color based on the domain index
                # This helps visually distinguish domains from each other
                
                # Get domain index based on current number of domains
                domain_index = len(self.domains)
                
                # Generate a color using HSV for better distribution
                # Start with golden ratio for good distribution
                golden_ratio = 0.618033988749895
                hue = (domain_index * golden_ratio) % 1.0
                saturation = 0.8
                value = 0.9
                
                # Convert to RGB and add alpha
                rgb = colorsys.hsv_to_rgb(hue, saturation, value)
                domain_color = (rgb[0], rgb[1], rgb[2], 1.0)
                
                # Store the generated color in the domain object for UI synchronization
                domain.color = domain_color
                
                # Also set the domain_color property on the Blender object for UI
                if domain.object:
                    domain.object["domain_color"] = domain_color
                
                color_emit = nodes.add_custom(domain.node_group, "Color Common")
                color_emit.location = (select_res_id_range.location.x - 400, select_res_id_range.location.y)
                
                # Create a unique node tree for this domain to ensure independent color control
                original_node_tree = color_emit.node_tree
                new_node_tree_name = f"Color Common_{domain.id}"
                
                # Create a copy of the node tree with a unique name
                new_node_tree = original_node_tree.copy()
                new_node_tree.name = new_node_tree_name
                color_emit.node_tree = new_node_tree
                
                # Set the domain color using our generated color
                if "Carbon" in color_emit.inputs:
                    color_emit.inputs["Carbon"].default_value = domain_color
                elif len(color_emit.inputs) > 0 and hasattr(color_emit.inputs[0], "default_value"):
                    color_emit.inputs[0].default_value = domain_color
            
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
                # Create style node if not found, using the domain's style property
                style_node_name = "Style Ribbon"  # Default fallback
                
                # Get the style node name from the domain's style property
                from ..utils.molecularnodes.blender.nodes import styles_mapping
                if domain.style in styles_mapping:
                    style_node_name = styles_mapping[domain.style]
                
                # Create the style node
                style_node = nodes.add_custom(domain.node_group, style_node_name)
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
            print(f"DEBUG: Error in _setup_domain_network: {str(e)}") # DEBUG
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
        print(f"DEBUG: _create_domain_mask_nodes called for ID: {domain_id}, Range: {chain_id} ({start}-{end})") # DEBUG
        if not self.molecule.object:
            return
        
        # Get the parent molecule's node group
        parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
        if not parent_modifier or not parent_modifier.node_group:
            print("DEBUG: _create_domain_mask_nodes - Parent molecule has no valid node group") # DEBUG
            return
            
        parent_node_group = parent_modifier.node_group
        
        try:
            # Find main style node
            main_style_node = self.get_main_style_node()
            if not main_style_node:
                print("DEBUG: _create_domain_mask_nodes - Could not find main style node in parent molecule") # DEBUG
                return
            
            # Check if domain infrastructure is set up
            if self.domain_join_node is None:
                print("DEBUG: _create_domain_mask_nodes - Domain infrastructure not set up. Call _setup_protein_domain_infrastructure first.") # DEBUG
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
            
            # Step 5: Find next available input on the current join node
            # Use the most recent join node for input slots
            last_join = self.join_nodes[-1]
            available_input = None
            for i in range(1, 9):  # Check inputs 1-8
                input_name = f"Input_{i}"
                if input_name in last_join.inputs and not last_join.inputs[input_name].is_linked:
                    available_input = input_name
                    break
            
            # If all slots are filled, create an overflow join and chain it
            if available_input is None:
                # Create a new multi-boolean OR for overflow
                overflow_group = nodes.create_multi_boolean_or()
                overflow_join = parent_node_group.nodes.new("GeometryNodeGroup")
                overflow_join.node_tree = overflow_group
                overflow_join.location = (last_join.location.x + 400, last_join.location.y)
                overflow_join.name = f"Domain_Boolean_Join_{len(self.join_nodes) + 1}"
                # Chain previous join result into new join's first input
                parent_node_group.links.new(last_join.outputs["Result"], overflow_join.inputs["Input_1"])
                # Reconnect final_not to take its input from the new join
                for link in list(self.final_not.inputs[0].links):
                    parent_node_group.links.remove(link)
                parent_node_group.links.new(overflow_join.outputs["Result"], self.final_not.inputs[0])
                # Track new join node and use it for remaining inputs
                self.join_nodes.append(overflow_join)
                # Switch to using this new join and locate its first free slot
                last_join = overflow_join
                for i in range(1, 9):
                    input_name = f"Input_{i}"
                    if input_name in last_join.inputs and not last_join.inputs[input_name].is_linked:
                        available_input = input_name
                        break
            
            # Step 6: Connect residue selection to the appropriate join node
            # First remove any existing connections to this input slot
            if last_join.inputs[available_input].is_linked:
                for link in list(last_join.inputs[available_input].links):
                    parent_node_group.links.remove(link)
            # Connect residue selection output to that join input
            parent_node_group.links.new(res_select.outputs["Selection"], last_join.inputs[available_input])
            
            # Store the nodes for future reference
            self.domain_mask_nodes[domain_id] = (chain_select, res_select)
            
            # Remove any direct connections between chain selection and style node
            for link in list(parent_node_group.links):
                if (link.from_node == chain_select and 
                    link.to_node == main_style_node and 
                    link.to_socket.name == "Selection"):
                    parent_node_group.links.remove(link)
            
        except Exception as e:
            print(f"DEBUG: Error in _create_domain_mask_nodes: {str(e)}") # DEBUG
            import traceback
            traceback.print_exc()

    def _check_domain_overlap(self, chain_id: str, start: int, end: int, exclude_domain_id: Optional[str] = None) -> bool:
        """Check if proposed domain overlaps with existing domains"""
        for domain_id, domain in self.domains.items():
            # Skip the domain we're updating
            if exclude_domain_id and domain_id == exclude_domain_id:
                continue
            # Check for true overlap: ranges must overlap, not just touch at endpoints
            if domain.chain_id == chain_id and max(domain.start, start) <= min(domain.end, end):
                return True
        return False
        
    def _update_residue_assignments(self, domain: DomainDefinition):
        """Track which residues are assigned to which domains"""
        for res in range(domain.start, domain.end + 1):
            key = (domain.chain_id, res)
            self.residue_assignments[key] = domain.name

    def update_domain_color(self, domain_id: str, color: tuple) -> bool:
        """Update the color of a domain
        
        Args:
            domain_id (str): The ID of the domain to update
            color (tuple): The new color as an RGBA tuple (r, g, b, a)
            
        Returns:
            bool: True if successful, False otherwise
        """
        print(f"Updating domain color for {domain_id}")
        if domain_id not in self.domains or not self.domains[domain_id].node_group:
            print(f"Domain {domain_id} not found")
            return False
            
        domain = self.domains[domain_id]
        try:
            # Update the stored color in the domain object for consistency
            domain.color = color
            
            for node in domain.node_group.nodes:
                if node.name == "Color Common":
                    # Use the tuple values directly instead of trying to access attributes
                    print(f"Setting color to {color[0]}, {color[1]}, {color[2]}, {color[3]}")
                    # Set the default_value directly with the color tuple
                    node.inputs["Carbon"].default_value = color
                    return True
        except Exception as e:
            print(f"Error updating domain color: {str(e)}")
        return False
        
    def get_sorted_domains(self) -> Dict[str, DomainDefinition]:
        """
        Returns domains sorted by their start residue ID.
        This ensures consistent display order in the UI.
        """
        # Sort the domains by chain first, then by start residue
        sorted_items = sorted(
            self.domains.items(), 
            key=lambda x: (x[1].chain_id, x[1].start)
        )
        return dict(sorted_items)

    def _delete_domain_direct(self, domain_id: str):
        """Internal method to delete a domain without adjusting adjacent domains"""
        # Delete domain mask nodes in parent molecule
        self._delete_domain_mask_nodes(domain_id)
        
        # Clean up domain object and node group
        self.domains[domain_id].cleanup()
        
        # Remove from domains dictionary
        del self.domains[domain_id]

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