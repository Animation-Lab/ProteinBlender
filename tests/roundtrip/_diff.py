"""Path-precise structural diff for save/load round-trip snapshots.

``assert expected == actual`` on a deep dict tells you *that* a file lost
state; it does not tell you *what*. This produces one line per divergence,
each carrying the full path to the field, so a failure names the exact
persisted property that did not survive the round trip:

    scene.molecule_list_items[4hhb].chain_custom_names: '{"0": "Heavy"}' -> ''
    objects[Chain A_A_1_198].modifiers[MolecularNodes].inputs[Socket_5]: [1.0, 2.0, 3.0] -> [0.0, 0.0, 0.0]

That is the difference between "save/load is broken" and "``chain_custom_names``
is missing from ``_snapshot_list_item``".

Keys are matched by identity where a collection has a natural one (molecule
identifier, object name, linker uid, ...) rather than by list index, so a
re-ordered collection reports as a re-order and an added/removed member reports
as added/removed - not as every element after it having changed.
"""

from __future__ import annotations

# Collections keyed by a stable identity field rather than by position. Blender
# does not promise collection ordering across a file round trip, and diffing an
# unordered collection by index turns one insertion into N spurious diffs.
IDENTITY_KEYS = (
    "identifier",   # MoleculeListItem
    "item_id",      # ProteinOutlinerItem
    "uid",          # LinkerDefinition
    "domain_id",    # Domain / DomainTransform
    "name",         # poses, keyframes, generic named rows
    "_key",         # explicit key injected by the snapshot
)

MAX_REPORTED = 40


def _key_for(entry, index):
    """Stable identity for one member of a list-of-dicts, or its index."""
    if isinstance(entry, dict):
        for key in IDENTITY_KEYS:
            value = entry.get(key)
            if isinstance(value, str) and value:
                return f"{key}={value}"
    return f"#{index}"


def _fmt(value, limit=120):
    text = repr(value)
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    return text


def diff(expected, actual, path="") -> list[str]:
    """Return a list of human-readable divergences between two snapshots."""
    out: list[str] = []
    _diff_into(expected, actual, path, out)
    return out


def _diff_into(expected, actual, path, out):
    if type(expected) is not type(actual) and not (
            isinstance(expected, (int, float)) and isinstance(actual, (int, float))):
        out.append(f"{path}: type {type(expected).__name__} -> "
                   f"{type(actual).__name__} ({_fmt(expected)} -> {_fmt(actual)})")
        return

    if isinstance(expected, dict):
        for key in expected:
            sub = f"{path}.{key}" if path else str(key)
            if key not in actual:
                out.append(f"{sub}: MISSING after reload (was {_fmt(expected[key])})")
            else:
                _diff_into(expected[key], actual[key], sub, out)
        for key in actual:
            if key not in expected:
                sub = f"{path}.{key}" if path else str(key)
                out.append(f"{sub}: APPEARED after reload ({_fmt(actual[key])})")
        return

    if isinstance(expected, list):
        exp_keyed = {_key_for(e, i): e for i, e in enumerate(expected)}
        act_keyed = {_key_for(a, i): a for i, a in enumerate(actual)}
        # Fall back to positional comparison when identities collide (e.g. a
        # list of plain numbers, or duplicate names) so nothing is silently
        # dropped from the comparison.
        if len(exp_keyed) != len(expected) or len(act_keyed) != len(actual):
            if len(expected) != len(actual):
                out.append(f"{path}: length {len(expected)} -> {len(actual)}")
            for i, (e, a) in enumerate(zip(expected, actual)):
                _diff_into(e, a, f"{path}[{i}]", out)
            return
        for key, entry in exp_keyed.items():
            if key not in act_keyed:
                out.append(f"{path}[{key}]: MISSING after reload")
            else:
                _diff_into(entry, act_keyed[key], f"{path}[{key}]", out)
        for key in act_keyed:
            if key not in exp_keyed:
                out.append(f"{path}[{key}]: APPEARED after reload")
        if list(exp_keyed) != list(act_keyed) and set(exp_keyed) == set(act_keyed):
            out.append(f"{path}: order changed {list(exp_keyed)} -> {list(act_keyed)}")
        return

    if expected != actual:
        out.append(f"{path}: {_fmt(expected)} -> {_fmt(actual)}")


def format_report(differences, header):
    """Render diffs as an assertion message, capped so a total wipe stays
    readable while still reporting how much was hidden."""
    shown = differences[:MAX_REPORTED]
    lines = [header, f"  {len(differences)} field(s) diverged:"]
    lines += [f"    {d}" for d in shown]
    if len(differences) > len(shown):
        lines.append(f"    ... and {len(differences) - len(shown)} more")
    return "\n".join(lines)
