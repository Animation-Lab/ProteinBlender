"""Reading a built filament back out of Blender, and the deposit to judge it by.

Shared by the filament tests. Everything here observes: the drawn atoms come
from the evaluated scene and the expected arrangement from the PDB entry a
subunit was cut out of. Nothing asks the lattice generator, a preset or the
bend code where a copy should be.
"""

import json
import os

import bpy
import numpy as np

import helpers as H

WORLD_SCALE = 0.01          # Blender units per Angstrom

_TRUTH_FILES = {"ACTIN": "actin_8a2t", "MICROTUBULE": "tubulin_7sj7"}


def presets():
    from proteinblender.core import filament_presets
    return filament_presets


def truth(preset_id):
    """Where the unit's neighbours sit in the deposit, in the unit's own frame."""
    name = _TRUTH_FILES[preset_id]
    with open(H.data_path(os.path.join("filaments", f"{name}_neighbours.json")),
              encoding="utf-8") as handle:
        return json.load(handle)


def alpha_carbons(path):
    """``{(chain, residue number): xyz}`` read from the PDB text itself."""
    found = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("ATOM") and line[12:16].strip() == "CA":
                found[(line[21], int(line[22:26]))] = np.array(
                    [float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return found


def drawn_copies(molecule, chain_letter, residues):
    """Where Blender drew some C-alpha atoms of one chain, once per copy.

    Read from the evaluated scene: each copy is an instance carrying the
    chain's atoms with their ``res_id`` and ``is_alpha_carbon`` attributes, so
    an atom is found by what it is rather than by where the add-on's own
    coordinate helpers say it should be. Returns one ``(n, 3)`` array per
    copy, in Angstrom, rows in the order of ``residues``.

    A surface draws no atoms, so a chain drawn as one (as a new filament is)
    is drawn as spheres for the reading and put back afterwards. Where a copy
    stands does not depend on how it is drawn.
    """
    obj = next(d.object for d in molecule.domains.values()
               if str(d.chain_id) == chain_letter)
    from proteinblender.core import visual_style

    style = visual_style.find_style_node(obj)
    surface = (style is not None and style.node_tree is not None
               and style.node_tree.name.startswith("Style Surface"))
    if not surface:
        return _drawn_copies(obj, chain_letter, residues)
    visual_style.apply_style_to_object(obj, "spheres", sync_morphsets=False)
    try:
        return _drawn_copies(obj, chain_letter, residues)
    finally:
        visual_style.apply_style_to_object(obj, "surface", sync_morphsets=False)
        bpy.context.view_layer.update()


def _drawn_copies(obj, chain_letter, residues):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    copies = []
    for instance in depsgraph.object_instances:
        parent = instance.parent
        if parent is None or parent.original.name != obj.name:
            continue
        data = instance.object.data
        count = len(getattr(data, "points", ()))
        if not count:
            continue
        position = np.zeros(count * 3)
        data.attributes["position"].data.foreach_get("vector", position)
        res_id = np.zeros(count, dtype=np.int32)
        data.attributes["res_id"].data.foreach_get("value", res_id)
        is_alpha = np.zeros(count, dtype=bool)
        data.attributes["is_alpha_carbon"].data.foreach_get("value", is_alpha)

        matrix = np.array(instance.matrix_world)
        world = position.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        rows = []
        for residue in residues:
            found = np.flatnonzero(is_alpha & (res_id == residue))
            assert len(found) == 1, (
                f"chain {chain_letter} residue {residue} has {len(found)} "
                f"C-alpha atoms in the drawn copy")
            rows.append(world[found[0]])
        copies.append(np.array(rows) / WORLD_SCALE)
    return copies


def between(first, second):
    """Every distance from an atom of ``first`` to an atom of ``second``."""
    return np.linalg.norm(first[:, None, :] - second[None, :, :], axis=2)


def worst_miss(molecule, preset, neighbour):
    """How well any two drawn copies reproduce a neighbour pair in the deposit.

    In the deposit, the shipped subunit and one of its neighbours are a fixed
    arrangement of two bodies. Eight atoms on each give sixty-four distances
    between them, and those pin the arrangement down - position *and*
    orientation - without saying anything about where in a scene it is, so
    the comparison owes nothing to how the import centres a structure or
    where its pivot went. The filament is right if some pair of drawn copies
    stands in the same arrangement; the answer is the worst of the sixty-four
    for the best pair, in Angstrom.
    """
    shipped = alpha_carbons(presets().structure_path(preset))
    chain = neighbour["copy_of_chain"]
    residues = sorted(int(r) for r in neighbour["landmarks"])
    unit = np.array([shipped[(chain, r)] for r in residues])
    beside = np.array([neighbour["landmarks"][str(r)] for r in residues])
    deposited = between(unit, beside)

    copies = drawn_copies(molecule, chain, residues)
    assert len(copies) > 1, f"only {len(copies)} copies of chain {chain} drawn"
    return min(float(np.abs(between(a, b) - deposited).max())
               for i, a in enumerate(copies)
               for j, b in enumerate(copies) if i != j)


def chain_centres(molecule, preset, chain_letter="A"):
    """The middle of one chain in every drawn copy, in Angstrom.

    The mean of the chain's C-alpha atoms, which for a rigid copy is a point
    fixed in the subunit - so how the centres stand to one another is how the
    copies do.
    """
    shipped = alpha_carbons(presets().structure_path(preset))
    residues = sorted(r for (chain, r) in shipped if chain == chain_letter)
    return np.array([copy.mean(axis=0)
                     for copy in drawn_copies(molecule, chain_letter, residues)])
