"""Ligands, ions and water stay out of chains and domains.

Reported on 4BV3 (SIRT3 with NAD and EX-527): the import showed chain A as
122-2124, "over 2000 residues" for a 270-residue protein. The file numbers the
protein 122-391, its ligands and ions 1392-1400 and its waters 2001-2124, all
in author chain A, and the chain range was taken over every residue in the
chain. The default domain inherited 122-2124, and splitting the chain dragged
every ligand into whichever domain covered the end.

Now a chain is its polymer residues only, domains only ever draw polymer atoms,
and the ligands and ions get objects of their own, listed under the protein.

Ground truth is read from the mmCIF text itself (``ATOM`` records are the
polymer, ``HETATM`` records the rest), never from the add-on's classifier.
"""

import gzip

import numpy as np
import pytest
import bpy

import helpers as H

FIXTURE = "4bv3.cif.gz"

# Hand-checked from the deposited entry: these residue names are the
# non-polymer, non-water residues of 4BV3.
LIGAND_NAMES = {"NAD", "APR", "OCZ", "GOL"}
ION_NAMES = {"ZN", "NA", "CL", "NO3"}


def _file_residues():
    """{group_PDB: {res_name: set(auth_seq_id)}} for author chain A."""
    with gzip.open(H.data_path(FIXTURE), "rt") as handle:
        lines = [line.split() for line in handle
                 if line.startswith(("ATOM ", "HETATM"))]
    out = {"ATOM": {}, "HETATM": {}}
    for fields in lines:
        # _atom_site column order in this file: group_PDB id type_symbol
        # label_atom_id label_alt_id label_comp_id label_asym_id
        # label_entity_id label_seq_id pdbx_PDB_ins_code Cartn_x Cartn_y
        # Cartn_z occupancy B_iso_or_equiv pdbx_formal_charge auth_seq_id
        # auth_comp_id auth_asym_id auth_atom_id pdbx_PDB_model_num
        group, res_name, res_id, chain = fields[0], fields[5], int(fields[16]), fields[18]
        if chain == "A":
            out[group].setdefault(res_name, set()).add(res_id)
    return out


def _polymer_res_ids():
    return set().union(*_file_residues()["ATOM"].values())


def _res_ids_of(names):
    het = _file_residues()["HETATM"]
    return set().union(*(het[n] for n in names))


def _drawn_res_ids(objects):
    """Residue ids Blender actually draws for *objects*, read off the evaluated
    geometry: Spheres draws a point cloud and Ball and Stick a mesh, and both
    carry each atom's res_id through to what is drawn."""
    names = {getattr(o, "name", o) for o in objects}
    bpy.context.view_layer.update()
    found = set()
    for instance in bpy.context.evaluated_depsgraph_get().object_instances:
        owner = (instance.parent.original if instance.is_instance
                 else instance.object.original)
        if owner.name not in names:
            continue
        data = instance.object.data
        if instance.object.type == "POINTCLOUD":
            count = len(data.points)
        elif instance.object.type == "MESH":
            count = len(data.vertices)
        else:
            continue
        attr = data.attributes.get("res_id")
        if attr is None or not count or attr.domain != "POINT":
            continue
        values = np.zeros(count, dtype=np.int32)
        data.attributes["res_id"].data.foreach_get("value", values)
        found.update(int(v) for v in values)
    return found


def _rows(scene, mid, item_type):
    return [it for it in scene.outliner_items
            if it.item_type == item_type and it.parent_id == mid]


@pytest.fixture
def sirt3(scene):
    mid = H.import_local(FIXTURE, "4bv3")
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    return mid


def _group_object(scene, mid, label):
    row = next(it for it in _rows(scene, mid, "HETERO") if it.name.startswith(label))
    return bpy.data.objects[row.object_name]


@pytest.mark.integration
def test_chain_range_is_its_amino_acids(scene, sm, sirt3):
    polymer = _polymer_res_ids()
    assert (min(polymer), max(polymer)) == (122, 391)   # sanity: the file

    chain = next(it for it in _rows(scene, sirt3, "CHAIN"))
    assert (chain.chain_start, chain.chain_end) == (122, 391)

    domains = list(sm.molecules[sirt3].domains.values())
    assert [(d.start, d.end) for d in domains] == [(122, 391)]


