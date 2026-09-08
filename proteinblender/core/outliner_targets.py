"""Stable protein, chain and domain targets shared by scene builders."""

from types import SimpleNamespace


def resolve_target(item_id, *, include_protein_domains=False):
    """Return (molecule, objects) without depending on expanded UI rows."""
    from ..utils.scene_manager import ProteinBlenderScene
    from ..utils.chain_utils import get_chain_objects

    for mid, molecule in ProteinBlenderScene.get_instance().molecules.items():
        if item_id == mid:
            objects = [molecule.object] if molecule.object else []
            if include_protein_domains:
                objects.extend(d.object for d in molecule.domains.values() if d.object)
            return molecule, objects
        if item_id.startswith(f"{mid}_chain_"):
            token = item_id[len(f"{mid}_chain_"):]
            row = SimpleNamespace(item_id=item_id, chain_id=token,
                                  parent_id=mid, item_type='CHAIN')
            return molecule, get_chain_objects(molecule, row)
        domain = molecule.domains.get(item_id)
        if domain is not None:
            # A copied chain is keyed by its primary domain, too.
            row = SimpleNamespace(item_id=item_id, chain_id=str(domain.chain_id),
                                  parent_id=mid, item_type='CHAIN')
            if getattr(domain, 'is_copy', False):
                return molecule, get_chain_objects(molecule, row)
            return molecule, [domain.object] if domain.object else []
    return None, []


def target_rows(scene):
    """Picker rows, with no puppet references or non-protein builders."""
    from ..utils.scene_manager import ProteinBlenderScene
    molecules = ProteinBlenderScene.get_instance().molecules
    for row in scene.outliner_items:
        if row.item_type not in {'PROTEIN', 'CHAIN', 'DOMAIN'}:
            continue
        molecule, objects = resolve_target(row.item_id)
        if (molecule is None or not objects or molecule.identifier not in molecules
                or molecule.object.get('pb_is_nucleic_acid', False)):
            continue
        yield row
