"""Per-base coloring for DNA/RNA molecules.

Sets the Color attribute on mesh vertices based on the res_name attribute
and user-defined base colors.  Works with any MN style node since styles
read the existing Color attribute from the geometry.
"""

import numpy as np


# MolecularNodes res_name integer codes (from data.py)
_DNA_A = 30   # DA
_DNA_C = 31   # DC
_DNA_G = 32   # DG
_DNA_T = 33   # DT
_RNA_A = 40   # A
_RNA_C = 41   # C
_RNA_G = 42   # G
_RNA_U = 43   # U


def apply_base_colors(obj, colors: dict) -> None:
    """Overwrite the ``Color`` attribute on *obj* with per-base colours and
    push the backbone colour into the Style Cartoon/Ribbon node's
    ``Backbone Color`` socket.

    Parameters
    ----------
    obj : bpy.types.Object
        Blender mesh object created by the MN pipeline.
    colors : dict
        Keys ``'A'``, ``'T'``, ``'G'``, ``'C'``, ``'U'``, ``'backbone'``.
        Each value is an RGBA tuple/list of 4 floats in [0, 1].
    """
    mesh = obj.data
    n = len(mesh.vertices)

    # Read residue type per atom. Prefer pb_real_res_name (a snapshot of
    # the original per-atom residue type) if present — uniform-rungs
    # mode overrides the mesh's res_name attribute to all DT so MN's
    # Cartoon style draws every base with the same pyrimidine block,
    # but we still need the *real* base identity to colour correctly.
    rn_attr = mesh.attributes.get("pb_real_res_name") or mesh.attributes.get("res_name")
    if rn_attr is None:
        return
    res_names = np.zeros(n, dtype=np.int32)
    rn_attr.data.foreach_get("value", res_names)

    # is_backbone is written by the MN pipeline (bool per atom). Used to
    # exclude sugar/phosphate atoms from the per-base recolouring so the
    # backbone keeps its own colour in styles that read the Color attribute
    # directly (ball-and-stick, sticks, spheres, surface).
    bb_attr = mesh.attributes.get("is_backbone")
    is_backbone = np.zeros(n, dtype=bool)
    if bb_attr is not None:
        try:
            bb_attr.data.foreach_get("value", is_backbone)
        except Exception:
            pass

    base_mask = ~is_backbone

    # Backbone colour everywhere, then overwrite only base-ring atoms
    bb = np.array(colors.get("backbone", [0.75, 0.75, 0.75, 1.0]), dtype=np.float32)
    color_data = np.tile(bb, (n, 1))

    # Adenine
    mask_a = base_mask & np.isin(res_names, [_DNA_A, _RNA_A])
    color_data[mask_a] = colors["A"]

    # Thymine
    mask_t = base_mask & (res_names == _DNA_T)
    color_data[mask_t] = colors["T"]

    # Guanine
    mask_g = base_mask & np.isin(res_names, [_DNA_G, _RNA_G])
    color_data[mask_g] = colors["G"]

    # Cytosine
    mask_c = base_mask & np.isin(res_names, [_DNA_C, _RNA_C])
    color_data[mask_c] = colors["C"]

    # Uracil
    mask_u = base_mask & (res_names == _RNA_U)
    color_data[mask_u] = colors["U"]

    # Write back
    color_attr = mesh.attributes.get("Color")
    if color_attr is None:
        color_attr = mesh.attributes.new("Color", "FLOAT_COLOR", "POINT")
    color_attr.data.foreach_set("color", color_data.flatten())

    mesh.update()

    # The cartoon/ribbon style's backbone tube does NOT read the per-atom
    # Color attribute — it has its own Backbone Color socket. Push the user
    # colour into any matching socket on the object's modifier node tree.
    _apply_backbone_color_to_style(obj, bb)


def _apply_backbone_color_to_style(obj, backbone_rgba) -> None:
    """Set Backbone Color on Style Cartoon / Ribbon nodes in obj's modifiers."""
    rgba = tuple(float(v) for v in backbone_rgba)
    for mod in obj.modifiers:
        if mod.type != "NODES" or mod.node_group is None:
            continue
        for node in mod.node_group.nodes:
            # Style Cartoon, Style Ribbon, etc. are GROUP nodes whose
            # subgroup name starts with "Style ".
            ng = getattr(node, "node_tree", None)
            if ng is None or not ng.name.startswith("Style "):
                continue
            socket = node.inputs.get("Backbone Color")
            if socket is not None:
                socket.default_value = rgba


def colors_from_props(props) -> dict:
    """Extract a color dict from a DNABuilderProperties instance."""
    return {
        "A": list(props.color_a),
        "T": list(props.color_t),
        "G": list(props.color_g),
        "C": list(props.color_c),
        "U": list(props.color_u),
        "backbone": list(props.color_backbone),
    }


def colors_from_object(obj) -> dict:
    """Read stored per-base colours from an object's custom properties."""
    def _get(key, default):
        val = obj.get(key)
        if val is not None:
            return list(val)
        return default

    return {
        "A": _get("pb_color_a", [1.0, 0.0, 0.0, 1.0]),
        "T": _get("pb_color_t", [0.0, 0.0, 1.0, 1.0]),
        "G": _get("pb_color_g", [0.0, 1.0, 0.0, 1.0]),
        "C": _get("pb_color_c", [1.0, 1.0, 0.0, 1.0]),
        "U": _get("pb_color_u", [0.0, 1.0, 1.0, 1.0]),
        "backbone": _get("pb_color_backbone", [0.75, 0.75, 0.75, 1.0]),
    }


def store_colors_on_object(obj, colors: dict) -> None:
    """Persist per-base colours as custom properties on *obj*."""
    obj["pb_color_a"] = list(colors["A"])
    obj["pb_color_t"] = list(colors["T"])
    obj["pb_color_g"] = list(colors["G"])
    obj["pb_color_c"] = list(colors["C"])
    obj["pb_color_u"] = list(colors["U"])
    obj["pb_color_backbone"] = list(colors["backbone"])
