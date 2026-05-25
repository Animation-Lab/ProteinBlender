"""Centralized chain mapping utilities.

This module provides functions for working with protein chain IDs and mappings.
It consolidates chain-related logic that was previously duplicated across
multiple files (molecule_wrapper.py, molecule_props.py, scene_manager.py).
"""

import bpy
from typing import Dict, List, Tuple, Optional, Any
import json

from .blender_utils import get_object_safe


def get_chain_mapping_from_string(mapping_str: str) -> Dict[int, str]:
    """Parse chain mapping from a comma-separated string format.

    Args:
        mapping_str: String in format "0:A,1:B,2:C"

    Returns:
        Dictionary mapping chain index (int) to chain ID (str)
    """
    if not mapping_str:
        return {}

    mapping = {}
    for pair in mapping_str.split(","):
        if ":" in pair:
            try:
                k, v = pair.split(":", 1)
                mapping[int(k.strip())] = v.strip()
            except (ValueError, TypeError):
                continue
    return mapping


def chain_mapping_to_string(mapping: Dict[int, str]) -> str:
    """Convert chain mapping dictionary to string format.

    Args:
        mapping: Dictionary mapping chain index (int) to chain ID (str)

    Returns:
        String in format "0:A,1:B,2:C"
    """
    if not mapping:
        return ""
    return ",".join(f"{k}:{v}" for k, v in sorted(mapping.items()))


def get_chain_mapping_from_object(obj: bpy.types.Object) -> Dict[int, str]:
    """Extract chain mapping from a Blender object's custom property.

    MolecularNodes stores chain mapping in the mesh data as "chain_mapping_str".

    Args:
        obj: The Blender object (typically a protein mesh)

    Returns:
        Dictionary mapping chain index (int) to chain ID (str)
    """
    if not obj or not hasattr(obj, 'data') or not obj.data:
        return {}

    mapping_str = obj.data.get("chain_mapping_str", "")
    return get_chain_mapping_from_string(mapping_str)


def get_chain_ids_from_object(obj: bpy.types.Object) -> List[int]:
    """Get sorted list of unique chain IDs from object's mesh attributes.

    Args:
        obj: The Blender object (typically a protein mesh)

    Returns:
        Sorted list of unique chain index integers
    """
    if not obj or not hasattr(obj, 'data') or not obj.data:
        return []

    if "chain_id" not in obj.data.attributes:
        return []

    try:
        chain_attr = obj.data.attributes["chain_id"]
        return sorted({value.value for value in chain_attr.data})
    except (AttributeError, KeyError):
        return []


def get_author_chain_id(molecule: Any, chain_idx: int) -> str:
    """Get the author-assigned chain ID from internal chain index.

    This function tries multiple chain mapping sources in order of preference:
    1. auth_chain_id_map - Author-provided chain IDs (most accurate for display)
    2. chain_mapping - General chain mapping
    3. idx_to_label_asym_id_map - Label asymmetric ID mapping
    4. Fallback to alphabet conversion

    Args:
        molecule: MoleculeWrapper or similar object with chain mapping attributes
        chain_idx: The internal chain index (0, 1, 2, ...)

    Returns:
        The author chain ID string (e.g., "A", "B", "S", "T")
    """
    # Try auth_chain_id_map first (most accurate for display)
    if hasattr(molecule, 'auth_chain_id_map') and molecule.auth_chain_id_map:
        if chain_idx in molecule.auth_chain_id_map:
            return molecule.auth_chain_id_map[chain_idx]

    # Fall back to chain_mapping
    if hasattr(molecule, 'chain_mapping') and molecule.chain_mapping:
        if chain_idx in molecule.chain_mapping:
            return molecule.chain_mapping[chain_idx]

    # Fall back to idx_to_label_asym_id_map
    if hasattr(molecule, 'idx_to_label_asym_id_map') and molecule.idx_to_label_asym_id_map:
        if chain_idx in molecule.idx_to_label_asym_id_map:
            return molecule.idx_to_label_asym_id_map[chain_idx]

    # Final fallback: convert index to letter (A=0, B=1, etc.)
    if isinstance(chain_idx, int) and 0 <= chain_idx < 26:
        return chr(65 + chain_idx)

    return f"Chain{chain_idx}"


