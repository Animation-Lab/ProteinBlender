"""Where a molecule or domain object's pivot lives, and how to map its atoms.

Blender's ``bpy.ops.object.origin_set`` moves an object's origin by *rewriting
mesh vertex data* and compensating the object's transform. That works fine when
an object owns its mesh, and not at all when several objects share one: the
vertex shift reaches every user of the datablock while only the active object's
origin compensates, so every other sharer visibly jumps.

That single behaviour is why each domain used to deep-copy the whole molecule's
mesh - a domain covering 5% of a protein still stored 100% of the atoms, purely
so its origin could move. Here the pivot is carried as a geometry-nodes group
input instead: it lives on the *modifier*, which is per-object, so the mesh stays
shared and canonical and nothing is ever written to it.

The representation
------------------
Each molecule/domain node tree gets a ``Pivot`` vector input feeding a Transform
node that translates the incoming atoms by ``-Pivot``. Combined with the object's
own transform, the atom at ``co`` renders at::

    world(co) = obj.matrix_world @ (co - pivot)

Two consequences worth internalising:

* ``obj.matrix_world.translation`` is the pivot's world position, exactly as an
  origin was before. ``world(pivot) == matrix_world.translation``, so anything
  reading the origin keeps working unchanged.
* ``obj.matrix_world @ co`` is **no longer** the local->world mapping. That
  identity held only while each domain owned a privately-shifted mesh. Every
  caller mapping mesh coordinates to world space must go through
  :func:`local_to_world`, or it will be wrong by exactly the pivot.

Objects with no pivot input (linker curves, membranes, anything non-molecular)
report a zero pivot, so these helpers degrade to plain ``matrix_world @ co`` and
are safe to call on any object.
"""

from __future__ import annotations

import logging
from typing import Optional

import bpy
from mathutils import Matrix, Vector

logger = logging.getLogger(__name__)

# The geometry-nodes modifiers ProteinBlender puts on molecule/domain objects.
# Domains carry "DomainNodes"; the parent molecule carries MolecularNodes' own.
_MODIFIER_NAMES = ("DomainNodes", "MolecularNodes")

PIVOT_SOCKET = "Pivot"
PIVOT_NODE = "PB_Pivot_Transform"
PIVOT_NEGATE_NODE = "PB_Pivot_Negate"

ZERO = Vector((0.0, 0.0, 0.0))


# --------------------------------------------------------------------------
# Locating the pieces
# --------------------------------------------------------------------------

def pb_modifier(obj) -> Optional[bpy.types.Modifier]:
    """The geometry-nodes modifier driving *obj*, or None if it isn't ours."""
    if obj is None:
        return None
    for name in _MODIFIER_NAMES:
        mod = obj.modifiers.get(name)
        if mod is not None and mod.node_group is not None:
            return mod
    return None


def _pivot_socket(node_group) -> Optional[bpy.types.NodeTreeInterfaceSocket]:
    for item in node_group.interface.items_tree:
        if (getattr(item, "in_out", None) == "INPUT"
                and item.item_type == "SOCKET"
                and item.name == PIVOT_SOCKET):
            return item
    return None


def _group_inputs(node_group):
    return [n for n in node_group.nodes if n.bl_idname == "NodeGroupInput"]


def _geometry_output(node):
    for socket in node.outputs:
        if socket.type == "GEOMETRY":
            return socket
    return None


# --------------------------------------------------------------------------
# Building the pivot into a tree
# --------------------------------------------------------------------------

