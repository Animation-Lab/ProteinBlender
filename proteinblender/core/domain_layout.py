"""Declarative domain layouts for a single chain.

A *layout* is the complete, ordered list of domains a chain should be split
into. The Domain Splitter dialog edits a layout and hands it here; this module
reconciles it against what the chain currently has.

Why reconcile instead of rebuild
--------------------------------
A domain's id embeds its residue range (`MoleculeWrapper._create_domain_with_params`)
and its Blender object name embeds the range too (`DomainDefinition`). Meanwhile
almost everything downstream keys off one of those two strings:

  * puppet membership          -> domain id   (`ProteinOutlinerItem.puppet_memberships`)
  * linker endpoints           -> domain id   (`linkers/linker_props.py`)
  * saved per-molecule poses   -> domain id   (`properties/molecule_props.py`)
  * the scene pose library     -> object name (`properties/pose_props.py`)
  * pose/colour keyframes      -> the object itself
  * the pivot                  -> the object's DomainNodes modifier
  * outliner selection/expand  -> domain id

So the obvious implementation - delete the chain's domains and build the new
set - silently destroys all of it. Reconciling means a domain the user did not
touch is never deleted, and one whose range they nudged is mutated in place, so
its id and object survive and every reference above keeps resolving.

Only domains that genuinely disappear from the layout are deleted, and those go
through the full cleanup path (puppet membership strip, linker prune).
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import bpy

from ..utils.chain_utils import (
    chain_match_tokens,
    normalize_domain_residue_range,
)


class DomainSpec(NamedTuple):
    """One row of a desired layout.

    ``domain_id`` is the *existing* domain this row corresponds to, or None for
    a row the user added. Carrying it is what makes reconciliation possible:
    it is the only way to tell "domain X moved to 20-60" apart from "domain X
    was deleted and a new 20-60 domain appeared".
    """
    name: str
    start: int
    end: int
    domain_id: Optional[str] = None


class ApplyResult(NamedTuple):
    updated: List[str]
    created: List[str]
    deleted: List[str]
    errors: List[str]


# ---------------------------------------------------------------------------
# Reading the current state
# ---------------------------------------------------------------------------

def chain_residue_range(molecule: Any, chain_token: Any) -> Tuple[int, int]:
    """Return the (min, max) author residue numbers valid for a chain.

    Resolves through the molecule's own chain maps so it works whether the
    caller holds a chain index ("2") or an author letter ("D"), and applies the
    same one-based normalisation the rest of the domain UI uses.
    """
    tokens = chain_match_tokens(molecule, chain_token)
    ranges = getattr(molecule, "chain_residue_ranges", {}) or {}
    for token in tokens:
        if token in ranges:
            return normalize_domain_residue_range(ranges[token])

    # Fall back to the span the chain's existing domains cover rather than
    # inventing a number: a wrong hard-coded ceiling silently truncates every
    # range the user types.
    domains = current_layout(molecule, chain_token)
    if domains:
        return (min(d.start for d in domains), max(d.end for d in domains))
    return (1, 1)


def current_layout(molecule: Any, chain_token: Any) -> List[DomainSpec]:
    """Return the chain's existing domains as a layout, ordered by start residue."""
    if molecule is None:
        return []
    tokens = chain_match_tokens(molecule, chain_token)
    specs = []
    for domain_id, domain in molecule.domains.items():
        if getattr(domain, "is_copy", False):
            continue
        if str(getattr(domain, "chain_id", "")) not in tokens:
            continue
        specs.append(DomainSpec(name=domain.name, start=int(domain.start),
                                end=int(domain.end), domain_id=domain_id))
    specs.sort(key=lambda s: (s.start, s.end))
    return specs


