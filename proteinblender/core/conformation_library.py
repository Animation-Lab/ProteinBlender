"""Immutable coordinate sets owned by a protein, independent of scene time.

Coordinates use the protein's canonical mesh space (Blender units). State meshes
are ID references, so undo and .blend persistence do not depend on a Python cache
or the original downloaded file. The live mesh is only the displayed state.
"""
import re
import uuid
from pathlib import Path

import bpy
import numpy as np

from . import structural_alignment as alignment


def model_metadata(parsed):
    """Use experiment/provenance, never RMSD, to interpret model records."""
    file = getattr(parsed, 'file', None)
    lines = getattr(file, 'lines', None) if not hasattr(file, 'block') else None
    if lines is not None:
        method = ' '.join(line[10:].strip() for line in lines if line.startswith('EXPDTA'))
        numbers = [line[10:14].strip() for line in lines if line.startswith('MODEL ')]
    else:
        block = getattr(file, 'block', {})
        method = ('; '.join(block['exptl']['method'].as_array(str))
                  if 'exptl' in block else '')
        numbers = (list(dict.fromkeys(block['atom_site']['pdbx_PDB_model_num'].as_array(str)))
                   if 'atom_site' in block and 'pdbx_PDB_model_num' in block['atom_site'] else [])
    return method, numbers


def prepare_import(parsed, interpretation='AUTO', *, deposited=False):
    import biotite.structure as struc
    array = parsed.array
    count = array.stack_depth() if isinstance(array, struc.AtomArrayStack) else 1
    method, numbers = model_metadata(parsed)
    path = str(getattr(parsed, 'pb_import_path', '') or getattr(parsed, 'file_path', ''))
    if interpretation == 'AUTO' and count > 1:
        if re.search(r'\.pdb\d+(?:\.gz)?$', path, re.I):
            interpretation = 'ASSEMBLY'
        elif deposited or 'NMR' in method.upper():
            interpretation = 'CONFORMATIONS'
        else:
            raise ValueError('This file has multiple models with no ensemble provenance. '
                             'Choose Conformations or Assembly copies in the import options.')
    if interpretation == 'ASSEMBLY' and count > 1:
        # A legacy assembly file repeats chain labels in each MODEL. Distinct
        # labels keep the physical copies separate in domains and atom identity.
        copies = []
        for i, atoms in enumerate(array):
            atoms = atoms.copy()
            atoms.chain_id = np.asarray([f'{c}_{i + 1}' for c in atoms.chain_id])
            copies.append(atoms)
        parsed.array = struc.concatenate(copies)
        count, numbers = 1, ['1']
    parsed.pb_model_metadata = (method, numbers or ['1'], interpretation)
    return count


def states(molecule):
    return molecule.object.pb_conformations.states


def read_mesh(mesh):
    coords = np.empty((len(mesh.vertices), 3), dtype=np.float64)
    mesh.vertices.foreach_get('co', coords.ravel())
    return coords


def state(molecule, identifier):
    item = next((s for s in states(molecule) if s.uid == identifier), None)
    if item is None or item.mesh is None:
        raise ValueError('This conformation is no longer available.')
    if len(item.mesh.vertices) != len(molecule.object.data.vertices):
        raise ValueError('The atom topology has changed; reimport the protein to browse conformations.')
    return item


def add_coordinates(molecule, coordinates, name, source, model=''):
    coordinates = np.asarray(coordinates, dtype=float)
    if coordinates.shape != (len(molecule.object.data.vertices), 3) or not np.isfinite(coordinates).all():
        raise ValueError('A conformation must contain one finite position for every protein atom.')
    mesh = bpy.data.meshes.new(f'{molecule.identifier} · {name} coordinates')
    mesh.from_pydata(coordinates.tolist(), [], [])
    item = states(molecule).add()
    item.uid = uuid.uuid4().hex
    item.name, item.source, item.model, item.mesh = name, source, str(model), mesh
    return item