def ensure_pivot_input(node_group) -> Optional[str]:
    """Insert (or repair) the Pivot input and its Transform node in *node_group*.

    Idempotent, and deliberately re-wires every time rather than bailing early
    when the nodes already exist: ``_setup_domain_network`` rebuilds a domain's
    tree with ``links.clear()``, which strips the pivot's links while leaving its
    nodes behind. Call this *after* any such rebuild.

    Returns the Pivot socket's identifier, which is the key its per-object value
    is stored under on the modifier.
    """
    socket = _pivot_socket(node_group)
    if socket is None:
        socket = node_group.interface.new_socket(
            PIVOT_SOCKET, in_out="INPUT", socket_type="NodeSocketVector")
        socket.description = (
            "Origin of this object in canonical mesh space. Atoms are "
            "translated by -Pivot so the object's transform rotates about it.")
    # Keep the identifier, not the socket: the pointer must not outlive the
    # nodes.new() calls below.
    identifier = socket.identifier

    # Create every missing node BEFORE taking a reference to any node.
    #
    # nodes.new() can reallocate the tree's node collection, which invalidates
    # every bpy pointer previously taken from it - they do not raise, they
    # silently resolve to whatever now occupies that slot. Holding a Group Input
    # reference across these two calls made it come back as the Transform node,
    # which then got wired to its own geometry input: the atoms never entered the
    # tree and nothing rendered, on every import. Nothing may be held across a
    # nodes.new(); re-resolve by name afterwards. (Same hazard as the stale
    # domain_join_node pointers in molecule_wrapper.)
    if node_group.nodes.get(PIVOT_NODE) is None:
        created = node_group.nodes.new("GeometryNodeTransform")
        created.name = PIVOT_NODE
        created.label = "PB Pivot"

    if node_group.nodes.get(PIVOT_NEGATE_NODE) is None:
        created = node_group.nodes.new("ShaderNodeVectorMath")
        created.name = PIVOT_NEGATE_NODE
        created.label = "PB Pivot (negate)"
        created.operation = "SCALE"
        created.inputs["Scale"].default_value = -1.0

    # The collection is stable from here; resolve everything by name.
    transform = node_group.nodes[PIVOT_NODE]
    negate = node_group.nodes[PIVOT_NEGATE_NODE]
    group_inputs = _group_inputs(node_group)
    if not group_inputs:
        logger.warning("%r has no Group Input node; cannot install a pivot",
                       node_group.name)
        return identifier

    anchor = group_inputs[0]
    transform.location = (anchor.location.x + 180, anchor.location.y - 40)
    negate.location = (anchor.location.x + 180, anchor.location.y - 220)

    # Everything the group input's geometry currently feeds has to move behind
    # the transform. Collect first: creating links while iterating link
    # collections invalidates them.
    #
    # Compare by NAME, not with `is`. Blender hands out a fresh bpy_struct
    # wrapper on every attribute access, so `link.to_node is transform` is False
    # even when they are the same node - which silently classified the pivot's
    # own input as "downstream" on any tree where it was already wired. It then
    # got relinked to the pivot's own output, clobbering the real source: the
    # Transform fed itself, the atoms never entered the tree, and nothing
    # rendered. (bpy_struct implements __eq__ for data identity; `is` does not.)
    downstream = []
    for gi in group_inputs:
        geo = _geometry_output(gi)
        if geo is None:
            continue
        for link in list(geo.links):
            if link.to_node.name != PIVOT_NODE:
                downstream.append(link.to_socket)

    source = next((_geometry_output(gi) for gi in group_inputs
                   if _geometry_output(gi) is not None), None)
    if source is None:
        logger.warning("%r Group Input exposes no geometry; cannot install a "
                       "pivot", node_group.name)
        return identifier

    node_group.links.new(source, transform.inputs["Geometry"])
    for to_socket in downstream:
        node_group.links.new(transform.outputs["Geometry"], to_socket)

    for gi in group_inputs:
        pivot_out = gi.outputs.get(PIVOT_SOCKET)
        if pivot_out is not None:
            node_group.links.new(pivot_out, negate.inputs[0])
            break
    node_group.links.new(negate.outputs["Vector"], transform.inputs["Translation"])

    return identifier


# --------------------------------------------------------------------------
# Reading / writing the per-object pivot
# --------------------------------------------------------------------------