def even_split(chain_min: int, chain_max: int, count: int) -> List[Tuple[int, int]]:
    """Divide [chain_min, chain_max] into ``count`` contiguous, gapless ranges.

    The remainder is spread one residue at a time across the leading ranges, so
    the pieces differ by at most one residue and together cover the chain
    exactly - no gaps, no overlaps, whatever the chain length.
    """
    count = max(1, int(count))
    total = chain_max - chain_min + 1
    if total <= 0:
        return [(chain_min, chain_max)]
    count = min(count, total)

    base, remainder = divmod(total, count)
    ranges = []
    cursor = chain_min
    for i in range(count):
        size = base + (1 if i < remainder else 0)
        ranges.append((cursor, cursor + size - 1))
        cursor += size
    return ranges


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_layout(specs: List[DomainSpec], chain_min: int,
                    chain_max: int) -> List[str]:
    """Return human-readable problems with a layout; empty means it is valid.

    Checked independently of any domain code so it also catches a bad layout
    that came from somewhere other than the dialog.
    """
    errors: List[str] = []
    if not specs:
        errors.append("A chain needs at least one domain")
        return errors

    for i, spec in enumerate(specs, start=1):
        label = spec.name or f"Domain {i}"
        if spec.start > spec.end:
            errors.append(f"{label}: start {spec.start} is after end {spec.end}")
        if spec.start < chain_min or spec.end > chain_max:
            errors.append(
                f"{label}: {spec.start}-{spec.end} is outside the chain's "
                f"{chain_min}-{chain_max}")

    ordered = sorted(specs, key=lambda s: (s.start, s.end))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start <= prev.end:
            errors.append(
                f"'{prev.name}' ({prev.start}-{prev.end}) overlaps "
                f"'{nxt.name}' ({nxt.start}-{nxt.end})")

    names = [s.name.strip() for s in specs]
    duplicates = {n for n in names if n and names.count(n) > 1}
    for name in sorted(duplicates):
        errors.append(f"Two domains are both named '{name}'")

    return errors


def coverage_gaps(specs: List[DomainSpec], chain_min: int,
                  chain_max: int) -> List[Tuple[int, int]]:
    """Return the residue spans of the chain no domain covers.

    Gaps are legal - a user may deliberately leave a stretch out - so this is
    reported as information rather than as a validation error.
    """
    ordered = sorted(specs, key=lambda s: (s.start, s.end))
    gaps = []
    cursor = chain_min
    for spec in ordered:
        if spec.start > cursor:
            gaps.append((cursor, spec.start - 1))
        cursor = max(cursor, spec.end + 1)
    if cursor <= chain_max:
        gaps.append((cursor, chain_max))
    return gaps


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def _is_identity(matrix, tolerance: float = 1e-6) -> bool:
    from mathutils import Matrix
    identity = Matrix.Identity(4)
    return all(abs(matrix[r][c] - identity[r][c]) <= tolerance
               for r in range(4) for c in range(4))


def _capture_pose(domain) -> Optional[Tuple[Any, Any]]:
    """Snapshot how a domain maps mesh coordinates into the world.

    Returns (matrix_world, pivot). A domain renders an atom at
    ``matrix_world @ (co - pivot)``, so both halves are needed to reproduce its
    pose on a replacement object.
    """
    obj = getattr(domain, "object", None)
    if obj is None:
        return None
    from . import domain_space
    try:
        return (obj.matrix_world.copy(), domain_space.get_pivot(obj))
    except (ReferenceError, AttributeError):
        return None


def _read_style(domain) -> Optional[str]:
    """Best-effort read of a domain's current visual style.

    The `style` attribute goes stale when the style was changed through the
    Visual Setup panel, which rewrites the geometry nodes directly, so fall
    back to reading the node graph.
    """
    obj = getattr(domain, "object", None)
    if obj is not None:
        try:
            from ..panels.visual_setup_panel import get_object_style
            actual = get_object_style(obj)
            if actual:
                return actual
        except Exception:
            pass
    return getattr(domain, "style", None)


def _puppets_containing(scene, member_ids: set) -> List[Any]:
    """Puppet rows whose membership includes any of ``member_ids``."""
    found = []
    for item in scene.outliner_items:
        if item.item_type != 'PUPPET' or not item.puppet_memberships:
            continue
        members = set(item.puppet_memberships.split(','))
        if members & member_ids:
            found.append(item)
    return found


def _strip_from_puppets(scene, dead_ids: set):
    """Remove deleted domain ids from every puppet's membership list.

    Without this the membership string keeps a dangling id. The outliner
    rebuild prunes unknown ids, and deletes the puppet's controller outright if
    that leaves it empty - taking the puppet's animation with it.
    """
    for item in scene.outliner_items:
        if item.item_type != 'PUPPET' or not item.puppet_memberships:
            continue
        members = [m for m in item.puppet_memberships.split(',') if m]
        kept = [m for m in members if m not in dead_ids]
        if len(kept) != len(members):
            item.puppet_memberships = ','.join(kept)


