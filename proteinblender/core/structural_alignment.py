"""Sequence-guided superposition, with atom identity independent of residue numbering.

Coordinates are imported atom-mesh coordinates (0.01 Blender units / Angstrom),
not evaluated surfaces or domain poses. Pure numerical functions have no bpy
side effects; dialog analysis can therefore be cancelled without touching data.
"""
from dataclasses import dataclass
import json

import numpy as np

SCALE = .01
IDENTITY_KEY = 'pb_alignment_identity'
AA = dict(zip(
    'ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split(),
    'ARNDCQEGHILKMFPSTWYV'))
AA.update(MSE='M', SEC='C', PYL='K', HYP='P')
BACKBONE = {'N', 'CA', 'C', 'O', 'OXT'}


@dataclass
class AtomIdentity:
    chain: list
    residue: list
    insertion: list
    residue_name: list
    atom_name: list
    element: list

    @classmethod
    def from_array(cls, array):
        return cls(*[getattr(array, attr).tolist() for attr in
                     ('chain_id', 'res_id', 'ins_code', 'res_name', 'atom_name', 'element')])


def _imported_array(molecule):
    import biotite.structure as struc
    array = molecule.working_array
    # PB imports always request del_solvent=True. MN retains the unfiltered
    # AtomArray on its Python molecule, while its mesh contains the filtered one.
    if array is not None and len(array) != len(molecule.object.data.vertices):
        array = array[~struc.filter_solvent(array)]
    return array


def store_identity(molecule):
    """Preserve exact identifiers, including insertion codes, across file loads."""
    array = _imported_array(molecule)
    if array is not None and len(array) == len(molecule.object.data.vertices):
        molecule.object.data[IDENTITY_KEY] = json.dumps(
            AtomIdentity.from_array(array).__dict__, separators=(',', ':'))


def read_identity(molecule):
    obj = molecule.object
    saved = obj.data.get(IDENTITY_KEY)
    if saved:
        identity = AtomIdentity(**json.loads(saved))
    else:
        # Existing unsaved scenes predate identity persistence. Their original
        # AtomArray is still complete. A reconstructed minimal wrapper isn't.
        array = _imported_array(molecule)
        if array is None or not np.any(np.asarray(array.atom_name) == 'CA'):
            raise ValueError('Re-import this structure to recover its atom identities.')
        identity = AtomIdentity.from_array(array)
    if any(len(values) != len(obj.data.vertices) for values in identity.__dict__.values()):
        raise ValueError('Atom data has changed. Re-import the structure before aligning.')
    return identity


def positions(obj):
    result = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get('co', result)
    return result.reshape(-1, 3) / SCALE


def protein_chains(identity):
    """Ordered residues with a genuine amino-acid CA, excluding ions/ligands."""
    residues = {}
    for i, (chain, res, ins, name, atom, element) in enumerate(zip(
            identity.chain, identity.residue, identity.insertion,
            identity.residue_name, identity.atom_name, identity.element)):
        if name not in AA:
            continue
        key = (chain, res, ins)
        residue = residues.setdefault(key, {'key': key, 'name': name, 'atoms': {}})
        if atom in residue['atoms']:
            raise ValueError('Multiple alternate atoms remain. Import one alternate location.')
        residue['atoms'][atom] = i
        if atom == 'CA' and element.upper() == 'C':
            residue['ca'] = i
    chains = {}
    for residue in residues.values():
        if 'ca' in residue:
            chains.setdefault(residue['key'][0], []).append(residue)
    if not chains:
        raise ValueError('No protein alpha carbons found. Choose a protein structure.')
    return chains


def sequence_pair(first, second):
    from biotite.sequence import ProteinSequence
    from biotite.sequence.align import SubstitutionMatrix, align_optimal
    a = ''.join(AA[r['name']] for r in first)
    b = ''.join(AA[r['name']] for r in second)
    if a == b:
        return np.column_stack((np.arange(len(a)), np.arange(len(b)))), 1.0
    # Bound quadratic memory in a popup; large structures can use one chain.
    if len(a) * len(b) > 16_000_000:
        raise ValueError('These chains are too long for interactive matching. Use shorter chains.')
    alignment = align_optimal(ProteinSequence(a), ProteinSequence(b),
                             SubstitutionMatrix.std_protein_matrix(),
                             gap_penalty=(-10, -1), terminal_penalty=False,
                             max_number=1)[0]
    pairs = alignment.trace[np.all(alignment.trace >= 0, axis=1)]
    identity = sum(a[i] == b[j] for i, j in pairs) / max(1, len(pairs))
    return pairs, identity


def rigid_fit(fixed, mobile):
    """Proper Kabsch rotation; never reflects or scales a molecular structure."""
    fixed, mobile = np.asarray(fixed), np.asarray(mobile)
    if len(fixed) < 3 or min(np.linalg.matrix_rank(x - x.mean(0), tol=1e-6)
                             for x in (fixed, mobile)) < 2:
        raise ValueError('At least three non-collinear matched alpha carbons are needed.')
    f, m = fixed.mean(0), mobile.mean(0)
    u, _, vt = np.linalg.svd((mobile - m).T @ (fixed - f))
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    return rotation, f - m @ rotation