def get_pivot(obj) -> Vector:
    """*obj*'s pivot in canonical mesh space. Zero when it has no pivot input."""
    mod = pb_modifier(obj)
    if mod is None:
        return ZERO.copy()
    socket = _pivot_socket(mod.node_group)
    if socket is None:
        return ZERO.copy()
    try:
        return Vector(getattr(mod.properties.inputs, socket.identifier).value)
    except (AttributeError, TypeError):
        return ZERO.copy()


def set_pivot_local(obj, pivot) -> bool:
    """Write *obj*'s pivot directly, leaving its transform alone.

    This moves the geometry. Use :func:`set_pivot_world` to move the pivot
    without moving what the user sees.
    """
    mod = pb_modifier(obj)
    if mod is None:
        return False
    identifier = ensure_pivot_input(mod.node_group)
    if identifier is None:
        return False
    try:
        getattr(mod.properties.inputs, identifier).value = tuple(pivot)
    except (AttributeError, TypeError) as e:
        logger.warning("Could not set pivot on %r: %s", obj.name, e)
        return False
    return True


def set_pivot_world(obj, world_pos) -> bool:
    """Move *obj*'s origin to *world_pos* without moving its atoms.

    The replacement for ``bpy.ops.object.origin_set(type='ORIGIN_CURSOR')``. It
    touches no mesh data, so it is safe on an object whose mesh is shared, and it
    needs no selection dance - origin_set operated on everything selected, which
    is why callers used to snapshot and restore the whole selection state.

    The maths: with ``world(co) = M @ (co - p)``, holding the linear part of M
    fixed and requiring the atoms not to move gives
    ``p_new = p_old + M.inverted() @ P`` and ``M_new.translation = P``.
    """
    mod = pb_modifier(obj)
    if mod is None:
        logger.warning("%r has no ProteinBlender geometry-nodes modifier; "
                       "cannot set a pivot", getattr(obj, "name", obj))
        return False

    target = Vector(world_pos)
    matrix = obj.matrix_world.copy()
    new_pivot = get_pivot(obj) + (matrix.inverted() @ target)

    if not set_pivot_local(obj, new_pivot):
        return False

    matrix.translation = target
    obj.matrix_world = matrix
    return True


# --------------------------------------------------------------------------
# Coordinate mapping
# --------------------------------------------------------------------------

def local_to_world(obj, co) -> Vector:
    """Map a raw mesh coordinate of *obj* into world space.

    Use this instead of ``obj.matrix_world @ co`` anywhere you read
    ``obj.data.vertices`` / a POINT attribute, since the pivot is applied inside
    geometry nodes and raw mesh data has not been through it yet.

    Coordinates read from an *evaluated* object already have the pivot applied
    and must not be passed through here.
    """
    return obj.matrix_world @ (Vector(co) - get_pivot(obj))


def world_to_local(obj, world_co) -> Vector:
    """Inverse of :func:`local_to_world`."""
    return (obj.matrix_world.inverted() @ Vector(world_co)) + get_pivot(obj)


def local_to_world_many(obj, coords):
    """Vectorised :func:`local_to_world` for an ``(N, 3)`` numpy array.

    Returns an ``(N, 3)`` array. Worth using for whole-molecule reads: 4hhb is
    ~4558 atoms and a per-vertex mathutils round-trip is noticeably slower.
    """
    import numpy as np

    coords = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
    matrix = np.array(obj.matrix_world.to_4x4(), dtype=np.float64)
    shifted = coords - np.array(get_pivot(obj), dtype=np.float64)
    rotated = shifted @ matrix[:3, :3].T
    return rotated + matrix[:3, 3]


def copy_pivot(src_obj, dst_obj) -> bool:
    """Give *dst_obj* the same pivot as *src_obj*.

    Domains are created sharing the parent's mesh and matrix_world, so they must
    inherit its pivot too: a fresh modifier defaults the Pivot input to zero, and
    a domain whose pivot disagreed with its parent's would render offset from the
    rest of the molecule by exactly that difference.
    """
    return set_pivot_local(dst_obj, get_pivot(src_obj))