def apply_layout(context, molecule: Any, chain_token: Any,
                 specs: List[DomainSpec]) -> ApplyResult:
    """Reconcile a chain's domains to ``specs``.

    Rows carrying a known ``domain_id`` are updated in place (keeping id,
    object, pivot, animation, puppet membership and linker endpoints); rows
    without one are created; existing domains absent from ``specs`` are
    deleted with full cleanup.

    Returns an :class:`ApplyResult`; ``errors`` is non-empty only when the
    layout was rejected outright, in which case nothing was changed.
    """
    from ..utils.scene_manager import ProteinBlenderScene, build_outliner_hierarchy

    scene = context.scene
    chain_min, chain_max = chain_residue_range(molecule, chain_token)

    errors = validate_layout(specs, chain_min, chain_max)
    if errors:
        return ApplyResult([], [], [], errors)

    # Heal any domain object/node-group references invalidated by an earlier
    # undo before mutating, exactly as the split and delete paths do.
    ProteinBlenderScene.get_instance().refresh_domain_refs_before_destructive_op(
        molecule.identifier)

    existing = {s.domain_id: s for s in current_layout(molecule, chain_token)}
    requested_ids = {s.domain_id for s in specs if s.domain_id in existing}
    doomed_ids = [d for d in existing if d not in requested_ids]

    # Snapshot the pose/style of everything currently on the chain BEFORE any
    # deletion, so new pieces can inherit from whichever domain used to cover
    # their territory. Read once here because the domains are about to go away.
    inherit_from: List[Tuple[int, int, Optional[Tuple[Any, Any]], Optional[str]]] = []
    for domain_id, spec in existing.items():
        domain = molecule.domains.get(domain_id)
        if domain is None:
            continue
        inherit_from.append((spec.start, spec.end, _capture_pose(domain),
                             _read_style(domain)))

    # Puppets that own this chain (by chain row or by one of its domains) need
    # the new pieces parented to their controller, or moving the puppet would
    # leave them behind.
    chain_row_ids = {item.item_id for item in scene.outliner_items
                     if item.item_type == 'CHAIN'
                     and str(getattr(item, 'chain_id', '')) in chain_match_tokens(molecule, chain_token)}
    owning_puppets = _puppets_containing(scene, chain_row_ids | set(existing))

    deleted: List[str] = []
    for domain_id in doomed_ids:
        try:
            molecule.delete_domain(domain_id)
            deleted.append(domain_id)
        except Exception as exc:
            print(f"apply_layout: failed to delete {domain_id}: {exc}")

    if deleted:
        _strip_from_puppets(scene, set(deleted))

    # Re-range the survivors. Overlap enforcement is off because the layout as
    # a whole was validated above: intermediate states legitimately overlap
    # (swapping two adjacent domains' ranges has no conflict-free ordering).
    updated: List[str] = []
    for spec in specs:
        if spec.domain_id not in existing:
            continue
        domain = molecule.domains.get(spec.domain_id)
        if domain is None:
            continue
        changed = False
        if (domain.start, domain.end) != (spec.start, spec.end):
            if molecule.update_domain_range(spec.domain_id, spec.start, spec.end,
                                            enforce_no_overlap=False):
                changed = True
        new_name = spec.name.strip()
        if new_name and domain.name != new_name:
            domain.name = new_name
            changed = True
        if changed:
            updated.append(spec.domain_id)

    # Create the rows the user added.
    created: List[str] = []
    for spec in specs:
        if spec.domain_id in existing:
            continue
        name = spec.name.strip() or f"Residues {spec.start}-{spec.end}"
        new_ids = molecule._create_domain_with_params(
            chain_token, spec.start, spec.end, name,
            False,  # auto_fill_chain: the layout is already complete
            None,   # parent_domain_id
        )
        if not new_ids:
            print(f"apply_layout: failed to create {name} ({spec.start}-{spec.end})")
            continue
        created.extend(new_ids)

        # Inherit the style of whichever old domain covered this range's start,
        # so a split looks like the chain was cut rather than reset.
        source = _source_for(inherit_from, spec.start)
        if source and source[3]:
            for domain_id in new_ids:
                domain = molecule.domains.get(domain_id)
                if domain is None:
                    continue
                domain.style = source[3]
                if domain.object:
                    try:
                        from ..panels.visual_setup_panel import apply_style_to_object
                        apply_style_to_object(domain.object, source[3])
                    except Exception as exc:
                        print(f"apply_layout: could not apply style: {exc}")

    if created:
        _place_created(context, molecule, chain_token, specs, existing,
                       created, inherit_from)
        _reparent_to_puppets(molecule, created, owning_puppets)

    molecule._mirror_domains_to_property_group()

    # Rebuild the outliner here rather than leaving it to the caller: the prune
    # below resolves linker endpoints against `scene.outliner_items`, so running
    # it against the pre-edit rows would find every endpoint still "valid" and
    # silently prune nothing.
    build_outliner_hierarchy(context)

    # Linkers whose endpoint domain is gone would otherwise keep pointing at a
    # dead id. Endpoints on surviving domains are untouched, which is the whole
    # point of reconciling.
    if deleted:
        try:
            from ..linkers.linker_handlers import prune_dangling_linkers
            prune_dangling_linkers(scene, "domain layout edited")
        except Exception as exc:
            print(f"apply_layout: linker prune failed: {exc}")

    return ApplyResult(updated, created, deleted, [])