def get_chain_idx_from_author_id(molecule: Any, author_id: str) -> Optional[int]:
    """Get the internal chain index from an author chain ID.

    This is the reverse of get_author_chain_id.

    Args:
        molecule: MoleculeWrapper or similar object with chain mapping attributes
        author_id: The author chain ID string (e.g., "A", "B")

    Returns:
        The internal chain index, or None if not found
    """
    # Check auth_chain_id_map
    if hasattr(molecule, 'auth_chain_id_map') and molecule.auth_chain_id_map:
        for idx, aid in molecule.auth_chain_id_map.items():
            if aid == author_id:
                return idx

    # Check chain_mapping
    if hasattr(molecule, 'chain_mapping') and molecule.chain_mapping:
        for idx, aid in molecule.chain_mapping.items():
            if aid == author_id:
                return idx

    # Check idx_to_label_asym_id_map
    if hasattr(molecule, 'idx_to_label_asym_id_map') and molecule.idx_to_label_asym_id_map:
        for idx, aid in molecule.idx_to_label_asym_id_map.items():
            if aid == author_id:
                return idx

    # Try converting single letter to index
    if len(author_id) == 1 and author_id.isalpha():
        return ord(author_id.upper()) - 65

    return None


def get_chain_residue_range(
    molecule: Any,
    chain_id: str
) -> Tuple[int, int]:
    """Get the residue number range for a chain.

    Args:
        molecule: MoleculeWrapper or similar with chain_residue_ranges attribute
        chain_id: The chain ID to look up (can be author ID or label ID)

    Returns:
        Tuple of (min_residue, max_residue), defaults to (1, 9999) if not found
    """
    default_range = (1, 9999)

    if not hasattr(molecule, 'chain_residue_ranges') or not molecule.chain_residue_ranges:
        return default_range

    # Try direct lookup first
    if chain_id in molecule.chain_residue_ranges:
        return molecule.chain_residue_ranges[chain_id]

    # Try as string if it was passed as int
    str_chain_id = str(chain_id)
    if str_chain_id in molecule.chain_residue_ranges:
        return molecule.chain_residue_ranges[str_chain_id]

    return default_range


def serialize_chain_mapping(mapping: Dict[int, str]) -> str:
    """Serialize chain mapping to JSON string for storage in PropertyGroup.

    Args:
        mapping: Dictionary mapping chain index (int) to chain ID (str)

    Returns:
        JSON string representation
    """
    # Convert int keys to strings for JSON compatibility
    str_keyed = {str(k): v for k, v in mapping.items()}
    return json.dumps(str_keyed)


