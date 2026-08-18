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

#: Where the built assembly id is stashed, on the inserted node itself, so it
#: survives a save/load without needing a parallel property to keep in sync.
_ASSEMBLY_ID_KEY = "pb_assembly_id"

#: MolecularNodes stores structures at 1/100 scale, so an Angstrom of operator
#: translation is 0.01 Blender units.
WORLD_SCALE = 0.01

#: Node group inputs driving the assembly animation. Factor 0 puts every copy
#: back on the asymmetric unit, 1 builds the deposited assembly; Stagger
#: spreads the copies' arrivals across that span instead of moving them
#: together.
FACTOR_SOCKET = "Factor"
STAGGER_SOCKET = "Stagger"


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
            stored = node.get(_ASSEMBLY_ID_KEY)
            if stored is not None:
                return str(stored)
    return None




def build_assembly(molecule, assembly_id: str) -> bool:
    """Build a deposited assembly, replacing whatever was built before.

    Each operator is applied as a *placement* of the whole structure, in the
    coordinate frame the file deposited it in - which is what ChimeraX's
    ``sym`` does, and the only way the copies land where the depositor meant.

    MolecularNodes' own assembly node cannot be reused for this. It splits the
    structure into per-chain *centred* instances first, which throws away where
    each chain sits relative to the crystallographic origin - the exact thing a
    BIOMT operator is defined against. The copies then rotate about each
    chain's own centroid and pile up on the original: right in number, wrong in
    space. For 4ins that put consecutive copies 0.0095 apart instead of 0.303.

    Returns True if the assembly reached at least one object.
    """
    info = get_assembly_info(molecule, assembly_id)
    if info is None:
        logger.warning("no assembly %r on %s", assembly_id, molecule)
        return False

    operators = _operators_for(molecule, assembly_id)
    if not operators:
        return False

    # Rebuilding from scratch keeps this idempotent, and means a failed
    # half-build cannot leave two assembly nodes stacked in one tree.
    clear_assembly(molecule)

    wired = 0
    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue
        try:
            if _wire_assembly_into(obj, group, molecule, assembly_id, operators):
                wired += 1
        except Exception:
            logger.exception("could not wire the assembly into %s", obj.name)

    return wired > 0


def _operators_for(molecule, assembly_id: str):
    """(rotation 3x3, translation 3) for each operator of this assembly.

    Only the operators that apply to chains this molecule actually has; a
    transform naming chains that were never imported would place an empty copy.
    """
    operators = []
    for transform in _raw_assemblies(molecule).get(str(assembly_id), []):
        if not isinstance(transform, dict):
            continue
        matrix = np.array(transform.get("matrix"), dtype=float)
        if matrix.shape != (4, 4):
            continue
        operators.append((matrix[:3, :3], matrix[:3, 3]))
    return operators


def _wire_assembly_into(obj, group, molecule, assembly_id, operators) -> bool:
    """Instance this object's whole geometry once per operator."""
    points = _build_points_object(obj, molecule, assembly_id, operators)
    if points is None:
        return False

    node = _add_assembly_node(group, points)
    if node is None:
        return False

    node[_ASSEMBLY_ID_KEY] = str(assembly_id)
    return True


