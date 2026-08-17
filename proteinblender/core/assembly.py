"""Deposited biological assemblies (BIOMT / mmCIF) for ProteinBlender.

A deposited structure often contains only the asymmetric unit - the smallest
piece the crystallographer had to solve. The *biological* assembly, the thing
that exists in a cell, is that unit repeated under a set of symmetry
operators: a dimer, a ring, a viral capsid. Those operators ship with the
file, as ``REMARK 350`` BIOMT records in PDB or ``pdbx_struct_assembly_gen``
in mmCIF, and MolecularNodes already parses both into
``object.mn.biological_assemblies``.

This module is the ProteinBlender side of that: reading what a molecule
offers, deciding whether any of it is worth showing, and wiring the
geometry-nodes assembly node into the objects that are actually on screen.

**Why the copies go on the domain objects.** A ProteinBlender import creates
one object per domain on top of the molecule object, all sharing one mesh.
The molecule object only draws the atoms *no* domain covers, and since import
gives every chain a domain, it renders nothing at all - verified by rendering
it in isolation, which produces zero covered pixels. Inserting the assembly
node into the molecule object alone would therefore build a perfectly correct
assembly that nobody can see. The node goes into every domain object, and
into the molecule object too so that a molecule whose domains have been
deleted still assembles.

The copies are geometry-nodes *instances*, not real geometry - the same
tradeoff ChimeraX makes when it shows a capsid as graphical clones rather
than atomic copies. One capsid's atoms are stored once no matter how many
copies are drawn.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import bpy
import numpy as np

logger = logging.getLogger(__name__)

#: Name given to every assembly node this module inserts, so they can be found
#: again for removal without keeping bpy pointers around (which a later
#: ``nodes.new()``/``nodes.remove()`` would silently invalidate).
ASSEMBLY_NODE_NAME = "PB_Assembly"

#: Rotation/translation blend factors are exposed on the node as 0-1 sliders.
#: At 0 every copy sits on the asymmetric unit; at 1 the assembly is complete.
#: Phase 2 animates this; Phase 1 just pins it to "assembled".
_FULLY_ASSEMBLED = 1.0


@dataclass(frozen=True)
class AssemblyInfo:
    """One deposited assembly, as offered to the UI."""

    assembly_id: str
    #: How many transformed copies this assembly places. One transform per
    #: chain set, so this is the number of *operator applications*, which is
    #: what the file's own BIOMT numbering counts.
    transform_count: int
    chain_ids: List[str]
    #: False when every transform is the identity, i.e. the "assembly" is just
    #: the asymmetric unit already on screen.
    has_symmetry: bool

    @property
    def label(self) -> str:
        chains = ", ".join(self.chain_ids)
        copies = f"{self.transform_count} cop{'y' if self.transform_count == 1 else 'ies'}"
        return f"Assembly {self.assembly_id} - {copies} of chain{'' if len(self.chain_ids) == 1 else 's'} {chains}"


def _molecule_object(molecule) -> Optional[bpy.types.Object]:
    try:
        return molecule.object
    except (AttributeError, ReferenceError):
        return None


def _raw_assemblies(molecule) -> dict:
    """The parsed assemblies MolecularNodes stored on the molecule object.

    Returns ``{}`` rather than raising for every way this can be absent: no
    object, no ``mn`` properties, a structure whose file carried no assembly
    records (stored as the JSON string ``"null"``), or unparseable JSON.
    """
    obj = _molecule_object(molecule)
    if obj is None:
        return {}

    raw = getattr(getattr(obj, "mn", None), "biological_assemblies", "")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("could not parse biological_assemblies on %s", obj.name)
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _is_identity(matrix) -> bool:
    try:
        return bool(np.allclose(np.array(matrix, dtype=float), np.eye(4), atol=1e-6))
    except (ValueError, TypeError):
        return False


def available_assemblies(molecule) -> List[AssemblyInfo]:
    """Every assembly the molecule's file described, in file order."""
    infos = []
    for assembly_id, transforms in _raw_assemblies(molecule).items():
        if not transforms:
            continue

        chain_ids, has_symmetry = [], False
        for transform in transforms:
            if not isinstance(transform, dict):
                # A parser returning the wrong shape is a bug worth hearing
                # about rather than silently rendering nothing.
                logger.warning(
                    "assembly %s has a %s transform, expected the documented "
                    "dict", assembly_id, type(transform).__name__)
                continue
            for chain in transform.get("chain_ids", []):
                if chain not in chain_ids:
                    chain_ids.append(chain)
            if not _is_identity(transform.get("matrix")):
                has_symmetry = True

        infos.append(AssemblyInfo(
            assembly_id=str(assembly_id),
            transform_count=len(transforms),
            chain_ids=chain_ids,
            has_symmetry=has_symmetry,
        ))
    return infos


def buildable_assemblies(molecule) -> List[AssemblyInfo]:
    """Only the assemblies that would actually put something new on screen."""
    return [info for info in available_assemblies(molecule) if info.has_symmetry]


def has_buildable_symmetry(molecule) -> bool:
    """Whether this molecule has symmetry worth offering the user.

    Deliberately *not* "does the file mention an assembly". Almost every
    deposited structure carries an assembly record, and for a monomer that
    record is a single identity transform - the asymmetric unit relabelled.
    Gating the UI on mere presence would put a symmetry panel on every
    monomer, where building it would visibly do nothing.
    """
    return bool(buildable_assemblies(molecule))


