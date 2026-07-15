"""Shared test helpers for the ProteinBlender suite.

These are plain functions (no pytest, no fixtures) so they can be called from
any test module, from conftest fixtures, or from a bare `blender --python`
session. Everything here runs *inside* Blender's Python — `bpy` is imported
lazily at call time so the module can also be imported by tooling that only
wants the constants.

Import style: the top-level ``conftest.py`` puts the ``tests/`` directory on
``sys.path``, so any test module can simply ``import helpers as H``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo layout ---------------------------------------------------------------
TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
DATA_DIR = TESTS_DIR / "data"

# The addon is imported as a top-level package (see conftest bootstrap), so the
# module path is plain ``proteinblender.*`` rather than the installed
# ``bl_ext.*`` extension path.
PKG = "proteinblender"


# --------------------------------------------------------------------------
# Addon / scene-manager access
# --------------------------------------------------------------------------

def scene_manager_module():
    return sys.modules[f"{PKG}.utils.scene_manager"]


def sm():
    """Return the live ProteinBlenderScene singleton."""
    return scene_manager_module().ProteinBlenderScene.get_instance()


def data_path(name: str) -> str:
    """Absolute path to a bundled structure fixture under tests/data."""
    return str(DATA_DIR / name)


# --------------------------------------------------------------------------
# Scene reset  (headless Blender is one long-lived process — every test must
# tear the scene + addon registry down or state bleeds between tests)
# --------------------------------------------------------------------------

def reset_scene():
    """Delete everything the addon manages, then flush orphan datablocks."""
    import bpy

    mgr = sm()
    for ident in list(getattr(mgr, "molecules", {}).keys()):
        try:
            mgr.delete_molecule(ident)
        except Exception:
            try:
                del mgr.molecules[ident]
            except Exception:
                pass

    scene = bpy.context.scene
    for coll_name in ("molecule_list_items", "outliner_items", "pb2_linkers",
                      "pose_library", "chain_selections"):
        coll = getattr(scene, coll_name, None)
        if coll is not None:
            try:
                while len(coll) > 0:
                    coll.remove(0)
            except Exception:
                pass

    # Remove all objects, then orphaned data of every relevant type.
    for obj in list(bpy.data.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    for blockset in (bpy.data.meshes, bpy.data.curves, bpy.data.lattices,
                     bpy.data.materials, bpy.data.node_groups,
                     bpy.data.collections, bpy.data.armatures):
        for blk in list(blockset):
            try:
                blockset.remove(blk)
            except Exception:
                pass

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Import helpers
# --------------------------------------------------------------------------

def import_local(filename: str, identifier: str | None = None) -> str:
    """Import a bundled local structure (offline). Returns the molecule id.

    Uses the scene-manager's file path directly (bypassing the file-browser
    operator, which needs interactive context). This is the preferred import
    in tests — no network, deterministic.
    """
    path = data_path(filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"test fixture missing: {path}")
    ident = identifier or os.path.splitext(os.path.basename(filename))[0]
    mgr = sm()
    before = set(mgr.molecules.keys())
    ok = mgr.import_molecule_from_file(path, ident)
    if not ok:
        raise RuntimeError(f"import_molecule_from_file failed for {path}")
    new = sorted(set(mgr.molecules.keys()) - before)
    if not new:
        raise RuntimeError(f"no new molecule registered for {path}")
    return new[-1]


def import_pdb(pdb_id: str, fmt: str = "pdb") -> str:
    """Import a protein via the public operator (network fetch from RCSB).

    Mark tests that call this with ``@pytest.mark.network``.
    """
    import bpy
    scene = bpy.context.scene
    scene.protein_props.import_method = "PDB"
    scene.protein_props.pdb_id = pdb_id
    scene.protein_props.remote_format = fmt
    mgr = sm()
    before = set(mgr.molecules.keys())
    bpy.ops.molecule.import_protein()
    new = sorted(set(mgr.molecules.keys()) - before)
    if not new:
        raise RuntimeError(f"import_protein produced no molecule for {pdb_id}")
    return new[-1]


def build_dna(seq="ATCGATCGATCG", name_prefix="DNA", nt="DNA", ds=True,
              style="ball_and_stick"):
    """Build a nucleic-acid structure through the DNA builder operator.

    Returns the created object (first pb_is_nucleic_acid object with the prefix).
    """
    import bpy
    props = bpy.context.scene.dna_builder_props
    props.nucleic_type = nt
    props.sequence = seq
    props.double_stranded = ds
    props.style = style
    props.name_prefix = name_prefix
    bpy.ops.proteinblender.build_dna()
    for o in bpy.data.objects:
        if o.get("pb_is_nucleic_acid") and o.name.startswith(name_prefix):
            return o
    raise RuntimeError(f"build_dna({name_prefix}) produced no nucleic object")


def build_membrane(**overrides):
    """Build a membrane through the operator. `overrides` set membrane props.

    Returns the set of object names created by the build (so callers can find
    the membrane surface / lipid objects regardless of naming).
    """
    import bpy
    props = bpy.context.scene.membrane_builder_props
    for key, val in overrides.items():
        setattr(props, key, val)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.proteinblender.build_membrane()
    after = set(o.name for o in bpy.data.objects)
    return sorted(after - before)


# --------------------------------------------------------------------------
# Lookups / assertions support
# --------------------------------------------------------------------------

def list_item(mol_id):
    """Return the MoleculeListItem PropertyGroup for a molecule id, or None."""
    import bpy
    for it in bpy.context.scene.molecule_list_items:
        if it.identifier == mol_id:
            return it
    return None


def outliner_items_of_type(item_type):
    import bpy
    return [it for it in bpy.context.scene.outliner_items
            if it.item_type == item_type]


def select_only(obj):
    import bpy
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# --------------------------------------------------------------------------
# Geometry snapshot support (for syrupy regression of GN / mesh output)
# --------------------------------------------------------------------------

def eval_positions(obj):
    """Evaluated vertex positions of an object (after modifiers/GN), as a
    numpy (N, 3) float array. The single most useful geometry regression
    signal — feed it to the ``geo_snapshot`` fixture."""
    import bpy
    import numpy as np
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()
    n = len(mesh.vertices)
    arr = np.empty(n * 3, dtype=np.float64)
    if n:
        mesh.vertices.foreach_get("co", arr)
    ev.to_mesh_clear()
    return arr.reshape(-1, 3)


def geometry_summary(obj):
    """A compact, deterministic dict summarising an object's evaluated
    geometry — vertex count, bounding box, centroid. Stable enough to snapshot
    without tripping on floating-point noise (values rounded)."""
    import numpy as np
    pos = eval_positions(obj)
    if len(pos) == 0:
        return {"verts": 0}
    return {
        "verts": int(len(pos)),
        "bbox_min": [round(float(x), 3) for x in pos.min(axis=0)],
        "bbox_max": [round(float(x), 3) for x in pos.max(axis=0)],
        "centroid": [round(float(x), 3) for x in pos.mean(axis=0)],
    }