def _build_points_object(obj, molecule, assembly_id, operators):
    """One point per operator, carrying that operator's rotation.

    The position is not simply the operator's translation. ProteinBlender's
    node tree has already shifted the geometry by ``-pivot`` by the time our
    node sees it, so for a point ``co`` the tree is handing us ``co - pivot``
    and we need the copy to land at ``R @ co + s*t - pivot``. Solving for the
    translation to apply to what we actually receive:

        R @ (co - pivot) + x  ==  R @ co + s*t - pivot
        x                     ==  R @ pivot + s*t - pivot

    Miss that term and every copy is offset by the pivot, which for a domain
    is nowhere near the origin.
    """
    from mathutils import Matrix as BlenderMatrix

    from . import domain_space

    try:
        pivot = np.array(domain_space.get_pivot(obj), dtype=float)
    except Exception:
        pivot = np.zeros(3)

    name = f".pb_assembly_{molecule.identifier}_{assembly_id}_{obj.name}"

    existing = bpy.data.objects.get(name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    # Each operator is stored as an axis and an angle rather than a finished
    # matrix, because that is what makes the assembly animatable: rotating
    # about the same axis by a fraction of the angle *is* the interpolation
    # from the identity to that operator, exactly, with no approximation. The
    # node tree scales the angle and the translation by a factor, so factor 0
    # lands every copy back on the asymmetric unit and factor 1 reproduces the
    # deposited assembly.
    axes, angles, translations, delays = [], [], [], []
    last = max(len(operators) - 1, 1)

    for i, (rotation, translation) in enumerate(operators):
        quaternion = BlenderMatrix(rotation.tolist()).to_quaternion()
        angle = float(quaternion.angle)
        # A zero rotation leaves the axis undefined; pick one so the maths
        # downstream stays finite.
        axis = tuple(quaternion.axis) if abs(angle) > 1e-9 else (0.0, 0.0, 1.0)

        axes.append(axis)
        angles.append(angle)
        translations.append((translation * WORLD_SCALE).tolist())
        # Arrival order for the stagger, normalised so the last copy leaves at
        # the latest possible moment and still finishes at factor 1.
        delays.append(i / last)

    mesh = bpy.data.meshes.new(name)
    # Points start at the origin; the node tree positions them from the
    # attributes below, so that a factor change re-places them without a
    # rebuild.
    mesh.from_pydata([(0.0, 0.0, 0.0)] * len(operators), [], [])
    mesh.update()

    for attr_name, attr_type, values in (
        ("axis", "FLOAT_VECTOR", axes),
        ("trans", "FLOAT_VECTOR", translations),
        ("pivot", "FLOAT_VECTOR", [pivot.tolist()] * len(operators)),
        ("angle", "FLOAT", angles),
        ("delay", "FLOAT", delays),
    ):
        attribute = mesh.attributes.new(attr_name, attr_type, "POINT")
        for i, value in enumerate(values):
            if attr_type == "FLOAT":
                attribute.data[i].value = value
            else:
                attribute.data[i].vector = value

    points = bpy.data.objects.new(name, mesh)
    points.hide_viewport = True
    points.hide_render = True
    points.hide_select = True
    for collection in obj.users_collection:
        collection.objects.link(points)
        break
    else:
        bpy.context.scene.collection.objects.link(points)

    return points


def _add_assembly_node(group, points):
    """Instance the incoming geometry onto the operator points."""
    tree = _assembly_node_tree(points)
    if tree is None:
        return None

    from ..utils.molecularnodes.blender import nodes as mn_nodes

    node = group.nodes.new("GeometryNodeGroup")
    node.node_tree = tree
    node.name = ASSEMBLY_NODE_NAME
    mn_nodes.insert_last_node(group, node)

    # Re-resolve by name: insert_last_node ran nodes.new(), and any reference
    # held across that is no longer safe to touch.
    return next((n for n in group.nodes if n.name.startswith(ASSEMBLY_NODE_NAME)),
                None)


def _assembly_node_tree(points):
    """Geometry in, the same geometry placed at every operator out."""
    name = f"Assembly {points.name.lstrip('.')}"
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        bpy.data.node_groups.remove(existing)

    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT",
                              socket_type="NodeSocketGeometry")
    factor = tree.interface.new_socket(
        FACTOR_SOCKET, in_out="INPUT", socket_type="NodeSocketFloat")
    factor.min_value, factor.max_value, factor.default_value = 0.0, 1.0, 1.0
    stagger = tree.interface.new_socket(
        STAGGER_SOCKET, in_out="INPUT", socket_type="NodeSocketFloat")
    stagger.min_value, stagger.max_value, stagger.default_value = 0.0, 1.0, 0.0
    tree.interface.new_socket("Geometry", in_out="OUTPUT",
                              socket_type="NodeSocketGeometry")

    node = tree.nodes.new
    link = tree.links.new

    group_in = node("NodeGroupInput");  group_in.location = (-900, 0)
    group_out = node("NodeGroupOutput"); group_out.location = (700, 0)

    def attribute(attr_name, data_type, y):
        reader = node("GeometryNodeInputNamedAttribute")
        reader.location = (-900, y)
        reader.data_type = data_type
        reader.inputs["Name"].default_value = attr_name
        return reader.outputs["Attribute"]

    axis = attribute("axis", "FLOAT_VECTOR", -200)
    trans = attribute("trans", "FLOAT_VECTOR", -340)
    pivot_attr = attribute("pivot", "FLOAT_VECTOR", -480)
    angle = attribute("angle", "FLOAT", -620)
    delay = attribute("delay", "FLOAT", -760)

    def math(operation, a, b=None, loc=(0, 0)):
        m = node("ShaderNodeMath")
        m.operation = operation
        m.location = loc
        _plug(link, m.inputs[0], a)
        if b is not None:
            _plug(link, m.inputs[1], b)
        return m.outputs[0]

    def vector_math(operation, a, b=None, loc=(0, 0), scale=None):
        m = node("ShaderNodeVectorMath")
        m.operation = operation
        m.location = loc
        _plug(link, m.inputs[0], a)
        if b is not None:
            _plug(link, m.inputs[1], b)
        if scale is not None:
            _plug(link, m.inputs["Scale"], scale)
        return m.outputs["Vector"]

    # Each copy waits for its share of the timeline before it starts moving.
    # With Stagger at 0 every copy shares the same factor and they assemble
    # together; at 1 the last copy only begins as the first one finishes.
    start = math("MULTIPLY", delay, group_in.outputs[STAGGER_SOCKET], loc=(-650, -700))
    span = math("SUBTRACT", 1.0, start, loc=(-500, -700))
    safe_span = math("MAXIMUM", span, 1e-4, loc=(-350, -700))
    elapsed = math("SUBTRACT", group_in.outputs[FACTOR_SOCKET], start, loc=(-350, -560))
    raw = math("DIVIDE", elapsed, safe_span, loc=(-200, -620))

    clamp = node("ShaderNodeClamp")
    clamp.location = (-50, -620)
    link(raw, clamp.inputs["Value"])
    clamp.inputs["Min"].default_value = 0.0
    clamp.inputs["Max"].default_value = 1.0
    local_factor = clamp.outputs["Result"]

    # Rotating about the operator's own axis by a fraction of its angle is the
    # exact interpolation from the identity to that operator.
    partial_angle = math("MULTIPLY", angle, local_factor, loc=(100, -500))
    rotation = node("FunctionNodeAxisAngleToRotation")
    rotation.location = (250, -420)
    link(axis, rotation.inputs["Axis"])
    link(partial_angle, rotation.inputs["Angle"])

    # The tree has already shifted geometry by -pivot, so a copy belongs at
    # rotate(pivot) - pivot + factor * translation. At factor 0 that is zero,
    # putting every copy back exactly on the asymmetric unit.
    rotate_pivot = node("FunctionNodeRotateVector")
    rotate_pivot.location = (400, -250)
    link(pivot_attr, rotate_pivot.inputs["Vector"])
    link(rotation.outputs["Rotation"], rotate_pivot.inputs["Rotation"])

    swung = vector_math("SUBTRACT", rotate_pivot.outputs["Vector"], pivot_attr,
                        loc=(550, -250))
    moved = vector_math("SCALE", trans, scale=local_factor, loc=(550, -400))
    position = vector_math("ADD", swung, moved, loc=(700, -320))

    object_info = node("GeometryNodeObjectInfo")
    object_info.location = (-650, 200)
    object_info.transform_space = "ORIGINAL"
    object_info.inputs["Object"].default_value = points

    set_position = node("GeometryNodeSetPosition")
    set_position.location = (250, 200)
    link(object_info.outputs["Geometry"], set_position.inputs["Geometry"])
    link(position, set_position.inputs["Position"])

    to_instance = node("GeometryNodeGeometryToInstance")
    to_instance.location = (-650, 60)
    link(group_in.outputs[0], to_instance.inputs[0])

    instance_on = node("GeometryNodeInstanceOnPoints")
    instance_on.location = (500, 120)
    link(set_position.outputs["Geometry"], instance_on.inputs["Points"])
    link(to_instance.outputs[0], instance_on.inputs["Instance"])
    link(rotation.outputs["Rotation"], instance_on.inputs["Rotation"])
    link(instance_on.outputs[0], group_out.inputs[0])

    if hasattr(tree, "color_tag"):
        tree.color_tag = "GEOMETRY"
    return tree


