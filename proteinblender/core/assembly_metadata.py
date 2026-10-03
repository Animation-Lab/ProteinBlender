"""Depositor descriptions and mmCIF chain names, saved with the molecule."""
import json


def initialize(molecule):
    obj = molecule.object
    if 'pb_assembly_metadata' in obj:
        return
    file = getattr(molecule.molecule, 'file', None)
    descriptions, chains = {}, {}
    block = getattr(file, 'block', None)
    if block is not None:
        if 'pdbx_struct_assembly' in block:
            category = block['pdbx_struct_assembly']
            if 'details' in category:
                descriptions = dict(zip(category['id'].as_array(str), category['details'].as_array(str)))
        if 'atom_site' in block:
            atoms = block['atom_site']
            if 'label_asym_id' in atoms and 'auth_asym_id' in atoms:
                chains = dict(zip(atoms['label_asym_id'].as_array(str), atoms['auth_asym_id'].as_array(str)))
    elif getattr(file, 'lines', None) is not None:
        ids = []
        for line in file.lines:
            if not line.startswith('REMARK 350'):
                continue
            text = line[10:].strip()
            if text.startswith('BIOMOLECULE:'):
                ids = [v.strip() for v in text.split(':', 1)[1].split(',')]
            elif 'DETERMINED BIOLOGICAL UNIT:' in text:
                for aid in ids:
                    descriptions.setdefault(aid, text.split(':', 1)[1].strip().lower())
    obj['pb_assembly_metadata'] = json.dumps(dict(descriptions=descriptions, chains=chains))


def read(molecule):
    if molecule is None or molecule.object is None:
        return {}
    return json.loads(molecule.object.get('pb_assembly_metadata', '{}'))
