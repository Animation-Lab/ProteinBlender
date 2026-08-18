"""Complete scene snapshot for save/load round-trip tests.

Imported by the in-process test (to capture the EXPECTED state before saving)
and by the subprocess verifier (to capture the ACTUAL state after reopening the
.blend in a fresh Blender). Both sides run identical code, so any divergence is
attributable to the save/load cycle rather than to the measurement.

Design rules, in order of importance:

1. **Enumerate, never hand-pick.** Every PropertyGroup is serialized by walking
   its RNA (``bl_rna.properties``) rather than by listing fields. A field added
   to a PropertyGroup next year is captured the day it is added, with no edit
   here. This is what makes "full coverage" a property of the mechanism instead
   of a claim about a list someone maintained.

2. **Independent of the product's own accessors.** Geometry-nodes modifier
   inputs are read through a local version split (``_gn_input_value``) rather
   than through ``proteinblender.utils.gn_compat``. If the product's compat
   layer breaks, both sides of the comparison would read the same wrong value
   and the round trip would stay green while data was lost.

3. **Deterministic.** Floats are rounded, collections are sorted by a stable
   identity, and anything whose value is inherently per-session (memory
   addresses, pointer identity, timers) is excluded explicitly in EXCLUSIONS
   with a stated reason rather than silently skipped.

The scene- and object-level property *names* covered here are asserted against
the add-on's own source by ``test_persistence_contract.py``: registering a new
``bpy.types.Scene`` / ``bpy.types.Object`` property without adding it here fails
that test.
"""

from __future__ import annotations

import hashlib

FLOAT_DP = 5
MAX_INLINE_LINKS = 200
MAX_RECURSION = 12


# ---------------------------------------------------------------------------
# Coverage declarations
#
# SCENE_PROPS / OBJECT_PROPS are the add-on-registered properties this snapshot
# captures. EXCLUSIONS lists the registered properties it deliberately does not,
# each with the reason. test_persistence_contract.py parses the add-on source
# for `bpy.types.Scene.X = ` / `bpy.types.Object.X = ` and requires every one to
# appear in exactly one of the three, so this file cannot drift out of date
# without the suite going red.
# ---------------------------------------------------------------------------

SCENE_PROPS = (
    # Molecule model - the primary persistent store.
    "molecule_list_items", "molecule_list_index", "selected_molecule_id",
    "edit_molecule_identifier", "molecule_style",
    # Outliner.
    "outliner_items", "outliner_index",
    # Poses.
    "pose_library", "active_pose_index",
    # Linkers.
    "pb2_linkers", "pb2_linkers_index",
    # Feature-package property groups.
    "protein_props", "dna_builder_props", "membrane_builder_props",
    # Domain creation / editing state.
    "chain_selections", "domain_start", "domain_end",
    "new_domain_chain", "new_domain_start", "new_domain_end",
    "selected_chain_for_domain", "show_domain_preview",
    "active_splitting_domain_id", "split_domain_new_start",
    "split_domain_new_end",
    "temp_domain_start", "temp_domain_end", "temp_domain_id",
    "temp_domain_color",
    # Visual setup + animation panel.
    "visual_setup_color", "visual_setup_style",
    "pb_keyframe_list", "pb_keyframe_list_index",
    "pb_keyframe_filter_by_selection",
)

OBJECT_PROPS = (
    "domain_expanded", "domain_color", "domain_style", "domain_name",
    "temp_domain_name",
    "pb_force_field_enabled", "pb_force_field_spacing",
)

