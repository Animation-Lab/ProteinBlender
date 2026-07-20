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
    """Delete everything the addon manages, then flush orphan datablocks.

    Individual removals remain best-effort because Blender can invalidate an
    RNA wrapper while a deletion cascade is running.  The autouse fixture calls
    ``harness_contract.assert_clean_scene`` afterwards, so an ignored exception
    can no longer silently contaminate the next test.
    """
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

    Executes the public local-import operator used by the file browser. When a
    test needs a stable custom identifier, it then uses the public rename
    operator instead of calling the scene manager directly.
    """
    import bpy

    path = data_path(filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"test fixture missing: {path}")
    mgr = sm()
    before = set(mgr.molecules.keys())
    requested_id = identifier or os.path.splitext(os.path.basename(filename))[0]
    result = bpy.ops.molecule.import_local(
        "EXEC_DEFAULT", filepath=path, identifier_override=requested_id)
    if result != {"FINISHED"}:
        raise RuntimeError(f"molecule.import_local failed for {path}")
    new = sorted(set(mgr.molecules.keys()) - before)
    if not new:
        raise RuntimeError(f"no new molecule registered for {path}")
    imported_id = new[-1]
    if imported_id != requested_id:
        raise RuntimeError(
            f"public import returned {imported_id!r}, expected {requested_id!r}")
    return imported_id


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


def split_domain_from_outliner(molecule_id, chain_id, start, end,
                               domain_id=None):
    """Split through the operator exposed by the Protein Outliner panel."""
    import bpy

    scene_manager_module().build_outliner_hierarchy(bpy.context)
    scene = bpy.context.scene
    scene.selected_molecule_id = molecule_id
    target = None
    if domain_id:
        target = next((item for item in scene.outliner_items
                       if item.item_type == "DOMAIN"
                       and item.item_id == domain_id), None)
    if target is None:
        molecule = sm().molecules[molecule_id]
        accepted_ids = {str(chain_id)}
        for index, author_id in molecule.chain_mapping.items():
            if str(author_id) == str(chain_id):
                accepted_ids.add(str(index))
        target = next(item for item in scene.outliner_items
                      if item.item_type == "CHAIN"
                      and item.parent_id == molecule_id
                      and (item.chain_id in accepted_ids
                           or item.name == f"Chain {chain_id}"))
    for item in scene.outliner_items:
        item.is_selected = item.item_id == target.item_id
    return bpy.ops.proteinblender.split_domain_popup(
        "EXEC_DEFAULT", item_id=target.item_id, item_type=target.item_type,
        split_start=start, split_end=end)


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
    pos = eval_positions(obj)
    if len(pos) == 0:
        return {"verts": 0}
    return {
        "verts": int(len(pos)),
        "bbox_min": [round(float(x), 3) for x in pos.min(axis=0)],
        "bbox_max": [round(float(x), 3) for x in pos.max(axis=0)],
        "centroid": [round(float(x), 3) for x in pos.mean(axis=0)],
    }


def renders_geometry(obj):
    """True iff ``obj``'s evaluated output actually draws something.

    The canonical anti-facade "is this thing visible" check. It deliberately
    ignores the *base* mesh: molecule / DNA / membrane base meshes always carry
    their raw atom (or patch) points, so a base-vertex count stays positive even
    when the style / GN tree emits nothing — that shortcut is exactly what let a
    zero-lipid membrane and a broken style pass their tests. What a user sees is
    the evaluated object, which is either *realized* mesh (cartoon / sticks /
    surface bake to thousands of verts) or geometry-node *instances* (spheres /
    a membrane bilayer realize 0 verts but emit instances). Count both.
    """
    import bpy
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    realized = 0
    try:
        m = ev.to_mesh()
        realized = len(m.vertices)
        ev.to_mesh_clear()
    except Exception:
        realized = 0
    instances = sum(1 for inst in deps.object_instances
                    if inst.is_instance and inst.parent == ev)
    return realized > 0 or instances > 0


# --------------------------------------------------------------------------
# Independent ground truth (no addon code) for pivot / residue-position tests
# --------------------------------------------------------------------------
#
# The rule (see CLAUDE.md "Ground truth must be independent of the code under
# test"): a pivot/position test must not compute its expected value with the
# same helper the operator calls. These parse the source PDB with biotite and
# render pixels with Blender - neither touches proteinblender code - so they can
# falsify a bug instead of moving with it.

# MolecularNodes scales Angstrom -> Blender units by this factor at import
# (utils/molecularnodes/entities/molecule/molecule.py). Distances in the mesh's
# world space are PDB Angstrom distances times this.
WORLD_SCALE = 0.01


def pdb_amino_acid_cas(filename: str, chain_letter: str):
    """{res_id: (x, y, z)} for the amino-acid alpha carbons of one chain, read
    straight from the PDB fixture with biotite.

    Independent of the addon: it re-parses the source file and uses biotite's
    filter_amino_acids, so it excludes bound ions/ligands (e.g. 1ATN's Ca2+,
    atom name 'CA') and keeps modified residues. Coordinates are in Angstrom, in
    the PDB frame - compare via transform-invariant pairwise distances, not
    absolute positions (the mesh is scaled and re-centred).
    """
    import numpy as np
    import biotite.structure as struc
    import biotite.structure.io.pdb as pdb

    arr = pdb.PDBFile.read(data_path(filename)).get_structure(model=1)
    chain = arr[arr.chain_id == chain_letter]
    names = np.char.strip(chain.atom_name.astype(str))
    mask = (np.char.upper(names) == "CA") & struc.filter_amino_acids(chain)
    return {int(r): tuple(float(c) for c in xyz)
            for r, xyz in zip(chain.res_id[mask], chain.coord[mask])}


def assert_world_points_match_residues(points_by_label, cas, scale=WORLD_SCALE,
                                       atol=2e-3):
    """Verify a set of world-space points landed on the intended PDB residues,
    using only pairwise distances (invariant under the unknown rigid+scale
    transform between PDB Angstrom space and the mesh's world space).

    ``points_by_label``: {label: mathutils.Vector | (x,y,z)} - the operator
    results. ``cas``: {label: (x,y,z)} - the PDB Angstrom ground truth for the
    residue each label should have landed on. For every pair of labels, the
    world distance must equal the PDB distance times ``scale``. A pivot that
    landed on the wrong atom (say a central ion instead of the terminus) breaks
    at least one pair, so this cannot pass with the bug present.
    """
    import numpy as np

    labels = list(points_by_label)
    assert set(labels) == set(cas), "label mismatch between points and CAs"
    problems = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a, b = labels[i], labels[j]
            pw = float(np.linalg.norm(np.array(tuple(points_by_label[a]))
                                      - np.array(tuple(points_by_label[b]))))
            pdb_d = float(np.linalg.norm(np.array(cas[a]) - np.array(cas[b])))
            if abs(pw - pdb_d * scale) > atol:
                problems.append(
                    f"{a}<->{b}: world {pw:.4f} vs pdb {pdb_d * scale:.4f} "
                    f"(pdb {pdb_d:.2f} A x {scale})")
    assert not problems, (
        "world pivot points do not match the intended residues:\n  "
        + "\n  ".join(problems))


def render_coverage(tmp_path, resolution=96):
    """Pixels covered by geometry in a Cycles render (film_transparent alpha>0).

    Ground truth for 'is anything on screen' and, compared frame-to-frame, for
    'did the geometry move' - Blender's renderer, independent of any addon
    coordinate maths.
    """
    import bpy
    import numpy as np

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.device = "CPU"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    out = str(tmp_path / "cov.png")
    scene.render.filepath = out
    cam_data = bpy.data.cameras.new("cov_cam")
    cam = bpy.data.objects.new("cov_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0, -12, 0)
    cam.rotation_euler = (1.5707963, 0, 0)
    scene.camera = cam
    try:
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(out)
        try:
            px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
            return px[:, 3] > 0.01
        finally:
            bpy.data.images.remove(img)
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