def _plug(link, socket, value):
    """Link ``value`` into ``socket`` if it is a socket, else set it."""
    if hasattr(value, "is_output"):
        link(value, socket)
    else:
        socket.default_value = value


def clear_assembly(molecule) -> bool:
    """Remove every assembly node, restoring the asymmetric unit.

    Returns True if anything was removed.
    """
    removed = False

    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue

        # Re-resolve after every removal: nodes.remove() reallocates the
        # collection, so a list captured up front goes stale mid-loop.
        while True:
            nodes = _existing_assembly_nodes(group)
            if not nodes:
                break
            _unlink_and_remove(group, nodes[0])
            removed = True

    _purge_assembly_datablocks(molecule)
    return removed


def _purge_assembly_datablocks(molecule) -> None:
    """Drop the per-object point clouds and node groups a build created."""
    prefix = f".pb_assembly_{molecule.identifier}_"

    for obj in [o for o in bpy.data.objects if o.name.startswith(prefix)]:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    tree_prefix = f"Assembly pb_assembly_{molecule.identifier}_"
    for tree in [t for t in bpy.data.node_groups if t.name.startswith(tree_prefix)]:
        if tree.users == 0:
            bpy.data.node_groups.remove(tree)


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


# --------------------------------------------------------------------------
# Animation
# --------------------------------------------------------------------------