EXCLUSIONS = {
    "Scene.MNSession": (
        "Runtime MolecularNodes session object assigned as a plain class "
        "attribute, not an RNA property - it is rebuilt on registration and "
        "is not written to the .blend."),
    "Scene.mn": (
        "Embedded MolecularNodes' own scene properties. Upstream-owned state; "
        "ProteinBlender neither writes nor relies on its persistence."),
    "Object.mn": (
        "Embedded MolecularNodes' own object properties. Upstream-owned; the "
        "ProteinBlender state that matters (domain_*, pb_*) is captured "
        "separately, as are the custom ID properties MN writes."),
    "Scene.pb_assembly_factor": (
        "Live handle on the assembly nodes, not the state itself. How far "
        "assembled a protein is lives on its geometry-nodes assembly node - "
        "that is what keyframe_assembly keys and what the .blend carries - so "
        "this resets on load without losing anything. It is also a single "
        "scene-level slider standing in for whichever protein is active, so a "
        "stored value would be meaningless against a different selection."),
    "Scene.pb_assembly_stagger": (
        "Same as pb_assembly_factor: a live handle on the assembly nodes, "
        "where the value actually lives and persists."),
    "Scene.pb_assembly_id": (
        "Transient UI choice - which deposited assembly the Symmetry panel "
        "would build next. The assembly actually *built* persists as the "
        "geometry-nodes assembly node in each object's tree and is read back "
        "from there by core.assembly.built_assembly_id, so nothing is lost "
        "when this resets on load. Its enum items are also computed from the "
        "active molecule, so a stored value would be meaningless against a "
        "different selection."),
}

# Per-PropertyGroup fields excluded from the RNA walk, with reasons.
PG_EXCLUSIONS = {
    # PointerProperty to an Object. Its persistence IS tested - via the
    # object_name string that heals it - but the pointer itself resolves to a
    # different Python wrapper each access and cannot be compared by value.
    ("MoleculeListItem", "object_ptr"): "pointer identity; covered by object_name",
}


def _round(value):
    return round(float(value), FLOAT_DP) + 0.0  # +0.0 normalises -0.0


