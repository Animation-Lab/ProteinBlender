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
            
            # Get chain mapping if available
            mapping_str = self.object.data.get("chain_mapping_str", "")
            chain_mapping = {}
            if mapping_str:
                for pair in mapping_str.split(","):
                    if ":" in pair:
                        k, v = pair.split(":")
                        chain_mapping[int(k)] = v
            
            # Map numeric IDs to author chain IDs
            mapped_chains = {}
            for chain_id in numeric_chain_ids:
                mapped_chain_id = chain_mapping.get(chain_id, str(chain_id))
                mapped_chains[str(mapped_chain_id)] = chain_id

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
        return None # Changed from [] to None to match original return type for this specific path
        
    def _create_domain_with_params(self, chain_id: str, start: int, end: int, name: Optional[str] = None, 
                                   auto_fill_chain: bool = True, 
                                   parent_domain_id: Optional[str] = None,
                                   fill_boundaries_start: Optional[int] = None,
                                   fill_boundaries_end: Optional[int] = None) -> List[str]: # Changed return type
        """Internal method to create a domain with specific parameters
        
        Args:
            chain_id: The chain ID
            start: Start residue
            end: End residue
            name: Optional name for the domain
            auto_fill_chain: Whether to automatically create additional domains to fill the chain/context.
            parent_domain_id: Optional ID of the parent domain
            fill_boundaries_start: Optional start residue for the context to fill (used by auto_fill_chain).
            fill_boundaries_end: Optional end residue for the context to fill (used by auto_fill_chain).
        Returns:
            A list of domain IDs created (the primary one, plus any auto-filled ones).
        """
        created_domain_ids_list = []

        # Adjust end value based on chain's residue range if needed
        chain_id_int = int(chain_id) if isinstance(chain_id, str) and chain_id.isdigit() else chain_id
        mapped_chain = self.chain_mapping.get(chain_id_int, str(chain_id))
        if mapped_chain in self.chain_residue_ranges:
            min_res_chain, max_res_chain = self.chain_residue_ranges[mapped_chain]
            start = max(min_res_chain, start)
            end = min(max_res_chain, end) # Clamp end to max_res_chain first
            end = max(start, end)       # Ensure end is not less than start
            
        # Generate default name if None is provided
        generated_name = None
        if name is None:
            # Default name format: "Chain <MappedChainID>: <start>-<end>"
            generated_name = f"Chain {mapped_chain}: {start}-{end}"
            
        # Create domain ID - use a sanitized version of the name (original or generated) for more robust IDs
        # This helps if names have spaces or special characters that might be problematic in IDs.
        name_for_id = name if name is not None else generated_name
        sanitized_name_part = "".join(c if c.isalnum() or c in '-_' else '_' for c in name_for_id)
        domain_id = f"{self.identifier}_{mapped_chain}_{start}_{end}_{sanitized_name_part}"
        
        # Prevent duplicate domains more robustly: if this domain already exists, return its ID
        idx = 0
        base_domain_id = domain_id
        while domain_id in self.domains:
            idx += 1
            domain_id = f"{base_domain_id}_{idx}"
            print(f"Domain ID collision, trying {domain_id}")

        # Create domain definition, using generated_name if original name was None
        domain = DomainDefinition(mapped_chain, start, end, name if name is not None else generated_name)
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
        
        # Generate a default color for this new domain using golden ratio for color distribution
        try:
            domain_index = len(self.domains)
            golden_ratio = 0.618033988749895
            hue = (domain_index * golden_ratio) % 1.0
            saturation = 0.8
            value = 0.9
            rgb = colorsys.hsv_to_rgb(hue, saturation, value)
            domain_color = (rgb[0], rgb[1], rgb[2], 1.0)
            domain.color = domain_color
            # Set the Blender object property for UI color picker
            if domain.object:
                domain.object.domain_color = domain_color
        except Exception as e:
            print(f"Warning: failed to assign default domain color: {e}")
        
        # Ensure the domain's node network uses the same structure as the preview domain
        self._setup_domain_network(domain, chain_id, start, end)
        
        # --- Set the initial pivot using the new robust method --- 
        if domain.object: # Check again if object exists before setting pivot
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
        created_domain_ids_list.append(domain_id) # Add primary domain to list
        
        # Check if we need to create additional domains to span the rest of the chain/context
        if auto_fill_chain:
            # Determine the effective min/max residues for filling.
            # If fill_boundaries are provided, use them. Otherwise, use full chain boundaries.
            effective_min_res = fill_boundaries_start if fill_boundaries_start is not None else self.chain_residue_ranges.get(mapped_chain, (start, end))[0]
            effective_max_res = fill_boundaries_end if fill_boundaries_end is not None else self.chain_residue_ranges.get(mapped_chain, (start, end))[1]
            
            # Ensure start and end of current domain are within these effective boundaries for auto-fill logic
            # (They should be if fill_boundaries were from a parent being split)
            if not (effective_min_res <= start <= effective_max_res and effective_min_res <= end <= effective_max_res):
                 print(f"Warning: Domain ({start}-{end}) is outside effective fill boundaries ({effective_min_res}-{effective_max_res}). Auto-fill might be skipped or incorrect.")
            
            additional_created_ids = self._create_additional_domains_to_span_context(
                chain_id=chain_id,                    # Original numeric chain ID for consistency
                current_domain_start=start,
                current_domain_end=end,
                mapped_chain=mapped_chain,
                context_min_res=effective_min_res,
                context_max_res=effective_max_res,
                # domain_id_of_current=domain_id, # Not strictly needed by the revised logic
                parent_domain_id_for_fillers=parent_domain_id
            )
            created_domain_ids_list.extend(additional_created_ids)
        
        # Normalization will be handled by the calling function (e.g., split_domain, update_domain)
        # after all related domains are created/updated.
        # if domain_id in self.domains: # Should always be true if we added it
        #      self._normalize_domain_name(domain_id) # REMOVED INTERNAL NORMALIZATION
        # else:
        #     print(f"Warning: Domain {domain_id} not in self.domains before normalization call.")

        return created_domain_ids_list # Return list of all created IDs

    def _normalize_domain_name(self, domain_id_to_normalize: str):
        if domain_id_to_normalize not in self.domains:
            print(f"_normalize_domain_name: Domain {domain_id_to_normalize} not found.")
            return

        domain = self.domains[domain_id_to_normalize]
        mapped_chain_id = domain.chain_id # This is the mapped chain ID like 'A'
        
        # Get the full residue range for this domain's specific chain from the molecule's overall chain_residue_ranges
        chain_min_res, chain_max_res = self.chain_residue_ranges.get(mapped_chain_id, (domain.start, domain.end))

        # Count domains on the same chain
        count_on_chain = 0
        for d_id, d_obj in self.domains.items():
            if d_obj.chain_id == mapped_chain_id:
                count_on_chain += 1

        new_name = None
        # Check if current name is already custom (i.e., not matching default patterns)
        is_current_name_short_default = domain.name == f"Chain {mapped_chain_id}"
        is_current_name_long_default_correct_range = domain.name == f"Chain {mapped_chain_id}: {domain.start}-{domain.end}"
        # More general check for any default-like long name, helps catch if range was slightly off but still auto-named
        is_current_name_long_default_any_range = domain.name.startswith(f"Chain {mapped_chain_id}: ") and \
                                               len(domain.name.split(': ')) > 1 and \
                                               '-' in domain.name.split(': ')[-1]
        
        is_custom_name = not (is_current_name_short_default or is_current_name_long_default_any_range)

        is_sole_full_span_domain = (count_on_chain == 1 and 
                                  domain.start == chain_min_res and 
                                  domain.end == chain_max_res)

        if not is_custom_name: # Only attempt to normalize if the name isn't already custom
            if is_sole_full_span_domain:
                # If it's the sole full-span domain, preferred name is short
                if not is_current_name_short_default: # Only change if not already the correct short name
                    new_name = f"Chain {mapped_chain_id}"
            else:
                # Not sole full-span, preferred name is long (if it was a default name)
                # This also corrects long names that had the wrong range due to prior state
                if not is_current_name_long_default_correct_range: # Only change if not already the correct long name
                    new_name = f"Chain {mapped_chain_id}: {domain.start}-{domain.end}"

        if new_name and new_name != domain.name:
            print(f"Normalizing domain name for {domain_id_to_normalize}: '{domain.name}' -> '{new_name}'")
            domain.name = new_name
            if domain.object:
                # Update Blender object name and custom properties
                current_obj_name = domain.object.name
                obj_name_suffix = ""

                # Try to preserve existing suffixes like "_nodes" or user additions
                # This is a heuristic. If the old domain name was part of the object name, extract the rest.
                old_name_variations = [
                    f"Chain {mapped_chain_id}: {domain.start}-{domain.end}", # Check against its actual range before normalization
                    f"Chain {mapped_chain_id}" # Check against short form too
                ]
                # Add any previous name patterns if they were default-like
                if domain.name != new_name: # If current name (before setting new_name) was different
                     if domain.name.startswith(f"Chain {mapped_chain_id}: ") or domain.name == f"Chain {mapped_chain_id}":
                        old_name_variations.append(domain.name)
                
                found_suffix = False
                for old_n in set(old_name_variations): # Use set to avoid redundant checks
                    if current_obj_name.startswith(old_n) and len(current_obj_name) > len(old_n):
                        potential_suffix = current_obj_name[len(old_n):]
                        # Common suffixes often start with _ or are numbers for uniqueness
                        if potential_suffix.startswith('_') or potential_suffix.isdigit(): 
                            obj_name_suffix = potential_suffix
                            found_suffix = True
                            break
                if not found_suffix and current_obj_name != domain.name: # If no clear prefix match but names differ
                    # This might be a fully custom object name, or suffix logic was too simple.
                    # To be safe, append new domain name to existing object name if it doesn't seem to contain it.
                    # However, for now, let's assume simple renaming if no clear suffix is found from defaults.
                    pass # Stick to new_name + found obj_name_suffix (which is empty if not found)

                domain.object.name = f"{new_name}{obj_name_suffix}"

                if hasattr(domain.object, "domain_name"):
                    domain.object.domain_name = new_name
                if hasattr(domain.object, "temp_domain_name"):
                    domain.object.temp_domain_name = new_name # Keep temp name in sync
        elif is_custom_name:
            print(f"Domain {domain_id_to_normalize} has custom name '{domain.name}'. Skipping normalization.")

    def split_domain(self, original_domain_id: str, split_start: int, split_end: int, split_name: Optional[str] = None) -> List[str]:
        """Splits an existing domain into multiple new domains.

        The split is defined by a new start and end residue.
        If auto_fill_chain was true for the original domain, the new segments will fill
        the original domain's boundaries. Otherwise, they fill the protein chain's boundaries.

        Args:
            original_domain_id: The ID of the domain to be split.
            split_start: The starting residue of the main new segment.
            split_end: The ending residue of the main new segment.
            split_name: Optional base name for the new split domain(s). This is currently ignored and names are auto-generated.

        Returns:
            A list of new domain IDs created by the split operation, or an empty list if failed.
        """    
        all_newly_created_domain_ids = [] # To collect all IDs from this operation

        if original_domain_id not in self.domains:
            print(f"Error: Original domain {original_domain_id} not found for splitting.")
            return []

        original_domain = self.domains[original_domain_id]
        original_chain_id_auth = original_domain.chain_id # Author chain ID like 'A'
        original_domain_actual_start = original_domain.start
        original_domain_actual_end = original_domain.end
        
        # Validation: Ensure split_start and split_end are within the original domain's range
        if not (original_domain_actual_start <= split_start <= split_end <= original_domain_actual_end):
            print(f"Error: Split range {split_start}-{split_end} is outside the original domain's range {original_domain_actual_start}-{original_domain_actual_end}.")
            bpy.ops.wm.call_message_box(message=f"Split range {split_start}-{split_end} must be within the domain's current range ({original_domain_actual_start}-{original_domain_actual_end}).", title="Invalid Split Range", icon='ERROR')
            return []
        if split_start == original_domain_actual_start and split_end == original_domain_actual_end:
            print(f"Warning: Split range matches original domain range. No actual split performed.")
            # bpy.ops.wm.call_message_box(message="Split range matches the domain's current range. No change made.", title="Split Matches Domain", icon='INFO')
            return [original_domain_id] # No split, return original

        original_numeric_chain_id = None
        # Find the original numeric chain ID for _create_domain_with_params
        for num_id, auth_id in self.chain_mapping.items():
            if auth_id == original_chain_id_auth:
                original_numeric_chain_id = str(num_id)
                break
        if not original_numeric_chain_id:
            original_numeric_chain_id = original_chain_id_auth # Fallback

        original_parent_id = getattr(original_domain, 'parent_domain_id', None)
        
        print(f"Splitting domain {original_domain_id} (Chain: {original_chain_id_auth}, Range: {original_domain_actual_start}-{original_domain_actual_end}, Parent: {original_parent_id})")
        print(f"  New segment: {split_start}-{split_end}")

        # --- Delete the original domain first --- 
        # This simplifies logic, as _create_domain_with_params
        # will then use its auto_fill_chain logic (now context-aware) 
        # to create necessary prefix/suffix domains within the original domain's boundaries.
        self._delete_domain_direct(original_domain_id) 
        print(f"Deleted original domain {original_domain_id}")

        # --- Create the main specified segment --- 
        # Pass the original domain's boundaries as the fill_boundaries.
        # The `auto_fill_chain=True` will now respect these boundaries.
        main_segment_ids = self._create_domain_with_params(
            chain_id=original_numeric_chain_id,
            start=split_start,
            end=split_end,
            name=None, # Auto-generate name
            auto_fill_chain=True, 
            parent_domain_id=original_parent_id,
            fill_boundaries_start=original_domain_actual_start, # Context for filling
            fill_boundaries_end=original_domain_actual_end      # Context for filling
        )

        if main_segment_ids:
            print(f"Successfully created main split segment(s): {main_segment_ids}")
            all_newly_created_domain_ids.extend(main_segment_ids)
        else:
            print(f"Failed to create the main split domain segment. Attempting to restore original (this is a fallback and may not always work).")
            # Fallback: try to recreate the original domain if split failed badly.
            # This is a simplistic recovery.
            restored_ids = self._create_domain_with_params(
                chain_id=original_numeric_chain_id,
                start=original_domain_actual_start,
                end=original_domain_actual_end,
                name=original_domain.name, # Try to use its old name
                auto_fill_chain=False, # Don't auto-fill if restoring
                parent_domain_id=original_parent_id
            )
            if restored_ids:
                 print(f"Fallback: Recreated original-like domain(s): {restored_ids}")
                 all_newly_created_domain_ids.extend(restored_ids) # Add to list for normalization
            else:
                 print(f"Fallback: Failed to recreate original domain.")
        
        # Normalize names for ALL newly created domains from this operation
        for new_id in all_newly_created_domain_ids:
            if new_id in self.domains: # Ensure it exists before normalizing
                self._normalize_domain_name(new_id)
            else:
                print(f"Warning: Domain ID {new_id} from split operation not found in self.domains for normalization.")

        print(f"Split operation resulted in domains: {all_newly_created_domain_ids}")
        return all_newly_created_domain_ids

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

            # Map geometry node chain_id attribute to actual chain IDs via object custom property
            obj_chain_ids_list = None
            if hasattr(mol_obj, 'keys') and "chain_ids" in mol_obj.keys():
                obj_chain_ids_list = mol_obj["chain_ids"]

            # --- Search for the first CA encountered in the specified range order ---
            for target_res_num in residue_search_range:
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

    def _create_additional_domains_to_span_context(self, chain_id: str, 
                                               current_domain_start: int, current_domain_end: int,
                                               mapped_chain: str, 
                                               context_min_res: int, context_max_res: int,
                                               parent_domain_id_for_fillers: Optional[str] = None) -> List[str]:
        """Create additional domains to span a given context (e.g., original domain's range or full chain).
        
        This function is called after creating a domain that doesn't span the entire context.
        It creates up to two additional domains:
        1. Before the current_domain (context_min_res to current_domain_start - 1)
        2. After the current_domain (current_domain_end + 1 to context_max_res)
        
        Args:
            chain_id: The original numeric chain ID (e.g., '0', '1').
            current_domain_start: Start residue of the domain just created.
            current_domain_end: End residue of the domain just created.
            mapped_chain: The author chain ID (e.g., 'A', 'B').
            context_min_res: Minimum residue ID of the context to fill.
            context_max_res: Maximum residue ID of the context to fill.
            parent_domain_id_for_fillers: The parent_domain_id for any created filler domains.
        Returns:
            A list of domain IDs created by this fill operation.
        """
        created_filler_ids = []
        
        # Check if the current domain already spans the entire context
        if current_domain_start <= context_min_res and current_domain_end >= context_max_res:
            return [] # No additional domains needed
        
        # Create Prefix Domain (if needed)
        if current_domain_start > context_min_res:
            prefix_start = context_min_res
            prefix_end = current_domain_start - 1
            
            if prefix_start <= prefix_end: # Ensure valid range
                if not self._check_domain_overlap(mapped_chain, prefix_start, prefix_end):
                    print(f"Creating prefix filler domain for context: Chain {mapped_chain}, Range {prefix_start}-{prefix_end}")
                    # _create_domain_with_params returns a list, so we extend
                    prefix_ids = self._create_domain_with_params(
                    chain_id=chain_id,
                        start=prefix_start,
                        end=prefix_end,
                        name=None, # Auto-generate name
                        auto_fill_chain=False,  # Prevent recursion within this fill step
                        parent_domain_id=parent_domain_id_for_fillers,
                        # No fill_boundaries here, as these are the fillers themselves
                    )
                    created_filler_ids.extend(prefix_ids)
                    
                    # Color sync (already handled within _create_domain_with_params via its setup calls)
            else:
                    print(f"Skipping creation of prefix filler domain ({prefix_start}-{prefix_end}) due to overlap.")
        
        # Create Suffix Domain (if needed)
        if current_domain_end < context_max_res:
            suffix_start = current_domain_end + 1
            suffix_end = context_max_res
            
            if suffix_start <= suffix_end: # Ensure valid range
                if not self._check_domain_overlap(mapped_chain, suffix_start, suffix_end):
                    print(f"Creating suffix filler domain for context: Chain {mapped_chain}, Range {suffix_start}-{suffix_end}")
                    # _create_domain_with_params returns a list, so we extend
                    suffix_ids = self._create_domain_with_params(
                    chain_id=chain_id,
                        start=suffix_start,
                        end=suffix_end,
                        name=None, # Auto-generate name
                    auto_fill_chain=False,  # Prevent recursion
                        parent_domain_id=parent_domain_id_for_fillers,
                    )
                    created_filler_ids.extend(suffix_ids)
                    # Color sync handled by _create_domain_with_params
            else:
                    print(f"Skipping creation of suffix filler domain ({suffix_start}-{suffix_end}) due to overlap.")
        
        return created_filler_ids
        
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
                if domain_id in self.domains: # Ensure old ID exists before attempting to delete
                    del self.domains[domain_id]
                # Normalization called by the caller of update_domain, or if ID does not change, see below.
                # For now, let's assume caller handles normalization for the *returned* ID.
                # However, if the ID changes, the *new* domain should be normalized.
                self._normalize_domain_name(new_domain_id) 
                return new_domain_id
            
            # If domain ID didn't change, still normalize its name as its range or context might have.
            self._normalize_domain_name(domain_id)
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

    def delete_domain(self, domain_id: str, is_cleanup_call: bool = False) -> Optional[str]:
        """Delete a domain and its object.

        If the domain is the only one on its chain, deletion is prevented by the UI.
        If multiple domains exist on the chain, deleting one will cause an adjacent
        domain (preferring the one with a lower start residue) to expand and fill the gap.
        
        Args:
            domain_id (str): The ID of the domain to delete.
            is_cleanup_call (bool): True if called during full molecule cleanup, to suppress UI messages.
        
        Returns:
            Optional[str]: The ID of the domain that filled the gap, if any.
        """
        if domain_id not in self.domains:
            print(f"Warning: Domain {domain_id} not found for deletion.")
            return None
        
        domain_to_delete = self.domains[domain_id]
        chain_id = domain_to_delete.chain_id
        start_del = domain_to_delete.start
        end_del = domain_to_delete.end
        deleted_domain_name = domain_to_delete.name # For logging
        original_parent_id = getattr(domain_to_delete, 'parent_domain_id', None)

        # Count domains on the same chain
        domains_on_this_chain = []
        for d_id, d_obj in self.domains.items():
            if d_obj.chain_id == chain_id:
                domains_on_this_chain.append((d_id, d_obj))
        
        # UI should prevent deleting the last domain on a chain, but double check here
        if len(domains_on_this_chain) <= 1 and domain_id in [d[0] for d in domains_on_this_chain] and not is_cleanup_call:
            print(f"Deletion of domain {domain_id} prevented as it's the last on chain {chain_id}.")
            if not is_cleanup_call: # Only show message if not part of a full cleanup
                bpy.ops.wm.call_message_box(message=f"Cannot delete the last domain ({deleted_domain_name}) on chain {chain_id}.", title="Deletion Prevented", icon='ERROR')
            return None # Should not happen if UI is working correctly

        children_to_reparent = []
        for child_id, child_domain in self.domains.items():
            if hasattr(child_domain, 'parent_domain_id') and child_domain.parent_domain_id == domain_id:
                children_to_reparent.append(child_id)
            
        # --- Find adjacent domains on the same chain --- 
        domain_before = None # Tuple: (id, domain_obj) ending right before 'start_del'
        domain_after = None  # Tuple: (id, domain_obj) starting right after 'end_del'

        for adj_domain_id, adj_domain in domains_on_this_chain:
            if adj_domain_id == domain_id: # Skip the domain being deleted
                continue
            if adj_domain.end == start_del - 1:
                    domain_before = (adj_domain_id, adj_domain)
            elif adj_domain.start == end_del + 1:
                    domain_after = (adj_domain_id, adj_domain)
        
        # --- Determine update target and range BEFORE deletion --- 
        update_target_id = None
        update_new_start = -1
        update_new_end = -1
        final_reparent_target_id = original_parent_id

        # Determine which domain to expand or if merging is more complex
        if domain_before and domain_after:
            # Scenario: A - B(del) - C.  Expand A to cover B. C remains separate.
            # update_target_id becomes domain_before.
            # domain_after is NOT deleted in this specific step, domain_before just expands.
            update_target_id = domain_before[0]
            update_new_start = domain_before[1].start
            update_new_end = end_del # Expand domain_before to cover the deleted domain
            print(f"Planning to expand {update_target_id} (ending at {domain_before[1].end}) to cover deleted range, new end: {update_new_end}. Domain {domain_after[0]} remains.")
        elif domain_before:
            # Scenario: A - B(del). Expand A to cover B.
            update_target_id = domain_before[0]
            update_new_start = domain_before[1].start
            update_new_end = end_del
            print(f"Planning to expand {update_target_id} to cover deleted range: {update_new_start}-{update_new_end}")
        elif domain_after:
            # Scenario: B(del) - C. Expand C to cover B.
            update_target_id = domain_after[0]
            update_new_start = start_del
            update_new_end = domain_after[1].end
            print(f"Planning to expand {update_target_id} to cover deleted range: {update_new_start}-{update_new_end}")
        else:
            # No adjacent domains on this chain to expand. 
            print(f"No adjacent domains to merge with {domain_id} on chain {chain_id}. It will be deleted directly.")

        if update_target_id:
             final_reparent_target_id = update_target_id 

        # --- Perform Deletion of the primary domain FIRST --- 
        print(f"Deleting original domain {deleted_domain_name} ({domain_id}).")
        self._delete_domain_direct(domain_id)
        
        # If domain_before and domain_after existed (A-B(del)-C case):
        # The old logic was: merge all three into domain_before, and delete domain_after.
        # New logic: domain_before expands to cover B. domain_after is untouched here.
        # So, we no longer need to explicitly delete domain_after here as part of a three-way merge.
        # if domain_before and domain_after and domain_after[0] in self.domains:
        #     print(f"Old logic would have deleted merged domain {domain_after[0]}. New logic keeps it separate.")
            # self._delete_domain_direct(domain_after[0]) # REMOVED: domain_after is not deleted now

        # --- Perform Update AFTER Deletion(s) --- 
        updated_domain_id_result = None
        if update_target_id is not None and update_target_id in self.domains: # Check if target still exists
            print(f"Executing update for domain {update_target_id} to range {update_new_start}-{update_new_end}")
            updated_domain_id_result = self.update_domain(update_target_id, chain_id, update_new_start, update_new_end)
            final_reparent_target_id = updated_domain_id_result # Ensure reparenting uses the potentially new ID from update_domain
            # Normalization is handled by update_domain if successful, or by _create_domain_with_params if new ones are made.
            # If update_domain itself returns a new ID, that new ID would have been normalized.
            # If it returns the same ID, it will normalize that one.
            # So, no explicit call to _normalize_domain_name here for updated_domain_id_result is needed,
            # as update_domain should handle it.
        elif update_target_id:
            print(f"Warning: Update target domain {update_target_id} was not found after deletions. Cannot expand.")
        else:
             print("No adjacent domain found to update or merge with.")

        # --- Final Steps --- 
        print(f"Reparenting children of {deleted_domain_name} to target: {final_reparent_target_id}")
        self._reparent_child_domains(children_to_reparent, final_reparent_target_id)
        
        # After deletion and potential merge, re-normalize names of all remaining domains on the affected chain
        # This is because their status (e.g. sole domain) might have changed.
        # Need to use the original chain_id of the deleted domain.
        affected_chain_id = chain_id # This was `domain_to_delete.chain_id` (author chain id)
        
        # Create a list of domain IDs on this chain to iterate over, as self.domains might change during normalization
        # if object names/etc., are modified in a way that affects ID generation (though less likely with current setup)
        ids_on_chain_to_normalize = []
        for d_id, d_obj in self.domains.items():
            if d_obj.chain_id == affected_chain_id:
                ids_on_chain_to_normalize.append(d_id)
        
        for id_to_norm in ids_on_chain_to_normalize:
            if id_to_norm in self.domains: # Check if it still exists (e.g. wasn't the merged 'after' domain)
                self._normalize_domain_name(id_to_norm)
                
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
                # Preserve world transform before changing parent
                world_mat = domain.object.matrix_world.copy()
                # Set the new parent
                domain.object.parent = parent_obj
                # Compute parent inverse to maintain world transform
                domain.object.matrix_parent_inverse = parent_obj.matrix_world.inverted()
                # Restore the original world transform
                domain.object.matrix_world = world_mat
            except Exception as e:
                print(f"Error updating parent for {domain.name}: {str(e)}")

    def cleanup(self):
        """Remove all domains and clean up resources"""
        # First clean up all domains
        for domain_id in list(self.domains.keys()):
            self.delete_domain(domain_id, is_cleanup_call=True) # Pass True here
        
        # Clean up domain infrastructure nodes in parent molecule
        if self.molecule and self.molecule.object:
            parent_modifier = self.molecule.object.modifiers.get("MolecularNodes")
            if parent_modifier and parent_modifier.node_group:
                parent_node_group = parent_modifier.node_group
                
                # List of specific node *instances* to remove from the parent molecule's node group
                # These are part of the domain masking infrastructure.
                infra_node_instances_to_remove = []

                # Gather all join nodes (primary and overflows)
                if hasattr(self, 'join_nodes'): 
                    for node_instance in self.join_nodes:
                        if node_instance and node_instance.name in parent_node_group.nodes:
                            if node_instance not in infra_node_instances_to_remove:
                                infra_node_instances_to_remove.append(node_instance)
                
                # Gather the final_not node
                if hasattr(self, 'final_not') and self.final_not and self.final_not.name in parent_node_group.nodes:
                    if self.final_not not in infra_node_instances_to_remove: # Avoid double add
                        infra_node_instances_to_remove.append(self.final_not)
                
                # Note: Domain_Chain_Select_ and Domain_Res_Select_ nodes (per-domain masks)
                # are already removed by _delete_domain_mask_nodes when each domain is deleted in the loop above.

                # Remove links connected to these infrastructure nodes before removing the nodes themselves.
                if infra_node_instances_to_remove:
                    links_to_detach_for_infra = []
                    for link in parent_node_group.links: # Iterate over a copy if modifying links directly
                        if link.from_node in infra_node_instances_to_remove or \
                           link.to_node in infra_node_instances_to_remove:
                            links_to_detach_for_infra.append(link)
                    
                    for link in links_to_detach_for_infra:
                        try:
                            parent_node_group.links.remove(link)
                        except RuntimeError: # Link might have been removed due to other node removals
                            pass

                    # Remove the infrastructure node instances themselves
                    for node_instance in infra_node_instances_to_remove:
                        # IMPORTANT: We remove the node *instance* from this specific parent_node_group.
                        # We DO NOT remove node_instance.node_tree, as it might be a shared asset.
                        try:
                            parent_node_group.nodes.remove(node_instance)
                        except RuntimeError: # Node might have been removed already
                            pass
                
                # Reset internal trackers for these nodes
                self.domain_join_node = None # This was the primary one, typically the first in self.join_nodes
                if hasattr(self, 'join_nodes'): self.join_nodes = []
                if hasattr(self, 'final_not'): self.final_not = None
        
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
                    domain.object.domain_color = domain_color
                
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
            else:
                # Override existing Color Common node to our domain color
                try:
                    if "Carbon" in color_emit.inputs:
                        color_emit.inputs["Carbon"].default_value = domain.color
                    elif len(color_emit.inputs) > 0 and hasattr(color_emit.inputs[0], "default_value"):
                        color_emit.inputs[0].default_value = domain.color
                except Exception as e:
                    print(f"Warning: failed to override Color Common for domain {domain.domain_id}: {e}")
            
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

    def delete_molecule(self, identifier: str):
        """Deletes a molecule and all its associated Blender objects and data."""
        print(f"Attempting to delete molecule: {identifier}")
        molecule_wrapper = self.get_molecule(identifier)
        if not molecule_wrapper:
            print(f"Molecule {identifier} not found in manager.")
            return

        # 1. Call cleanup on the MoleculeWrapper to remove domains and their objects/nodes
        print(f"Cleaning up domains for molecule {identifier}...")
        molecule_wrapper.cleanup()

        # 2. Delete the main Blender object for the molecule
        if molecule_wrapper.molecule and molecule_wrapper.molecule.object:
            main_mol_object = molecule_wrapper.molecule.object
            object_name = main_mol_object.name
            collection_name = main_mol_object.users_collection[0].name if main_mol_object.users_collection else None
            print(f"Deleting main molecule object: {object_name}")
            try:
                bpy.data.objects.remove(main_mol_object, do_unlink=True)
            except Exception as e:
                print(f"Error removing main molecule object {object_name}: {e}")

            # 3. Attempt to remove the collection if it was specific to this molecule and is now empty
            # This is a heuristic. A more robust system might tag collections or use naming conventions.
            if collection_name:
                collection = bpy.data.collections.get(collection_name)
                if collection and not collection.all_objects: # If collection is empty
                    # Further check if the collection name matches a pattern or the molecule identifier
                    # to avoid deleting general-purpose collections.
                    if identifier in collection_name or object_name.startswith(collection_name): # Basic check
                        print(f"Deleting empty collection: {collection_name}")
                        try:
                            bpy.data.collections.remove(collection)
                        except Exception as e:
                            print(f"Error removing collection {collection_name}: {e}")
                    else:
                        print(f"Collection {collection_name} is empty but not deemed specific to {identifier}, not deleting.")
                elif collection:
                    print(f"Collection {collection_name} is not empty, not deleting.")

        # 4. Remove the molecule from the manager's dictionary
        if identifier in self.molecules:
            del self.molecules[identifier]
            print(f"Molecule {identifier} removed from manager.")

        # Ensure UI updates if an operator calls this
        # This might involve tagging areas for redraw or using a message bus
        # For now, this function focuses on data cleanup.
        # Operators calling this should handle their own UI refresh.