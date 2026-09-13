"""Capture canonical atom identities with the current native domain poses."""
import tempfile
import uuid
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

from . import structural_alignment as alignment
from .domain_space import get_pivot


def coordinates(molecule):
    identity = alignment.read_identity(molecule)
    original = alignment.positions(molecule.object) * alignment.SCALE
    depsgraph = bpy.context.evaluated_depsgraph_get()

    def world(obj, points):
        matrix = np.asarray(obj.evaluated_get(depsgraph).matrix_world)
        return (points - np.asarray(get_pivot(obj))) @ matrix[:3, :3].T + matrix[:3, 3]

    result = world(molecule.object, original)
    assigned = np.zeros(len(original), dtype=bool)
    for domain in molecule.domains.values():
        obj = domain.object
        if obj is None:
            continue
        if domain.is_copy:
            raise ValueError('Capture a protein without duplicate chains/domains; copies have ambiguous atom identities.')
        if (obj.data != molecule.object.data or obj.data.shape_keys or
                any(m.type != 'NODES' for m in obj.modifiers)):
            raise ValueError('Capture supports native chain/domain poses. Bake other deformations into an imported conformation first.')
        chain = molecule._resolve_chain_socket_name(domain.chain_id)
        mask = ((np.asarray(identity.chain) == chain) &
                (np.asarray(identity.residue) >= domain.start) &
                (np.asarray(identity.residue) <= domain.end))
        if np.any(assigned & mask):
            raise ValueError('Overlapping domains cannot define a unique captured atom position.')
        result[mask] = world(obj, original[mask])
        assigned |= mask
    if not np.isfinite(result).all():
        raise ValueError('The pose contains invalid atom coordinates.')
    return identity, result


def capture(context, molecule, name):
    import biotite.structure as struc
    from biotite.structure.io import pdbx
    from ..utils.scene_manager import ProteinBlenderScene

    context.view_layer.update()
    identity, positions = coordinates(molecule)
    atoms = struc.AtomArray(len(positions))
    for attr, values in (('chain_id', identity.chain), ('res_id', identity.residue),
                         ('ins_code', identity.insertion), ('res_name', identity.residue_name),
                         ('atom_name', identity.atom_name), ('element', identity.element)):
        setattr(atoms, attr, np.asarray(values))
    atoms.coord = positions / alignment.SCALE
    atoms.hetero = np.asarray([res not in alignment.AA for res in identity.residue_name])
    atoms.set_annotation('occupancy', np.ones(len(atoms)))
    atoms.set_annotation('b_factor', np.zeros(len(atoms)))
    manager = ProteinBlenderScene.get_instance()
    identifier = name if name not in manager.molecules else f'{name}_{uuid.uuid4().hex[:6]}'
    structure = pdbx.CIFFile()
    pdbx.set_structure(structure, atoms)
    chains = list(dict.fromkeys(identity.chain))
    protein_chains = [chain for chain in chains if any(
        c == chain and residue in alignment.AA
        for c, residue in zip(identity.chain, identity.residue_name))]
    structure.block['entity_poly'] = pdbx.CIFCategory({
        'entity_id': [str(chains.index(chain) + 1) for chain in protein_chains],
        'type': ['polypeptide(L)'] * len(protein_chains),
        'pdbx_strand_id': protein_chains,
    })
    structure.block['entity'] = pdbx.CIFCategory({
        'id': [str(i + 1) for i in range(len(chains))],
        'type': ['polymer' if chain in protein_chains else 'non-polymer' for chain in chains],
        'pdbx_description': [f'Captured chain {chain}' for chain in chains],
    })
    with tempfile.TemporaryDirectory(prefix='pb-conformation-') as directory:
        path = Path(directory) / 'captured.cif'
        structure.write(str(path))
        result = bpy.ops.molecule.import_local(filepath=str(path), identifier_override=identifier)
    if result != {'FINISHED'}:
        raise ValueError('Could not import the captured conformation.')
    captured = ProteinBlenderScene.get_instance().molecules[identifier]
    # Preserve the imported secondary-structure annotation for the authored
    # state rather than presenting all residues as coils after CIF import.
    source_sec = molecule.object.data.attributes.get('sec_struct')
    target_sec = captured.object.data.attributes.get('sec_struct')
    if source_sec and target_sec:
        captured_identity = alignment.read_identity(captured)
        source_keys = list(zip(identity.chain, identity.residue, identity.insertion, identity.atom_name))
        target_keys = list(zip(captured_identity.chain, captured_identity.residue,
                               captured_identity.insertion, captured_identity.atom_name))
        lookup = {key: i for i, key in enumerate(source_keys)}
        values = np.array([source_sec.data[lookup[key]].value for key in target_keys], dtype=np.int32)
        target_sec.data.foreach_set('value', values)
        captured.object.data.update()
    # Import centers a structure at the origin. Restore its captured world
    # placement by putting the imported canonical pivot back into world space.
    captured.object.matrix_world = Matrix.Translation(get_pivot(captured.object))
    captured.object['pb_captured_conformation'] = True
    captured.object['pb_capture_source'] = getattr(molecule, 'name', molecule.identifier)
    captured.object['pb_capture_frame'] = context.scene.frame_current
    from .conformation import rebuild_outliner
    captured.object['pb_conformation_name'] = name
    rebuild_outliner(context)
    return captured