def _digest(parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(repr(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Generic RNA serialization
# ---------------------------------------------------------------------------

def _is_id(value):
    import bpy
    return isinstance(value, bpy.types.ID)


def serialize_rna(owner, depth=0):
    """Recursively serialize any bpy_struct (PropertyGroup, settings block) by
    walking its RNA. IDs become their name; sub-PropertyGroups and collections
    recurse; everything else becomes a JSON-safe scalar or list.

    Read failures are recorded as ``"<unreadable: ...>"`` rather than skipped:
    a property that becomes unreadable after a reload is itself a round-trip
    defect, and silently dropping it would hide that.
    """
    if depth > MAX_RECURSION:
        return "<max depth>"

    out = {}
    type_name = type(owner).__name__
    for prop in owner.bl_rna.properties:
        pid = prop.identifier
        if pid == "rna_type":
            continue
        if (type_name, pid) in PG_EXCLUSIONS:
            continue
        try:
            value = getattr(owner, pid)
        except Exception as exc:            # dynamic enums can raise
            out[pid] = f"<unreadable: {type(exc).__name__}>"
            continue
        try:
            out[pid] = _serialize_value(prop, value, depth)
        except Exception as exc:
            out[pid] = f"<unserializable: {type(exc).__name__}>"
    return out


def _serialize_value(prop, value, depth):
    import bpy

    if prop.type == "COLLECTION":
        return [serialize_rna(entry, depth + 1) for entry in value]

    if prop.type == "POINTER":
        if value is None:
            return None
        if _is_id(value):
            return {"__id__": type(value).__name__, "name": value.name}
        return serialize_rna(value, depth + 1)

    if getattr(prop, "is_array", False):
        if prop.type == "FLOAT":
            return [_round(v) for v in value]
        return [bool(v) if prop.type == "BOOLEAN" else int(v) for v in value]

    if prop.type == "FLOAT":
        return _round(value)
    if prop.type == "BOOLEAN":
        return bool(value)
    if prop.type == "INT":
        return int(value)
    if prop.type in ("STRING", "ENUM"):
        # Multi-select enums come back as a set; sort for determinism.
        if isinstance(value, set):
            return sorted(value)
        return str(value)
    if isinstance(value, bpy.types.bpy_struct):
        return serialize_rna(value, depth + 1)
    return str(value)


def _custom_properties(owner):
    """ID custom properties (``obj["key"]``), which is where the add-on keeps
    ``pb_is_membrane``, ``parent_molecule_id``, ``pb_brownian_metadata``,
    ``pb_sequence``, ``chain_ids`` and friends."""
    out = {}
    try:
        keys = list(owner.keys())
    except Exception:
        return out
    for key in sorted(keys):
        if key in ("_RNA_UI", "cycles"):
            continue
        try:
            value = owner[key]
        except Exception as exc:
            out[key] = f"<unreadable: {type(exc).__name__}>"
            continue
        out[key] = _plain(value)
    return out


def _plain(value):
    """Coerce an IDProperty value (which may be an IDPropertyArray or group)
    into something JSON-safe and comparable."""
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _round(value)
    if hasattr(value, "to_dict"):
        try:
            return {k: _plain(v) for k, v in value.to_dict().items()}
        except Exception:
            pass
    if hasattr(value, "to_list"):
        try:
            return [_plain(v) for v in value.to_list()]
        except Exception:
            pass
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return str(value)


# ---------------------------------------------------------------------------
# Geometry-nodes modifier inputs (version-independent, product-independent)
# ---------------------------------------------------------------------------

def _gn_socket_identifiers(node_group):
    """Input socket identifiers of a geometry node group, newest API first."""
    ids = []
    tree_items = getattr(getattr(node_group, "interface", None), "items_tree", None)
    if tree_items is not None:
        for item in tree_items:
            if getattr(item, "item_type", "") == "SOCKET" and \
                    getattr(item, "in_out", "") == "INPUT":
                ids.append(item.identifier)
        return ids
    for socket in getattr(node_group, "inputs", []):    # pre-4.0 fallback
        ids.append(socket.identifier)
    return ids


def _gn_input_value(mod, identifier):
    """Read one geometry-nodes modifier input on any Blender 4.2-5.x.

    Deliberately NOT routed through ``proteinblender.utils.gn_compat``: the
    snapshot must not share an accessor with the product, or a broken accessor
    reads the same wrong value on both sides of the round trip and the test
    stays green while the pivot (or the lipid collection) is silently lost.
    """
    # Blender 5.2+: typed modifier interface. IDProperty writes raise here.
    props = getattr(mod, "properties", None)
    if props is not None:
        try:
            return props.inputs[identifier]["value"]
        except Exception:
            pass
    # Blender 4.2-5.1: plain IDProperty subscript.
    try:
        return mod[identifier]
    except Exception:
        return None


def _serialize_modifier(mod):
    import bpy

    entry = {"name": mod.name, "type": mod.type,
             "show_viewport": bool(mod.show_viewport),
             "show_render": bool(mod.show_render)}
    node_group = getattr(mod, "node_group", None)
    if node_group is None:
        # Non-GN modifiers still carry persisted settings worth comparing
        # (Lattice/Curve object bindings, subsurf levels, ...).
        for prop in mod.bl_rna.properties:
            pid = prop.identifier
            if pid in ("rna_type", "name", "type", "show_viewport", "show_render"):
                continue
            try:
                value = getattr(mod, pid)
            except Exception:
                continue
            if _is_id(value):
                entry[pid] = value.name
            elif prop.type in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM") \
                    and not getattr(prop, "is_array", False):
                entry[pid] = _serialize_value(prop, value, MAX_RECURSION)
        return entry

    entry["node_group"] = node_group.name
    inputs = {}
    for identifier in _gn_socket_identifiers(node_group):
        value = _gn_input_value(mod, identifier)
        if value is None:
            inputs[identifier] = None
        elif _is_id(value):
            inputs[identifier] = {"__id__": type(value).__name__, "name": value.name}
        elif isinstance(value, (bool, int, str)):
            inputs[identifier] = value
        elif isinstance(value, float):
            inputs[identifier] = _round(value)
        else:
            inputs[identifier] = _plain(value)
    entry["inputs"] = inputs
    entry["tree"] = _serialize_node_tree(node_group)
    return entry


def _serialize_node_tree(tree):
    """Topology + unconnected input values of a node tree.

    The link list is the guard for the class of bug that made every imported
    molecule render nothing (a Transform node wired to its own input): state
    assertions cannot see it, but the link set can. Node *socket* values are
    captured for this tree only - nested MolecularNodes asset trees are shared
    library data, recorded by name.
    """
    links = sorted(
        (l.from_node.name, l.from_socket.identifier,
         l.to_node.name, l.to_socket.identifier)
        for l in tree.links)
    out = {
        "node_count": len(tree.nodes),
        "link_count": len(links),
        "links": [list(l) for l in links] if len(links) <= MAX_INLINE_LINKS
                 else _digest(links),
    }
    nodes = {}
    for node in sorted(tree.nodes, key=lambda n: n.name):
        info = {"idname": node.bl_idname}
        sub = getattr(node, "node_tree", None)
        if sub is not None:
            info["node_tree"] = sub.name
        values = {}
        for socket in node.inputs:
            if socket.is_linked:
                continue
            value = getattr(socket, "default_value", None)
            if value is None:
                continue
            if _is_id(value):
                values[socket.identifier] = {"__id__": type(value).__name__,
                                             "name": value.name}
            elif isinstance(value, (bool, int, str)):
                values[socket.identifier] = value
            elif isinstance(value, float):
                values[socket.identifier] = _round(value)
            else:
                values[socket.identifier] = _plain(value)
        if values:
            info["input_values"] = values
        nodes[node.name] = info
    out["nodes"] = nodes
    return out


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

def _action_fcurves(action, animation_data):
    """Every F-curve of an action on both the legacy and the 4.4+ slotted
    action layouts, deduplicated by (data_path, array_index)."""
    found = {}
    for fcurve in getattr(action, "fcurves", []) or []:
        found[(fcurve.data_path, fcurve.array_index)] = fcurve
    for layer in getattr(action, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                slot = getattr(animation_data, "action_slot", None)
                bag = strip.channelbag(slot) if slot is not None else None
                bags = [bag] if bag is not None else []
            for bag in bags:
                for fcurve in getattr(bag, "fcurves", []) or []:
                    found[(fcurve.data_path, fcurve.array_index)] = fcurve
    return found


def _serialize_animation(owner):
    """Actions and their keyframes.

    Keyframe *values* are captured, not just counts: a reload that keeps three
    keyframes but flattens them all to the same value is exactly the failure
    mode a count cannot see.
    """
    animation_data = getattr(owner, "animation_data", None)
    if animation_data is None:
        return None
    action = getattr(animation_data, "action", None)
    entry = {
        "action": action.name if action else None,
        "action_slot": getattr(getattr(animation_data, "action_slot", None),
                               "name_display", None),
    }
    if action is None:
        return entry
    curves = {}
    for (data_path, index), fcurve in sorted(_action_fcurves(action, animation_data).items()):
        curves[f"{data_path}[{index}]"] = {
            "extrapolation": fcurve.extrapolation,
            "mute": bool(fcurve.mute),
            "keyframes": [
                {
                    "co": [_round(kp.co[0]), _round(kp.co[1])],
                    "type": kp.type,
                    "interpolation": kp.interpolation,
                    "handle_left": [_round(kp.handle_left[0]), _round(kp.handle_left[1])],
                    "handle_right": [_round(kp.handle_right[0]), _round(kp.handle_right[1])],
                }
                for kp in fcurve.keyframe_points
            ],
        }
    entry["fcurves"] = curves
    return entry


# ---------------------------------------------------------------------------
# Object data
# ---------------------------------------------------------------------------

def _serialize_object_data(obj):
    data = obj.data
    if data is None:
        return None
    entry = {"name": data.name, "type": type(data).__name__}

    vertices = getattr(data, "vertices", None)
    if vertices is not None:
        import numpy as np
        count = len(vertices)
        entry["vertex_count"] = count
        if count:
            coords = np.empty(count * 3, dtype=np.float64)
            vertices.foreach_get("co", coords)
            entry["vertex_digest"] = _digest(np.round(coords, FLOAT_DP).tolist())
            reshaped = coords.reshape(-1, 3)
            entry["bbox_min"] = [_round(v) for v in reshaped.min(axis=0)]
            entry["bbox_max"] = [_round(v) for v in reshaped.max(axis=0)]
        # Mesh attributes are where MolecularNodes keeps res_id, chain_id,
        # is_alpha_carbon ... - the data every domain mask reads.
        attributes = getattr(data, "attributes", None)
        if attributes is not None:
            entry["attributes"] = sorted(
                f"{a.name}:{a.data_type}:{a.domain}" for a in attributes)

    splines = getattr(data, "splines", None)
    if splines is not None:                       # curves (linkers, DNA bends)
        # A digest alone answers "did it change" but not "by how much", which
        # for a generated curve (a linker coil is rebuilt on load) is the
        # difference between floating-point noise and a visibly different
        # shape. The summary makes the diff self-explanatory.
        spline_entries = []
        for spline in splines:
            points = spline.bezier_points or spline.points
            coords = [[_round(c) for c in point.co[:3]] for point in points]
            summary = {
                "type": spline.type,
                "point_count": len(points),
                "points_digest": _digest(coords),
            }
            if coords:
                axes = list(zip(*coords))
                summary["bbox_min"] = [_round(min(a)) for a in axes]
                summary["bbox_max"] = [_round(max(a)) for a in axes]
                summary["centroid"] = [_round(sum(a) / len(a)) for a in axes]
            spline_entries.append(summary)
        entry["splines"] = spline_entries
        entry["bevel_depth"] = _round(getattr(data, "bevel_depth", 0.0))

    points = getattr(data, "points", None)
    if points is not None and splines is None:    # lattices (membrane deform)
        entry["point_count"] = len(points)
        entry["points_digest"] = _digest(
            [[_round(c) for c in point.co_deform] for point in points])
    return entry


def _serialize_object(obj, object_props):
    entry = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "parent_type": obj.parent_type,
        "matrix_world": [[_round(v) for v in row] for row in obj.matrix_world],
        "matrix_parent_inverse": [[_round(v) for v in row]
                                  for row in obj.matrix_parent_inverse],
        "location": [_round(v) for v in obj.location],
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": [_round(v) for v in obj.rotation_euler],
        "rotation_quaternion": [_round(v) for v in obj.rotation_quaternion],
        "scale": [_round(v) for v in obj.scale],
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_get": bool(obj.hide_get()),
        "collections": sorted(c.name for c in obj.users_collection),
        "custom_properties": _custom_properties(obj),
        "modifiers": [_serialize_modifier(m) for m in obj.modifiers],
        "constraints": sorted(f"{c.name}:{c.type}" for c in obj.constraints),
        "animation": _serialize_animation(obj),
        "data": _serialize_object_data(obj),
        "materials": [m.name if m else None for m in obj.data.materials]
                     if getattr(obj.data, "materials", None) is not None else [],
    }
    addon = {}
    for name in object_props:
        if not hasattr(obj, name):
            continue
        try:
            value = getattr(obj, name)
        except Exception as exc:
            addon[name] = f"<unreadable: {type(exc).__name__}>"
            continue
        if hasattr(value, "__len__") and not isinstance(value, str):
            addon[name] = [_round(v) for v in value]
        elif isinstance(value, float):
            addon[name] = _round(value)
        else:
            addon[name] = value if isinstance(value, (bool, int, str)) else str(value)
    entry["addon_properties"] = addon
    return entry


def _serialize_material(material):
    entry = {"name": material.name, "use_nodes": bool(material.use_nodes)}
    if not material.use_nodes or material.node_tree is None:
        entry["diffuse_color"] = [_round(v) for v in material.diffuse_color]
        return entry
    entry["tree"] = _serialize_node_tree(material.node_tree)
    return entry


# ---------------------------------------------------------------------------
# Runtime registry (the singleton a reopened file must rebuild)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Datablock inventories
#
# Compared by REACHABILITY from the scene, not by what happens to sit in
# bpy.data. Blender writes a datablock into a .blend only if the scene reaches
# it, and ``ID.users`` is not that test: MolecularNodes appends its asset trees
# on every import, so a scene accumulates orphans like "MN Fresnel.001" that
# reference each other and therefore report users > 0 while being unreachable
# and unsaved. Diffing raw bpy.data reports their disappearance as data loss on
# every single case; diffing reachable data still reports a tree that a real
# object depended on and lost.
# ---------------------------------------------------------------------------

def _reachable_node_groups():
    import bpy

    seen = set()

    def walk(tree):
        if tree is None or tree.name in seen:
            return
        seen.add(tree.name)
        for node in tree.nodes:
            walk(getattr(node, "node_tree", None))

    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            walk(getattr(mod, "node_group", None))
        for slot in (getattr(obj.data, "materials", None) or []):
            if slot is not None and slot.use_nodes:
                walk(slot.node_tree)
    return sorted(seen)


def _reachable_actions():
    import bpy

    names = set()
    for obj in bpy.data.objects:
        for owner in (obj, obj.data, getattr(obj.data, "shape_keys", None)):
            animation_data = getattr(owner, "animation_data", None)
            action = getattr(animation_data, "action", None)
            if action is not None:
                names.add(action.name)
    # Actions deliberately kept alive across a rebuild (the DNA bend rig parks
    # its action with a fake user while the strand is rebuilt) are saved too.
    names.update(a.name for a in bpy.data.actions if a.use_fake_user)
    return sorted(names)


def _reachable_collections():
    import bpy

    seen = []

    def walk(collection):
        if collection.name in seen:
            return
        seen.append(collection.name)
        for child in collection.children:
            walk(child)

    for scene in bpy.data.scenes:
        for child in scene.collection.children:
            walk(child)
    return sorted(seen)


def _find_addon_module():
    """Resolve the add-on package under either the source name
    (``proteinblender``) or the installed extension name
    (``bl_ext.<repo>.proteinblender``), so this module works in both lanes."""
    import sys
    for name in sys.modules:
        if name == "proteinblender" or name.endswith(".proteinblender"):
            if f"{name}.utils.scene_manager" in sys.modules:
                return name
    return "proteinblender"


def _serialize_registry():
    """The live ``ProteinBlenderScene.molecules`` registry.

    An empty registry after a reopen is the single most user-visible save/load
    failure: the outliner still lists the proteins, but colour / split / centre
    / duplicate / pose all fail with "Molecule not found".
    """
    import sys
    module = sys.modules.get(f"{_find_addon_module()}.utils.scene_manager")
    if module is None:
        return {"error": "scene_manager not importable"}
    try:
        manager = module.ProteinBlenderScene.get_instance()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    molecules = {}
    for identifier, wrapper in getattr(manager, "molecules", {}).items():
        obj = getattr(wrapper, "object", None)
        domains = {}
        for domain_id, domain in getattr(wrapper, "domains", {}).items():
            domain_obj = getattr(domain, "object", None)
            domains[str(domain_id)] = {
                "name": getattr(domain, "name", ""),
                "chain_id": str(getattr(domain, "chain_id", "")),
                "start": int(getattr(domain, "start", -1)),
                "end": int(getattr(domain, "end", -1)),
                "object": getattr(domain_obj, "name", None) if domain_obj else None,
            }
        molecules[str(identifier)] = {
            "object": getattr(obj, "name", None) if obj else None,
            "domain_ids": sorted(domains),
            "domains": domains,
            "chain_mapping": {str(k): str(v) for k, v in
                              (getattr(wrapper, "chain_mapping", {}) or {}).items()},
            "chain_residue_ranges": {
                str(k): [int(v[0]), int(v[1])] for k, v in
                (getattr(wrapper, "chain_residue_ranges", {}) or {}).items()},
        }
    return {"molecule_ids": sorted(molecules), "molecules": molecules}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def scene_snapshot(include_registry=True):
    """A complete, comparable picture of every piece of add-on state that a
    .blend is expected to carry."""
    import bpy

    scene = bpy.context.scene

    scene_state = {}
    for name in SCENE_PROPS:
        if not hasattr(scene, name):
            scene_state[name] = "<not registered>"
            continue
        prop = scene.bl_rna.properties.get(name)
        try:
            value = getattr(scene, name)
        except Exception as exc:
            scene_state[name] = f"<unreadable: {type(exc).__name__}>"
            continue
        if prop is None:
            scene_state[name] = str(value)
        else:
            try:
                scene_state[name] = _serialize_value(prop, value, 0)
            except Exception as exc:
                scene_state[name] = f"<unserializable: {type(exc).__name__}>"

    objects = {obj.name: _serialize_object(obj, OBJECT_PROPS)
               for obj in sorted(bpy.data.objects, key=lambda o: o.name)}

    used_materials = sorted({
        slot.name for obj in bpy.data.objects
        for slot in (getattr(obj.data, "materials", None) or []) if slot})
    materials = {name: _serialize_material(bpy.data.materials[name])
                 for name in used_materials if name in bpy.data.materials}

    snapshot = {
        "scene": scene_state,
        "scene_frames": {
            "current": scene.frame_current,
            "start": scene.frame_start,
            "end": scene.frame_end,
        },
        "objects": objects,
        "object_names": sorted(objects),
        "materials": materials,
        "collections": _reachable_collections(),
        "node_group_names": _reachable_node_groups(),
        "action_names": _reachable_actions(),
    }
    if include_registry:
        snapshot["registry"] = _serialize_registry()
    return snapshot
