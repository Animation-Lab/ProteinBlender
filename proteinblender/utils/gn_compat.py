"""Writing geometry-nodes modifier inputs across the supported Blender 5.x line.

Blender moved where a geometry-nodes modifier keeps its socket values, and the
two APIs do not overlap:

* **5.0 - 5.1** stores them as IDProperties directly on the modifier, addressed
  by the interface socket's identifier: ``mod["Socket_2"] = value``.
* **5.2** removed IDProperty support from ``NodesModifier``. The same assignment
  now raises ``TypeError: id properties not supported for this type``. Values
  live one level deeper, under ``mod.properties.inputs["Socket_2"]["value"]``.

The add-on supports both (``blender_version_min = "5.0.0"``, developed against
the 5.x series), so every write tries the modern path and falls back.

This module exists because getting it wrong is *silent*, and it shipped that way.
Both membrane call sites wrapped the write in ``except Exception: pass``, so on
5.2 every input write failed, the Lipid Collection was never bound, Collection
Info fed Instance on Points an empty collection, and a "successful" build
produced a membrane with no lipids at all: zero instances, nothing on screen.
The build reported success and the structural tests passed, because everything
except the geometry was correct. That is why a failed write raises here.

One trap is worth stating explicitly, because it cost a long debugging detour.
``mod.properties.inputs[identifier]`` is an ``IDPropertyGroup`` for *every*
socket type, datablock sockets included; the value always goes in its ``value``
key. Assigning the datablock onto the mapping instead
(``mod.properties.inputs[identifier] = collection``) appears to work and reads
back as the collection, but it replaces the group Blender expects with a bare ID
and the next depsgraph evaluation hangs the process indefinitely. Always write
through ``["value"]``, and read back the same way.
"""

from __future__ import annotations

import bpy

_MISSING = object()


def set_modifier_input(mod: bpy.types.Modifier, socket_name: str, value) -> None:
    """Set a geometry-nodes modifier input by its *interface socket name*.

    Raises ``KeyError`` if the tree has no such input, and ``RuntimeError`` if
    neither Blender API accepts the write. Both are louder than the wrong
    geometry they would otherwise produce.
    """
    tree = mod.node_group
    if tree is None:
        raise RuntimeError(
            f"modifier {mod.name!r} has no node group; cannot set "
            f"{socket_name!r}")

    for item in tree.interface.items_tree:
        if getattr(item, "in_out", "") == "INPUT" and item.name == socket_name:
            write_modifier_socket(mod, item.identifier, value, socket_name)
            return

    raise KeyError(
        f"node group {tree.name!r} has no input socket named {socket_name!r}")


def write_modifier_socket(mod: bpy.types.Modifier, identifier: str, value,
                          socket_name: str | None = None) -> None:
    """Write one socket value by identifier, on whichever API this Blender has."""
    label = socket_name or identifier
    errors = []

    # Blender 5.2+ first: it is the version this add-on is developed against,
    # and on earlier versions the attribute is simply absent.
    if getattr(mod, "properties", None) is not None:
        try:
            mod.properties.inputs[identifier]["value"] = value
            return
        except (KeyError, TypeError, AttributeError) as exc:
            errors.append(f"5.2 path: {type(exc).__name__}: {exc}")

    try:
        mod[identifier] = value
        return
    except (KeyError, TypeError, AttributeError) as exc:
        errors.append(f"4.2-5.1 path: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        f"could not set geometry-nodes input {label!r} ({identifier}) on "
        f"modifier {mod.name!r} using any supported Blender API. "
        + "; ".join(errors))


def read_modifier_socket(mod: bpy.types.Modifier, identifier: str,
                         default=None):
    """Read one socket value by identifier, on whichever API this Blender has."""
    if getattr(mod, "properties", None) is not None:
        try:
            return mod.properties.inputs[identifier]["value"]
        except (KeyError, TypeError, AttributeError):
            pass
    try:
        return mod[identifier]
    except (KeyError, TypeError, AttributeError):
        return default