@dataclass
class Match:
    source_indices: np.ndarray
    target_indices: np.ndarray
    start: np.ndarray
    end: np.ndarray
    summary: dict


def match_structures(source, target, source_chain='ALL', target_chain='ALL', fit='CORE'):
    if source.object == target.object:
        raise ValueError('Choose two different structures.')
    a, b = read_identity(source), read_identity(target)
    ac, bc = protein_chains(a), protein_chains(b)
    if (source_chain == 'ALL') != (target_chain == 'ALL'):
        raise ValueError('Choose Whole protein for both structures, or select two chains.')
    if source_chain != 'ALL':
        if source_chain not in ac or target_chain not in bc:
            raise ValueError('The selected chain is no longer available.')
        assignments = [(source_chain, target_chain)]
        cache = {}
    else:
        from scipy.optimize import linear_sum_assignment
        cache, names_a, names_b = {}, list(ac), list(bc)
        if len(names_a) * len(names_b) > 1024:
            raise ValueError('Choose a specific chain pair for this large assembly.')
        scores = np.zeros((len(ac), len(bc)))
        for i, ca in enumerate(names_a):
            for j, cb in enumerate(names_b):
                pairs, identity = sequence_pair(ac[ca], bc[cb])
                cache[ca, cb] = pairs, identity
                # Names only break sequence-equivalent ties. They never override
                # a better sequence match (author chain labels need not agree).
                scores[i, j] = identity * len(pairs) + (1e-6 if ca == cb else 0)
        ii, jj = linear_sum_assignment(-scores)
        assignments = [(names_a[i], names_b[j]) for i, j in zip(ii, jj)]

    atoms_a, atoms_b, cas_a, cas_b, mapping, residues = [], [], [], [], [], []
    matches, identical = 0, 0
    for ca, cb in assignments:
        pairs, identity = cache.get((ca, cb), (None, None))
        if pairs is None:
            pairs, identity = sequence_pair(ac[ca], bc[cb])
        if len(pairs) < 3 or identity < .3:
            continue
        mapping.append(f'{ca or "(blank)"} → {cb or "(blank)"}')
        for i, j in pairs:
            ra, rb = ac[ca][i], bc[cb][j]
            cas_a.append(ra['ca'])
            cas_b.append(rb['ca'])
            matches += 1
            identical += AA[ra['name']] == AA[rb['name']]
            residues.append([list(ra['key']), list(rb['key'])])
            same = ra['name'] == rb['name']
            for atom, ia in ra['atoms'].items():
                ib = rb['atoms'].get(atom)
                if ib is not None and (same or atom in BACKBONE) and a.element[ia] == b.element[ib]:
                    atoms_a.append(ia)
                    atoms_b.append(ib)
    if matches < 3:
        raise ValueError('No suitable protein match (at least 3 residues and 30% sequence identity).')
    if source_chain == 'ALL' and len(mapping) != len(assignments):
        raise ValueError('Some chains do not match. Choose a specific chain pair.')
    p, q = positions(source.object), positions(target.object)
    if not np.isfinite(p).all() or not np.isfinite(q).all():
        raise ValueError('The structure contains invalid atom coordinates.')
    fixed, mobile = p[cas_a], q[cas_b]
    selected = np.arange(matches)
    minimum = max(3, int(np.ceil(matches / 2)))
    for _ in range(30 if fit == 'CORE' else 1):
        rotation, translation = rigid_fit(fixed[selected], mobile[selected])
        distances = np.linalg.norm(mobile @ rotation + translation - fixed, axis=1)
        if fit != 'CORE' or distances[selected].max() <= 2 or len(selected) <= minimum:
            break
        remove = max(1, min(int(np.ceil(len(selected) * .1)),
                            int(np.ceil(np.sum(distances[selected] > 2) * .5))))
        remove = min(remove, len(selected) - minimum)
        selected = selected[np.argsort(distances[selected])[:-remove]]
    # Refit after the last pruning pass, too.
    rotation, translation = rigid_fit(fixed[selected], mobile[selected])
    distances = np.linalg.norm(mobile @ rotation + translation - fixed, axis=1)
    order = np.argsort(atoms_a)
    ia, ib = np.asarray(atoms_a)[order], np.asarray(atoms_b)[order]
    total_a = sum(map(len, ac.values())) if source_chain == 'ALL' else len(ac[source_chain])
    total_b = sum(map(len, bc.values())) if target_chain == 'ALL' else len(bc[target_chain])
    summary = dict(mapping=mapping, residues=matches, fit_residues=len(selected),
                   identity=identical / matches, source_residues=total_a,
                   target_residues=total_b, atoms=len(ia),
                   rmsd=float(np.sqrt(np.mean(distances ** 2))),
                   fit_rmsd=float(np.sqrt(np.mean(distances[selected] ** 2))),
                   residue_pairs=residues, fit=fit,
                   omitted_atoms=[len(p) - len(ia), len(q) - len(ib)])
    return Match(ia, ib, p[ia] * SCALE, (q[ib] @ rotation + translation) * SCALE, summary)