def _assembly_nodes(molecule):
    """Every assembly node across the molecule's objects, freshly resolved."""
    for obj in _target_objects(molecule):
        group = _node_group_of(obj)
        if group is None:
            continue
        for node in _existing_assembly_nodes(group):
            yield group, node


def set_assembly_factor(molecule, factor: float, stagger: Optional[float] = None) -> bool:
    """How far through assembling the copies are.

    0 leaves every copy sitting on the asymmetric unit, 1 is the deposited
    assembly, and anything between is a real intermediate - each copy rotated
    part of the way about its own operator's axis.
    """
    touched = False
    for _group, node in _assembly_nodes(molecule):
        _set_socket(node, FACTOR_SOCKET, float(factor))
        if stagger is not None:
            _set_socket(node, STAGGER_SOCKET, float(stagger))
        touched = True
    return touched


def get_assembly_factor(molecule) -> Optional[float]:
    for _group, node in _assembly_nodes(molecule):
        socket = node.inputs.get(FACTOR_SOCKET)
        if socket is not None:
            return float(socket.default_value)
    return None


def get_assembly_stagger(molecule) -> Optional[float]:
    for _group, node in _assembly_nodes(molecule):
        socket = node.inputs.get(STAGGER_SOCKET)
        if socket is not None:
            return float(socket.default_value)
    return None


def keyframe_assembly(molecule, frame: Optional[int] = None) -> int:
    """Key the current factor on every assembly node.

    Keyed on the nodes themselves rather than on a scene property, so the
    animation travels with the .blend and survives the molecule being
    renamed or reselected. Returns how many sockets were keyed.
    """
    if frame is None:
        frame = bpy.context.scene.frame_current

    keyed = 0
    for group, node in _assembly_nodes(molecule):
        socket = node.inputs.get(FACTOR_SOCKET)
        if socket is None:
            continue
        try:
            index = list(node.inputs).index(socket)
            group.keyframe_insert(
                data_path=f'nodes["{node.name}"].inputs[{index}].default_value',
                frame=frame)
            keyed += 1
        except Exception:
            logger.exception("could not keyframe the assembly factor on %s",
                             group.name)
    return keyed


def _set_socket(node, name: str, value) -> None:
    socket = node.inputs.get(name)
    if socket is None:
        logger.warning("assembly node has no %r input", name)
        return
    try:
        socket.default_value = value
    except (TypeError, AttributeError):
        logger.warning("could not set %r on the assembly node", name)
