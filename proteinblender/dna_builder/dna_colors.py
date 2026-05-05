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
    """Overwrite the ``Color`` attribute on *obj* with per-base colours.

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

    # Read res_name integers from mesh attribute
    rn_attr = mesh.attributes.get("res_name")
    if rn_attr is None:
        return
    res_names = np.zeros(n, dtype=np.int32)
    rn_attr.data.foreach_get("value", res_names)

    # Start with backbone colour everywhere
    bb = np.array(colors.get("backbone", [0.75, 0.75, 0.75, 1.0]), dtype=np.float32)
    color_data = np.tile(bb, (n, 1))

    # Adenine
    mask_a = np.isin(res_names, [_DNA_A, _RNA_A])
    color_data[mask_a] = colors["A"]

    # Thymine
    mask_t = res_names == _DNA_T
    color_data[mask_t] = colors["T"]

    # Guanine
    mask_g = np.isin(res_names, [_DNA_G, _RNA_G])
    color_data[mask_g] = colors["G"]

    # Cytosine
    mask_c = np.isin(res_names, [_DNA_C, _RNA_C])
    color_data[mask_c] = colors["C"]

    # Uracil
    mask_u = res_names == _RNA_U
    color_data[mask_u] = colors["U"]

    # Write back
    color_attr = mesh.attributes.get("Color")
    if color_attr is None:
        color_attr = mesh.attributes.new("Color", "FLOAT_COLOR", "POINT")
    color_attr.data.foreach_set("color", color_data.flatten())

    mesh.update()


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