def get_assembly_info(molecule, assembly_id: str) -> Optional[AssemblyInfo]:
    for info in available_assemblies(molecule):
        if info.assembly_id == str(assembly_id):
            return info
    return None


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------

def _target_objects(molecule) -> List[bpy.types.Object]:
    """The objects an assembly has to be wired into to be visible.

    Every domain object (what the user actually sees) plus the molecule object
    (which draws any atoms no domain covers - nothing at all in a normal
    import, but everything if the domains have been deleted).
    """
    targets = []

    molobj = _molecule_object(molecule)
    if molobj is not None:
        targets.append(molobj)

    for domain in getattr(molecule, "domains", {}).values():
        try:
            obj = domain.object
        except (AttributeError, ReferenceError):
            continue
        if obj is not None and obj not in targets:
            targets.append(obj)

    return [o for o in targets if any(m.type == "NODES" for m in o.modifiers)]


def _node_group_of(obj) -> Optional[bpy.types.NodeTree]:
    modifier = next((m for m in obj.modifiers if m.type == "NODES"), None)
    return modifier.node_group if modifier is not None else None


def _existing_assembly_nodes(group) -> list:
    """Assembly nodes in this tree, resolved by name at point of use.

    Never cache these across a ``nodes.new()`` / ``nodes.remove()`` - Blender
    reallocates the node collection and invalidates held references.
    """
    return [n for n in group.nodes if n.name.startswith(ASSEMBLY_NODE_NAME)]


def is_assembly_built(molecule) -> bool:
    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is not None and _existing_assembly_nodes(group):
            return True
    return False


def built_assembly_id(molecule) -> Optional[str]:
    """Which assembly is currently built, read back off the node itself."""
    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue
        for node in _existing_assembly_nodes(group):
            socket = node.inputs.get("assembly_id")
            if socket is not None:
                return str(socket.default_value)
    return None


def build_assembly(molecule, assembly_id: str) -> bool:
    """Build a deposited assembly, replacing whatever was built before.

    Returns True if the assembly node reached at least one object.
    """
    info = get_assembly_info(molecule, assembly_id)
    if info is None:
        logger.warning("no assembly %r on %s", assembly_id, molecule)
        return False

    molobj = _molecule_object(molecule)
    if molobj is None:
        return False

    # Rebuilding from scratch each time keeps this idempotent and means a
    # failed half-build cannot leave two assembly nodes stacked in one tree.
    clear_assembly(molecule)

    from ..utils.molecularnodes.blender import nodes as mn_nodes

    try:
        # Creates the shared transforms data object (once per molecule) and the
        # "Assembly <name>" node tree that reads it.
        assembly_tree = mn_nodes.assembly_initialise(molobj)
    except Exception:
        logger.exception("could not initialise the assembly node tree")
        return False

    numeric_id = _as_socket_id(assembly_id)
    wired = 0

    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue
        try:
            node = group.nodes.new("GeometryNodeGroup")
            node.node_tree = assembly_tree
            node.name = ASSEMBLY_NODE_NAME
            node.label = f"Assembly {assembly_id}"
            mn_nodes.insert_last_node(group, node)

            # Re-resolve by name: insert_last_node ran nodes.new() above, and
            # anything held across that is no longer safe to touch.
            for inserted in _existing_assembly_nodes(group):
                _set_socket(inserted, "assembly_id", numeric_id)
                _set_socket(inserted, "Rotation", _FULLY_ASSEMBLED)
                _set_socket(inserted, "Translation", _FULLY_ASSEMBLED)
            wired += 1
        except Exception:
            logger.exception("could not wire the assembly node into %s", obj.name)

    return wired > 0


def clear_assembly(molecule) -> bool:
    """Remove every assembly node, restoring the asymmetric unit.

    Returns True if anything was removed.
    """
    removed = False

    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue

        # Re-resolve the list after every removal: nodes.remove() reallocates
        # the collection, so a list captured up front goes stale mid-loop.
        while True:
            nodes = _existing_assembly_nodes(group)
            if not nodes:
                break
            _unlink_and_remove(group, nodes[0])
            removed = True

    return removed


def _unlink_and_remove(group, node) -> None:
    """Take a node out of the chain, reconnecting what it sat between."""
    upstream = None
    if node.inputs and node.inputs[0].links:
        upstream = node.inputs[0].links[0].from_socket

    downstream = [link.to_socket for link in node.outputs[0].links] if node.outputs else []

    group.nodes.remove(node)

    if upstream is not None:
        for socket in downstream:
            group.links.new(upstream, socket)


def _as_socket_id(assembly_id: str) -> int:
    """The node's ``assembly_id`` socket is an int index into the data object.

    MolecularNodes numbers assemblies 1..N in file order when it writes that
    object, so a file whose assemblies are named non-numerically still maps by
    position rather than by name.
    """
    try:
        return int(assembly_id)
    except (TypeError, ValueError):
        return 1


def _set_socket(node, name: str, value) -> None:
    socket = node.inputs.get(name)
    if socket is None:
        logger.warning("assembly node has no %r input", name)
        return
    try:
        socket.default_value = value
    except (TypeError, AttributeError):
        logger.warning("could not set %r on the assembly node", name)
