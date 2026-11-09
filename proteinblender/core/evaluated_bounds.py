"""World-space bounds of what a set of objects actually draws.

``obj.bound_box`` is the wrong question for a molecule. It covers one object's
own evaluated geometry, so it misses everything geometry nodes *instance* from
that object - every copy of a biological or generated assembly. A puppet made
from 1STM's icosahedral assembly was centred on the deposited pentamer's box,
well off the middle of the 12-copy particle (Janet, 2026-11-03).

These bounds walk the evaluated depsgraph instead, so assembly copies, domain
pivots and every other evaluated transform are included. Points are mapped one
by one rather than as a local box: rotating a box and re-boxing it inflates the
bounds unevenly and pulls the centre off a rotated copy.

(``core.lighting.scene_bounds`` deliberately keeps its own corner walk: it
sizes a light rig for the whole scene, where a slightly loose box is harmless
and walking every vertex of a large realized scene is not free.)
"""

import math

import numpy as np
from mathutils import Vector

DRAWN_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME',
               'POINTCLOUD', 'CURVES'}


def _local_points(obj):
    """``(points, radii)`` in local space for one evaluated geometry.

    Point clouds carry their sphere radii (MolecularNodes draws atoms as
    points; Blender's object box for GN point-cloud instances can be zero or
    stale). Meshes give their vertices. Anything else falls back to its box
    corners. Empty geometry gives None.
    """
    if obj.type == 'POINTCLOUD':
        count = len(obj.data.points)
        if not count:
            return None
        positions = np.empty(count * 3, dtype=np.float64)
        obj.data.attributes['position'].data.foreach_get('vector', positions)
        radii = np.zeros(count, dtype=np.float64)
        attr = obj.data.attributes.get('radius')
        if attr:
            attr.data.foreach_get('value', radii)
        return positions.reshape(-1, 3), radii
    if obj.type == 'MESH':
        count = len(obj.data.vertices)
        if not count:
            # An empty evaluated mesh can still report a misleading zero box.
            return None
        positions = np.empty(count * 3, dtype=np.float64)
        obj.data.vertices.foreach_get('co', positions)
        return positions.reshape(-1, 3), np.zeros(count)
    corners = np.array([tuple(c) for c in obj.bound_box], dtype=np.float64)
    if (corners == -1).all():
        return None
    return corners, np.zeros(len(corners))


def evaluated_bounds(context, owners):
    """``(low, high)`` world corners of what ``owners`` draw, or None.

    ``owners``: names of the objects to measure. An instance counts toward its
    owner - the object whose geometry nodes made it - so an assembly's copies
    count toward the domain they copy. Viewport-hidden objects never reach the
    depsgraph's instance list, so they are not measured.
    """
    context.view_layer.update()
    low = np.full(3, math.inf)
    high = np.full(3, -math.inf)
    cache = {}
    for instance in context.evaluated_depsgraph_get().object_instances:
        obj = instance.object
        if not instance.show_self or obj.type not in DRAWN_TYPES:
            continue
        owner = instance.parent.original if instance.is_instance else obj.original
        if owner.name not in owners:
            continue
        # Depsgraph reuses a temporary Object for GN components/instances.
        # Its pointer is not a geometry identity; the evaluated data is.
        key = (obj.type, obj.data.as_pointer())
        if key not in cache:
            cache[key] = _local_points(obj)
        if cache[key] is None:
            continue
        points, radii = cache[key]
        matrix = np.array(instance.matrix_world)
        linear = matrix[:3, :3]
        world = points @ linear.T + matrix[:3, 3]
        # A local sphere of radius r maps to an ellipsoid whose reach along
        # world axis i is r * |row i of the linear part|: exact under rotation,
        # non-uniform scale and shear alike.
        reach = radii[:, None] * np.linalg.norm(linear, axis=1)[None, :]
        finite = np.isfinite(world).all(axis=1)
        if not finite.any():
            continue
        low = np.minimum(low, (world - reach)[finite].min(axis=0))
        high = np.maximum(high, (world + reach)[finite].max(axis=0))
    if not np.isfinite(low).all():
        return None
    return Vector(low), Vector(high)


def evaluated_center(context, owners):
    """Centre of the box around what ``owners`` draw, or None if nothing."""
    bounds = evaluated_bounds(context, owners)
    if bounds is None:
        return None
    low, high = bounds
    return (low + high) * 0.5
