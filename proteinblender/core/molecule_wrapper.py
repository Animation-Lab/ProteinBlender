"""MoleculeWrapper class for ProteinBlender.

This module wraps MolecularNodes Molecule objects with ProteinBlender-specific
functionality including domain management, chain mapping, and reference healing.

The MoleculeWrapper uses ObjectRef for safe handling of Blender object references
that can become invalid after undo/redo operations.
"""

from typing import Optional, Dict, List, Tuple
import bpy
import numpy as np
import colorsys
from mathutils import Vector

from ..utils.molecularnodes.entities.molecule.molecule import Molecule
from ..utils.molecularnodes.blender import nodes
from .domain import DomainDefinition
from ..core.domain import ensure_domain_properties_registered
from . import domain_space
from ..utils.blender_utils import is_object_valid

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
        self.object_name = self.molecule.object.name if self.molecule and self.molecule.object else ""
        
        # Handle both AtomArrayStack (multi-model) and AtomArray (single model)
        import biotite.structure as struc
        
        # Get the working array - if it's a stack, use the first model
        working_array = molecule.array
        if isinstance(molecule.array, struc.AtomArrayStack):
            working_array = molecule.array[0]

        # Ensure the working array has the necessary integer chain ID attribute
        existing_categories = working_array.get_annotation_categories()
        if "chain_id_int" not in existing_categories:
            working_array.add_annotation("chain_id_int", dtype=int)
            unique_chain_ids, int_indices = np.unique(working_array.chain_id, return_inverse=True)
            working_array.set_annotation("chain_id_int", int_indices)

        # 1. Author-provided chain ID map (often from mmCIF _atom_site.auth_asym_id)
        # Biotite's chain_mapping_str() typically provides a map from an integer index to the auth_asym_id string.
        raw_auth_map = working_array.chain_mapping_str() if hasattr(working_array, 'chain_mapping_str') else {}
        self.auth_chain_id_map: Dict[int, str] = {}
        if isinstance(raw_auth_map, dict):
            self.auth_chain_id_map = {k: v for k, v in raw_auth_map.items() if isinstance(k, int) and isinstance(v, str)}

        # 2. Map from internal integer chain index (0,1,2...) to _atom_site.label_asym_id ('A','B','C'...)
        # This uses working_array.chain_id which Biotite populates with label_asym_id for mmCIF.
        self.idx_to_label_asym_id_map: Dict[int, str] = {}
        if hasattr(working_array, 'chain_id'):  # This is label_asym_id from Biotite for mmCIF
            unique_label_asym_ids = sorted(list(np.unique(working_array.chain_id)))
            for i, label_id_str in enumerate(unique_label_asym_ids):
                self.idx_to_label_asym_id_map[i] = str(label_id_str)  # Ensure it's a string
        
        # Store reference to working array for other methods
        self.working_array = working_array
        
        # Keep legacy chain_mapping for backward compatibility (use auth_chain_id_map as source)
        self.chain_mapping = self.auth_chain_id_map

        # Initialize chain residue ranges
        self.chain_residue_ranges = self._get_chain_residue_ranges()

        # Bug C fallback: on Blender 5.1 + biotite 1.2.x, `chain_mapping_str()`
        # returns an empty dict for many structures, leaving auth_chain_id_map
        # empty. Without a chain_mapping, the create-domain operator can't
        # translate UI numeric chain indices back to author chain IDs and
        # ends up reporting bogus overlap errors. Fall back to deriving the
        # map from chain_residue_ranges keys (label_asym_ids) so downstream
        # code always has a non-empty {idx -> author-id} dict to work with.
        if not self.chain_mapping and self.chain_residue_ranges:
            for idx, auth_id in enumerate(sorted(self.chain_residue_ranges.keys())):
                self.chain_mapping[idx] = auth_id
            # Keep auth_chain_id_map in lock-step so any direct reads of it
            # see the same fallback values.
            self.auth_chain_id_map = self.chain_mapping
        
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

        # Idempotency / self-heal. __init__ runs this every time a wrapper is
        # built — INCLUDING when wrappers are reconstructed on file load / undo,
        # at which point the node group already contains the Domain_Boolean_Join
        # and Domain_Final_Not nodes saved in the file. The old code blindly
        # created a SECOND Join->NOT layer wrapping the existing selection; a
        # second NOT inverts the mask from "select all" to "select nothing", so
        # a molecule with no separate per-chain objects (DNA/RNA, or an unsplit
        # protein) renders nothing — "only a point where the DNA was". If the
        # infrastructure already exists, reuse it and collapse any stacked
        # duplicate layers instead of adding another.
        existing_join = parent_node_group.nodes.get("Domain_Boolean_Join")
        existing_not = parent_node_group.nodes.get("Domain_Final_Not")
        if existing_join and existing_not:
            self._rebind_domain_infrastructure(
                parent_node_group, existing_join, existing_not)
            return

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

    def _rebind_domain_infrastructure(self, parent_node_group, join_node, final_not):
        """Reuse domain-mask nodes already present in the node group (file load /
        undo reconstruction) instead of rebuilding them, and collapse any
        duplicate Join/NOT layers a previous non-idempotent run stacked, so the
        style Selection ends up driven by exactly one Final NOT. See the
        idempotency note in _setup_protein_domain_infrastructure."""
        # Drop duplicate copies Blender auto-suffixed (".001", ".002", ...) when
        # a prior reconstruction recreated nodes that already existed. Genuine
        # overflow joins use an underscore ("Domain_Boolean_Join_2"), so the
        # dot-suffixed ones are always stale duplicates.
        for node in list(parent_node_group.nodes):
            if (node.name.startswith("Domain_Boolean_Join.")
                    or node.name.startswith("Domain_Final_Not.")):
                parent_node_group.nodes.remove(node)

        # Re-establish join -> NOT -> style Selection through the canonical nodes
        # only (the duplicate layer we just removed may have been in between).
        for link in list(final_not.inputs[0].links):
            parent_node_group.links.remove(link)
        parent_node_group.links.new(join_node.outputs["Result"], final_not.inputs[0])

        main_style_node = self.get_main_style_node()
        if main_style_node:
            for link in list(main_style_node.inputs["Selection"].links):
                parent_node_group.links.remove(link)
            parent_node_group.links.new(
                final_not.outputs["Boolean"], main_style_node.inputs["Selection"])

        # Rebind tracked references: primary join + any underscore overflow joins.
        self.domain_join_node = join_node
        self.final_not = final_not
        self.join_nodes = [join_node]
        i = 2
        while True:
            overflow = parent_node_group.nodes.get(f"Domain_Boolean_Join_{i}")
            if not overflow:
                break
            self.join_nodes.append(overflow)
            i += 1

    def _refresh_domain_node_refs(self, parent_node_group) -> bool:
        """Re-resolve the cached domain-mask infrastructure nodes by NAME.

        Blender reallocates a node group's node collection whenever nodes are
        added or removed — including elsewhere in the file. Duplicating a
        molecule and then deleting the copy (which purges the copy's node
        groups) is enough to invalidate the ``bpy`` node pointers this wrapper
        cached at setup time (``domain_join_node`` / ``join_nodes`` /
        ``final_not``). Dereferencing a stale pointer reads freed memory and
        hard-crashes Blender (seen on 5.1); if it instead lands on a different
        live node it raises a confusing KeyError (seen on 5.0 as
        ``key "Result" not found``).

        Node NAMES are stable, so re-resolve from them at use time — the same
        approach ``get_main_style_node`` and ``_rebind_domain_infrastructure``
        already take. Returns True if the primary join + final NOT exist (the
        infrastructure is set up), False otherwise.
        """
        join = parent_node_group.nodes.get("Domain_Boolean_Join")
        final_not = parent_node_group.nodes.get("Domain_Final_Not")
        if join is None or final_not is None:
            return False
        self.domain_join_node = join
        self.final_not = final_not
        self.join_nodes = [join]
        i = 2
        while True:
            overflow = parent_node_group.nodes.get(f"Domain_Boolean_Join_{i}")
            if not overflow:
                break
            self.join_nodes.append(overflow)
            i += 1
        return True

    @property
    def object(self) -> Optional[bpy.types.Object]:
        """Get the Blender object, healing reference if needed."""
        # Resolving via databpy can raise LinkedObjectError when the
        # underlying object has been removed (e.g. after ed.undo of an
        # import). Catch that explicitly so callers see None instead of
        # a crash, which would otherwise kill the undo-sync loop and
        # leave stale wrappers in mgr.molecules.
        try:
            obj = self.molecule.object if self.molecule else None
        except Exception:
            obj = None

        # Check if reference is still valid
        if not is_object_valid(obj):
            # Try to heal from stored name
            if self.object_name and self.object_name in bpy.data.objects:
                healed_obj = bpy.data.objects[self.object_name]
                if self.molecule:
                    try:
                        self.molecule.object = healed_obj
                    except Exception:
                        pass
                return healed_obj
            return None

        return obj

    def heal_references(self) -> bool:
        """Heal all stale object references after undo/redo.

        This method attempts to recover valid references for:
        - The main molecule object
        - All domain objects and node groups
        - Node infrastructure references

        Returns:
            True if all critical references were healed successfully
        """
        all_valid = True

        # Heal main object reference
        obj = self.object  # Uses property which already heals
        if not obj:
            all_valid = False

        # Heal all domain references
        for domain_id, domain in self.domains.items():
            if not domain.heal_references():
                print(f"Warning: Could not heal domain {domain_id}")
                all_valid = False

        # Update object_name if we have a valid object
        if obj:
            try:
                self.object_name = obj.name
            except (ReferenceError, AttributeError):
                pass

        return all_valid

    def is_valid(self) -> bool:
        """Check if the molecule wrapper has valid references.

        Returns:
            True if the main object reference is valid
        """
        try:
            return is_object_valid(self.object)
        except Exception:
            # Any exception while resolving the object reference
            # (LinkedObjectError, ReferenceError, etc.) means the wrapper
            # is no longer pointing at a live Blender object.
            return False

    @classmethod
    def from_existing_object(
        cls,
        obj: bpy.types.Object,
        identifier: str,
        chain_mapping: Optional[Dict[int, str]] = None,
        chain_residue_ranges: Optional[Dict[str, Tuple[int, int]]] = None
    ) -> Optional['MoleculeWrapper']:
        """Create a MoleculeWrapper from an existing Blender object.

        This is used to reconstruct a wrapper after undo/redo or file load
        when the runtime wrapper was lost but the Blender object still exists.

        Args:
            obj: The existing Blender protein object
            identifier: The molecule identifier
            chain_mapping: Optional chain index to ID mapping
            chain_residue_ranges: Optional chain residue ranges

        Returns:
            A new MoleculeWrapper instance, or None if creation failed
        """
        try:

            # Create a minimal mock Molecule that wraps the existing object
            class MockMolecule:
                """Minimal mock of MolecularNodes Molecule for wrapping existing objects."""

                def __init__(self, blender_obj):
                    self.object = blender_obj
                    self.array = cls._extract_array_from_object(blender_obj, chain_mapping)

            mock = MockMolecule(obj)

            # Create wrapper - this will set up chain mappings from the array
            wrapper = cls(mock, identifier)

            # Override with provided mappings if available (more reliable)
            if chain_mapping:
                wrapper.chain_mapping = chain_mapping
                wrapper.auth_chain_id_map = chain_mapping

            if chain_residue_ranges:
                wrapper.chain_residue_ranges = chain_residue_ranges

            return wrapper

        except Exception as e:
            print(f"Failed to create wrapper from existing object: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def _extract_array_from_object(
        obj: bpy.types.Object,
        chain_mapping: Optional[Dict[int, str]] = None
    ):
        """Extract a minimal biotite array from Blender object attributes.

        Args:
            obj: The Blender protein object
            chain_mapping: Optional chain mapping to use

        Returns:
            A biotite AtomArray with chain_id and res_id populated
        """
        import biotite.structure as struc

        try:
            if not obj or not hasattr(obj, 'data') or not obj.data:
                return struc.AtomArray(0)

            attrs = obj.data.attributes
            num_atoms = len(obj.data.vertices)

            if num_atoms == 0:
                return struc.AtomArray(0)

            array = struc.AtomArray(num_atoms)

            # Get chain mapping from object if not provided
            if not chain_mapping:
                mapping_str = obj.data.get("chain_mapping_str", "")
                if mapping_str:
                    chain_mapping = {}
                    for pair in mapping_str.split(","):
                        if ":" in pair:
                            try:
                                k, v = pair.split(":")
                                chain_mapping[int(k)] = v
                            except (ValueError, TypeError):
                                continue

            # Extract chain IDs
            if "chain_id" in attrs:
                chain_data = np.zeros(num_atoms, dtype=np.int32)
                attrs["chain_id"].data.foreach_get("value", chain_data)

                if chain_mapping:
                    chain_labels = np.array([
                        chain_mapping.get(cid, str(cid)) for cid in chain_data
                    ])
                    array.chain_id = chain_labels
                else:
                    array.chain_id = chain_data.astype(str)

            # Extract residue IDs
            if "res_id" in attrs:
                res_data = np.zeros(num_atoms, dtype=np.int32)
                attrs["res_id"].data.foreach_get("value", res_data)
                array.res_id = res_data

            return array

        except Exception as e:
            print(f"Warning: Could not extract array data: {e}")
            return struc.AtomArray(0)
        
    def change_style(self, new_style: str) -> None:
        """Change the visualization style of the molecule"""
        try:
            nodes.change_style_node(self.object, new_style)
            self.style = new_style
        except Exception as e:
            print(f"Error changing style for {self.identifier}: {str(e)}")
            raise

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
        
        # If parent_domain_id was explicitly provided (including None), use it
        if parent_domain_id is not None and parent_domain_id in self.domains:
            domain.parent_domain_id = parent_domain_id
        # Only auto-find parent if parent_domain_id was not explicitly passed
        elif parent_domain_id != "NO_AUTO_PARENT":  # Special flag to prevent auto-parenting
            # Find potential parent domains (domains that contain this one)
            potential_parents = []
            for existing_id, existing_domain in self.domains.items():
                # Don't make copies children of originals or other copies
                if hasattr(existing_domain, 'is_copy') and existing_domain.is_copy:
                    continue
                    
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
        if not self.molecule or not self.molecule.object:
            print(f"ERROR: Cannot create domain {domain_id} - parent molecule object does not exist")
            return None
            
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

        # --- Set the initial pivot intelligently based on domain type ---
        if domain.object:
            # Determine if this is a full chain domain
            chain_min_res, chain_max_res = self.chain_residue_ranges.get(mapped_chain, (start, end))
            # chain_residue_ranges can report a min of 0, but auto-created chain
            # domains are normalised to start at 1 (see
            # _create_domains_for_each_chain). Without matching that
            # normalisation here, a full chain whose range starts at 0 fails the
            # is_full_chain test, is treated as a partial domain, and is pivoted
            # at its first residue instead of its centre of mass - so "Set Pivot
            # First" then looks like a no-op because the pivot is already there.
            from ..utils.chain_utils import normalize_domain_residue_range
            chain_min_res, chain_max_res = normalize_domain_residue_range(
                (chain_min_res, chain_max_res))
            is_full_chain = (start == chain_min_res and end == chain_max_res)

            pivot_pos = None
            if is_full_chain:
                # For full chain domains, use center of mass
                pivot_pos = self._calculate_center_of_mass(bpy.context, domain.object,
                                                           chain_id=mapped_chain,
                                                           start_res=start,
                                                           end_res=end)
                if not pivot_pos:
                    # Fallback to start residue if center of mass calculation fails
                    pivot_pos = self._find_residue_alpha_carbon_pos(bpy.context, domain, residue_target='START')
            else:
                # For partial domains, use start residue (existing behavior)
                pivot_pos = self._find_residue_alpha_carbon_pos(bpy.context, domain, residue_target='START')

            # Apply the pivot position
            if pivot_pos:
                self._set_domain_origin_and_update_matrix(bpy.context, domain, pivot_pos)
        # --- End initial pivot setting --- 

        # Update residue assignments
        self._update_residue_assignments(domain)
        
        # Create mask nodes in the parent molecule to hide this domain region
        self._create_domain_mask_nodes(domain_id, chain_id, start, end)
        
        # Add the domain to our domain collection
        self.domains[domain_id] = domain
        created_domain_ids_list.append(domain_id) # Add primary domain to list
        # Mirror the new domain into the persistent PropertyGroup collection
        # so it survives .blend save → load (Bug B).
        self._mirror_domains_to_property_group()
        
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
        
        # Skip normalization for domain copies - they have their own naming scheme
        if hasattr(domain, 'is_copy') and domain.is_copy:
            print(f"Domain {domain_id_to_normalize} is a copy with name '{domain.name}'. Skipping normalization.")
            return
        
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
            # Only print this message if it's not a default chain name
            if not domain.name.startswith("Chain "):
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
            print("Warning: Split range matches original domain range. No actual split performed.")
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
            print("Failed to create the main split domain segment. Attempting to restore original (this is a fallback and may not always work).")
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
                 print("Fallback: Failed to recreate original domain.")
        
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
                     except Exception:
                         pass
                 elif isinstance(chain_id, (str, int)) and str(chain_id).isdigit():
                     try:
                         int_chain_id = int(chain_id)
                         alpha_chain = chr(int_chain_id + ord('A'))
                         search_ids.append(alpha_chain)
                         search_ids.append(int_chain_id)
                         search_ids.append(str(int_chain_id))
                     except Exception:
                         pass
                 return list(set(filter(lambda x: x is not None, search_ids)))
            # --- End helper --- 

            search_chain_ids = get_possible_chain_ids(domain_chain_id)

            # Determine which chain attribute to use (support 'chain_id' or 'chain_id_int')
            if "chain_id" in attrs:
                chain_attr_name = "chain_id"
            elif "chain_id_int" in attrs:
                chain_attr_name = "chain_id_int"
            else:
                print("Error: Chain ID attribute ('chain_id' or 'chain_id_int') not found.")
                return None

            # Get attribute data arrays
            chain_ids_data = attrs[chain_attr_name].data
            res_nums_data = attrs[residue_attr_name].data
            positions_data = attrs["position"].data

            # Get custom chain mapping if available
            obj_chain_ids_list = None
            if hasattr(mol_obj, 'keys') and "chain_ids" in mol_obj.keys():
                obj_chain_ids_list = mol_obj["chain_ids"]
            
            # **FIX: Create reverse mapping for better chain matching**
            # If we have custom mapping, we need to find which numeric indices correspond to our target chain
            target_chain_indices = []
            
            if obj_chain_ids_list is not None:
                # Search for all indices that map to our target chain
                for idx, mapped_chain in enumerate(obj_chain_ids_list):
                    if str(mapped_chain) == str(domain_chain_id):
                        target_chain_indices.append(idx)
                
                # Also add the mathematical conversions
                for search_id in search_chain_ids:
                    if isinstance(search_id, int) and 0 <= search_id < len(obj_chain_ids_list):
                        if search_id not in target_chain_indices:
                            target_chain_indices.append(search_id)
            else:
                # No custom mapping, use the mathematical conversion
                target_chain_indices = [idx for idx in search_chain_ids if isinstance(idx, int)]
            
            # Convert to strings for comparison
            search_chain_ids_str = [str(s) for s in search_chain_ids]
            target_chain_indices_str = [str(idx) for idx in target_chain_indices]

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

            # --- Search for the first CA encountered in the specified range order ---
            for target_res_num in residue_search_range:
                atoms_in_residue = 0
                atoms_in_target_chain = 0
                
                for atom_idx in range(len(positions_data)):
                    try:
                        atom_res_num = res_nums_data[atom_idx].value
                        if atom_res_num != target_res_num:
                            continue 
                        
                        atoms_in_residue += 1
                        
                        # Get the chain ID value for this atom
                        chain_id_val = chain_ids_data[atom_idx].value
                        
                        # **FIX: Use both custom mapping and direct comparison**
                        atom_matches_target_chain = False
                        
                        # Method 1: Check if atom's chain index is in our target indices
                        if str(chain_id_val) in target_chain_indices_str:
                            atom_matches_target_chain = True
                        
                        # Method 2: If we have custom mapping, check the mapped value
                        if obj_chain_ids_list is not None and not atom_matches_target_chain:
                            try:
                                actual_chain_id = obj_chain_ids_list[chain_id_val]
                                if str(actual_chain_id) in search_chain_ids_str:
                                    atom_matches_target_chain = True
                            except (IndexError, TypeError):
                                pass
                        
                        # Method 3: Direct comparison (fallback)
                        if not atom_matches_target_chain:
                            if str(chain_id_val) in search_chain_ids_str:
                                atom_matches_target_chain = True
                        
                        if not atom_matches_target_chain:
                            continue
                        
                        atoms_in_target_chain += 1
                        
                        # --- Check using the preferred method (is_alpha_carbon) --- 
                        is_ca = False
                        if is_alpha_carbon_data: 
                            is_ca = is_alpha_carbon_data[atom_idx].value
                        elif atom_names_data: # Fallback to checking name 'CA'
                            atom_name = str(atom_names_data[atom_idx].value).strip().upper()
                            if atom_name == "CA":
                                is_ca = True
                        
                        if is_ca:
                            # Raw mesh coordinate: the pivot is applied inside
                            # geometry nodes, so this has not been through it.
                            # local_to_world subtracts the parent's pivot before
                            # applying its transform.
                            local_pos = positions_data[atom_idx].vector
                            return domain_space.local_to_world(mol_obj, local_pos)
                            
                    except (AttributeError, IndexError, ValueError, TypeError):
                        continue # Skip malformed atom data

            # If we finish the loop without finding any CA in the entire range
            return None

        except Exception:
            import traceback
            traceback.print_exc()
            return None
    # --- End Moved Helper ---

    # --- Helper: Calculate Center of Mass ---
    def _calculate_center_of_mass(self, context, obj, chain_id=None, start_res=None, end_res=None):
        """
        Calculate center of mass based on alpha carbons.

        Args:
            context: Blender context
            obj: Blender object to calculate center of mass for
            chain_id: Optional chain ID to filter by
            start_res: Optional start residue to filter by
            end_res: Optional end residue to filter by

        Returns:
            Vector: World space position of center of mass, or None if calculation fails
        """
        try:
            import numpy as np

            if not obj or not hasattr(obj, 'data') or not hasattr(obj.data, 'attributes'):
                return None

            # Read the RAW mesh, not the evaluated one.
            #
            # Two reasons, both bugs we hit with the evaluated mesh:
            #  * At domain-creation time the evaluated geometry is not reliably
            #    populated yet, so this returned None and the caller fell back to
            #    the start residue - non-deterministically (1ATN chain A fell
            #    back, chain D did not). That mis-placed the default full-chain
            #    pivot onto the first residue, which made "Set Pivot First" a
            #    silent no-op.
            #  * Once a molecule has domains, the parent's evaluated geometry is
            #    masked by Domain_Final_Not, so the centre of mass would be taken
            #    over whatever survives the mask.
            # The raw mesh is the full canonical atom set, always present and
            # deterministic. Its coordinates are canonical (pre-pivot), so the
            # centroid is mapped to world with local_to_world below, not
            # matrix_world @ co.
            mesh = obj.data
            attrs = mesh.attributes

            # Check for required attributes
            if "is_alpha_carbon" not in attrs or "position" not in attrs:
                # Fallback to bounding box center
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                if bbox:
                    return sum(bbox, Vector()) / len(bbox)
                return None

            # Get alpha carbon mask
            is_alpha_attr = attrs["is_alpha_carbon"]
            is_alpha = np.zeros(len(mesh.vertices), dtype=bool)
            is_alpha_attr.data.foreach_get("value", is_alpha)

            # Get vertex positions
            positions = np.zeros(len(mesh.vertices) * 3)
            mesh.vertices.foreach_get("co", positions)
            positions = positions.reshape(-1, 3)

            # Apply chain and residue filters if specified
            if chain_id is not None or start_res is not None or end_res is not None:
                # Get chain and residue data
                filter_mask = is_alpha.copy()

                if chain_id is not None and "chain_id" in attrs:
                    chain_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                    attrs["chain_id"].data.foreach_get("value", chain_ids)

                    # Resolve the chain to the INTEGER index the mesh attribute
                    # uses. MolecularNodes encodes chain_id as a sorted-unique
                    # integer and keeps the string labels in obj["chain_ids"]
                    # (list index == the integer). A caller passing a letter
                    # ("A") must be mapped through that list, or np.isin compares
                    # a letter against an int array, never matches, and the whole
                    # thing silently falls back to the bounding-box centre of the
                    # (shared, full) mesh - the same wrong point for every chain.
                    search_indices = []
                    if isinstance(chain_id, int):
                        search_indices.append(chain_id)
                    elif isinstance(chain_id, str) and chain_id.isdigit():
                        search_indices.append(int(chain_id))
                    chain_labels = list(obj.get("chain_ids") or [])
                    if chain_id in chain_labels:
                        search_indices.append(chain_labels.index(chain_id))

                    if search_indices:
                        chain_mask = np.isin(chain_ids, search_indices)
                        filter_mask &= chain_mask
                    else:
                        print(f"Warning: could not resolve chain {chain_id!r} to "
                              f"an index on {obj.name}; using all chains")

                if (start_res is not None or end_res is not None) and "res_id" in attrs:
                    res_ids = np.zeros(len(mesh.vertices), dtype=np.int32)
                    attrs["res_id"].data.foreach_get("value", res_ids)

                    if start_res is not None:
                        filter_mask &= (res_ids >= start_res)
                    if end_res is not None:
                        filter_mask &= (res_ids <= end_res)

                # Filter positions
                alpha_positions = positions[filter_mask]
            else:
                # Just use all alpha carbons
                alpha_positions = positions[is_alpha]

            if len(alpha_positions) == 0:
                # Fallback to bounding box center
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                if bbox:
                    return sum(bbox, Vector()) / len(bbox)
                return None

            # Calculate center of mass (simple average of alpha carbons)
            # Using carbon mass (12.01) for all alpha carbons
            center_local = np.mean(alpha_positions, axis=0)
            # Raw mesh coordinates are canonical (pre-pivot); map through the
            # pivot with local_to_world, not matrix_world @ co.
            center_world = domain_space.local_to_world(obj, Vector(center_local))

            return center_world

        except Exception as e:
            print(f"Error calculating center of mass: {e}")
            import traceback
            traceback.print_exc()
            return None
    # --- End Helper ---

    # --- Helper: Set Protein Pivot and Center ---
    def set_protein_pivot_to_center_of_mass(self, context):
        """
        Set protein's pivot to center of mass and move protein to world origin.
        This is called automatically on protein import.

        Args:
            context: Blender context

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.molecule or not self.molecule.object:
            return False

        try:
            obj = self.molecule.object

            # Calculate center of mass for entire protein
            center_of_mass = self._calculate_center_of_mass(context, obj)

            if not center_of_mass:
                # Nothing to aim at: fall back to the bounding-box centre of the
                # evaluated geometry, which is already pivot-corrected.
                print("Warning: Could not calculate center of mass, "
                      "falling back to the bounding-box centre")
                bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                if not bbox:
                    return False
                center_of_mass = sum(bbox, Vector()) / len(bbox)

            # Put the origin on the centre of mass without moving any atoms...
            if not domain_space.set_pivot_world(obj, center_of_mass):
                return False

            # ...then move the protein so that origin sits at the world origin.
            obj.location = (0, 0, 0)

            print("Set protein pivot to center of mass and moved to world origin")
            return True

        except Exception as e:
            print(f"Error setting protein pivot: {e}")
            import traceback
            traceback.print_exc()
            return False
    # --- End Helper ---

    # --- Helper: Set Domain Split Pivots ---
    def set_domain_split_pivots(self, context, domain_ids, chain_id):
        """
        Set intelligent pivots for domains created from a split operation.

        For 2 domains: Set pivots at boundary
        For 3+ domains: First at end, middle at beginning, last at center of mass

        Args:
            context: Blender context
            domain_ids: List of domain IDs created from the split (in order)
            chain_id: Chain ID for the domains

        Returns:
            bool: True if successful
        """
        if not domain_ids or len(domain_ids) < 2:
            return False

        try:
            num_domains = len(domain_ids)

            for i, domain_id in enumerate(domain_ids):
                if domain_id not in self.domains:
                    continue

                domain = self.domains[domain_id]
                if not domain.object:
                    continue

                pivot_pos = None

                if num_domains == 2:
                    # For 2 domains, set pivot at boundary between them
                    if i == 0:
                        # First domain: pivot at end (boundary)
                        pivot_pos = self._find_residue_alpha_carbon_pos(context, domain, residue_target='END')
                    else:
                        # Second domain: pivot at start (same boundary)
                        pivot_pos = self._find_residue_alpha_carbon_pos(context, domain, residue_target='START')

                elif num_domains >= 3:
                    # For 3+ domains
                    if i == 0:
                        # First domain: pivot at end
                        pivot_pos = self._find_residue_alpha_carbon_pos(context, domain, residue_target='END')
                    elif i == num_domains - 1:
                        # Last domain: pivot at center of mass
                        pivot_pos = self._calculate_center_of_mass(context, domain.object,
                                                                   chain_id=domain.chain_id,
                                                                   start_res=domain.start,
                                                                   end_res=domain.end)
                        if not pivot_pos:
                            # Fallback to start if center of mass fails
                            pivot_pos = self._find_residue_alpha_carbon_pos(context, domain, residue_target='START')
                    else:
                        # Middle domains: pivot at beginning
                        pivot_pos = self._find_residue_alpha_carbon_pos(context, domain, residue_target='START')

                # Apply the pivot
                if pivot_pos:
                    self._set_domain_origin_and_update_matrix(context, domain, pivot_pos)
                    print(f"Set split pivot for domain {domain.name} (position {i+1}/{num_domains})")

            return True

        except Exception as e:
            print(f"Error setting domain split pivots: {e}")
            import traceback
            traceback.print_exc()
            return False
    # --- End Helper ---

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
            return False

        try:
            # Carries the pivot on the domain's geometry-nodes modifier rather
            # than baking it into vertices, so this is safe even though the
            # domain shares the parent molecule's mesh. No cursor to stash and no
            # selection to isolate: unlike origin_set, this touches only the one
            # object it is handed.
            if not domain_space.set_pivot_world(domain.object, target_pos):
                return False

            context.view_layer.update()

            # Store the domain's local matrix for resetting later
            # This is critical for Reset Transform functionality
            domain.object["initial_matrix_local"] = [list(row) for row in domain.object.matrix_local]

            return True

        except Exception:
            import traceback
            traceback.print_exc()
            return False
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
            # Use numeric ID as string if no mapping
            available_chains.append(str(chain_id))
            
        return available_chains
        
    def _show_message(self, message: str, title: str = "Message", icon: str = 'INFO'):
        """Show a message to the user via Blender's interface"""
        def draw(self, context):
            self.layout.label(text=message)
            
        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

    def update_domain_range(self, domain_id: str, start: int, end: int,
                            enforce_no_overlap: bool = True) -> bool:
        """Re-range an existing domain in place, keeping its identity intact.

        `domain_id` and the domain's Blender object are deliberately left
        untouched. Both are load-bearing keys elsewhere: puppet memberships,
        linker endpoints and saved domain poses all store the domain id, while
        the scene pose library stores the object *name*. The old
        delete-and-recreate route silently orphaned every one of them, because
        the id embeds the residue range (see `_create_domain_with_params`) and
        the object name embeds it too (see `DomainDefinition`). Mutating in
        place is what lets a user re-range a domain without losing its puppet,
        its linkers, its animation or its pivot.

        Args:
            domain_id: The domain to re-range.
            start: New first residue (inclusive).
            end: New last residue (inclusive).
            enforce_no_overlap: Reject a range that collides with a sibling.
                Callers reconciling a whole chain layout at once turn this off:
                they have already validated the final layout, and intermediate
                states legitimately overlap - swapping two adjacent domains'
                ranges has no conflict-free ordering.

        Returns:
            True if the domain was updated.
        """
        if domain_id not in self.domains:
            return False

        try:
            domain = self.domains[domain_id]

            if enforce_no_overlap and self._check_domain_overlap(
                    domain.chain_id, start, end, exclude_domain_id=domain_id):
                print(f"update_domain_range: {start}-{end} overlaps another domain "
                      f"on chain {domain.chain_id}; leaving {domain_id} unchanged")
                return False

            if domain.start == start and domain.end == end:
                return True

            domain.start = start
            domain.end = end

            # Retarget the domain's own residue-range selection. This reuses the
            # existing nodes (and so preserves the domain's colour and style)
            # rather than rebuilding the tree from scratch.
            self._setup_domain_network(domain, domain.chain_id, start, end)

            # Re-punch the matching hole in the parent molecule. Same domain_id
            # in and out, so `domain_mask_nodes` stays keyed consistently.
            self._delete_domain_mask_nodes(domain_id)
            self._create_domain_mask_nodes(domain_id, domain.chain_id, start, end)

            self._update_residue_assignments(domain)
            self._mirror_domains_to_property_group()
            return True

        except Exception:
            import traceback
            traceback.print_exc()
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
                try:
                    if node and (link.from_node == node or link.to_node == node):
                        parent_node_group.links.remove(link)
                        break
                except ReferenceError:
                    continue

        # Remove the nodes safely
        for node in nodes_to_remove:
            try:
                if node:
                    # membership check on name avoids TypeError when node is invalid
                    if node.name in parent_node_group.nodes:
                        parent_node_group.nodes.remove(parent_node_group.nodes[node.name])
            except ReferenceError:
                # Node might already be freed; ignore
                pass
            
        # Remove from tracking dictionary
        del self.domain_mask_nodes[domain_id]
        
        # Note: We're no longer removing the domain infrastructure nodes (join node and NOT node)
        # when all domains are deleted. They will persist for future domain creations.

    def delete_domain(self, domain_id: str, is_cleanup_call: bool = False) -> Optional[str]:
        """Delete a domain and its object.

        If the domain is the last one on its chain, returns "DELETE_CHAIN" to signal
        that the entire chain should be removed.
        Otherwise, deletes only the specified domain without modifying other domains.

        Args:
            domain_id (str): The ID of the domain to delete.
            is_cleanup_call (bool): True if called during full molecule cleanup, to suppress UI messages.

        Returns:
            Optional[str]: "DELETE_CHAIN" if this was the last domain on the chain, None otherwise.
        """
        if domain_id not in self.domains:
            print(f"Warning: Domain {domain_id} not found for deletion.")
            return None

        # During cleanup (molecule deletion), just delete domains directly without merging
        if is_cleanup_call:
            print(f"Cleanup mode: directly deleting domain {domain_id}")
            self._delete_domain_direct(domain_id)
            return None

        # Get domain info before deletion
        domain_to_delete = self.domains[domain_id]
        chain_id = domain_to_delete.chain_id
        deleted_domain_name = domain_to_delete.name
        original_parent_id = getattr(domain_to_delete, 'parent_domain_id', None)

        # Count domains on the same chain
        domains_on_this_chain = []
        for d_id, d_obj in self.domains.items():
            if d_obj.chain_id == chain_id:
                domains_on_this_chain.append((d_id, d_obj))

        # Check if this is the last domain on the chain
        if len(domains_on_this_chain) <= 1 and domain_id in [d[0] for d in domains_on_this_chain]:
            print(f"Last domain on chain {chain_id}. Signaling chain deletion.")
            # Delete the domain first
            self._delete_domain_direct(domain_id)
            # Return special flag to signal chain deletion
            return "DELETE_CHAIN"

        # Find child domains that need reparenting
        children_to_reparent = []
        for child_id, child_domain in self.domains.items():
            if hasattr(child_domain, 'parent_domain_id') and child_domain.parent_domain_id == domain_id:
                children_to_reparent.append(child_id)

        # Delete the domain directly without merging or modifying adjacent domains
        print(f"Deleting domain {deleted_domain_name} ({domain_id}).")
        self._delete_domain_direct(domain_id)

        # Reparent child domains to the original parent
        if children_to_reparent:
            print(f"Reparenting {len(children_to_reparent)} child domain(s) to {original_parent_id}")
            self._reparent_child_domains(children_to_reparent, original_parent_id)

        return None

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
        
        print("Reparenting complete")

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
            except Exception:
                pass

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

                # Re-resolve infra node refs by name before touching them — the
                # cached pointers may be stale (see _refresh_domain_node_refs),
                # and reading `.name` off a stale pointer crashes Blender. If
                # the infrastructure is already gone, there's nothing to remove.
                if not self._refresh_domain_node_refs(parent_node_group):
                    self.join_nodes = []
                    self.final_not = None

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
                if hasattr(self, 'join_nodes'):
                    self.join_nodes = []
                if hasattr(self, 'final_not'):
                    self.final_not = None
        
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
        except Exception:
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

    def _get_chain_residue_ranges(self) -> Dict[str, Tuple[int, int]]:
        """Computes the min and max residue numbers for each chain, keyed by label_asym_id.
        Returns:
            Dict with structure:
            {
                'A': (1, 300),
                'B': (301, 511)
                ...
            }
        """
        ranges: Dict[str, Tuple[int, int]] = {}
        
        # Use working_array instead of molecule.array to handle AtomArrayStack
        working_array = getattr(self, 'working_array', None)
        if working_array is None:
            # Fallback if working_array wasn't set
            import biotite.structure as struc
            working_array = self.molecule.array
            if isinstance(self.molecule.array, struc.AtomArrayStack):
                working_array = self.molecule.array[0]
        
        # Check if required annotations exist using get_annotation_categories()
        existing_categories = working_array.get_annotation_categories()
        if 'res_id' not in existing_categories or 'chain_id_int' not in existing_categories:
            return {}

        res_ids = working_array.res_id
        # Use 'chain_id_int' for grouping, as this is our reliable internal integer index (0, 1, 2...)
        int_chain_indices = working_array.chain_id_int 

        unique_int_chain_keys = np.unique(int_chain_indices)

        for int_chain_key in unique_int_chain_keys:
            # Convert integer chain key to label_asym_id for the ranges dictionary key
            label_asym_id_for_key = self.idx_to_label_asym_id_map.get(int(int_chain_key))
            
            if not label_asym_id_for_key:
                # Fallback attempt using auth_chain_id_map if it has this integer key
                label_asym_id_for_key = self.auth_chain_id_map.get(int(int_chain_key))
                if not label_asym_id_for_key:
                    label_asym_id_for_key = str(int_chain_key) # Last resort, use the int as string

            mask = (int_chain_indices == int_chain_key)
            if np.any(mask):
                chain_res_ids = res_ids[mask]
                if chain_res_ids.size > 0:
                    ranges[label_asym_id_for_key] = (int(np.min(chain_res_ids)), int(np.max(chain_res_ids)))
            
        if not ranges:
            # As a last resort, if idx_to_label_asym_id_map exists, create default (e.g., 1-100) ranges for all known label_asym_ids
            if self.idx_to_label_asym_id_map:
                for label_asym_id_val in self.idx_to_label_asym_id_map.values():
                    ranges[label_asym_id_val] = (1, 100) # Default placeholder range

        return ranges

    def get_author_chain_id(self, numeric_chain_id: int) -> str:
        """Convert numeric chain ID to author chain ID
        
        Args:
            numeric_chain_id (int): The numeric chain ID to convert
            
        Returns:
            str: The author chain ID if found, otherwise the numeric chain ID as string
        """
        # Try auth_chain_id_map first (more authoritative)
        if self.auth_chain_id_map:
            auth_id = self.auth_chain_id_map.get(numeric_chain_id)
            if auth_id:
                return auth_id
        
        # Fallback to idx_to_label_asym_id_map
        if self.idx_to_label_asym_id_map:
            label_id = self.idx_to_label_asym_id_map.get(numeric_chain_id)
            if label_id:
                return label_id
        
        # Final fallback
        return str(numeric_chain_id)

    def get_int_chain_index(self, label_asym_id: str) -> Optional[int]:
        """Return the internal integer chain index for a given label_asym_id
        
        Args:
            label_asym_id (str): The label asymmetric ID to look up
            
        Returns:
            Optional[int]: The integer chain index if found, otherwise None
        """
        # Direct mapping from idx_to_label_asym_id_map
        for idx, lab in self.idx_to_label_asym_id_map.items():
            if lab == label_asym_id:
                return idx
        
        # Fallback mapping from auth_chain_id_map
        for idx, auth_lab in self.auth_chain_id_map.items():
            if auth_lab == label_asym_id:
                return idx

        return None

    def _resolve_chain_socket_name(self, chain_id) -> Optional[str]:
        """Resolve a chain identifier to the chain-select iswitch socket name.

        The chain-select iswitch's Index is the INT ``chain_id`` mesh attribute
        (the sorted-label_asym_id index), and each boolean socket is NAMED after
        ``idx_to_label_asym_id_map[index]``. So resolve ``chain_id`` to its
        integer index first — handling an index string ("2"), an int, or an
        author/label letter ("D") — then map that index back to the canonical
        socket name. This avoids the author-vs-label ambiguity in
        ``get_blender_chain_id`` that left per-chain mask terms empty (so the
        parent's NOT(OR) selection became "all" and it re-rendered the whole
        molecule).
        """
        chain_idx = None
        if isinstance(chain_id, int):
            chain_idx = chain_id
        elif isinstance(chain_id, str) and chain_id.isdigit():
            chain_idx = int(chain_id)
        if chain_idx is None:
            chain_idx = self.get_int_chain_index(str(chain_id))
        if chain_idx is None:
            for idx, auth in self.auth_chain_id_map.items():
                if str(auth) == str(chain_id):
                    chain_idx = idx
                    break
        if chain_idx is None:
            return None
        return self.idx_to_label_asym_id_map.get(chain_idx)

    def _setup_domain_network(self, domain: DomainDefinition, chain_id: str, start: int, end: int):
        """Set up the domain's node network using the same structure as the preview domain"""
        if not domain.object or not domain.node_group:
            return False
            
        try:
            # Get references to key nodes
            input_node = nodes.get_input(domain.node_group)
            output_node = nodes.get_output(domain.node_group)
            
            if not (input_node and output_node):
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
                
                # Use the label_asym_id values which are the source of truth for node socket names
                available_chains = list(self.idx_to_label_asym_id_map.values()) or [str(chain_id)]
                
                chain_select_group = nodes.custom_iswitch(
                    name=f"selection_{self.identifier}", 
                    iter_list=available_chains, 
                    field="chain_id", 
                    dtype="BOOLEAN"
                )
                
                chain_select = nodes.add_custom(
                    domain.node_group,
                    chain_select_group.name
                )
                chain_select.name = "Select Chain"
                chain_select.location = (input_node.location.x + 200, input_node.location.y + 100)
            
            # Set the selected chain. Resolve via the integer chain index (what
            # the iswitch compares) so domain copies and the parent mask agree.
            socket_name = self._resolve_chain_socket_name(chain_id)
            for input_socket in chain_select.inputs:
                if input_socket.type == 'BOOLEAN':
                    input_socket.default_value = (
                        socket_name is not None and input_socket.name == socket_name)
            
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
            
            # The colour node is matched by tree-name *prefix*: the first
            # setup renames its tree to "Color Common_<domain_id>" to make it
            # unique, so an exact match finds nothing on a later re-range -
            # which then created a second colour node with a fresh random
            # colour, silently repainting the domain every time its range was
            # edited.
            for node in domain.node_group.nodes:
                if (node.bl_idname == 'GeometryNodeGroup' and
                    node.node_tree and
                    node.node_tree.name.startswith("Color Common")):
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
                new_node_tree_name = f"Color Common_{domain.domain_id}"

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
                # Found existing Color Common node - need to make it unique for this domain
                # Check if this node's tree is already unique to this domain
                if color_emit.node_tree and not color_emit.node_tree.name.endswith(f"_{domain.domain_id}"):
                    # This node tree is shared - create a unique copy
                    original_node_tree = color_emit.node_tree
                    new_node_tree_name = f"Color Common_{domain.domain_id}"

                    # Create a copy of the node tree with a unique name
                    new_node_tree = original_node_tree.copy()
                    new_node_tree.name = new_node_tree_name
                    color_emit.node_tree = new_node_tree
                    print(f"Created unique Color Common node tree for domain {domain.domain_id}")

                # Now update the color on our unique node tree
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

            # Re-insert the pivot transform between the group input and the rest
            # of the chain. This has to run *after* the links.clear() above: that
            # strips the pivot's links while leaving its nodes in place, so the
            # domain would silently render at pivot-offset until something else
            # rebuilt the tree. ensure_pivot_input is idempotent and rewires
            # unconditionally for exactly this reason.
            domain_space.ensure_pivot_input(domain.node_group)

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
            
        except Exception:
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
            return
            
        parent_node_group = parent_modifier.node_group
        
        try:
            # Find main style node
            main_style_node = self.get_main_style_node()
            if not main_style_node:
                return
            
            # Re-resolve the domain-mask infrastructure nodes by name. The
            # cached bpy pointers (domain_join_node / join_nodes / final_not)
            # can be invalidated — and dereferencing them crashes Blender —
            # after an unrelated node-collection reallocation, e.g. duplicating
            # this molecule and then deleting the copy.
            if not self._refresh_domain_node_refs(parent_node_group):
                # The infrastructure is missing from this node group entirely.
                # Deleting a duplicate of this molecule tears the Join/NOT nodes
                # out of the (aliased) group, leaving the original without them.
                # Rebuild it (idempotent self-heal) rather than silently
                # skipping the mask — otherwise the split "succeeds" but the
                # domain is never actually masked out. Then re-resolve.
                self._setup_protein_domain_infrastructure()
                if not self._refresh_domain_node_refs(parent_node_group):
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
                # Use the label_asym_id values for the geometry node chain selection
                available_chains = list(self.idx_to_label_asym_id_map.values()) or [str(chain_id)]
                
                chain_select_group = nodes.custom_iswitch(
                    name=f"selection_{self.identifier}", 
                    iter_list=available_chains, 
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
            
            # Step 2: Configure chain selection. Resolve via the integer chain
            # index (what the iswitch's Index attribute is) rather than the
            # author/label-ambiguous get_blender_chain_id, so the parent mask
            # actually excludes this chain.
            socket_name = self._resolve_chain_socket_name(chain_id)
            matched = False
            for input_socket in chain_select.inputs:
                if input_socket.type != 'BOOLEAN':
                    continue
                on = (socket_name is not None and input_socket.name == socket_name)
                input_socket.default_value = on
                matched = matched or on

            if not matched:
                # Fail loud: an unresolved chain leaves the mask term empty,
                # which makes the parent re-render the whole molecule.
                print(f"[ProteinBlender] domain mask: could not resolve chain "
                      f"'{chain_id}' to a chain-select socket on {self.identifier}; "
                      f"the parent object may render its full surface.")
            
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
            
        except Exception:
            # Error in mask node creation suppressed to reduce log noise
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

    @staticmethod
    def _write_color_to_active_driver(domain, color: tuple) -> bool:
        """Set ``color`` on whatever node currently feeds Set Color's Color input.

        Returns True when it handled the write. Only the Visual Set-up path's
        "Custom Combine Color" node is handled here; the Color Common wiring is
        left to the caller, which also has to give each domain its own copy of
        that group first.

        Node lookups are by name and links are compared with ``==``: Blender
        hands back a fresh wrapper per access, so ``is`` would never match.
        """
        tree = getattr(domain, "node_group", None)
        if tree is None:
            return False

        set_color = next((n for n in tree.nodes if n.name == "Set Color"), None)
        if set_color is None:
            return False
        color_input = next((s for s in set_color.inputs if "Color" in s.name),
                           None)
        if color_input is None:
            return False

        driver = next((link.from_node for link in tree.links
                       if link.to_socket == color_input), None)
        if driver is None or driver.name != "Custom Combine Color":
            return False

        for channel, value in zip(("Red", "Green", "Blue"), color):
            if channel in driver.inputs:
                driver.inputs[channel].default_value = value
        return True

    def update_domain_color(self, domain_id: str, color: tuple) -> bool:
        """Update the color of a domain

        Args:
            domain_id (str): The ID of the domain to update
            color (tuple): The new color as an RGBA tuple (r, g, b, a)

        Returns:
            bool: True if successful, False otherwise
        """
        if domain_id not in self.domains or not self.domains[domain_id].node_group:
            return False

        domain = self.domains[domain_id]
        try:
            # Update the stored color in the domain object for consistency
            domain.color = color

            # Write the colour where the tree actually reads it.
            #
            # There are two colour paths into a domain and they use different
            # nodes. Import wires "Set Color".Color from the "Color Common"
            # group, which is what the loop below drives. But the Visual Set-up
            # picker (core/visual_style.apply_color_to_object) builds a
            # "Custom Combine Color" node and *relinks* Set Color.Color to it,
            # discarding the Color Common link. From then on this operator was
            # writing to a node that drives nothing: it reported FINISHED,
            # updated the domain model, and left the render untouched.
            if self._write_color_to_active_driver(domain, color):
                return True

            # Matched by prefix, not equality: a range update rebuilds the
            # domain's selection nodes and the re-added colour node comes back
            # name-collided as "Color Common.001". An exact match then finds
            # nothing and the colour write silently does nothing.
            for node in domain.node_group.nodes:
                if node.name.startswith("Color Common"):
                    # Check if this Color Common node has a unique node tree for this domain
                    if (node.bl_idname == 'GeometryNodeGroup' and node.node_tree and
                        not node.node_tree.name.endswith(f"_{domain_id}")):
                        # The node tree is shared - create a unique copy
                        original_node_tree = node.node_tree
                        new_node_tree_name = f"Color Common_{domain_id}"

                        # Create a copy of the node tree with a unique name
                        new_node_tree = original_node_tree.copy()
                        new_node_tree.name = new_node_tree_name
                        node.node_tree = new_node_tree
                        print(f"Created unique Color Common node tree for domain {domain_id} during color update")

                    # Set the default_value directly with the color tuple
                    node.inputs["Carbon"].default_value = color
                    return True
        except Exception as e:
            print(f"Error updating domain color for {domain_id}: {e}")
            import traceback
            traceback.print_exc()
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

    def copy_domain(self, domain_id: str) -> Optional[str]:
        """Create a copy of an existing domain.
        
        Args:
            domain_id: The ID of the domain to copy
            
        Returns:
            The ID of the newly created domain copy, or None if failed
        """
        if domain_id not in self.domains:
            print(f"Error: Domain {domain_id} not found for copying")
            return None
            
        original_domain = self.domains[domain_id]
        
        # Track copy numbers for this domain family
        if not hasattr(self, '_domain_copy_counters'):
            self._domain_copy_counters = {}
        
        # Determine the base name for copies
        if hasattr(original_domain, 'original_domain_id') and original_domain.original_domain_id:
            # This is already a copy, use its original
            base_domain_id = original_domain.original_domain_id
        else:
            # This is an original domain
            base_domain_id = domain_id
            
        # Get the next copy number
        if base_domain_id not in self._domain_copy_counters:
            self._domain_copy_counters[base_domain_id] = 0
        self._domain_copy_counters[base_domain_id] += 1
        copy_number = self._domain_copy_counters[base_domain_id]
        
        # Create a new domain with the same parameters
        # The original domain's chain_id might be either numeric or author format
        # We need to ensure we pass the numeric chain_id to _create_domain_with_params
        numeric_chain_id = None
        original_chain = original_domain.chain_id
        
        # Check if original_chain is already numeric
        if str(original_chain).isdigit():
            numeric_chain_id = str(original_chain)
        else:
            # It's an author chain ID (like 'J'), find the numeric equivalent
            for num_id, auth_id in self.chain_mapping.items():
                if auth_id == original_chain:
                    numeric_chain_id = str(num_id)
                    break
        
        if not numeric_chain_id:
            # Fallback: try to find it in reverse
            # Maybe the original_chain is in a different format
            print(f"Warning: Could not find numeric chain_id for {original_chain}")
            print(f"  Chain mapping: {self.chain_mapping}")
            print(f"  Original domain chain_id: {original_domain.chain_id}")
            numeric_chain_id = "0"  # Default to first chain
        
        print(f"DEBUG: Copying domain with chain_id conversion: {original_chain} -> {numeric_chain_id}")
            
        # Generate copy name with number suffix (e.g., "Chain A 1")
        # If copying a copy, we need to extract the base name without the copy number
        original_name = original_domain.name
        
        # Check if the name already has a copy number suffix (e.g., "Chain A 1")
        import re
        match = re.match(r'^(.+)\s+(\d+)$', original_name)
        if match and hasattr(original_domain, 'is_copy') and original_domain.is_copy:
            # This is a copy, extract the base name
            base_name = match.group(1)
            copy_name = f"{base_name} {copy_number}"
        else:
            # This is an original or doesn't have a numbered suffix
            copy_name = f"{original_name} {copy_number}"
            
        # Create the domain copy
        # For full chain copies, don't set parent_domain_id to avoid making it a child
        # Check if this is a full chain domain
        is_full_chain = False
        if hasattr(self, 'chain_residue_ranges'):
            chain_key = str(original_domain.chain_id)
            if hasattr(self, 'idx_to_label_asym_id_map'):
                # Map numeric chain_id to label if needed
                if str(original_domain.chain_id).isdigit():
                    chain_key = self.idx_to_label_asym_id_map.get(int(original_domain.chain_id), chain_key)
            
            if chain_key in self.chain_residue_ranges:
                min_res, max_res = self.chain_residue_ranges[chain_key]
                if original_domain.start == min_res and original_domain.end == max_res:
                    is_full_chain = True
        
        # If it's a full chain copy, use special flag to prevent auto-parenting
        # Otherwise, keep the same parent as the original
        parent_for_copy = "NO_AUTO_PARENT" if is_full_chain else original_domain.parent_domain_id
        
        new_domain_ids = self._create_domain_with_params(
            chain_id=numeric_chain_id,
            start=original_domain.start,
            end=original_domain.end,
            name=copy_name,
            auto_fill_chain=False,  # Don't auto-fill
            parent_domain_id=parent_for_copy  # NO_AUTO_PARENT for full chains, otherwise keep same parent
        )
        
        if not new_domain_ids:
            print(f"Failed to create domain copy")
            return None
            
        # Get the main new domain ID (should be the first one)
        new_domain_id = new_domain_ids[0] if new_domain_ids else None
        
        if new_domain_id and new_domain_id in self.domains:
            new_domain = self.domains[new_domain_id]
            
            # Mark as a copy
            new_domain.is_copy = True
            new_domain.copy_number = copy_number
            new_domain.original_domain_id = base_domain_id
            
            # Copy the color from the original
            new_domain.color = original_domain.color
            if new_domain.object:
                new_domain.object.domain_color = original_domain.color
                
            # Copy the style
            new_domain.style = original_domain.style
            if new_domain.object:
                new_domain.object.domain_style = original_domain.style
                
            print(f"Created domain copy: {new_domain_id} (copy #{copy_number} of {base_domain_id})")
            print(f"  Copy chain_id: {new_domain.chain_id}, Original chain_id: {original_domain.chain_id}")
            print(f"  Copy name: {new_domain.name}")
            print(f"  Copy object: {new_domain.object.name if new_domain.object else 'None'}")
            print(f"  Original object: {original_domain.object.name if original_domain.object else 'None'}")
            
            # Verify objects are different
            if new_domain.object and original_domain.object:
                if new_domain.object.name == original_domain.object.name:
                    print(f"WARNING: Copy and original share the same object name!")
            
            return new_domain_id
        
        return None

    def _delete_domain_direct(self, domain_id: str):
        """Internal method to delete a domain without adjusting adjacent domains"""
        # Delete domain mask nodes in parent molecule
        self._delete_domain_mask_nodes(domain_id)

        # Clean up domain object and node group
        self.domains[domain_id].cleanup()

        # Remove from domains dictionary
        del self.domains[domain_id]

        # Keep PG mirror in sync so the next save doesn't keep a ghost entry.
        self._mirror_domains_to_property_group()

    def _get_list_item(self):
        """Find the MoleculeListItem PropertyGroup for this molecule.

        Returns None when called from a context without a scene (e.g. during
        construction before the item has been added).
        """
        try:
            scene = bpy.context.scene
        except Exception:
            return None
        if not scene or not hasattr(scene, "molecule_list_items"):
            return None
        for item in scene.molecule_list_items:
            if item.identifier == self.identifier:
                return item
        return None

    def _mirror_domains_to_property_group(self):
        """Mirror self.domains (runtime dict) into MoleculeListItem.domains
        (persistent CollectionProperty).

        Without this, every domain create/split/copy/delete is invisible to
        a .blend save - see tests/COVERAGE.md, "Domains never reached the
        .blend". Called at the end of each domain CRUD operation.
        """
        item = self._get_list_item()
        if item is None:
            return
        try:
            item.domains.clear()
            for domain_id, domain in self.domains.items():
                pg = item.domains.add()
                pg.domain_id = domain_id
                pg.chain_id = domain.chain_id
                pg.start = domain.start
                pg.end = domain.end
                pg.name = domain.name
                # Keep the object PointerProperty AND a stored name so
                # reconstruction can heal a stale pointer.
                if domain.object:
                    pg.object = domain.object
                    pg.object_name = domain.object.name
                else:
                    pg.object_name = getattr(domain, 'object_name', '')
        except Exception as e:
            # Mirror failure must never break the surrounding op.
            print(f"_mirror_domains_to_property_group: failed for {self.identifier}: {e}")

    # NOTE: the former author/label-ambiguous get_blender_chain_id() was removed;
    # use _resolve_chain_socket_name() — it resolves to the integer chain index
    # first, which is what the chain-select iswitch actually compares.