def _source_for(inherit_from, start: int):
    """The snapshot of the old domain that covered residue ``start``, if any."""
    for entry in inherit_from:
        if entry[0] <= start <= entry[1]:
            return entry
    return None


def _place_created(context, molecule, chain_token, specs, existing,
                   created: List[str], inherit_from):
    """Give newly created domains sensible pivots and the chain's current pose.

    Two separate jobs, in order:

    1. **Pivots.** When the whole chain was rebuilt, use the split heuristic
       (boundary pivots) so a fresh N-way split behaves as it always has.
       Otherwise leave the per-domain default from creation alone, because the
       surviving domains' pivots are the user's and must not be disturbed.

    2. **Pose.** A fresh domain object is created at the molecule's imported
       pose. If the chain had been moved or rotated, the new piece has to be
       carried to where the rest of the chain is, or it visibly snaps back.
    """
    from mathutils import Matrix
    from . import domain_space

    rebuilt_whole_chain = not any(s.domain_id in existing for s in specs)
    if rebuilt_whole_chain and len(created) >= 2:
        ordered = sorted(created,
                         key=lambda d: molecule.domains[d].start
                         if d in molecule.domains else 0)
        molecule.set_domain_split_pivots(context, ordered, chain_token)

    # How a fresh, untouched piece maps mesh coords to the world. Every domain
    # object starts as an identical copy of the molecule object, so any of the
    # new ones defines the imported-pose mapping to compare against.
    reference = None
    for domain_id in created:
        domain = molecule.domains.get(domain_id)
        if domain and domain.object:
            reference = (domain.object.matrix_world.copy(),
                         domain_space.get_pivot(domain.object))
            break
    if reference is None:
        return

    ref_map = reference[0] @ Matrix.Translation(-reference[1])

    for domain_id in created:
        domain = molecule.domains.get(domain_id)
        if domain is None or domain.object is None:
            continue
        source = _source_for(inherit_from, domain.start)
        if source is None or source[2] is None:
            continue
        src_matrix, src_pivot = source[2]
        # Comparing in this pivot-corrected render space (rather than comparing
        # matrix_world alone) makes the delta exactly identity whenever the old
        # domain drew its atoms where a fresh piece would - so an unmoved chain
        # is left alone instead of being nudged by floating-point noise.
        delta = (src_matrix @ Matrix.Translation(-src_pivot)) @ ref_map.inverted()
        if _is_identity(delta):
            continue
        domain.object.matrix_world = delta @ domain.object.matrix_world
        domain.object["initial_matrix_local"] = [
            list(row) for row in domain.object.matrix_local]

    context.view_layer.update()


def _reparent_to_puppets(molecule, created: List[str], puppets: List[Any]):
    """Parent new domain pieces to the controller of any puppet owning the chain.

    Membership is stored per chain row, so a puppet keeps "owning" a chain
    across a re-split - but the Blender parenting that actually makes the
    puppet move it lives on the objects, which are brand new here.
    """
    for puppet_item in puppets:
        controller = bpy.data.objects.get(puppet_item.controller_object_name)
        if controller is None:
            continue
        for domain_id in created:
            domain = molecule.domains.get(domain_id)
            obj = domain.object if domain else None
            if obj is None or obj.parent == controller:
                continue
            world = obj.matrix_world.copy()
            obj.parent = controller
            obj.matrix_world = world  # keep_transform