def deserialize_chain_mapping(json_str: str) -> Dict[int, str]:
    """Deserialize chain mapping from JSON string.

    Args:
        json_str: JSON string representation

    Returns:
        Dictionary mapping chain index (int) to chain ID (str)
    """
    if not json_str:
        return {}
    try:
        str_keyed = json.loads(json_str)
        return {int(k): v for k, v in str_keyed.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def serialize_residue_ranges(ranges: Dict[str, Tuple[int, int]]) -> str:
    """Serialize chain residue ranges to JSON string.

    Args:
        ranges: Dictionary mapping chain ID to (min, max) residue tuple

    Returns:
        JSON string representation
    """
    # Convert tuples to lists for JSON compatibility
    serializable = {k: list(v) for k, v in ranges.items()}
    return json.dumps(serializable)


def deserialize_residue_ranges(json_str: str) -> Dict[str, Tuple[int, int]]:
    """Deserialize chain residue ranges from JSON string.

    Args:
        json_str: JSON string representation

    Returns:
        Dictionary mapping chain ID to (min, max) residue tuple
    """
    if not json_str:
        return {}
    try:
        data = json.loads(json_str)
        return {k: tuple(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def get_possible_chain_ids(chain_id: Any) -> List[Any]:
    """Get all possible representations of a chain ID for matching.

    Chain IDs can be stored as strings or integers, and may need to be
    matched in different formats. This function returns all possible
    representations to try.

    Args:
        chain_id: The chain ID (can be int, str, etc.)

    Returns:
        List of possible representations to try for matching
    """
    search_ids = [chain_id]

    # If it's a single letter, also try the numeric equivalent
    if isinstance(chain_id, str) and len(chain_id) == 1 and chain_id.isalpha():
        try:
            numeric_chain = ord(chain_id.upper()) - ord('A')
            search_ids.append(numeric_chain)
            search_ids.append(str(numeric_chain))
        except Exception:
            pass

    # If it's numeric (int or string of digits), also try the letter equivalent
    elif isinstance(chain_id, (int, str)):
        str_id = str(chain_id)
        if str_id.isdigit():
            try:
                int_chain_id = int(str_id)
                if 0 <= int_chain_id < 26:
                    alpha_chain = chr(int_chain_id + ord('A'))
                    search_ids.append(alpha_chain)
                search_ids.append(int_chain_id)
                search_ids.append(str_id)
            except Exception:
                pass

    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for cid in search_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)

    return unique_ids


def chain_match_tokens(molecule: Any, chain_token: Any) -> set:
    """Return every string form a chain may be identified by.

    The protein outliner identifies a chain by its numeric *index* ("2")
    while a domain stores the author chain *letter* ("D"). ``chain_token``
    may be either; this returns both forms (e.g. ``{"2", "D"}``) so callers
    can match a domain's ``chain_id`` regardless of which convention it uses.

    The index<->letter step goes through the molecule's own chain maps rather
    than alphabet math (``chr(65 + idx)``), which is wrong for gapped chain
    sets such as A, B, D — there index 2 is "D", not "C".
    """
    tokens = {str(chain_token)}
    s = str(chain_token)
    if s.isdigit():
        letter = get_author_chain_id(molecule, int(s))
        if letter:
            tokens.add(str(letter))
    else:
        idx = get_chain_idx_from_author_id(molecule, s)
        if idx is not None:
            tokens.add(str(idx))
    return tokens


def domain_in_chain(molecule: Any, chain_token: Any, domain: Any) -> bool:
    """True if ``domain`` belongs to the chain identified by ``chain_token``.

    Bridges the chain-index vs. chain-letter mismatch via
    :func:`chain_match_tokens`.
    """
    domain_chain_id = getattr(domain, "chain_id", None)
    if domain_chain_id is None:
        return False
    return str(domain_chain_id) in chain_match_tokens(molecule, chain_token)


def chain_token_from_item(chain_item: Any) -> str:
    """Extract the chain identifier from a chain outliner row.

    Regular chains use item_ids of the form ``<mol>_chain_<index>``; chain
    copies use the domain id directly. Falls back to the row's ``chain_id``.
    """
    item_id = getattr(chain_item, "item_id", "") or ""
    if "_chain_" in item_id:
        return item_id.split("_chain_")[-1]
    return getattr(chain_item, "chain_id", "") or item_id


def get_chain_domains(molecule: Any, chain_item: Any) -> List[Tuple[str, Any]]:
    """Return the ``(domain_id, domain)`` pairs a chain outliner row maps to.

    * A chain copy's row carries the domain id as its item_id, so that single
      domain is returned.
    * A full or split chain returns every non-copy domain whose chain matches
      the row (one domain for a whole chain, several once it is split).
    """
    if molecule is None:
        return []

    item_id = getattr(chain_item, "item_id", "") or ""
    # Chain copy: the row's item_id is the domain id itself.
    if item_id in molecule.domains:
        return [(item_id, molecule.domains[item_id])]

    token = chain_token_from_item(chain_item)
    pairs = []
    for domain_id, domain in molecule.domains.items():
        if getattr(domain, "is_copy", False):
            continue
        if domain_in_chain(molecule, token, domain):
            pairs.append((domain_id, domain))
    return pairs


def get_chain_objects(molecule: Any, chain_item: Any) -> List[bpy.types.Object]:
    """Return every live Blender object a chain outliner row maps to.

    This is the single source of truth for "what objects does this chain
    refer to", shared by selection sync, colouring and splitting so they all
    agree. Resolution order:

      1. If the row is backed by a single object — the common "one object per
         chain" case, and full-chain copies — its ``object_name`` points
         straight at it.
      2. Otherwise the chain has been split into domains: collect every
         non-copy domain object belonging to the chain.
    """
    # 1. Single-object shortcut (full chain or chain copy).
    name = getattr(chain_item, "object_name", "") or ""
    obj = bpy.data.objects.get(name)
    if obj is not None:
        return [obj]

    # 2. Split chain — gather the matching domain objects.
    objects: List[bpy.types.Object] = []
    seen = set()
    for _domain_id, domain in get_chain_domains(molecule, chain_item):
        live = get_object_safe(getattr(domain, "object", None),
                               getattr(domain, "object_name", "") or "")
        if live is not None and live.name not in seen:
            seen.add(live.name)
            objects.append(live)
    return objects


def build_chain_items_for_enum(molecule: Any) -> List[Tuple[str, str, str]]:
    """Build chain items list for Blender EnumProperty.

    Args:
        molecule: MoleculeWrapper or similar with chain data

    Returns:
        List of (identifier, name, description) tuples for EnumProperty
    """
    if not molecule or not hasattr(molecule, 'object'):
        return []

    obj = molecule.object
    if not obj:
        return []

    chain_ids = get_chain_ids_from_object(obj)
    if not chain_ids:
        return []

    items = []
    for chain_id in chain_ids:
        author_id = get_author_chain_id(molecule, chain_id)
        identifier = str(chain_id)
        name = f"Chain {author_id}"
        description = author_id
        items.append((identifier, name, description))

    return items
