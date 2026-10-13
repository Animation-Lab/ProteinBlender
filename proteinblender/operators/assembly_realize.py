"""Turning an assembly's instanced copies into things the PB Outliner lists.

An instance is one set of atoms drawn many times: nothing to click, nothing to
colour differently. Realizing trades that for per-copy identity - and identity
in ProteinBlender means a row in the PB Outliner, because that is where a copy
is selected, coloured, hidden and deleted. So a realized copy is never a bare
Blender object if it can be helped:

* an assembly that repeats the whole protein becomes that many proteins;
* one that repeats some of its chains or domains becomes chain and domain
  copies inside the protein, as the chain row's Copy button makes them;
* only atoms that no chain or domain row stands for - a protein whose domains
  have been deleted - still come out as plain objects.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from ..core import assembly as assembly_core

logger = logging.getLogger(__name__)


@dataclass
class Realized:
    """What a realization made."""

    proteins: list = field(default_factory=list)   # molecule ids
    domains: list = field(default_factory=list)    # domain ids
    objects: list = field(default_factory=list)    # plain objects
    copies: int = 0                                # rows, however many pieces each
    #: Set once the assembly has been taken down. A realization can make
    #: nothing new and still have happened: one copy, drawn away from its
    #: original, is realized by moving the original there.
    done: bool = False

    def __bool__(self):
        return self.done


def realize_assembly(context, molecule, force: bool = False):
    """Replace the built assembly with real copies of what it drew.

    Returns a :class:`Realized` - false, with the assembly left alone, when
    there is nothing but the original to realize - or ``None`` when an object
    is drawn more than :data:`assembly_core.REALIZE_THRESHOLD` times and
    ``force`` was not set.
    """
    jobs = assembly_core.copy_placements(molecule)
    result = Realized()
    if not jobs:
        return result

    # Everything read off the assembly is read before it is taken down.
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    world = {obj.name: obj.evaluated_get(depsgraph).matrix_world.copy()
             for obj in _objects_of(molecule)}
    drawn = {obj.name: _moves(placements, world[obj.name])
             for obj, _, placements in jobs}
    groups = {obj.name: group for obj, group, _ in jobs}

    if not any(_split(moves)[0] for moves in drawn.values()):
        return result
    if (max(len(moves) for moves in drawn.values())
            > assembly_core.REALIZE_THRESHOLD and not force):
        return None

    own_atoms = _draws_atoms(depsgraph, molecule.object)
    whole = _moves_of_the_whole_protein(molecule, drawn, own_atoms)

    # First, so that a copied protein does not inherit the assembly and draw
    # every copy over again.
    assembly_core.clear_assembly(molecule)
    result.done = True

    if whole is not None:
        _realize_as_proteins(context, molecule, whole, world, result)
    else:
        _realize_within_the_protein(context, molecule, drawn, groups, world,
                                    own_atoms, result)

    _retire_what_followed_the_assembly(context, molecule)
    return result


# ---------------------------------------------------------------------------
# What the assembly drew
# ---------------------------------------------------------------------------

@dataclass
class Move:
    """One copy of one object, as the move that copy makes in the scene.

    A placement is stored in its object's own frame, about that object's own
    pivot, so the same copy reads differently on every chain it draws. In the
    scene it is one move - the form two objects can be compared in, and the
    one that carries any of them to where the copy stood.
    """

    matrix: object                 # mathutils.Matrix, applied before the world matrix
    chain: object = None           # set where only one chain of the object is drawn
    original: bool = False         # the copy that is the original, where it already is


def _moves(placements, world):
    inverse = world.inverted()
    return [Move(world @ assembly_core.placement_matrix(rotation, offset) @ inverse,
                 chain,
                 chain is None and assembly_core.is_identity_placement(rotation, offset))
            for rotation, offset, chain in placements]


def _same_moves(first, second) -> bool:
    return (len(first) == len(second)
            and all(np.allclose(np.array(a.matrix), np.array(b.matrix), atol=1e-4)
                    for a, b in zip(first, second)))


def _split(moves):
    """(the moves that need a copy made, whether the original is drawn in place)."""
    extras, kept = [], False
    for move in moves:
        if move.original and not kept:
            kept = True
        else:
            extras.append(move)
    return extras, kept


def _objects_of(molecule):
    objects = [molecule.object] if molecule.object is not None else []
    objects.extend(d.object for d in molecule.domains.values() if d.object is not None)
    return objects


def _draws_atoms(depsgraph, obj) -> bool:
    """Whether anything is drawn through this object at all.

    A protein object draws only the atoms no chain or domain covers, which in
    a normal import is none of them.
    """
    if obj is None:
        return False
    for instance in depsgraph.object_instances:
        owner = instance.parent if instance.parent is not None else instance.object
        if owner.original.name != obj.name:
            continue
        # A point cloud or a mesh, depending on the style it is drawn in.
        data = instance.object.data
        if len(getattr(data, "points", ())) or len(getattr(data, "vertices", ())):
            return True
    return False


def _moves_of_the_whole_protein(molecule, drawn, own_atoms):
    """The moves, if every one of them draws the whole protein. Otherwise None."""
    if any(move.chain is not None for moves in drawn.values() for move in moves):
        return None

    names = [d.object.name for d in molecule.domains.values() if d.object is not None]
    protein = molecule.object.name if molecule.object is not None else None
    if protein is not None and (protein in drawn or own_atoms):
        names.append(protein)
    if not names or any(name not in drawn for name in names):
        return None

    moves = drawn[names[0]]
    if any(not _same_moves(moves, drawn[name]) for name in names[1:]):
        return None
    return moves


# ---------------------------------------------------------------------------
# Whole proteins
# ---------------------------------------------------------------------------

def _stand(context, source, target, mapping, world, move) -> None:
    """Put ``target`` where ``source`` was drawn under ``move``."""
    target.object.matrix_world = move.matrix @ world[source.object.name]
    # Children are placed against their parent's matrix, which has just moved.
    context.view_layer.update()
    for source_id, target_id in mapping.items():
        before = source.domains[source_id].object
        after = target.domains[target_id].object
        if before is None or after is None:
            continue
        after.matrix_world = move.matrix @ world[before.name]
    context.view_layer.update()


def _realize_as_proteins(context, molecule, moves, world, result) -> None:
    from .molecule_operators import duplicate_molecule

    extras, kept = _split(moves)
    # With the original cut away there is no copy for it to stay as, so it
    # becomes the first of the ones that are left rather than a hidden extra.
    first = None if kept else extras.pop(0)

    for move in extras:
        copy, mapping = duplicate_molecule(context, molecule)
        # A copy stays where its instance was drawn. Left with its source's
        # animation it would be carried back onto the source at the next frame.
        copy.object.animation_data_clear()
        _stand(context, molecule, copy, mapping, world, move)
        result.proteins.append(copy.identifier)
        result.copies += 1

    if first is not None:
        _stand(context, molecule, molecule, {i: i for i in molecule.domains}, world, first)


# ---------------------------------------------------------------------------
# Some of a protein
# ---------------------------------------------------------------------------

def _hide(obj) -> None:
    obj.hide_render = True
    obj.hide_set(True)


def _settle_originals(objects, moves, world):
    """Deal with originals the assembly did not draw in place.

    Drawn only elsewhere, an original moves to the first of those places;
    not drawn at all, it is hidden, as the assembly had it. Returns the moves
    that still need a copy made.
    """
    extras, kept = _split(moves)
    if kept:
        return extras
    if not extras:
        for obj in objects:
            _hide(obj)
        return extras
    for obj in objects:
        obj.matrix_world = extras[0].matrix @ world[obj.name]
    return extras[1:]


def _realize_within_the_protein(context, molecule, drawn, groups, world,
                                own_atoms, result) -> None:
    reached = {domain_id: drawn[domain.object.name]
               for domain_id, domain in molecule.domains.items()
               if domain.object is not None and domain.object.name in drawn}

    # A chain whose every piece was drawn alike is copied as a chain, so each
    # copy is one chain row however many domains the chain is split into.
    done = set()
    for domain_id in list(reached):
        domain = molecule.domains[domain_id]
        if domain_id in done or getattr(domain, "is_copy", False):
            continue
        pieces = molecule.chain_copy_sources(str(domain.chain_id))
        piece_ids = [piece_id for piece_id, _ in pieces]
        if (domain_id not in piece_ids
                or any(piece_id not in reached for piece_id in piece_ids)
                or any(not _same_moves(reached[domain_id], reached[piece_id])
                       for piece_id in piece_ids)):
            continue
        done.update(piece_ids)
        originals = [piece.object for _, piece in pieces]
        for move in _settle_originals(originals, reached[domain_id], world):
            new_ids = molecule.copy_chain(str(domain.chain_id))
            if len(new_ids) != len(originals):
                logger.warning("could not copy chain %s for a realized copy",
                               domain.chain_id)
                continue
            for original, new_id in zip(originals, new_ids):
                molecule.domains[new_id].object.matrix_world = (
                    move.matrix @ world[original.name])
            result.domains.extend(new_ids)
            result.copies += 1

    for domain_id, moves in reached.items():
        if domain_id in done:
            continue
        original = molecule.domains[domain_id].object
        for move in _settle_originals([original], moves, world):
            new_id = molecule.copy_domain(domain_id)
            if not new_id:
                logger.warning("could not copy domain %s for a realized copy",
                               domain_id)
                continue
            molecule.domains[new_id].object.matrix_world = move.matrix @ world[original.name]
            result.domains.append(new_id)
            result.copies += 1

    # Atoms the protein draws itself have no row to copy.
    protein = molecule.object
    if own_atoms and protein is not None and protein.name in drawn:
        extras, kept = _split(drawn[protein.name])
        for index, move in enumerate(extras):
            result.objects.append(assembly_core.realize_object_copy(
                protein, groups[protein.name], move.matrix @ world[protein.name],
                index, move.chain))
            result.copies += 1
        if not kept:
            _hide(protein)

    context.view_layer.update()


# ---------------------------------------------------------------------------
# Afterwards
# ---------------------------------------------------------------------------

def _retire_what_followed_the_assembly(context, molecule) -> None:
    """A bend rig and symmetry axes belong to an assembly that is now gone."""
    from ..core import symmetry_axes, symmetry_bend
    from ..utils.scene_manager import build_outliner_hierarchy

    if symmetry_bend.has_bend(molecule):
        symmetry_bend.remove_bend(molecule)
    symmetry_axes.clear_symmetry_axes(molecule)
    build_outliner_hierarchy(context)