def initialize(molecule):
    """Adopt MN frames once, before domains copy its initial node tree."""
    library = molecule.object.pb_conformations
    if library.states:
        return
    parsed = molecule.molecule
    method, numbers, interpretation = getattr(parsed, 'pb_model_metadata', ('', ['1'], 'AUTO'))
    library.method = method
    library.interpretation = interpretation
    source = (Path(parsed.pb_import_path).name if getattr(parsed, 'pb_import_path', '')
              else molecule.identifier)
    frames_name = getattr(parsed, '_frames_collection', None)
    frames = bpy.data.collections.get(frames_name) if frames_name else None
    if frames and len(frames.objects) > 1:
        # MN frame object names use zero-based numeric suffixes, not file IDs.
        objects = sorted(frames.objects, key=lambda o: int(o.name.rsplit('_', 1)[-1].split('.')[0]))
        for i, obj in enumerate(objects):
            number = numbers[i] if i < len(numbers) else str(i + 1)
            add_coordinates(molecule, read_mesh(obj.data), f'Model {number}', source, number)
        # Bypass automatic timeline interpolation. The browser owns display;
        # explicitly created morphs continue to own their own animation curves.
        for mod in molecule.object.modifiers:
            if mod.type != 'NODES' or not mod.node_group:
                continue
            tree = mod.node_group
            for node in list(tree.nodes):
                if node.type == 'GROUP' and node.node_tree and node.node_tree.name == 'Animate Frames':
                    upstream = node.inputs[0].links[0].from_socket
                    for link in list(node.outputs[0].links):
                        tree.links.new(upstream, link.to_socket)
                    tree.nodes.remove(node)
                elif node.type == 'GROUP' and node.node_tree and node.node_tree.name == 'Animate Value':
                    tree.nodes.remove(node)
        parsed.frames = None
        for obj in list(frames.objects):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(frames)
    else:
        add_coordinates(molecule, read_mesh(molecule.object.data), 'Imported conformation', source, numbers[0])
    library['active_index'] = 0
    library.start_uid = library.states[0].uid
    library.end_uid = library.states[-1].uid
    library.reference_uid = library.states[0].uid


def compatible_coordinates(molecule, array):
    """Reorder by exact atom identity; never silently drop a ligand or residue."""
    import biotite.structure as struc
    array = array[~struc.filter_solvent(array)]
    first = alignment.read_identity(molecule)
    second = alignment.AtomIdentity.from_array(array)
    def keys(identity):
        return list(zip(identity.chain, identity.residue, identity.insertion,
                        identity.residue_name, identity.atom_name, identity.element))
    a, b = keys(first), keys(second)
    if len(set(a)) != len(a) or len(set(b)) != len(b):
        raise ValueError('Alternate or duplicate atom identities must be resolved before adding a conformation.')
    if set(a) != set(b):
        raise ValueError(f'Atom identities differ: {len(set(a) - set(b))} missing, '
                         f'{len(set(b) - set(a))} additional atoms. Import separately and use '
                         'Align & Morph for a partial match.')
    lookup = {key: i for i, key in enumerate(b)}
    return array.coord[[lookup[key] for key in a]] * alignment.SCALE


def add_file(molecule, filepath, interpretation='AUTO'):
    from ..utils.molecularnodes.entities import parse
    parsed = parse(filepath)
    prepare_import(parsed, interpretation)
    return append_parsed(molecule, parsed, Path(filepath).name)


def append_parsed(molecule, parsed, source):
    import biotite.structure as struc
    arrays = list(parsed.array) if isinstance(parsed.array, struc.AtomArrayStack) else [parsed.array]
    # Validate the entire batch before adding any data to the library.
    coordinates = [compatible_coordinates(molecule, arr) for arr in arrays]
    numbers = parsed.pb_model_metadata[1]
    for i, coords in enumerate(coordinates):
        number = numbers[i] if i < len(numbers) else str(i + 1)
        add_coordinates(molecule, coords, f'{source} · Model {number}', source, number)
    return len(coordinates)