@pytest.mark.integration
def test_domains_draw_only_amino_acids(scene, sm, sirt3):
    molecule = sm.molecules[sirt3]
    drawn = _drawn_res_ids([d.object for d in molecule.domains.values()])
    assert drawn == _polymer_res_ids()
    # and the protein object itself no longer draws the leftovers
    assert _drawn_res_ids([molecule.object]) == set()


@pytest.mark.integration
def test_ligands_and_ions_are_children_of_the_protein(scene, sm, sirt3):
    rows = _rows(scene, sirt3, "HETERO")
    assert [r.name.split(" (")[0] for r in rows] == ["Ligands", "Ions"]

    protein = sm.molecules[sirt3].object
    ligands = _group_object(scene, sirt3, "Ligands")
    ions = _group_object(scene, sirt3, "Ions")
    assert ligands.parent == protein and ions.parent == protein

    assert _drawn_res_ids([ligands]) == _res_ids_of(LIGAND_NAMES)
    assert _drawn_res_ids([ions]) == _res_ids_of(ION_NAMES)


@pytest.mark.integration
def test_splitting_the_chain_leaves_ligands_alone(scene, sm, sirt3):
    assert H.split_domain_from_outliner(sirt3, "A", 122, 250) == {"FINISHED"}
    molecule = sm.molecules[sirt3]
    ranges = sorted((d.start, d.end) for d in molecule.domains.values())
    assert ranges == [(122, 250), (251, 391)]

    drawn = _drawn_res_ids([d.object for d in molecule.domains.values()])
    assert drawn == _polymer_res_ids()
    assert _drawn_res_ids([_group_object(scene, sirt3, "Ligands")]) == _res_ids_of(LIGAND_NAMES)


@pytest.mark.integration
def test_ligand_eye_hides_only_the_ligands(scene, sm, sirt3):
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    row = next(it for it in _rows(scene, sirt3, "HETERO") if it.name.startswith("Ligands"))
    ligands = bpy.data.objects[row.object_name]
    assert bpy.ops.proteinblender.toggle_visibility(item_id=row.item_id) == {"FINISHED"}
    assert ligands.hide_get()
    assert not sm.molecules[sirt3].object.hide_get()
    assert all(not d.object.hide_get() for d in sm.molecules[sirt3].domains.values())


@pytest.mark.integration
def test_delete_protein_removes_its_ligand_objects(scene, sm, sirt3):
    names = [it.object_name for it in _rows(scene, sirt3, "HETERO")]
    assert names
    assert bpy.ops.molecule.delete(molecule_id=sirt3) == {"FINISHED"}
    assert not any(bpy.data.objects.get(n) for n in names)


@pytest.mark.integration
def test_duplicate_protein_gets_its_own_ligands(scene, sm, sirt3):
    before = set(sm.molecules)
    assert bpy.ops.molecule.duplicate_protein(molecule_id=sirt3) == {"FINISHED"}
    (copy_id,) = set(sm.molecules) - before
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    rows = _rows(scene, copy_id, "HETERO")
    assert [r.name.split(" (")[0] for r in rows] == ["Ligands", "Ions"]
    copy_ligands = bpy.data.objects[rows[0].object_name]
    assert copy_ligands.parent == sm.molecules[copy_id].object
    assert _drawn_res_ids([copy_ligands]) == _res_ids_of(LIGAND_NAMES)


@pytest.mark.integration
def test_every_assembly_copy_carries_its_ions(scene, sm):
    """Insulin's hexamer is held together by zinc. When the ions rode inside
    the chain domains, every symmetry copy drew them; on an object of their
    own they must still be copied with the protein, not left on the original.

    4ins.pdb REMARK 350 BIOMOLECULE 3, read by eye: three transforms (identity
    plus two thirds of a three-fold) applied to chains A, B, C, D. Its HETATM
    records hold two ZN (chains B and D).
    """
    from proteinblender.core import assembly

    mid = H.import_local("4ins.pdb", "4ins")
    H.scene_manager_module().build_outliner_hierarchy(bpy.context)
    molecule = sm.molecules[mid]
    ions = _group_object(scene, mid, "Ions")
    assert assembly.build_assembly(molecule, "3")

    bpy.context.view_layer.update()
    placed = sum(1 for inst in bpy.context.evaluated_depsgraph_get().object_instances
                 if inst.is_instance and inst.parent is not None
                 and inst.parent.original.name == ions.name)
    assert placed == 3