def match(molecule, start_uid, end_uid, fit='CORE', fit_region='', **kwargs):
    if start_uid == end_uid:
        raise ValueError('Choose different start and end conformations.')
    a, b = state(molecule, start_uid), state(molecule, end_uid)
    result = alignment.match_structures(
        molecule, molecule, fit=fit, fit_region=fit_region,
        source_coordinates=read_mesh(a.mesh) / alignment.SCALE,
        target_coordinates=read_mesh(b.mesh) / alignment.SCALE, **kwargs)
    result.source_context = read_mesh(a.mesh)
    return result


def display_coordinates(molecule, uid):
    library = molecule.object.pb_conformations
    coords = read_mesh(state(molecule, uid).mesh)
    if library.fit == 'NONE' or uid == library.reference_uid:
        return coords
    # Fit to one immutable reference, not to whichever state was shown last.
    matched = match(molecule, library.reference_uid, uid, library.fit, library.fit_region)
    mobile = coords[matched.target_indices]
    rotation, translation = alignment.rigid_fit(matched.end, mobile)
    return coords @ rotation + translation


def refresh(molecule):
    library = molecule.object.pb_conformations
    if not library.states:
        return
    obj = molecule.object
    if obj.data.shape_keys:
        raise ValueError('This protein has shape keys. Browse a separate imported protein.')
    if any(d.object and d.object.data != obj.data for d in molecule.domains.values()):
        raise ValueError('Legacy domains use separate atom meshes. Reimport this protein to browse conformations.')
    coords = display_coordinates(molecule, library.states[library.active_index].uid)
    displayed = compensate_pose(molecule, coords, library.states[library.active_index])
    obj.data.vertices.foreach_set('co', displayed.ravel())
    obj.data.update()
    from . import conformation_comparison
    conformation_comparison.update(molecule, coords)
    bpy.context.view_layer.update()
    if bpy.context.screen:
        for area in bpy.context.screen.areas:
            area.tag_redraw()


def capture_pose(molecule, name):
    from .conformation_capture import coordinates
    from .domain_space import get_pivot
    bpy.context.view_layer.update()
    _, world = coordinates(molecule)
    try:
        inverse = np.asarray(molecule.object.matrix_world.inverted())
    except ValueError:
        raise ValueError('Restore the protein scale before capturing its pose.')
    coords = world @ inverse[:3, :3].T + inverse[:3, 3] + np.asarray(get_pivot(molecule.object))
    item = add_coordinates(molecule, coords, name, f'Captured pose · frame {bpy.context.scene.frame_current}')
    item.baked_pose = True
    return item


def compensate_pose(molecule, coords, item):
    """A captured pose already includes domain transforms; do not apply them twice."""
    if not item.baked_pose:
        return coords
    from .domain_space import get_pivot
    identity = alignment.read_identity(molecule)
    root = np.asarray(molecule.object.matrix_world)
    desired = (coords - np.asarray(get_pivot(molecule.object))) @ root[:3, :3].T + root[:3, 3]
    result = coords.copy()
    for domain in molecule.domains.values():
        if domain.object is None:
            continue
        if domain.is_copy:
            raise ValueError('Captured pose display requires a protein without duplicate chains/domains.')
        chain = molecule._resolve_chain_socket_name(domain.chain_id)
        mask = ((np.asarray(identity.chain) == chain) &
                (np.asarray(identity.residue) >= domain.start) &
                (np.asarray(identity.residue) <= domain.end))
        try:
            inverse = np.asarray(domain.object.matrix_world.inverted())
        except ValueError:
            raise ValueError('Restore the domain scale before displaying a captured pose.')
        result[mask] = desired[mask] @ inverse[:3, :3].T + inverse[:3, 3] + np.asarray(get_pivot(domain.object))
    return result


def clear(molecule):
    from .conformation_comparison import clear as clear_comparison
    clear_comparison(molecule)
    library = molecule.object.pb_conformations
    meshes = [s.mesh for s in library.states if s.mesh]
    library.states.clear()
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
